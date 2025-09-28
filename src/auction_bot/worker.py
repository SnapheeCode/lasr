"""Account worker orchestrating fetching, bidding, and messaging."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from . import browser
from .config import AccountConfig, MessageTemplate
from .graphql import Avtor24GraphQLClient
from .queue import Order, OrderQueue
from .scheduler import TaskScheduler

LOGGER = logging.getLogger(__name__)


@dataclass
class BidContext:
    order: Order
    bid_amount: float
    message: str
    captcha_required: bool


class AccountWorker:
    """Handle a single Avtor24 account."""

    def __init__(
        self,
        config: AccountConfig,
        graphql_client: Avtor24GraphQLClient,
        task_scheduler: Optional[TaskScheduler] = None,
    ) -> None:
        self.config = config
        self.graphql = graphql_client
        self.queue = OrderQueue()
        self.scheduler = task_scheduler or TaskScheduler()
        self._running = False
        self._last_bid_at: float = 0.0
        self._last_cookie_sync: float = 0.0

    async def start(self) -> None:
        self._running = True
        await self.scheduler.start()
        await self._run()

    async def stop(self) -> None:
        self._running = False
        await self.scheduler.stop()

    async def _run(self) -> None:
        async with browser.playwright_session(self.config.storage_path, headless=self.config.headless) as session:
            await session.ensure_logged_in(self.config.login, self.config.password)
            await self._sync_graphql_cookies(session, force=True)
            while self._running:
                try:
                    await self._tick(session)
                except Exception as exc:  # pragma: no cover - runtime resilience
                    LOGGER.exception("Worker %s encountered an error: %s", self.config.name, exc)
                    await asyncio.sleep(5)

    async def _tick(self, session: browser.BrowserSession) -> None:
        await self._refresh_queue(session)
        bid_context = await self._select_bid_candidate(session)
        if not bid_context:
            await asyncio.sleep(2)
            return
        await self._respect_bid_interval()
        await self._perform_bid(session, bid_context)

    async def _refresh_queue(self, session: browser.BrowserSession) -> None:
        await self._sync_graphql_cookies(session)
        filters = self._build_filters()
        try:
            payload = await self.graphql.fetch_orders(filters)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            LOGGER.warning(
                "GraphQL request unauthorized for %s, refreshing cookies",
                self.config.name,
            )
            await self._sync_graphql_cookies(session, force=True)
            payload = await self.graphql.fetch_orders(filters)
        captcha_required = payload.get("captcha", False)
        items = payload.get("orders", [])
        orders = []
        for item in items:
            order = Order(
                id=item["id"],
                title=item.get("title", ""),
                created_at=self._parse_timestamp(item.get("creation")),
                budget=item.get("budget"),
                author_has_offer=item.get("authorHasOffer", False),
                offers_count=item.get("countOffers", 0),
                subject=(item.get("category") or {}).get("name"),
                work_type=(item.get("type") or {}).get("name"),
            )
            orders.append(order)
        self.queue.bulk_update(orders)
        if captcha_required:
            LOGGER.warning("Captcha required for account %s, manual interaction needed", self.config.name)

    async def _select_bid_candidate(
        self, session: browser.BrowserSession
    ) -> Optional[BidContext]:
        await self._sync_graphql_cookies(session)
        order = self.queue.pop()
        if not order:
            return None
        await self.graphql.mark_read(order.id)
        order_details = await self.graphql.get_order_for_bid(order.id)
        bid_params = await self.graphql.get_bid_params(order.id)
        amount = self._calculate_bid_amount(order, order_details, bid_params)
        template = self._select_template(order)
        message = template.text if template else "Здравствуйте! Готов взяться за заказ."
        captcha_required = bool(order_details.get("currentAuthorBidWasHidden"))
        return BidContext(order=order, bid_amount=amount, message=message, captcha_required=captcha_required)

    def _calculate_bid_amount(self, order: Order, order_details: Dict[str, any], bid_params: Dict[str, any]) -> float:
        avg = bid_params.get("average")
        minimum = bid_params.get("minimum")
        maximum = bid_params.get("maximum")
        fallback = order.budget or maximum or minimum or avg or 500.0
        if avg and maximum:
            bid = (avg + maximum) / 2
        elif maximum:
            bid = maximum * 0.9
        elif avg:
            bid = avg
        else:
            bid = fallback
        min_budget = self.config.filters.min_budget
        if min_budget and bid < min_budget:
            bid = float(min_budget)
        return float(bid)

    def _select_template(self, order: Order) -> Optional[MessageTemplate]:
        for template in self.config.message_templates:
            if order.subject and order.subject in template.name:
                return template
        return self.config.message_templates[0] if self.config.message_templates else None

    async def _perform_bid(self, session: browser.BrowserSession, bid_context: BidContext) -> None:
        order = bid_context.order
        LOGGER.info("Placing bid on %s (%s) for %.2f", order.title, order.id, bid_context.bid_amount)
        await session.open_order(order.id)
        await session.place_bid(bid_context.bid_amount, bid_context.message, captcha_required=bid_context.captcha_required)
        await self._sync_graphql_cookies(session)
        await self.graphql.make_offer(order.id, bid_context.bid_amount, bid_context.message)
        self._last_bid_at = time.time()
        await self._schedule_followup(order, session)

    async def _schedule_followup(self, order: Order, session: browser.BrowserSession) -> None:
        if not self.config.message_templates:
            return
        followup_template = next(
            (tpl for tpl in self.config.message_templates if tpl.delay_seconds > 0),
            None,
        )
        if not followup_template and len(self.config.message_templates) > 1:
            followup_template = self.config.message_templates[1]
        if not followup_template:
            return

        delay = (
            followup_template.delay_seconds
            if followup_template.delay_seconds > 0
            else self.config.follow_up_delay_minutes * 60
        )

        async def _send() -> None:
            LOGGER.info("Sending follow-up for %s", order.id)
            await session.send_followup_message(followup_template.text)

        await self.scheduler.schedule(delay, _send)

    async def _respect_bid_interval(self) -> None:
        elapsed = time.time() - self._last_bid_at
        min_wait = self.config.min_seconds_between_bids
        max_wait = self.config.max_seconds_between_bids
        target = random.uniform(min_wait, max_wait)
        if elapsed < target:
            await asyncio.sleep(target - elapsed)

    def _build_filters(self) -> Dict[str, any]:
        filters: Dict[str, any] = {
            "types": self.config.filters.types,
            "categories": self.config.filters.categories,
            "contractual": True,
            "withoutMyBids": True,
        }
        if self.config.filters.min_budget is not None:
            filters["budgetFrom"] = self.config.filters.min_budget
        if self.config.filters.max_budget is not None:
            filters["budgetTo"] = self.config.filters.max_budget
        return filters

    def _parse_timestamp(self, iso_timestamp: Optional[str]) -> float:
        if not iso_timestamp:
            return time.time()
        try:
            return time.mktime(time.strptime(iso_timestamp.split(".")[0], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            return time.time()

    async def _sync_graphql_cookies(
        self, session: browser.BrowserSession, *, force: bool = False
    ) -> None:
        now = time.time()
        if not force and now - self._last_cookie_sync < 30:
            return
        cookies = await session.export_cookies()
        self.graphql.update_cookies(cookies)
        self._last_cookie_sync = now


async def run_workers(configs: List[AccountConfig]) -> None:
    clients = [Avtor24GraphQLClient() for _ in configs]
    workers = [AccountWorker(cfg, client) for cfg, client in zip(configs, clients)]
    await asyncio.gather(*(worker.start() for worker in workers))


__all__ = ["AccountWorker", "run_workers"]

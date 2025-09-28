"""Playwright-based browser automation helpers."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

LOGGER = logging.getLogger(__name__)

LOGIN_URL = "https://avtor24.ru/login"
SEARCH_URL = "https://avtor24.ru/order/search"
ORDER_URL_TEMPLATE = "https://avtor24.ru/order/{order_id}"


class BrowserSession:
    """Wrapper around a Playwright browser context."""

    def __init__(self, storage_path: Path, headless: bool = False) -> None:
        self.storage_path = storage_path
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> Page:
        LOGGER.info("Launching browser (headless=%s) with storage at %s", self.headless, self.storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        storage_state = str(self.storage_path) if self.storage_path.exists() else None
        self._context = await self._browser.new_context(storage_state=storage_state)
        self._page = await self._context.new_page()
        return self._page

    async def stop(self) -> None:
        if self._context and self.storage_path:
            LOGGER.info("Saving storage state to %s", self.storage_path)
            await self._context.storage_state(path=str(self.storage_path))
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser session not started")
        return self._page

    async def ensure_logged_in(self, login: str, password: str) -> None:
        """Navigate to the login form and ensure the user is authenticated."""

        page = self.page
        await page.goto(SEARCH_URL)
        if "login" not in page.url:
            LOGGER.debug("Already authenticated")
            return
        LOGGER.info("Logging in as %s", login)
        await page.goto(LOGIN_URL)
        await page.fill("input[name=email]", login)
        await page.fill("input[name=password]", password)
        await page.click("button[type=submit]")
        await page.wait_for_url(SEARCH_URL, timeout=30000)
        LOGGER.info("Authentication successful")

    async def open_order(self, order_id: str) -> None:
        url = ORDER_URL_TEMPLATE.format(order_id=order_id)
        LOGGER.debug("Opening order page %s", url)
        await self.page.goto(url)
        await self.page.wait_for_selector("[data-testid='MakeOffer__inputBid']", timeout=15000)

    async def place_bid(self, amount: float, message: str, *, captcha_required: bool) -> None:
        page = self.page
        await page.hover("[data-testid='MakeOffer__inputBid']")
        await page.click("[data-testid='MakeOffer__inputBid']")
        await page.fill("[data-testid='MakeOffer__inputBid']", str(int(amount)))
        await page.fill("textarea#makeOffer_comment", message)
        await page.mouse.move(300, 600, steps=5)
        await page.wait_for_timeout(400)
        button = page.locator("button:has-text('Поставить ставку')")
        await button.scroll_into_view_if_needed()
        await button.click()
        if captcha_required:
            LOGGER.warning("Captcha detected. Awaiting manual resolution...")
            await page.wait_for_selector(".smart-captcha", state="hidden", timeout=180000)
        await page.wait_for_timeout(1000)

    async def send_followup_message(self, text: str) -> None:
        page = self.page
        await page.fill("textarea#makeOffer_comment", text)
        await page.wait_for_timeout(300)
        await page.click("button:has-text('Отправить')")

    async def export_cookies(self) -> List[dict[str, Any]]:
        """Return the current browser cookies for reuse in HTTP clients."""

        if not self._context:
            raise RuntimeError("Browser session not started")
        state = await self._context.storage_state()
        cookies = state.get("cookies", [])
        return [cookie for cookie in cookies if isinstance(cookie, dict)]


@asynccontextmanager
async def playwright_session(storage_path: Path, headless: bool = False) -> AsyncIterator[BrowserSession]:
    session = BrowserSession(storage_path=storage_path, headless=headless)
    try:
        await session.start()
        yield session
    finally:
        await session.stop()


async def with_browser(
    storage_path: Path,
    headless: bool,
    coro: Callable[[BrowserSession], Awaitable[None]],
) -> None:
    async with playwright_session(storage_path, headless=headless) as session:
        await coro(session)


__all__ = ["BrowserSession", "playwright_session", "with_browser"]

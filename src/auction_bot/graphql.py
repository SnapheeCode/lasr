"""GraphQL client for Avtor24 interactions."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

LOGGER = logging.getLogger(__name__)

API_URL = "https://avtor24.ru/graphqlapi"  # production GraphQL endpoint


@dataclass
class GraphQLResponse:
    """Container for GraphQL responses."""

    data: Dict[str, Any]
    errors: Optional[list[dict[str, Any]]]

    def raise_for_errors(self) -> None:
        if self.errors:
            raise RuntimeError(f"GraphQL errors: {self.errors}")


class Avtor24GraphQLClient:
    """Thin async wrapper around HTTPX for GraphQL queries."""

    def __init__(self, token: Optional[str] = None) -> None:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(headers=headers, timeout=20.0, http2=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def execute(self, query: str, variables: Optional[Dict[str, Any]] = None) -> GraphQLResponse:
        payload = {"query": query, "variables": variables or {}}
        async for attempt in AsyncRetrying(
            wait=wait_exponential(multiplier=0.5, min=1, max=8),
            stop=stop_after_attempt(4),
            retry=retry_if_exception_type(httpx.RequestError),
            reraise=True,
        ):
            with attempt:
                response = await self._client.post(API_URL, json=payload)
                response.raise_for_status()
                body = response.json()
                return GraphQLResponse(data=body.get("data", {}), errors=body.get("errors"))
        raise RuntimeError("GraphQL execution failed")

    async def fetch_orders(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        response = await self.execute(_GET_AUCTION_WITH_CONSTRAINTS, {"filter": filters})
        response.raise_for_errors()
        return response.data["orders"]

    async def mark_read(self, order_id: str) -> None:
        result = await self.execute(_MARK_ORDER_READ, {"orderId": order_id})
        result.raise_for_errors()

    async def get_order_for_bid(self, order_id: str) -> Dict[str, Any]:
        result = await self.execute(_GET_ORDER_FOR_BID, {"orderId": order_id})
        result.raise_for_errors()
        return result.data["order"]

    async def get_bid_params(self, order_id: str) -> Dict[str, Any]:
        result = await self.execute(_GET_BID_PARAMS, {"orderId": order_id})
        result.raise_for_errors()
        return result.data["bidParams"]

    async def make_offer(
        self,
        order_id: str,
        amount: float,
        message: str,
        captcha_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        variables = {
            "orderId": order_id,
            "amount": amount,
            "message": message,
            "captchaToken": captcha_token,
        }
        result = await self.execute(_MAKE_OFFER, variables)
        result.raise_for_errors()
        return result.data["makeOffer"]

    async def send_message(self, dialog_id: str, text: str) -> None:
        result = await self.execute(_ADD_COMMENT, {"dialogId": dialog_id, "text": text})
        result.raise_for_errors()

    async def fetch_dialogs(self) -> Dict[str, Any]:
        result = await self.execute(_GET_DIALOGS, {})
        result.raise_for_errors()
        return result.data["dialogs"]


# GraphQL queries (trimmed to the fields we require) -----------------------------------------------------

_GET_AUCTION_WITH_CONSTRAINTS = """
query GetAuctionWithConstraints($filter: OrdersFilter!) {
  orders(filter: $filter) {
    captcha
    items {
      id
      title
      createdAt
      price
      authorHasOffer
      offersCount
      subject { name }
      workType { name }
    }
  }
}
"""

_MARK_ORDER_READ = """
mutation readOrder($orderId: ID!) {
  readOrder(orderId: $orderId) { id }
}
"""

_GET_ORDER_FOR_BID = """
query getOrderForBid($orderId: ID!) {
  order(id: $orderId) {
    id
    title
    minPrice
    maxPrice
    authorHasOffer
    currentAuthorBidWasHidden
  }
}
"""

_GET_BID_PARAMS = """
query getBidParams($orderId: ID!) {
  bidParams(orderId: $orderId) {
    average
    minimum
    maximum
  }
}
"""

_MAKE_OFFER = """
mutation makeOffer($orderId: ID!, $amount: Float!, $message: String!, $captchaToken: String) {
  makeOffer(orderId: $orderId, amount: $amount, message: $message, captchaToken: $captchaToken) {
    id
    amount
    status
  }
}
"""

_ADD_COMMENT = """
mutation addComment($dialogId: ID!, $text: String!) {
  addComment(dialogId: $dialogId, text: $text) {
    id
  }
}
"""

_GET_DIALOGS = """
query getDialogs {
  dialogs {
    id
    orderId
    unreadCount
    lastMessage {
      id
      text
      createdAt
    }
  }
}
"""


async def create_client_with_login(login_coro: Any) -> Avtor24GraphQLClient:
    """Helper to create a client after completing a login coroutine."""

    token = await asyncio.ensure_future(login_coro)
    return Avtor24GraphQLClient(token=token)


__all__ = ["Avtor24GraphQLClient", "GraphQLResponse", "create_client_with_login"]

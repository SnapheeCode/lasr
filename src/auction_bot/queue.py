"""Priority queue implementation for auction orders."""
from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, Optional


@dataclass(order=True)
class PrioritisedOrder:
    """Internal wrapper for heap ordering."""

    priority: float
    order_id: str = field(compare=False)
    payload: "Order" = field(compare=False)


@dataclass
class Order:
    """Simplified order representation used inside the bot."""

    id: str
    title: str
    created_at: float
    budget: Optional[int]
    author_has_offer: bool
    offers_count: int
    subject: Optional[str] = None
    work_type: Optional[str] = None

    def freshness_score(self) -> float:
        """Calculate a freshness score based on creation time."""

        age_seconds = max(time.time() - self.created_at, 1.0)
        return 1.0 / age_seconds


class OrderQueue:
    """Maintain a priority queue of orders preferring newer items."""

    def __init__(self) -> None:
        self._heap: list[PrioritisedOrder] = []
        self._index: Dict[str, PrioritisedOrder] = {}

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._index)

    def __iter__(self) -> Iterator[Order]:
        return (entry.payload for entry in sorted(self._heap))

    def _compute_priority(self, order: Order) -> float:
        """Combine multiple factors into a single priority value."""

        freshness = order.freshness_score()
        penalty = 0.0
        if order.author_has_offer:
            penalty += 1.0
        penalty += min(order.offers_count, 10) * 0.05
        return -(freshness - penalty)

    def upsert(self, order: Order) -> None:
        """Insert or update an order in the queue."""

        priority = self._compute_priority(order)
        if order.id in self._index:
            existing = self._index[order.id]
            existing.priority = priority
            existing.payload = order
            heapq.heapify(self._heap)
        else:
            entry = PrioritisedOrder(priority=priority, order_id=order.id, payload=order)
            self._index[order.id] = entry
            heapq.heappush(self._heap, entry)

    def pop(self) -> Optional[Order]:
        """Retrieve the best order available."""

        while self._heap:
            entry = heapq.heappop(self._heap)
            if entry.order_id in self._index and self._index[entry.order_id] is entry:
                del self._index[entry.order_id]
                return entry.payload
        return None

    def bulk_update(self, orders: Iterable[Order]) -> None:
        """Add or refresh multiple orders at once."""

        for order in orders:
            self.upsert(order)

    def discard(self, order_id: str) -> None:
        """Remove an order from the queue if it exists."""

        entry = self._index.pop(order_id, None)
        if entry is not None:
            entry.payload = None  # type: ignore[assignment]


__all__ = ["Order", "OrderQueue"]

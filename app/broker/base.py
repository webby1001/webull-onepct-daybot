"""Broker protocol / dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_entry: float
    stop_price: float | None = None
    take_profit_price: float | None = None
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OrderRequest:
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: float
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: float | None = None
    client_order_id: str | None = None


@dataclass
class OrderResult:
    ok: bool
    client_order_id: str
    order_id: str | None
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None
    status: str
    error: str | None = None
    broker: str = "mock"
    fill_price: float | None = None


class Broker(Protocol):
    name: str

    def place_order(self, req: OrderRequest) -> OrderResult: ...
    def get_positions(self) -> list[Position]: ...
    def get_orders(self) -> list[OrderResult]: ...

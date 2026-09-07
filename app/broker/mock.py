"""In-memory mock / paper broker."""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.broker.base import OrderRequest, OrderResult, Position


@dataclass
class ClosedTrade:
    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    quantity: float
    entry_price: float
    exit_price: float
    pnl: float
    reason: str

    @property
    def hold_minutes(self) -> float:
        return (self.exit_ts - self.entry_ts).total_seconds() / 60.0


class MockBroker:
    name = "mock"

    def __init__(self, starting_cash: float = 1000.0) -> None:
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self._positions: dict[str, Position] = {}
        self._orders: list[OrderResult] = []
        self.closed_trades: list[ClosedTrade] = []
        self.realized_pnl_total = 0.0
        self._lock = threading.Lock()
        self._id_seq = itertools.count(1)
        self._entry_meta: dict[str, tuple[datetime, float]] = {}

    def place_order(self, req: OrderRequest) -> OrderResult:
        with self._lock:
            cid = req.client_order_id or f"mock{int(time.time() * 1000)}{next(self._id_seq)}"
            oid = f"MO-{next(self._id_seq)}"
            price = req.limit_price if req.limit_price is not None else 0.0

            if req.side == "BUY":
                fill = price if price > 0 else 100.0
                cost = fill * req.quantity
                if cost > self.cash + 1e-9:
                    result = OrderResult(
                        ok=False,
                        client_order_id=cid,
                        order_id=None,
                        symbol=req.symbol,
                        side=req.side,
                        quantity=req.quantity,
                        order_type=req.order_type,
                        limit_price=req.limit_price,
                        status="REJECTED",
                        error=f"Insufficient cash: need {cost:.2f}, have {self.cash:.2f}",
                        broker=self.name,
                    )
                    self._orders.append(result)
                    return result
                self.cash -= cost
                existing = self._positions.get(req.symbol)
                if existing:
                    total_qty = existing.quantity + req.quantity
                    avg = (
                        (existing.avg_entry * existing.quantity) + (fill * req.quantity)
                    ) / total_qty
                    existing.quantity = total_qty
                    existing.avg_entry = avg
                else:
                    self._positions[req.symbol] = Position(
                        symbol=req.symbol,
                        quantity=req.quantity,
                        avg_entry=fill,
                    )
                    self._entry_meta[req.symbol] = (
                        datetime.now(timezone.utc),
                        fill,
                    )
            else:
                existing = self._positions.get(req.symbol)
                if not existing or existing.quantity < req.quantity - 1e-9:
                    result = OrderResult(
                        ok=False,
                        client_order_id=cid,
                        order_id=None,
                        symbol=req.symbol,
                        side=req.side,
                        quantity=req.quantity,
                        order_type=req.order_type,
                        limit_price=req.limit_price,
                        status="REJECTED",
                        error="Insufficient position to sell",
                        broker=self.name,
                    )
                    self._orders.append(result)
                    return result
                fill = price if price > 0 else existing.avg_entry
                proceeds = fill * req.quantity
                self.cash += proceeds
                pnl = (fill - existing.avg_entry) * req.quantity
                self.realized_pnl_total += pnl
                entry_ts, entry_px = self._entry_meta.get(
                    req.symbol, (existing.opened_at, existing.avg_entry)
                )
                reason = (req.client_order_id or "sell").split(":")[-1] if req.client_order_id else "sell"
                self.closed_trades.append(
                    ClosedTrade(
                        symbol=req.symbol,
                        entry_ts=entry_ts,
                        exit_ts=datetime.now(timezone.utc),
                        quantity=req.quantity,
                        entry_price=entry_px,
                        exit_price=fill,
                        pnl=pnl,
                        reason=reason,
                    )
                )
                existing.quantity -= req.quantity
                if existing.quantity <= 1e-9:
                    del self._positions[req.symbol]
                    self._entry_meta.pop(req.symbol, None)

            result = OrderResult(
                ok=True,
                client_order_id=cid,
                order_id=oid,
                symbol=req.symbol,
                side=req.side,
                quantity=req.quantity,
                order_type=req.order_type,
                limit_price=req.limit_price,
                status="FILLED",
                broker=self.name,
                fill_price=fill,
            )
            self._orders.append(result)
            return result

    def get_positions(self) -> list[Position]:
        with self._lock:
            return list(self._positions.values())

    def get_orders(self) -> list[OrderResult]:
        with self._lock:
            return list(self._orders)

    def equity(self, marks: dict[str, float] | None = None) -> float:
        marks = marks or {}
        with self._lock:
            eq = self.cash
            for sym, pos in self._positions.items():
                px = marks.get(sym, pos.avg_entry)
                eq += pos.quantity * px
            return eq

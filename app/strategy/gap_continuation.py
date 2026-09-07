"""Gap continuation: buy largest overnight gap ≥ threshold, hold to EOD flatten."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.broker.base import OrderRequest
from app.broker.mock import MockBroker
from app.config import Settings
from app.market.quotes import Quote, QuoteService
from app.risk.bankroll import BankrollRisk, SessionGate

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    scanned_at: str
    message: str
    entries: list[dict] = field(default_factory=list)
    exits: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


class GapContinuationStrategy:
    """Long-only concentrated gap continuation.

    At/after the open, rank watchlist by overnight gap (open vs prior close).
    If the best gap ≥ gap_min_pct, buy with up to max_notional_fraction of equity
    (default 100% — aggressive demo sizing). Exit on optional stop/take or EOD flatten.
    """

    def __init__(
        self,
        broker: MockBroker,
        settings: Settings,
        quotes: QuoteService,
        risk: BankrollRisk,
        gate: SessionGate,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.broker = broker
        self.settings = settings
        self.quotes = quotes
        self.risk = risk
        self.gate = gate
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.last_scan: ScanResult | None = None
        self._stops: dict[str, float] = {}
        self._tps: dict[str, float] = {}
        self._entered_today: bool = False
        self._day_key: str | None = None

    def _roll_day(self) -> None:
        et = self.gate.now_et(self.clock())
        key = et.strftime("%Y-%m-%d")
        if key != self._day_key:
            self._day_key = key
            self._entered_today = False
            self.risk.reset_day()

    def scan_and_trade(self, force: bool = False) -> ScanResult:
        self._roll_day()
        now = self.clock()
        entries: list[dict] = []
        exits: list[dict] = []
        candidates: list[dict] = []

        if self.gate.should_flatten(now):
            exits.extend(self.flatten_all(reason="eod_flatten"))
            result = ScanResult(
                scanned_at=now.isoformat(),
                message="flatten window — flat",
                entries=entries,
                exits=exits,
            )
            self.last_scan = result
            return result

        if not force and not self.gate.is_within_session(now):
            result = ScanResult(
                scanned_at=now.isoformat(),
                message="outside session",
            )
            self.last_scan = result
            return result

        qmap = self.quotes.get_quotes(self.settings.watchlist)
        # Manage open positions first
        for pos in list(self.broker.get_positions()):
            q = qmap.get(pos.symbol)
            if not q:
                continue
            px = q.last
            stop = self._stops.get(pos.symbol)
            tp = self._tps.get(pos.symbol)
            if stop is not None and px <= stop:
                exits.append(self._close(pos.symbol, px, "stop"))
            elif tp is not None and px >= tp:
                exits.append(self._close(pos.symbol, px, "take_profit"))

        # Rank by gap
        ranked = sorted(
            (
                {
                    "symbol": s,
                    "gap_pct": round(q.gap_pct, 4),
                    "day_pct": round(q.day_pct, 4),
                    "last": q.last,
                    "open": q.open,
                    "prior_close": q.prior_close,
                }
                for s, q in qmap.items()
            ),
            key=lambda x: -x["gap_pct"],
        )
        candidates = ranked[:10]

        if self._entered_today or self.broker.get_positions():
            result = ScanResult(
                scanned_at=now.isoformat(),
                message="already positioned / entered today",
                entries=entries,
                exits=exits,
                candidates=candidates,
            )
            self.last_scan = result
            return result

        if not self.risk.can_open(len(self.broker.get_positions())):
            result = ScanResult(
                scanned_at=now.isoformat(),
                message=f"risk blocked: {self.risk.halt_reason}",
                candidates=candidates,
            )
            self.last_scan = result
            return result

        if not ranked or ranked[0]["gap_pct"] < self.settings.gap_min_pct:
            result = ScanResult(
                scanned_at=now.isoformat(),
                message=f"no gap ≥ {self.settings.gap_min_pct}%",
                candidates=candidates,
            )
            self.last_scan = result
            return result

        best = ranked[0]
        sym = best["symbol"]
        q = qmap[sym]
        entry_px = q.open if q.open > 0 else q.last
        marks = {s: qq.last for s, qq in qmap.items()}
        equity = self.broker.equity(marks)
        notional = equity * float(self.settings.max_notional_fraction)
        if entry_px <= 0 or notional < entry_px:
            result = ScanResult(
                scanned_at=now.isoformat(),
                message="insufficient equity for 1 share",
                candidates=candidates,
            )
            self.last_scan = result
            return result

        qty = int(notional // entry_px)
        if qty < 1:
            result = ScanResult(
                scanned_at=now.isoformat(),
                message="qty < 1",
                candidates=candidates,
            )
            self.last_scan = result
            return result

        res = self.broker.place_order(
            OrderRequest(
                symbol=sym,
                side="BUY",
                quantity=qty,
                order_type="LIMIT",
                limit_price=entry_px,
                client_order_id=f"gap:{sym}",
            )
        )
        if res.ok:
            self._entered_today = True
            if self.settings.stop_loss_pct > 0:
                self._stops[sym] = entry_px * (1 - self.settings.stop_loss_pct / 100.0)
            if self.settings.take_profit_pct > 0:
                self._tps[sym] = entry_px * (1 + self.settings.take_profit_pct / 100.0)
            entries.append(
                {
                    "symbol": sym,
                    "qty": qty,
                    "price": entry_px,
                    "gap_pct": best["gap_pct"],
                }
            )
            msg = f"entered {sym} qty={qty} @ {entry_px:.4f} gap={best['gap_pct']:.2f}%"
        else:
            msg = f"entry rejected: {res.error}"

        result = ScanResult(
            scanned_at=now.isoformat(),
            message=msg,
            entries=entries,
            exits=exits,
            candidates=candidates,
        )
        self.last_scan = result
        return result

    def _close(self, symbol: str, price: float, reason: str) -> dict:
        pos = next((p for p in self.broker.get_positions() if p.symbol == symbol), None)
        if not pos:
            return {"symbol": symbol, "ok": False, "reason": reason}
        res = self.broker.place_order(
            OrderRequest(
                symbol=symbol,
                side="SELL",
                quantity=pos.quantity,
                order_type="LIMIT",
                limit_price=price,
                client_order_id=f"exit:{reason}",
            )
        )
        if res.ok and self.broker.closed_trades:
            self.risk.record_pnl(self.broker.closed_trades[-1].pnl)
        self._stops.pop(symbol, None)
        self._tps.pop(symbol, None)
        return {"symbol": symbol, "ok": res.ok, "reason": reason, "price": price}

    def flatten_all(self, reason: str = "flatten") -> list[dict]:
        out = []
        qmap = self.quotes.get_quotes(
            [p.symbol for p in self.broker.get_positions()] or self.settings.watchlist
        )
        for pos in list(self.broker.get_positions()):
            px = qmap[pos.symbol].last if pos.symbol in qmap else pos.avg_entry
            out.append(self._close(pos.symbol, px, reason))
        return out

"""Simple bankroll / session gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.config import Settings


@dataclass
class BankrollRisk:
    bankroll: float
    max_daily_loss_pct: float
    max_open_positions: int
    realized_pnl_today: float = 0.0
    halted: bool = False
    halt_reason: str | None = None

    @property
    def max_daily_loss_dollars(self) -> float:
        return self.bankroll * (self.max_daily_loss_pct / 100.0)

    def record_pnl(self, pnl: float) -> None:
        self.realized_pnl_today += pnl
        if self.realized_pnl_today <= -self.max_daily_loss_dollars:
            self.halted = True
            self.halt_reason = "max_daily_loss"

    def reset_day(self) -> None:
        self.realized_pnl_today = 0.0
        self.halted = False
        self.halt_reason = None

    def can_open(self, open_count: int) -> bool:
        if self.halted:
            return False
        return open_count < self.max_open_positions


class SessionGate:
    def __init__(self, start_et: str, flatten_et: str, tz_name: str = "America/New_York"):
        self.tz = ZoneInfo(tz_name)
        sh, sm = (int(x) for x in start_et.split(":"))
        fh, fm = (int(x) for x in flatten_et.split(":"))
        self.start = time(sh, sm)
        self.flatten = time(fh, fm)

    @classmethod
    def from_settings(cls, settings: Settings) -> "SessionGate":
        return cls(settings.session_start_et, settings.flatten_et, settings.timezone)

    def now_et(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(self.tz)
        if now.tzinfo is None:
            now = now.replace(tzinfo=self.tz)
        return now.astimezone(self.tz)

    def is_within_session(self, now: datetime | None = None) -> bool:
        et = self.now_et(now)
        if et.weekday() >= 5:
            return False
        t = et.time()
        return self.start <= t < self.flatten

    def should_flatten(self, now: datetime | None = None) -> bool:
        et = self.now_et(now)
        if et.weekday() >= 5:
            return True
        return et.time() >= self.flatten

"""Settings for the ~1%/day gap-continuation paper bot."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# High-beta / leveraged ETF universe for overnight gap ranking
DEFAULT_WATCHLIST = [
    "TQQQ",
    "SOXL",
    "SPXL",
    "NVDA",
    "TSLA",
    "AMD",
    "COIN",
    "MSTR",
    "PLTR",
    "SMCI",
    "ARM",
    "SMH",
    "ARKK",
    "XBI",
    "META",
    "AMZN",
    "NFLX",
    "MU",
    "AMAT",
    "AVGO",
    "CRWD",
    "UBER",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    webull_app_key: str = ""
    webull_app_secret: str = ""
    webull_account_id: str = ""
    webull_api_host: str = "api.sandbox.webull.com"

    trading_mode: Literal["paper", "live"] = "paper"
    allow_live_trading: bool = False

    paper_bankroll: float = 1000.0
    # Deploy up to 100% of equity into the single best gap name (documented risk)
    max_notional_fraction: float = 1.0
    gap_min_pct: float = 1.5
    stop_loss_pct: float = 0.0  # 0 = disabled (best in-sample mean daily)
    take_profit_pct: float = 0.0
    max_open_positions: int = 1
    max_daily_loss_pct: float = 25.0

    session_start_et: str = "09:35"
    flatten_et: str = "15:55"
    timezone: str = "America/New_York"
    scan_interval_minutes: int = 5

    watchlist: list[str] = Field(default_factory=lambda: list(DEFAULT_WATCHLIST))

    host: str = "0.0.0.0"
    port: int = 8082

    strategy_name: str = "gap_continuation_top_mover"

    @field_validator("watchlist", mode="before")
    @classmethod
    def parse_watchlist(cls, v: object) -> list[str]:
        if v is None or v == "":
            return list(DEFAULT_WATCHLIST)
        if isinstance(v, str):
            parts = [p.strip().upper() for p in v.replace(";", ",").split(",")]
            return [p for p in parts if p] or list(DEFAULT_WATCHLIST)
        if isinstance(v, (list, tuple)):
            return [str(x).strip().upper() for x in v if str(x).strip()]
        return list(DEFAULT_WATCHLIST)

    @property
    def has_webull_keys(self) -> bool:
        return bool(self.webull_app_key.strip() and self.webull_app_secret.strip())

    @property
    def max_daily_loss_dollars(self) -> float:
        return self.paper_bankroll * (self.max_daily_loss_pct / 100.0)

    def resolved_host(self) -> str:
        host = (
            self.webull_api_host.strip()
            .removeprefix("https://")
            .removeprefix("http://")
            .rstrip("/")
        )
        live_ok = self.trading_mode == "live" and self.allow_live_trading
        if not live_ok and host.lower() in {"api.webull.com", "api.webull.hk"}:
            return "api.sandbox.webull.com"
        return host or "api.sandbox.webull.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()

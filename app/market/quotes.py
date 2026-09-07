"""Quote service: yfinance last / prior close when possible, else deterministic mock."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    symbol: str
    last: float
    open: float
    prior_close: float
    volume: float = 0.0
    asof: datetime | None = None

    @property
    def gap_pct(self) -> float:
        if self.prior_close <= 0:
            return 0.0
        return (self.open / self.prior_close - 1.0) * 100.0

    @property
    def day_pct(self) -> float:
        if self.prior_close <= 0:
            return 0.0
        return (self.last / self.prior_close - 1.0) * 100.0


class QuoteService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, Quote] = {}

    def get_quotes(self, symbols: list[str] | None = None) -> dict[str, Quote]:
        symbols = symbols or self.settings.watchlist
        out: dict[str, Quote] = {}
        for sym in symbols:
            q = self._fetch_one(sym)
            if q:
                out[sym] = q
                self._cache[sym] = q
        return out

    def _fetch_one(self, symbol: str) -> Quote | None:
        try:
            import yfinance as yf

            t = yf.Ticker(symbol)
            info = {}
            try:
                fi = getattr(t, "fast_info", None)
                if fi:
                    info = dict(fi) if not isinstance(fi, dict) else fi
            except Exception:  # noqa: BLE001
                info = {}
            last = float(info.get("lastPrice") or info.get("last_price") or 0) or 0.0
            prior = float(info.get("previousClose") or info.get("previous_close") or 0) or 0.0
            day_open = float(info.get("open") or info.get("open_price") or 0) or 0.0
            if last > 0 and prior > 0:
                if day_open <= 0:
                    day_open = last
                return Quote(
                    symbol=symbol,
                    last=last,
                    open=day_open,
                    prior_close=prior,
                    asof=datetime.now(timezone.utc),
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("yf quote fail %s: %s", symbol, exc)
        return self._mock_quote(symbol)

    def _mock_quote(self, symbol: str) -> Quote:
        """Deterministic mock so paper demos can still rank gaps."""
        bucket = int(datetime.now(timezone.utc).timestamp() // 300)
        h = hashlib.sha256(f"{symbol}:{bucket}".encode()).hexdigest()
        n = int(h[:8], 16)
        base = 50 + (n % 500)
        # gap between -1% and +4%
        gap = ((n >> 8) % 500) / 10000.0 - 0.01  # -1% .. +4%
        prior = float(base)
        day_open = prior * (1 + gap)
        # last drifts from open
        drift = ((n >> 16) % 200) / 10000.0 - 0.01
        last = day_open * (1 + drift)
        return Quote(
            symbol=symbol,
            last=round(last, 4),
            open=round(day_open, 4),
            prior_close=round(prior, 4),
            volume=1_000_000,
            asof=datetime.now(timezone.utc),
        )

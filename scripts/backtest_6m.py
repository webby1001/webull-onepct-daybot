#!/usr/bin/env python3
"""Run ~6-month gap-continuation backtest and write artifacts/backtest/summary.json."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest.data import download_watchlist_bars
from app.backtest.engine import run_gap_continuation_backtest, write_artifacts
from app.config import DEFAULT_WATCHLIST, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backtest_6m")


def main() -> None:
    settings = get_settings()
    end = datetime(2026, 9, 7)
    start = end - timedelta(days=183)
    cache = ROOT / "artifacts" / "backtest" / "cache"
    # Prefer existing copied cache date range from sibling daybot
    symbols = list(settings.watchlist) or list(DEFAULT_WATCHLIST)

    logger.info("Downloading/loading %s symbols %s → %s (1h)", len(symbols), start.date(), end.date())
    bars, failed = download_watchlist_bars(
        symbols,
        start=start,
        end=end,
        interval="1h",
        cache_dir=cache,
    )
    if failed:
        logger.warning("Failed symbols: %s", failed)
    if not bars:
        # fallback: load whatever parquet is in cache
        import pandas as pd

        for p in cache.glob("*_1h_*.parquet"):
            sym = p.name.split("_1h_")[0].replace("-", ".")
            df = pd.read_parquet(p)
            bars[sym] = df
        logger.info("Fallback loaded %s from cache files", len(bars))

    result = run_gap_continuation_backtest(
        bars,
        start_equity=settings.paper_bankroll,
        gap_min_pct=settings.gap_min_pct,
        max_notional_fraction=settings.max_notional_fraction,
        stop_loss_pct=settings.stop_loss_pct,
        take_profit_pct=settings.take_profit_pct,
        bar_size="1h→daily OHLC",
        data_source="yfinance",
    )
    out = ROOT / "artifacts" / "backtest"
    write_artifacts(result, out)
    print("=" * 60)
    print("STRATEGY:", result.strategy_name)
    print("MEAN DAILY RETURN %:", result.mean_daily_return_pct)
    print("TOTAL / COMPOUNDED %:", result.compounded_total_return_pct)
    print("MAX DD %:", result.max_drawdown_pct)
    print("TRADES:", result.trade_count, "WIN RATE %:", result.win_rate_pct)
    print("TRADING DAYS:", result.trading_days, "WIN DAY %:", result.win_day_pct)
    print("SHARPE~:", result.sharpe_approx)
    print("PERIOD:", result.period_start, "→", result.period_end)
    print("END EQUITY:", result.end_equity)
    print("LABEL:", result.sample_label)
    print("Wrote", out / "summary.json")
    print("=" * 60)


if __name__ == "__main__":
    main()

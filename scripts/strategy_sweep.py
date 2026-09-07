#!/usr/bin/env python3
"""Quick strategy sweep — writes artifacts/backtest/sweep.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest.engine import run_gap_continuation_backtest
from app.config import DEFAULT_WATCHLIST


def load_cache() -> dict:
    cache = ROOT / "artifacts" / "backtest" / "cache"
    bars = {}
    for p in cache.glob("*_1h_*.parquet"):
        sym = p.name.split("_1h_")[0].replace("-", ".")
        if sym not in DEFAULT_WATCHLIST and sym.replace(".", "-") not in [
            s.replace(".", "-") for s in DEFAULT_WATCHLIST
        ]:
            # keep extras too for sweep richness
            pass
        df = pd.read_parquet(p)
        bars[sym] = df
    # filter to default watchlist intersection preferentially
    prefer = {s: bars[s] for s in DEFAULT_WATCHLIST if s in bars}
    return prefer or bars


def main() -> None:
    bars = load_cache()
    rows = []
    for gap in [1.0, 1.2, 1.5, 2.0, 2.5]:
        for stop in [0.0, 2.0, 3.0]:
            r = run_gap_continuation_backtest(
                bars,
                gap_min_pct=gap,
                stop_loss_pct=stop,
                take_profit_pct=0.0,
            )
            rows.append(
                {
                    "gap_min_pct": gap,
                    "stop_loss_pct": stop,
                    "mean_daily_return_pct": r.mean_daily_return_pct,
                    "total_pct": r.return_pct,
                    "max_dd_pct": r.max_drawdown_pct,
                    "trades": r.trade_count,
                    "win_rate_pct": r.win_rate_pct,
                    "sharpe_approx": r.sharpe_approx,
                }
            )
    rows.sort(key=lambda x: -x["mean_daily_return_pct"])
    out = ROOT / "artifacts" / "backtest" / "sweep.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(json.dumps(rows[:8], indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()

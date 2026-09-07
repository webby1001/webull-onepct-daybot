"""Daily gap-continuation backtest on 1h bars aggregated to RTH daily OHLC.

Measures mean daily return = mean of day-over-day equity % changes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")


@dataclass
class BacktestResult:
    strategy_name: str
    start_equity: float
    end_equity: float
    return_pct: float
    mean_daily_return_pct: float
    compounded_total_return_pct: float
    max_drawdown_pct: float
    trade_count: int
    win_rate_pct: float
    trading_days: int
    win_day_pct: float
    sharpe_approx: float
    period_start: str
    period_end: str
    bar_size: str
    data_source: str
    symbols_used: int
    gap_min_pct: float
    max_notional_fraction: float
    stop_loss_pct: float
    take_profit_pct: float
    sample_label: str = "in-sample / paper / not a guarantee"
    notes: list[str] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def bars_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    et = df.copy()
    if et.index.tz is None:
        et.index = et.index.tz_localize("UTC")
    et.index = et.index.tz_convert(ET)
    mask = (
        (et.index.time >= time(9, 30))
        & (et.index.time <= time(16, 0))
        & (et.index.weekday < 5)
    )
    et = et.loc[mask]
    g = et.groupby(et.index.date)
    daily = pd.DataFrame(
        {
            "Open": g["Open"].first(),
            "High": g["High"].max(),
            "Low": g["Low"].min(),
            "Close": g["Close"].last(),
            "Volume": g["Volume"].sum() if "Volume" in et.columns else 0,
        }
    )
    daily.index = pd.to_datetime(daily.index)
    return daily


def run_gap_continuation_backtest(
    bars_by_symbol: dict[str, pd.DataFrame],
    *,
    start_equity: float = 1000.0,
    gap_min_pct: float = 1.5,
    max_notional_fraction: float = 1.0,
    stop_loss_pct: float = 0.0,
    take_profit_pct: float = 0.0,
    bar_size: str = "1h→daily",
    data_source: str = "yfinance",
) -> BacktestResult:
    dailies = {s: bars_to_daily(df) for s, df in bars_by_symbol.items() if df is not None and not df.empty}
    if not dailies:
        raise ValueError("No daily bars")

    dates = sorted(set.intersection(*[set(d.index) for d in dailies.values()]))
    if len(dates) < 3:
        raise ValueError("Not enough overlapping days")

    equity = [float(start_equity)]
    trades: list[dict] = []
    curve: list[dict] = [
        {"date": str(dates[0].date()), "equity": float(start_equity), "cash": float(start_equity), "symbol": None}
    ]

    for i in range(1, len(dates)):
        dt = dates[i]
        prev = dates[i - 1]
        cands: list[tuple[str, float, float]] = []
        for sym, daily in dailies.items():
            o = float(daily.loc[dt, "Open"])
            pc = float(daily.loc[prev, "Close"])
            if pc <= 0 or o <= 0:
                continue
            gap = (o / pc - 1.0) * 100.0
            if gap >= gap_min_pct:
                cands.append((sym, gap, o))
        if not cands:
            equity.append(equity[-1])
            curve.append(
                {"date": str(dt.date()), "equity": round(equity[-1], 4), "cash": round(equity[-1], 4), "symbol": None}
            )
            continue

        cands.sort(key=lambda x: -x[1])
        sym, gap, o = cands[0]
        high = float(dailies[sym].loc[dt, "High"])
        low = float(dailies[sym].loc[dt, "Low"])
        close = float(dailies[sym].loc[dt, "Close"])

        exit_px = close
        reason = "eod"
        # Conservative path: stop before take if both could be hit
        if stop_loss_pct > 0 and low <= o * (1 - stop_loss_pct / 100.0):
            exit_px = o * (1 - stop_loss_pct / 100.0)
            reason = "stop"
        elif take_profit_pct > 0 and high >= o * (1 + take_profit_pct / 100.0):
            exit_px = o * (1 + take_profit_pct / 100.0)
            reason = "take"

        # Full (or fraction) bankroll as notional; fractional shares allowed in paper math
        notional = equity[-1] * max_notional_fraction
        qty = notional / o
        pnl = (exit_px - o) * qty
        ret = pnl / equity[-1]
        new_eq = equity[-1] * (1 + ret * max_notional_fraction / max(max_notional_fraction, 1e-9))
        # When fraction==1, new_eq = equity * (exit/o)
        new_eq = equity[-1] + pnl
        equity.append(new_eq)
        trades.append(
            {
                "date": str(dt.date()),
                "symbol": sym,
                "gap_pct": round(gap, 4),
                "entry": round(o, 4),
                "exit": round(exit_px, 4),
                "qty": round(qty, 4),
                "pnl": round(pnl, 4),
                "ret_pct": round(ret * 100, 4),
                "reason": reason,
            }
        )
        curve.append(
            {
                "date": str(dt.date()),
                "equity": round(new_eq, 4),
                "cash": round(new_eq, 4),
                "symbol": sym,
                "gap_pct": round(gap, 4),
            }
        )

    eq = pd.Series(equity, index=dates)
    daily_rets = eq.pct_change().dropna()
    mean_daily = float(daily_rets.mean() * 100) if len(daily_rets) else 0.0
    total = (eq.iloc[-1] / eq.iloc[0] - 1.0) * 100
    peak = eq.cummax()
    max_dd = float(((peak - eq) / peak * 100).max()) if len(eq) else 0.0
    sharpe = (
        float(daily_rets.mean() / daily_rets.std() * np.sqrt(252))
        if len(daily_rets) and daily_rets.std() > 0
        else 0.0
    )
    wins = [t for t in trades if t["pnl"] > 0]
    win_days = float((daily_rets > 0).mean() * 100) if len(daily_rets) else 0.0

    notes = [
        "IN-SAMPLE / PAPER / NOT A GUARANTEE — results are historical simulation only.",
        f"Bar size: Yahoo 1h bars aggregated to RTH daily OHLC ({bar_size}).",
        "Signal: rank universe by overnight gap (Open vs prior Close); buy best if gap ≥ threshold.",
        f"Sizing: {max_notional_fraction*100:.0f}% of equity in a single name (concentrated; high risk).",
        "Fills at daily Open / exit at Close (or stop/take); no commissions, borrow, or slippage.",
        "Mean daily return = mean of day-over-day equity % changes (includes flat cash days).",
        "1%/day compounded is extreme (~3.5× over ~126 sessions); treat as research demo only.",
        "Live fills on large gaps are worse than open prints; capacity is limited.",
    ]

    result = BacktestResult(
        strategy_name="gap_continuation_top_mover",
        start_equity=float(start_equity),
        end_equity=round(float(eq.iloc[-1]), 4),
        return_pct=round(float(total), 4),
        mean_daily_return_pct=round(mean_daily, 4),
        compounded_total_return_pct=round(float(total), 4),
        max_drawdown_pct=round(max_dd, 4),
        trade_count=len(trades),
        win_rate_pct=round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        trading_days=len(daily_rets),
        win_day_pct=round(win_days, 2),
        sharpe_approx=round(sharpe, 4),
        period_start=str(dates[0].date()),
        period_end=str(dates[-1].date()),
        bar_size=bar_size,
        data_source=data_source,
        symbols_used=len(dailies),
        gap_min_pct=gap_min_pct,
        max_notional_fraction=max_notional_fraction,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        notes=notes,
        equity_curve=curve,
        trades=trades,
    )
    result.summary = {
        "strategy_name": result.strategy_name,
        "mean_daily_return_pct": result.mean_daily_return_pct,
        "compounded_total_return_pct": result.compounded_total_return_pct,
        "return_pct": result.return_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "trade_count": result.trade_count,
        "win_rate_pct": result.win_rate_pct,
        "trading_days": result.trading_days,
        "win_day_pct": result.win_day_pct,
        "sharpe_approx": result.sharpe_approx,
        "start_equity": result.start_equity,
        "end_equity": result.end_equity,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "bar_size": result.bar_size,
        "data_source": result.data_source,
        "symbols_used": result.symbols_used,
        "gap_min_pct": result.gap_min_pct,
        "max_notional_fraction": result.max_notional_fraction,
        "stop_loss_pct": result.stop_loss_pct,
        "take_profit_pct": result.take_profit_pct,
        "sample_label": result.sample_label,
        "notes": result.notes,
    }
    return result


def write_artifacts(result: BacktestResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(result.summary, indent=2), encoding="utf-8"
    )
    pd.DataFrame(result.equity_curve).to_csv(out_dir / "equity_curve.csv", index=False)
    pd.DataFrame(result.trades).to_csv(out_dir / "trades.csv", index=False)

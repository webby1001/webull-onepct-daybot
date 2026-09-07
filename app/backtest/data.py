"""Download / cache historical OHLCV (copied pattern from momentum-daybot)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_YF_SYMBOL_MAP = {"BRK.B": "BRK-B", "BRK.A": "BRK-A"}


def to_yahoo_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    return _YF_SYMBOL_MAP.get(s, s.replace(".", "-"))


def _ensure_prior_close(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    daily_last = out["Close"].groupby(out.index.date).last()
    prior = daily_last.shift(1)
    priors: list[float] = []
    first_open = float(out["Open"].iloc[0])
    for ts in out.index:
        p = prior.get(ts.date())
        if p is None or (isinstance(p, float) and pd.isna(p)):
            priors.append(first_open)
        else:
            priors.append(float(p))
    out["PriorClose"] = priors
    return out


def download_watchlist_bars(
    symbols: list[str],
    *,
    start: datetime,
    end: datetime,
    interval: str = "1h",
    cache_dir: Path | None = None,
    batch_size: int = 20,
    pause_sec: float = 1.0,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    import yfinance as yf

    cache_dir = Path(cache_dir) if cache_dir else None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    end_pad = (end + timedelta(days=1)).strftime("%Y-%m-%d")

    bars: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    need: list[str] = []

    for sym in symbols:
        ysym = to_yahoo_symbol(sym)
        cache_path = (
            cache_dir / f"{ysym}_{interval}_{start_s}_{end_s}.parquet" if cache_dir else None
        )
        # Also accept sibling daybot-style filenames already copied
        if cache_dir and not (cache_path and cache_path.exists()):
            alts = list(cache_dir.glob(f"{ysym}_{interval}_*.parquet"))
            if alts:
                cache_path = alts[0]
        if cache_path and cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                if not df.empty:
                    bars[sym.upper()] = _ensure_prior_close(df)
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Cache read failed %s: %s", cache_path, exc)
        need.append(sym)

    for i in range(0, len(need), batch_size):
        batch = need[i : i + batch_size]
        ysyms = [to_yahoo_symbol(s) for s in batch]
        logger.info("Downloading %s", ysyms)
        try:
            raw = yf.download(
                tickers=" ".join(ysyms) if len(ysyms) > 1 else ysyms[0],
                start=start_s,
                end=end_pad,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Batch failed: %s", exc)
            raw = None

        for sym, ysym in zip(batch, ysyms):
            df = _extract_symbol_frame(raw, ysym, single=len(ysyms) == 1)
            if df is None or df.empty:
                try:
                    df = yf.Ticker(ysym).history(
                        start=start_s, end=end_pad, interval=interval, auto_adjust=True
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Fail %s: %s", sym, exc)
                    failed.append(sym)
                    continue
            if df is None or df.empty:
                failed.append(sym)
                continue
            df = df.rename(columns={c: str(c).title() for c in df.columns})
            keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
            df = df[keep].dropna(subset=["Close"])
            if df.empty:
                failed.append(sym)
                continue
            df = _ensure_prior_close(df)
            bars[sym.upper()] = df
            if cache_dir:
                cache_path = cache_dir / f"{ysym}_{interval}_{start_s}_{end_s}.parquet"
                try:
                    df.drop(columns=["PriorClose"], errors="ignore").to_parquet(cache_path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Cache write failed: %s", exc)
        if i + batch_size < len(need) and pause_sec > 0:
            time.sleep(pause_sec)

    return bars, failed


def _extract_symbol_frame(raw: pd.DataFrame | None, ysym: str, *, single: bool) -> pd.DataFrame | None:
    if raw is None or raw.empty:
        return None
    if single or not isinstance(raw.columns, pd.MultiIndex):
        df = raw.copy()
    else:
        levels0 = set(map(str, raw.columns.get_level_values(0)))
        if ysym in levels0:
            df = raw[ysym].copy()
        elif ysym in set(map(str, raw.columns.get_level_values(-1))):
            df = raw.xs(ysym, axis=1, level=-1).copy()
        else:
            return None
    if isinstance(df, pd.Series):
        return None
    return df

# webull-onepct-daybot

**Separate** paper trading bot (sibling of `webull-momentum-daybot`) that targets **~1% average return per trading day** on a recent ~6-month US market window.

> **Hard honesty:** 1%/day is extreme — compounded \((1.01)^{126} \approx 3.5\times\) over ~126 sessions. Results here are **in-sample / paper / not a guarantee**. Fills use daily Open→Close with **no commissions or slippage**. Concentrated full-bankroll sizing can wipe the account. This is a research demo, not financial advice, and **not** for live trading by default.

Default HTTP port: **8082** (does not bind 8081 / primary daybot).

## Strategy: Gap Continuation Top Mover

1. Universe: high-beta names + leveraged ETFs (`TQQQ`, `SOXL`, `SPXL`, `NVDA`, `TSLA`, `MSTR`, …).
2. Each RTH day, rank by **overnight gap** = Open / prior Close − 1.
3. If best gap ≥ `GAP_MIN_PCT` (default **1.5%**), buy that name with up to **100%** of equity (`MAX_NOTIONAL_FRACTION=1.0`).
4. Exit at the close (optional stop/take via env; defaults off — best in-sample mean daily).
5. Flat / cash when no qualifying gap.

**Bar size:** Yahoo Finance **1h** bars aggregated to RTH **daily OHLC** for the backtest. The live paper bot scans on an interval (default 5m) using last/open/prior-close quotes.

## In-sample backtest (cached ~6m)

After `scripts/backtest_6m.py`:

| Metric | Typical (gap≥1.5%, no stop) |
|--------|-----------------------------|
| Mean daily return | **≥ 1.0%** (see `artifacts/backtest/summary.json`) |
| Compounded total | large (path-dependent) |
| Max drawdown | material (~20–30%+) |
| Label | in-sample / paper / not a guarantee |

What would be needed for a *robust* 1%/day live: tighter risk, realistic slippage, capacity limits, out-of-sample validation, and acceptance that most periods will **not** look like this window.

## Quick start

```bash
cd webull-onepct-daybot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Paper API (mock broker)
python -m app
# → http://0.0.0.0:8082/  /health  /status  POST /force-scan
```

```bash
# Backtest (~6 months, uses artifacts/backtest/cache parquet when present)
python scripts/backtest_6m.py
python scripts/strategy_sweep.py
pytest -q
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Status UI |
| GET | `/health` | Liveness |
| GET | `/status` | Strategy + risk + last scan |
| GET | `/positions` | Open positions |
| GET | `/orders` | Order audit |
| POST | `/force-scan` | Run gap scan now |
| POST | `/flatten-all` | Close all |

## Config

See `.env.example`. Important knobs: `GAP_MIN_PCT`, `MAX_NOTIONAL_FRACTION`, `STOP_LOSS_PCT`, `PAPER_BANKROLL`, `PORT=8082`, `WATCHLIST`.

## Relation to momentum-daybot

This repo is intentionally **separate**. It does not change `webull-momentum-daybot` defaults. Cache files may be copied from the sibling project’s `artifacts/backtest/cache` for speed.

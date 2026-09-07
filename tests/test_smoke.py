"""Smoke tests for config, strategy sizing, and backtest metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from app.broker.mock import MockBroker
from app.config import Settings, get_settings
from app.market.quotes import Quote, QuoteService
from app.risk.bankroll import BankrollRisk, SessionGate
from app.strategy.gap_continuation import GapContinuationStrategy
from app.backtest.engine import bars_to_daily, run_gap_continuation_backtest


def test_default_port_8082():
    s = Settings()
    assert s.port == 8082
    assert s.paper_bankroll == 1000.0
    assert s.gap_min_pct == 1.5


def test_session_gate_weekday():
    gate = SessionGate("09:35", "15:55")
    et = ZoneInfo("America/New_York")
    monday_open = datetime(2026, 3, 9, 10, 0, tzinfo=et)
    assert gate.is_within_session(monday_open)
    monday_late = datetime(2026, 3, 9, 16, 0, tzinfo=et)
    assert gate.should_flatten(monday_late)


def test_mock_broker_roundtrip():
    b = MockBroker(1000)
    from app.broker.base import OrderRequest

    r = b.place_order(OrderRequest("TQQQ", "BUY", 10, "LIMIT", 50.0))
    assert r.ok
    assert abs(b.cash - 500) < 1e-6
    r2 = b.place_order(OrderRequest("TQQQ", "SELL", 10, "LIMIT", 55.0))
    assert r2.ok
    assert abs(b.cash - 1050) < 1e-6
    assert len(b.closed_trades) == 1


class StubQuotes(QuoteService):
    def __init__(self, quotes: dict[str, Quote]):
        self._q = quotes
        self.settings = Settings()

    def get_quotes(self, symbols=None):
        return {s: self._q[s] for s in (symbols or self._q) if s in self._q}


def test_gap_strategy_enters_best_gap():
    settings = Settings(gap_min_pct=1.5, max_notional_fraction=1.0)
    broker = MockBroker(1000)
    risk = BankrollRisk(1000, 25, 1)
    gate = SessionGate("00:00", "23:59")  # always open for unit test
    quotes = StubQuotes(
        {
            "AAA": Quote("AAA", last=101, open=101, prior_close=100),  # 1% gap
            "BBB": Quote("BBB", last=103, open=103, prior_close=100),  # 3% gap
        }
    )
    settings.watchlist = ["AAA", "BBB"]
    # freeze clock inside session
    et = ZoneInfo("America/New_York")
    clock = lambda: datetime(2026, 3, 9, 10, 0, tzinfo=et)
    strat = GapContinuationStrategy(broker, settings, quotes, risk, gate, clock=clock)
    res = strat.scan_and_trade(force=True)
    assert res.entries
    assert res.entries[0]["symbol"] == "BBB"
    assert broker.get_positions()[0].symbol == "BBB"


def test_backtest_mean_daily_on_synthetic():
    # Build 5 days where we always buy a +2% open→close winner
    idx = pd.date_range("2026-03-09 13:30", periods=5 * 7, freq="1h", tz="UTC")
    # crude synthetic hourly
    rows = []
    for i, ts in enumerate(idx):
        day = i // 7
        bar = i % 7
        # prior close path: day d close = 100 + d
        base = 100 + day
        if bar == 0:
            o, c = base * 1.02, base * 1.02  # gap open
        else:
            o, c = base * 1.025, base * 1.04
        rows.append({"Open": o, "High": max(o, c), "Low": min(o, c), "Close": c, "Volume": 1e6})
    df = pd.DataFrame(rows, index=idx)
    # Need prior days — simpler: two symbols with clear gaps
    dates = pd.bdate_range("2026-03-09", periods=10)
    # Build daily-like 1h frames manually via repeating
    def make_sym(mult_gap: float):
        frames = []
        px = 100.0
        for d in dates:
            # 7 hourly bars labeled 13:30..19:30 UTC (~9:30-15:30 ET)
            for h in range(7):
                ts = datetime(d.year, d.month, d.day, 13 + h, 30, tzinfo=timezone.utc)
                if h == 0:
                    o = px * (1 + mult_gap)
                    c = o
                else:
                    o = px * (1 + mult_gap + 0.005)
                    c = px * (1 + mult_gap + 0.02)
                frames.append((ts, o, max(o, c), min(o, c) * 0.99, c, 1e6))
            px = frames[-1][4]  # next prior close
        idx2 = [f[0] for f in frames]
        return pd.DataFrame(
            {"Open": [f[1] for f in frames], "High": [f[2] for f in frames],
             "Low": [f[3] for f in frames], "Close": [f[4] for f in frames],
             "Volume": [f[5] for f in frames]},
            index=pd.DatetimeIndex(idx2),
        )

    bars = {"GAPA": make_sym(0.02), "FLAT": make_sym(0.0)}
    # Sanity daily aggregation
    d = bars_to_daily(bars["GAPA"])
    assert len(d) >= 5
    result = run_gap_continuation_backtest(bars, gap_min_pct=1.5, start_equity=1000)
    assert result.trading_days >= 5
    assert "mean_daily_return_pct" in result.summary
    assert result.trade_count >= 1

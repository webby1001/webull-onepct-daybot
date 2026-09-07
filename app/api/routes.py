"""HTTP API: health, status, positions, orders, force-scan, flatten-all."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    html_path = Path(__file__).resolve().parents[1] / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


def _state(request: Request):
    return request.app.state


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "webull-onepct-daybot"}


@router.get("/status")
def status(request: Request) -> dict:
    st = _state(request)
    settings = st.settings
    strategy = st.strategy
    broker = st.broker
    positions = broker.get_positions()
    return {
        "ok": True,
        "service": "webull-onepct-daybot",
        "strategy_name": settings.strategy_name,
        "broker": getattr(broker, "name", "unknown"),
        "trading_mode": settings.trading_mode,
        "allow_live_trading": settings.allow_live_trading,
        "host": settings.resolved_host(),
        "keys_configured": settings.has_webull_keys,
        "account_id_configured": bool(settings.webull_account_id.strip()),
        "paper_bankroll": settings.paper_bankroll,
        "gap_min_pct": settings.gap_min_pct,
        "max_notional_fraction": settings.max_notional_fraction,
        "stop_loss_pct": settings.stop_loss_pct,
        "take_profit_pct": settings.take_profit_pct,
        "watchlist_size": len(settings.watchlist),
        "watchlist_sample": settings.watchlist[:12],
        "scan_interval_minutes": settings.scan_interval_minutes,
        "port": settings.port,
        "disclaimer": "IN-SAMPLE / PAPER / NOT A GUARANTEE",
        "session": {
            "start_et": settings.session_start_et,
            "flatten_et": settings.flatten_et,
            "timezone": settings.timezone,
            "within_session": strategy.gate.is_within_session(),
            "should_flatten": strategy.gate.should_flatten(),
        },
        "risk": {
            "realized_pnl_today": strategy.risk.realized_pnl_today,
            "max_daily_loss_dollars": strategy.risk.max_daily_loss_dollars,
            "halted": strategy.risk.halted,
            "halt_reason": strategy.risk.halt_reason,
            "open_positions": len(positions),
            "cash": getattr(broker, "cash", None),
        },
        "last_scan": None
        if strategy.last_scan is None
        else {
            "scanned_at": strategy.last_scan.scanned_at,
            "message": strategy.last_scan.message,
            "entries": strategy.last_scan.entries,
            "exits": strategy.last_scan.exits,
            "candidates": strategy.last_scan.candidates[:10],
        },
    }


@router.get("/positions")
def positions(request: Request) -> dict:
    broker = _state(request).broker
    strategy = _state(request).strategy
    out = []
    for p in broker.get_positions():
        out.append(
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_entry": p.avg_entry,
                "stop_price": strategy._stops.get(p.symbol),
                "take_profit_price": strategy._tps.get(p.symbol),
                "opened_at": p.opened_at.isoformat(),
            }
        )
    return {"positions": out}


@router.get("/orders")
def orders(request: Request) -> dict:
    broker = _state(request).broker
    return {
        "orders": [
            {
                "client_order_id": o.client_order_id,
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.quantity,
                "status": o.status,
                "fill_price": o.fill_price,
                "error": o.error,
            }
            for o in broker.get_orders()[-100:]
        ]
    }


@router.post("/force-scan")
def force_scan(request: Request) -> dict:
    strategy = _state(request).strategy
    result = strategy.scan_and_trade(force=True)
    return {
        "ok": True,
        "message": result.message,
        "entries": result.entries,
        "exits": result.exits,
        "candidates": result.candidates[:10],
    }


@router.post("/flatten-all")
def flatten_all(request: Request) -> dict:
    strategy = _state(request).strategy
    exits = strategy.flatten_all(reason="manual_flatten")
    return {"ok": True, "exits": exits}

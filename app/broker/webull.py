"""Webull sandbox/live equity broker client (adapted for onepct interfaces)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.broker.base import OrderRequest, OrderResult, Position
from app.broker.mock import MockBroker
from app.broker.signature import (
    compact_json,
    generate_webull_signature,
    new_nonce,
    utc_timestamp,
)
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

LIVE_HOSTS = {"api.webull.com", "api.webull.hk"}


class WebullLiveBlockedError(RuntimeError):
    pass


class WebullApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Webull API {status}: {body[:400]}")
        self.status = status
        self.body = body


class WebullBroker:
    """Signed Webull OpenAPI client for US EQUITY place/cancel.

    Mirrors successful submits into a local MockBroker so gap_continuation can
    use equity()/cash/closed_trades/get_positions while sandbox fills may lag.
    """

    name = "webull"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.host = self.settings.resolved_host()
        self._audit: list[OrderResult] = []
        self._local = MockBroker(starting_cash=self.settings.paper_bankroll)

    @property
    def cash(self) -> float:
        return self._local.cash

    @property
    def closed_trades(self):
        return self._local.closed_trades

    def equity(self, marks: dict[str, float] | None = None) -> float:
        return self._local.equity(marks)

    def _assert_not_live_blocked(self) -> None:
        if self.host.lower() in LIVE_HOSTS and not self.settings.allow_live_trading:
            raise WebullLiveBlockedError(
                "Production Webull host blocked: set ALLOW_LIVE_TRADING=true "
                "and TRADING_MODE=live."
            )

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: Any = None,
        version: str = "v2",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict | list | None, str]:
        self._assert_not_live_blocked()
        if not self.settings.has_webull_keys:
            raise WebullApiError(0, "Missing WEBULL_APP_KEY / WEBULL_APP_SECRET")

        timestamp = utc_timestamp()
        nonce = new_nonce()
        body_string = compact_json(body) if body is not None else None
        signature = generate_webull_signature(
            path=path,
            query=query,
            body=body_string,
            app_key=self.settings.webull_app_key,
            app_secret=self.settings.webull_app_secret,
            host=self.host,
            timestamp=timestamp,
            nonce=nonce,
        )
        headers = {
            "x-app-key": self.settings.webull_app_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "x-version": version,
            "Accept": "application/json",
            **(extra_headers or {}),
        }
        url = f"https://{self.host}{path}"
        if method.upper() == "POST":
            headers["Content-Type"] = "application/json"

        with httpx.Client(timeout=30.0) as client:
            resp = client.request(
                method.upper(),
                url,
                params=query,
                content=body_string if method.upper() == "POST" else None,
                headers=headers,
            )
        text = resp.text
        data: dict | list | None = None
        if text:
            try:
                data = resp.json()
            except Exception:
                data = None
        return resp.status_code, data, text

    def place_order(self, req: OrderRequest) -> OrderResult:
        account_id = self.settings.webull_account_id.strip()
        qty = int(req.quantity)
        if not account_id:
            result = OrderResult(
                ok=False,
                client_order_id=req.client_order_id or "",
                order_id=None,
                symbol=req.symbol,
                side=req.side,
                quantity=req.quantity,
                order_type=req.order_type,
                limit_price=req.limit_price,
                status="REJECTED",
                error="WEBULL_ACCOUNT_ID not set",
                broker=self.name,
            )
            self._audit.append(result)
            return result

        if qty < 1:
            result = OrderResult(
                ok=False,
                client_order_id=req.client_order_id or "",
                order_id=None,
                symbol=req.symbol,
                side=req.side,
                quantity=req.quantity,
                order_type=req.order_type,
                limit_price=req.limit_price,
                status="REJECTED",
                error="quantity must be >= 1 share",
                broker=self.name,
            )
            self._audit.append(result)
            return result

        cid = (
            (req.client_order_id or f"eq{int(time.time() * 1000)}")
            .replace("-", "")
            .replace(":", "")[:32]
        )
        order: dict[str, Any] = {
            "combo_type": "NORMAL",
            "client_order_id": cid,
            "symbol": req.symbol.upper(),
            "instrument_type": "EQUITY",
            "market": "US",
            "order_type": req.order_type,
            "quantity": str(qty),
            "side": req.side,
            "time_in_force": "DAY",
            "support_trading_session": "CORE",
            "entrust_type": "QTY",
        }
        if req.order_type == "LIMIT":
            if req.limit_price is None:
                result = OrderResult(
                    ok=False,
                    client_order_id=cid,
                    order_id=None,
                    symbol=req.symbol,
                    side=req.side,
                    quantity=req.quantity,
                    order_type=req.order_type,
                    limit_price=req.limit_price,
                    status="REJECTED",
                    error="limit_price required for LIMIT orders",
                    broker=self.name,
                )
                self._audit.append(result)
                return result
            order["limit_price"] = f"{req.limit_price:.2f}"

        body = {"account_id": account_id, "new_orders": [order]}
        try:
            status, data, text = self.request(
                "POST",
                "/openapi/trade/order/place",
                body=body,
            )
        except (WebullLiveBlockedError, WebullApiError, httpx.HTTPError) as exc:
            result = OrderResult(
                ok=False,
                client_order_id=cid,
                order_id=None,
                symbol=req.symbol,
                side=req.side,
                quantity=req.quantity,
                order_type=req.order_type,
                limit_price=req.limit_price,
                status="ERROR",
                error=str(exc),
                broker=self.name,
            )
            self._audit.append(result)
            return result

        ok = 200 <= status < 300
        order_id = None
        if isinstance(data, dict):
            order_id = data.get("order_id") or data.get("client_order_id")
            if not order_id and isinstance(data.get("data"), dict):
                order_id = data["data"].get("order_id")
        result = OrderResult(
            ok=ok,
            client_order_id=cid,
            order_id=str(order_id) if order_id else None,
            symbol=req.symbol,
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
            limit_price=req.limit_price,
            status="SUBMITTED" if ok else "REJECTED",
            error=None if ok else text[:400],
            broker=self.name,
            fill_price=req.limit_price if ok else None,
        )
        self._audit.append(result)
        if ok:
            # Mirror into local book for UI/status (sandbox fills may lag)
            mirror = OrderRequest(
                symbol=req.symbol,
                side=req.side,
                quantity=qty,
                order_type=req.order_type,
                limit_price=req.limit_price,
                client_order_id=cid,
            )
            self._local.place_order(mirror)
        return result

    def cancel_order(self, order_id: str) -> OrderResult:
        account_id = self.settings.webull_account_id.strip()
        body = {"account_id": account_id, "client_order_id": order_id}
        try:
            status, data, text = self.request(
                "POST",
                "/openapi/trade/order/cancel",
                body=body,
            )
        except (WebullLiveBlockedError, WebullApiError, httpx.HTTPError) as exc:
            result = OrderResult(
                ok=False,
                client_order_id=order_id,
                order_id=order_id,
                symbol="",
                side="BUY",
                quantity=0,
                order_type="MARKET",
                limit_price=None,
                status="ERROR",
                error=str(exc),
                broker=self.name,
            )
            self._audit.append(result)
            return result
        ok = 200 <= status < 300
        result = OrderResult(
            ok=ok,
            client_order_id=order_id,
            order_id=order_id,
            symbol="",
            side="BUY",
            quantity=0,
            order_type="MARKET",
            limit_price=None,
            status="CANCELLED" if ok else "REJECTED",
            error=None if ok else text[:400],
            broker=self.name,
        )
        self._audit.append(result)
        return result

    def get_positions(self) -> list[Position]:
        return self._local.get_positions()

    def get_orders(self) -> list[OrderResult]:
        return list(self._audit) + self._local.get_orders()

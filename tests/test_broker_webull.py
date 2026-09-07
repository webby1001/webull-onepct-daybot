"""HMAC signature + broker factory selection (no network)."""

from __future__ import annotations

import pytest

from app.broker import create_broker
from app.broker.mock import MockBroker
from app.broker.signature import generate_webull_signature
from app.broker.webull import LIVE_HOSTS, WebullBroker, WebullLiveBlockedError
from app.config import Settings


def test_signature_deterministic():
    sig = generate_webull_signature(
        path="/openapi/account/list",
        app_key="testkey",
        app_secret="testsecret",
        host="api.sandbox.webull.com",
        timestamp="2026-09-07T15:00:00Z",
        nonce="abc123",
        body=None,
    )
    sig2 = generate_webull_signature(
        path="/openapi/account/list",
        app_key="testkey",
        app_secret="testsecret",
        host="api.sandbox.webull.com",
        timestamp="2026-09-07T15:00:00Z",
        nonce="abc123",
        body=None,
    )
    assert sig == sig2
    assert isinstance(sig, str) and len(sig) > 10


def test_signature_with_body_differs():
    empty = generate_webull_signature(
        path="/openapi/trade/order/place",
        app_key="k",
        app_secret="s",
        host="api.sandbox.webull.com",
        timestamp="2026-09-07T15:00:00Z",
        nonce="n1",
        body=None,
    )
    with_body = generate_webull_signature(
        path="/openapi/trade/order/place",
        app_key="k",
        app_secret="s",
        host="api.sandbox.webull.com",
        timestamp="2026-09-07T15:00:00Z",
        nonce="n1",
        body='{"account_id":"1"}',
    )
    assert empty != with_body


def test_factory_mock_without_keys():
    s = Settings(webull_app_key="", webull_app_secret="")
    b = create_broker(s)
    assert isinstance(b, MockBroker)
    assert b.name == "mock"


def test_factory_webull_with_keys():
    s = Settings(
        webull_app_key="k",
        webull_app_secret="s",
        webull_account_id="acct1",
        trading_mode="paper",
        allow_live_trading=False,
        webull_api_host="api.sandbox.webull.com",
    )
    b = create_broker(s)
    assert isinstance(b, WebullBroker)
    assert b.name == "webull"
    assert b.host == "api.sandbox.webull.com"


def test_resolved_host_blocks_prod_without_dual_opt_in():
    s = Settings(
        trading_mode="paper",
        allow_live_trading=False,
        webull_api_host="api.webull.com",
    )
    assert s.resolved_host() == "api.sandbox.webull.com"
    s2 = Settings(
        trading_mode="live",
        allow_live_trading=False,
        webull_api_host="api.webull.com",
    )
    assert s2.resolved_host() == "api.sandbox.webull.com"
    s3 = Settings(
        trading_mode="live",
        allow_live_trading=True,
        webull_api_host="api.webull.com",
    )
    assert s3.resolved_host() == "api.webull.com"


def test_live_block_raises_on_prod_host_without_allow():
    s = Settings(
        webull_app_key="k",
        webull_app_secret="s",
        webull_account_id="a",
        trading_mode="live",
        allow_live_trading=False,
        webull_api_host="api.sandbox.webull.com",
    )
    b = WebullBroker(s)
    # Force production host as if dual-opt-in host resolution were bypassed
    b.host = "api.webull.com"
    assert b.host in LIVE_HOSTS
    with pytest.raises(WebullLiveBlockedError):
        b.request("GET", "/openapi/account/list")


def test_place_order_rejects_missing_account_id():
    s = Settings(
        webull_app_key="k",
        webull_app_secret="s",
        webull_account_id="",
        trading_mode="paper",
    )
    b = WebullBroker(s)
    from app.broker.base import OrderRequest

    r = b.place_order(
        OrderRequest(symbol="TQQQ", side="BUY", quantity=1, order_type="LIMIT", limit_price=50.0)
    )
    assert not r.ok
    assert "ACCOUNT_ID" in (r.error or "")

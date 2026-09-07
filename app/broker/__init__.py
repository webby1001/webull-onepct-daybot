"""Broker adapters: mock (no keys) and Webull sandbox equity."""

from __future__ import annotations

import logging

from app.broker.base import Broker, OrderRequest, OrderResult, Position
from app.broker.mock import MockBroker
from app.config import Settings

logger = logging.getLogger(__name__)


def create_broker(settings: Settings):
    """Mock if no keys; Webull sandbox/live client when WEBULL_APP_KEY+SECRET set.

    Live/production hosts still require TRADING_MODE=live AND ALLOW_LIVE_TRADING=true
    (enforced via Settings.resolved_host + WebullBroker live block).
    """
    if settings.has_webull_keys:
        from app.broker.webull import WebullBroker

        logger.info(
            "Using WebullBroker host=%s mode=%s",
            settings.resolved_host(),
            settings.trading_mode,
        )
        return WebullBroker(settings)
    logger.info("WEBULL keys missing — using MockBroker (paper demo)")
    return MockBroker(starting_cash=settings.paper_bankroll)


__all__ = [
    "Broker",
    "OrderRequest",
    "OrderResult",
    "Position",
    "MockBroker",
    "create_broker",
]

"""FastAPI entrypoint — paper gap-continuation bot on port 8082."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.broker import create_broker
from app.config import get_settings
from app.market.quotes import QuoteService
from app.risk.bankroll import BankrollRisk, SessionGate
from app.scheduler.jobs import BotScheduler
from app.strategy.gap_continuation import GapContinuationStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    broker = create_broker(settings)
    quotes = QuoteService(settings)
    risk = BankrollRisk(
        bankroll=settings.paper_bankroll,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        max_open_positions=settings.max_open_positions,
    )
    gate = SessionGate.from_settings(settings)
    strategy = GapContinuationStrategy(
        broker=broker,
        settings=settings,
        quotes=quotes,
        risk=risk,
        gate=gate,
    )
    scheduler = BotScheduler(strategy, settings)
    scheduler.start()

    app.state.settings = settings
    app.state.broker = broker
    app.state.strategy = strategy
    app.state.scheduler = scheduler

    logger.info(
        "webull-onepct-daybot up — strategy=%s broker=%s mode=%s bankroll=%.0f port=%s",
        settings.strategy_name,
        getattr(broker, "name", "?"),
        settings.trading_mode,
        settings.paper_bankroll,
        settings.port,
    )
    yield
    scheduler.shutdown()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Webull OnePct Daybot",
    description="Paper-first gap-continuation bot targeting ~1% mean daily return (in-sample / not a guarantee)",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)

"""APScheduler wrapper for periodic gap scans."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings
from app.strategy.gap_continuation import GapContinuationStrategy

logger = logging.getLogger(__name__)


class BotScheduler:
    def __init__(self, strategy: GapContinuationStrategy, settings: Settings) -> None:
        self.strategy = strategy
        self.settings = settings
        self.scheduler = BackgroundScheduler(timezone=settings.timezone)

    def start(self) -> None:
        mins = max(1, int(self.settings.scan_interval_minutes))
        self.scheduler.add_job(
            self._tick,
            "interval",
            minutes=mins,
            id="gap_scan",
            replace_existing=True,
            max_instances=1,
        )
        self.scheduler.start()
        logger.info("Scheduler started — every %s min", mins)

    def _tick(self) -> None:
        try:
            self.strategy.scan_and_trade(force=False)
        except Exception:  # noqa: BLE001
            logger.exception("scan tick failed")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

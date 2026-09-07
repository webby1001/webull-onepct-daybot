from app.broker.mock import MockBroker
from app.config import Settings


def create_broker(settings: Settings):
    """Paper-first: always mock unless live keys + dual opt-in (not implemented for live)."""
    return MockBroker(starting_cash=settings.paper_bankroll)

"""MoneyBee portal API modules.

Portal routes are transport adapters over MoneyBee's authoritative domain model.
They never trust client-provided tenant identifiers and never enable live provider
capabilities by themselves.
"""

from app.portal.router import router

__all__ = ["router"]

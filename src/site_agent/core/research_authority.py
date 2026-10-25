"""Durable fences for local research and recommendation producers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PRODUCER_FREEZE_KEY = "crawlseo_migration:producer_freeze"
CONNECTOR_DISPATCH_HOLD_KEY = "crawlseo_activation:connector_dispatch_hold"
_MISSING = object()


def producer_frozen(memory: Any) -> bool:
    """Return whether local research producers are frozen for migration.

    Missing state is the normal unfrozen state. A malformed persisted value is
    treated as frozen so a damaged migration fence cannot silently resume paid
    research or recommendation generation.
    """
    getter = getattr(memory, "kv_get", None)
    if not callable(getter):
        return False
    try:
        try:
            state = getter(PRODUCER_FREEZE_KEY, _MISSING)
        except TypeError:  # Lightweight compatibility for simple test/service adapters.
            state = getter(PRODUCER_FREEZE_KEY)
    except Exception:  # noqa: BLE001 — persistence uncertainty fails closed
        return True
    if state is _MISSING:
        return False
    if not isinstance(state, Mapping) or type(state.get("active")) is not bool:
        return True
    return state["active"]


def require_research_producers_enabled(memory: Any) -> None:
    """Raise before local research/recommendation producer work when frozen."""
    if producer_frozen(memory):
        raise RuntimeError("Local research and recommendation producers are frozen for CrawlSEO migration")


def require_connector_dispatch_enabled(memory: Any) -> None:
    """Hold new connector effects until cutover runtime verification commits."""
    getter = getattr(memory, "kv_get", None)
    if not callable(getter):
        return
    state = getter(CONNECTOR_DISPATCH_HOLD_KEY, None)
    if state is None:
        return  # Existing authoritative installations have no migration hold.
    if not isinstance(state, Mapping) or state.get("active") is not False:
        raise RuntimeError("CrawlSEO connector dispatch is paused pending activation verification")

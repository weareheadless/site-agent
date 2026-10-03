"""One bounded billing boundary for every paid growth producer."""

from __future__ import annotations

import datetime
import hashlib
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from ..core.contracts import ContractError
from ..core.growth_contracts import growth_timezone


class GrowthBudgetBlocked(RuntimeError):
    """A paid operation cannot proceed without owner/operator reconciliation."""


def budget_period(config: Mapping[str, Any], now: datetime.datetime | None = None) -> str:
    current = now or datetime.datetime.now(datetime.timezone.utc)
    return current.astimezone(ZoneInfo(growth_timezone(config))).strftime("%Y-%m")


def _growth_settings(config: Mapping[str, Any]) -> Mapping[str, Any]:
    return config.get("growth") if isinstance(config.get("growth"), Mapping) else {}


def quote_micros(config: Mapping[str, Any], operation: str) -> int:
    settings = _growth_settings(config)
    quotes = settings.get("research_quotes_micros")
    value = quotes.get(operation) if isinstance(quotes, Mapping) and quotes.get(operation) is not None else settings.get("research_quote_micros", 100_000)
    try:
        amount = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"growth research quote for {operation} must be an integer") from exc
    if amount < 0:
        raise ContractError(f"growth research quote for {operation} cannot be negative")
    return amount


def allowance_micros(config: Mapping[str, Any]) -> int:
    try:
        amount = int(_growth_settings(config).get("monthly_research_cap_micros", 500_000))
    except (TypeError, ValueError) as exc:
        raise ContractError("growth.monthly_research_cap_micros must be an integer") from exc
    if amount < 0:
        raise ContractError("growth.monthly_research_cap_micros cannot be negative")
    return amount


def reserve_paid_research(context: Mapping[str, Any], *, idempotency_key: str, operation: str, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    memory = context["memory"]
    config = context.get("config") if isinstance(context.get("config"), Mapping) else {}
    period = budget_period(config)
    idempotency_key = str(idempotency_key or "").strip()
    if not idempotency_key:
        raise ContractError("paid research idempotency key is required")
    reservation_id = "growth-budget-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    reservation = memory.reserve_growth_budget(
        reservation_id=reservation_id,
        period=period,
        idempotency_key=idempotency_key,
        amount_micros=quote_micros(config, operation),
        cap_micros=allowance_micros(config),
        operation=operation,
        detail={"period": period, **dict(detail or {})},
    )
    status = str(reservation.get("status") or "reserved")
    if status != "reserved":
        raise GrowthBudgetBlocked(f"paid {operation} is {status}; reconcile reservation {reservation.get('reservation_id')} before retrying")
    return reservation


def settle_paid_research(context: Mapping[str, Any], reservation_id: str, *, provider_task_id: str | None, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return context["memory"].settle_growth_budget(reservation_id, status="settled", provider_task_id=provider_task_id, detail=dict(detail or {}))


def release_paid_research(context: Mapping[str, Any], reservation_id: str, *, reason: str) -> dict[str, Any]:
    return context["memory"].settle_growth_budget(reservation_id, status="released", detail={"reason": str(reason or "provider rejected the request before dispatch")[:500]})


def mark_paid_research_uncertain(context: Mapping[str, Any], reservation_id: str, *, error: str) -> dict[str, Any]:
    return context["memory"].settle_growth_budget(reservation_id, status="uncertain", detail={"error": str(error or "provider outcome is unknown")[:500]})


__all__ = ["GrowthBudgetBlocked", "allowance_micros", "budget_period", "mark_paid_research_uncertain", "quote_micros", "release_paid_research", "reserve_paid_research", "settle_paid_research"]

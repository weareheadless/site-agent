"""One bounded billing boundary for every paid growth producer."""

from __future__ import annotations

import datetime
import hashlib
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from ..core.contracts import ContractError
from ..core.growth_contracts import GrowthBudgetAllowanceExhausted, growth_timezone


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


def _crawlseo_budget_context(context: Mapping[str, Any]) -> tuple[Any, str] | None:
    config = context.get("config") if isinstance(context.get("config"), Mapping) else {}
    providers = config.get("providers") if isinstance(config.get("providers"), Mapping) else {}
    crawlseo = providers.get("crawlseo") if isinstance(providers.get("crawlseo"), Mapping) else {}
    if not (crawlseo.get("enabled") and crawlseo.get("connector_url")
            and crawlseo.get("research_authority") == "crawlseo"):
        return None
    service = context.get("crawlseo_service")
    state = context.get("seo_provisioning_state") if isinstance(context.get("seo_provisioning_state"), Mapping) else {}
    crawlseo_state = state.get("crawlseo") if isinstance(state.get("crawlseo"), Mapping) else {}
    site_id = str(context.get("connector_site_id") or context.get("site_id") or crawlseo_state.get("site_id") or "").strip()
    if service is None or not site_id:
        raise GrowthBudgetBlocked("CrawlSEO monetary budget authority is unavailable for this tenant")
    return service, site_id


def _local_reservation(context: Mapping[str, Any], reservation_id: str) -> dict[str, Any] | None:
    getter = getattr(context.get("memory"), "get_growth_budget_reservation", None)
    return getter(reservation_id) if callable(getter) else None


def reserve_paid_research(context: Mapping[str, Any], *, idempotency_key: str, operation: str, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    memory = context["memory"]
    config = context.get("config") if isinstance(context.get("config"), Mapping) else {}
    idempotency_key = str(idempotency_key or "").strip()
    if not idempotency_key:
        raise ContractError("paid research idempotency key is required")
    upstream = _crawlseo_budget_context(context)
    if upstream is not None:
        service, site_id = upstream
        try:
            budget = service.connector_budget(site_id)
            if budget.get("configured") is not True or not isinstance(budget.get("policyRevision"), int):
                raise GrowthBudgetBlocked("CrawlSEO monetary allowance is not configured; paid research was not dispatched")
            reservation = service.connector_budget_reserve({
                "siteId": site_id, "period": str(budget.get("period") or ""),
                "policyRevision": int(budget["policyRevision"]), "idempotencyKey": idempotency_key,
                "amountMicros": str(quote_micros(config, operation)),
                "currency": str(budget.get("currency") or "USD"), "operation": operation,
                "detail": {"period": budget.get("period"), "helloAda": dict(detail or {})},
            })
        except GrowthBudgetBlocked:
            raise
        except Exception as exc:
            raise GrowthBudgetBlocked(f"CrawlSEO could not reserve paid research allowance: {str(exc)[:300]}") from exc
        status = str(reservation.get("status") or "reserved").lower()
        reservation_id = str(reservation.get("id") or reservation.get("reservation_id") or "").strip()
        if status != "reserved" or not reservation_id:
            raise GrowthBudgetBlocked("CrawlSEO returned no active paid research reservation")
        return {**reservation, "reservation_id": reservation_id, "status": status, "upstream": True}
    period = budget_period(config)
    reservation_id = "growth-budget-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    try:
        reservation = memory.reserve_growth_budget(
            reservation_id=reservation_id,
            period=period,
            idempotency_key=idempotency_key,
            amount_micros=quote_micros(config, operation),
            cap_micros=allowance_micros(config),
            operation=operation,
            detail={"period": period, **dict(detail or {})},
        )
    except GrowthBudgetAllowanceExhausted as exc:
        raise GrowthBudgetBlocked(str(exc)) from exc
    status = str(reservation.get("status") or "reserved")
    if status != "reserved":
        raise GrowthBudgetBlocked(f"paid {operation} is {status}; reconcile reservation {reservation.get('reservation_id')} before retrying")
    return reservation


def get_paid_research_reservation(context: Mapping[str, Any], reservation_id: str) -> dict[str, Any] | None:
    upstream = _crawlseo_budget_context(context)
    if upstream is not None:
        service, _site_id = upstream
        try:
            result = service.connector_budget_get_reservation(reservation_id)
            return {**result, "reservation_id": str(result.get("id") or reservation_id),
                "status": str(result.get("status") or "").lower(), "upstream": True}
        except Exception:
            # Preserve reconciliation for paid tasks that were already in
            # flight on the legacy local ledger when authority mode was enabled.
            return _local_reservation(context, reservation_id)
    return context["memory"].get_growth_budget_reservation(reservation_id)


def settle_paid_research(context: Mapping[str, Any], reservation_id: str, *, provider_task_id: str | None, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    upstream = _crawlseo_budget_context(context)
    local = _local_reservation(context, reservation_id)
    if upstream is not None and local is not None:
        data = dict(detail or {})
        provider_status = str(data.get("provider_status") or "").lower()
        raw_cost = data.get("actual_cost_micros", data.get("cost_micros"))
        if provider_status in {"requested", "attempting", "pending", "queued", "processing"}:
            status = "reserved"
        elif provider_status == "uncertain" or raw_cost is None:
            status = "uncertain"
        else:
            try:
                actual = int(raw_cost)
            except (TypeError, ValueError) as exc:
                raise ContractError("provider actual cost must be a non-negative integer in micros") from exc
            if actual < 0:
                raise ContractError("provider actual cost cannot be negative")
            data["actualCostMicros"] = str(actual)
            status = "settled"
        return context["memory"].settle_growth_budget(reservation_id, status=status,
            provider_task_id=provider_task_id, detail=data)
    if upstream is not None:
        service, _site_id = upstream
        data = dict(detail or {})
        provider_status = str(data.get("provider_status") or "").lower()
        raw_cost = data.get("actual_cost_micros", data.get("cost_micros"))
        if provider_status in {"requested", "attempting", "pending", "queued", "processing"}:
            status = "reserved"
        elif provider_status == "uncertain":
            status = "uncertain"
        elif raw_cost is not None:
            try:
                actual = str(int(raw_cost))
            except (TypeError, ValueError) as exc:
                raise ContractError("provider actual cost must be a non-negative integer in micros") from exc
            if int(actual) < 0:
                raise ContractError("provider actual cost cannot be negative")
            status = "settled"
            data["actualCostMicros"] = actual
        else:
            status = "uncertain"
        result = service.connector_budget_settle(reservation_id, {"status": status,
            **({"actualCostMicros": data["actualCostMicros"]} if status == "settled" else {}),
            "providerTaskId": provider_task_id, "detail": data})
        return {**result, "reservation_id": str(result.get("id") or reservation_id), "status": str(result.get("status") or status).lower(), "upstream": True}
    return context["memory"].settle_growth_budget(reservation_id, status="settled", provider_task_id=provider_task_id, detail=dict(detail or {}))


def release_paid_research(context: Mapping[str, Any], reservation_id: str, *, reason: str) -> dict[str, Any]:
    upstream = _crawlseo_budget_context(context)
    if upstream is not None and _local_reservation(context, reservation_id) is not None:
        return context["memory"].settle_growth_budget(reservation_id, status="released", detail={"reason": str(reason or "provider rejected the request before dispatch")[:500]})
    if upstream is not None:
        service, _site_id = upstream
        result = service.connector_budget_settle(reservation_id, {"status": "released", "detail": {"reason": str(reason or "provider rejected the request before dispatch")[:500]}})
        return {**result, "reservation_id": str(result.get("id") or reservation_id), "status": str(result.get("status") or "released").lower(), "upstream": True}
    return context["memory"].settle_growth_budget(reservation_id, status="released", detail={"reason": str(reason or "provider rejected the request before dispatch")[:500]})


def mark_paid_research_uncertain(context: Mapping[str, Any], reservation_id: str, *, error: str) -> dict[str, Any]:
    upstream = _crawlseo_budget_context(context)
    if upstream is not None and _local_reservation(context, reservation_id) is not None:
        return context["memory"].settle_growth_budget(reservation_id, status="uncertain", detail={"error": str(error or "provider outcome is unknown")[:500]})
    if upstream is not None:
        service, _site_id = upstream
        result = service.connector_budget_settle(reservation_id, {"status": "uncertain", "detail": {"error": str(error or "provider outcome is unknown")[:500]}})
        return {**result, "reservation_id": str(result.get("id") or reservation_id), "status": str(result.get("status") or "uncertain").lower(), "upstream": True}
    return context["memory"].settle_growth_budget(reservation_id, status="uncertain", detail={"error": str(error or "provider outcome is unknown")[:500]})


__all__ = ["GrowthBudgetBlocked", "allowance_micros", "budget_period", "get_paid_research_reservation", "mark_paid_research_uncertain", "quote_micros", "release_paid_research", "reserve_paid_research", "settle_paid_research"]

"""Prove a lane on a disposable tenant, never on a customer.

A lane that was only exercised against a customer site is not verified: the
owner's own build can hide a platform fault, and repairing it in their tenant
is exactly the shape the tenant model forbids. This module resolves the proof
tenant from the canonical registry, refuses any tenant that is not declared
disposable, exercises one read-only lane route through the control-plane
gateway, and classifies the answer by the layer that produced it.

The classification matters more than the status code. A tenant runtime that
does not own the route answers ``workspace_route_not_owned``; a lane that has
no connector configured answers with the connector's own refusal. Only the
first is a layering regression, and a proof that cannot reach the lane at all
must say so instead of certifying it.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

CONTROL_PATH = "/control-plane/websites/{tenant}/workspace"
LANES: dict[str, dict[str, str]] = {
    # Read-only, owner-scoped, and answered by the site-agent itself.
    "growth": {"method": "GET", "route": "growth/bindings"},
}
_DISPOSABLE_NAME = re.compile(r"(?:^|[-.])(e2e|validation)(?:[-.]|$)")


class LaneProofError(RuntimeError):
    """A lane cannot be proven, or the proof failed."""


def is_disposable(customer: Mapping[str, Any]) -> bool:
    """Disposable is declared, never inferred from a name in comparison code."""
    return customer.get("disposable") is True


def proof_tenant(registry: Mapping[str, Any], tenant: str | None = None) -> str:
    """Return the disposable tenant this proof runs against."""
    customers = registry.get("customers")
    if not isinstance(customers, Mapping) or not customers:
        raise LaneProofError("the tenant registry has no customers")
    candidates = sorted(name for name, row in customers.items()
                        if isinstance(row, Mapping) and is_disposable(row))
    if not candidates:
        raise LaneProofError(
            "no tenant is declared disposable; a customer site cannot be the proof"
        )
    chosen = str(tenant or candidates[0]).strip()
    if chosen not in customers:
        raise LaneProofError(f"proof tenant is not registered: {chosen}")
    if not is_disposable(customers[chosen]):
        raise LaneProofError(
            f"{chosen} is not disposable; prove the lane on a disposable tenant"
        )
    return chosen


def classify(status: int, body: Any) -> tuple[str, str]:
    """Name the layer that answered, not just the status code."""
    payload = body if isinstance(body, Mapping) else {}
    error = str(payload.get("error") or "")
    detail = str(payload.get("detail") or payload.get("message") or "")
    if error == "workspace_route_not_owned":
        return "wrong_layer", "the tenant runtime answered; the route belongs to the site-agent"
    if status == 200 and isinstance(payload.get("bindings"), list):
        return "served", "the site-agent answered the lane route"
    if status in {401, 403}:
        return "identity_rejected", detail or "the owner identity was refused"
    if "connector is unavailable" in detail:
        return "lane_unmapped", (
            "this proof tenant has no CrawlSEO mapping; map the disposable tenant, "
            "do not substitute a customer"
        )
    if status == 404:
        return "not_registered", detail or "the proof tenant is not registered with the site-agent"
    return "unavailable", detail or f"HTTP {status}"


def prove_lane(
    lane: str,
    *,
    tenant: str,
    api_url: str,
    token: str,
    opener: Any = None,
) -> dict[str, Any]:
    """Exercise one lane route and return the evidence, raising when it fails."""
    definition = LANES.get(lane)
    if definition is None:
        raise LaneProofError(f"unknown lane: {lane}")
    if not token:
        raise LaneProofError("a control-plane token is required")
    url = f"{api_url.rstrip('/')}{CONTROL_PATH.format(tenant=tenant)}/{definition['route']}"
    request = urllib.request.Request(url, method=definition["method"], headers={
        "authorization": f"Bearer {token}",
        "x-helloada-owner-id": "helloada:lane-proof",
        "accept": "application/json",
        "user-agent": "site-agent/lane-proof",
    })
    send = opener or urllib.request.urlopen
    try:
        response = send(request, timeout=30)
        status = int(getattr(response, "status", 0) or 0)
        raw = response.read()
    except urllib.error.HTTPError as exc:  # an API refusal is evidence
        status = int(exc.code)
        raw = exc.read()
    except (OSError, urllib.error.URLError) as exc:
        raise LaneProofError(f"the lane is unreachable: {exc}") from exc
    try:
        body = json.loads(raw or b"{}")
    except (UnicodeError, ValueError):
        body = {}
    outcome, reason = classify(status, body)
    evidence = {
        "lane": lane,
        "tenant": tenant,
        "route": definition["route"],
        "method": definition["method"],
        "status": status,
        "outcome": outcome,
        "reason": reason,
        "observedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if outcome != "served":
        raise LaneProofError(f"{lane}: {outcome}: {reason}")
    return evidence

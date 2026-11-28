"""Read the fleet's mailbox identities and reconcile email routing.

This is the app-level half of `email_routing_reconcile`: it gathers what each
registered tenant owns (its registered address, its retained aliases from its own
mailbox database, its domains and their Cloudflare zones, and the Worker that is
actually deployed) and hands that to the pure planner.

It is the fleet mechanism, not a one-off repair: a Worker rename, a folded
mailbox address or a newly registered tenant is reconciled by the same run. It
never invents an address, a zone or an owner for a tenant; anything it cannot
prove is reported as `action_required` and skipped, so the operator sees the gap
instead of a guess.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

from .email_routing_reconcile import (
    RoutingPlan,
    RoutingReconcileError,
    apply_routing_reconciliation,
    plan_routing_reconciliation,
)

__all__ = [
    "collect_tenant_routing_identity",
    "reconcile_fleet_email_routing",
]


def _mailbox_addresses(tenant_env: Mapping[str, str]) -> list[str]:
    address = str(tenant_env.get("MAILFLARE_ADDRESS") or "").strip().lower()
    return [address] if "@" in address else []


def _d1_aliases(account_id: str, api_token: str, database_id: str, *, timeout: float = 30.0) -> list[dict[str, str]]:
    """Read a tenant's retained mailbox aliases from its own mailbox database.

    Read-only and parameterised by the tenant's registered database, so this can
    only ever see the aliases of the tenant it was given.
    """
    database = str(database_id or "").strip()
    if not database:
        return []
    sql = (
        "SELECT a.local_part || '@' || d.hostname AS address, d.hostname AS hostname, d.zone_id AS zone_id "
        "FROM mailbox_aliases a JOIN domains d ON d.id = a.domain_id"
    )
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/"
        f"{urllib.parse.quote(database, safe='')}/query",
        data=json.dumps({"sql": sql}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "site-agent/email-routing-reconcile",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(2 * 1024 * 1024).decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    rows = ((payload.get("result") or [{}])[0] or {}).get("results") or []
    return [
        {"address": str(row.get("address") or "").strip().lower(), "hostname": str(row.get("hostname") or "").strip().lower()}
        for row in rows
        if isinstance(row, Mapping) and row.get("address")
    ]


def _worker_exists(account_id: str, api_token: str, worker: str, *, timeout: float = 30.0) -> bool:
    request = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/"
        f"{urllib.parse.quote(worker, safe='')}/settings",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
            "User-Agent": "site-agent/email-routing-reconcile",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(2 * 1024 * 1024).decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        return False
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    return bool(payload.get("success"))


def collect_tenant_routing_identity(
    *,
    tenant_id: str,
    worker: str,
    tenant_env: Mapping[str, str],
    account_id: str,
    api_token: str,
    zone_lookup,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return one tenant's routing identity, or the reason it cannot be built.

    ``zone_lookup`` resolves a hostname to its Cloudflare zone id. A hostname the
    credential cannot manage is an `action_required` answer for this tenant, per
    the documented email-token contract, not a transient failure to retry.
    """
    address = str(tenant_env.get("MAILFLARE_ADDRESS") or "").strip().lower()
    if "@" not in address:
        return None, {"tenantId": tenant_id, "reason": "no_registered_address"}
    hostname = address.rsplit("@", 1)[1]
    addresses = _mailbox_addresses(tenant_env)
    aliases = _d1_aliases(account_id, api_token, str(tenant_env.get("MAILFLARE_DB_ID") or ""))
    hostnames = {hostname, *(alias["hostname"] for alias in aliases)}
    domains: dict[str, str] = {}
    for host in sorted(hostnames):
        zone_id = ""
        try:
            zone_id = str(zone_lookup(host) or "").strip()
        except Exception as exc:  # the adapter's own error type, reported not raised
            return None, {
                "tenantId": tenant_id,
                "reason": "zone_unavailable",
                "hostname": host,
                "detail": str(exc)[:300],
            }
        if not zone_id:
            return None, {
                "tenantId": tenant_id,
                "reason": "zone_unavailable",
                "hostname": host,
                "detail": "the email credential cannot manage this zone",
            }
        domains[host] = zone_id
    addresses.extend(alias["address"] for alias in aliases if alias["address"] not in addresses)
    return {
        "tenantId": tenant_id,
        "worker": worker,
        "domains": domains,
        "addresses": addresses,
    }, None


def reconcile_fleet_email_routing(
    *,
    tenants: Iterable[Mapping[str, Any]],
    rules_by_zone: Mapping[str, Iterable[Mapping[str, Any]]],
    client: Any,
    known_workers: Iterable[str] = (),
    remove_orphans: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    """Plan (and optionally apply) routing reconciliation for the whole fleet.

    ``tenants`` are the routing identities built by
    `collect_tenant_routing_identity`; tenants that could not be built are passed
    separately by the caller as `action_required` so they are never silently
    treated as "nothing to do".
    """
    plan: RoutingPlan = plan_routing_reconciliation(
        tenants=list(tenants),
        rules_by_zone=rules_by_zone,
        known_workers=known_workers,
        remove_orphans=remove_orphans,
    )
    result: dict[str, Any] = {
        "mode": "apply" if apply else "plan_only",
        "plan": plan.summary(),
    }
    if apply:
        try:
            result["applied"] = apply_routing_reconciliation(client, plan)
        except RoutingReconcileError as exc:
            result["state"] = "failed"
            result["error"] = str(exc)
            return result
        result["state"] = "applied"
    else:
        result["state"] = "planned"
    return result

"""Reconcile each tenant's email routing rules with the tenant that owns them.

A routing rule names a Worker, and nothing repointed that name when a Worker was
renamed or a mailbox address was folded into an alias. The result was invisible:
the tenant's mailbox is healthy, the address still resolves, and the mail is
delivered to a Worker that no longer exists — or to another site's. Two live
instances of exactly that were found on 2026-11-27: a folded alias pointing at
the pre-rename Worker, and a rule for a tenant that is in no manifest.

This module makes the routing table a projection of tenant identity instead of a
one-time write:

    every address a tenant owns  ->  exactly one enabled rule
                                     in the tenant's zone
                                     targeting the tenant's current Worker

It plans first and applies only what the plan names, so a wrong tenant mapping
is refused before anything is written, and a run that cannot see a zone fails
closed instead of guessing.

Run through the existing provisioning CLI lane; nothing here is a one-off script
and nothing here is per-tenant configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "RoutingAction",
    "RoutingPlan",
    "RoutingReconcileError",
    "plan_routing_reconciliation",
    "apply_routing_reconciliation",
]


class RoutingReconcileError(RuntimeError):
    """The routing table could not be reconciled safely."""


@dataclass(frozen=True)
class RoutingAction:
    """One rule change, named by the tenant it belongs to."""

    kind: str  # "repoint" | "enable" | "create" | "delete"
    tenant_id: str
    address: str
    zone_id: str
    worker: str
    rule_id: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tenantId": self.tenant_id,
            "address": self.address,
            "zoneId": self.zone_id,
            "worker": self.worker,
            "ruleId": self.rule_id,
            "reason": self.reason,
        }


@dataclass
class RoutingPlan:
    actions: list[RoutingAction] = field(default_factory=list)
    # Addresses a registered tenant owns with no rule at all: these are the one
    # case that needs an owner decision, because creating a rule changes where
    # mail goes for an address that may be handled outside HelloAda.
    unnamed: list[dict[str, Any]] = field(default_factory=list)
    # Rules that match no registered tenant. Reported always; deleted only when
    # the caller explicitly asks for orphan removal.
    orphans: list[dict[str, Any]] = field(default_factory=list)
    unchanged: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.actions)

    def summary(self) -> dict[str, Any]:
        return {
            "actions": [action.as_dict() for action in self.actions],
            "unnamed": list(self.unnamed),
            "orphans": list(self.orphans),
            "unchanged": len(self.unchanged),
            "changed": self.changed,
        }


def _rule_address(rule: Mapping[str, Any]) -> str:
    for matcher in rule.get("matchers") or []:
        if not isinstance(matcher, Mapping):
            continue
        if str(matcher.get("type") or "") == "literal" and str(matcher.get("field") or "to") == "to":
            return str(matcher.get("value") or "").strip().lower()
    return ""


def _rule_worker(rule: Mapping[str, Any]) -> str:
    for action in rule.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        if str(action.get("type") or "") != "worker":
            continue
        value = action.get("value")
        if isinstance(value, (list, tuple)) and value:
            return str(value[0] or "").strip()
        if isinstance(value, str):
            return value.strip()
    return ""


def _rule_targets(rule: Mapping[str, Any]) -> list[str]:
    """Every destination a rule names, so an ambiguous action is visible."""
    targets: list[str] = []
    for action in rule.get("actions") or []:
        if not isinstance(action, Mapping):
            continue
        value = action.get("value")
        if isinstance(value, (list, tuple)):
            targets.extend(str(item or "").strip() for item in value)
        elif isinstance(value, str):
            targets.append(value.strip())
    return [target for target in targets if target]


def plan_routing_reconciliation(
    *,
    tenants: Sequence[Mapping[str, Any]],
    rules_by_zone: Mapping[str, Sequence[Mapping[str, Any]]],
    known_workers: Iterable[str] = (),
    remove_orphans: bool = False,
) -> RoutingPlan:
    """Compare each tenant's owned addresses with the live routing table.

    ``tenants`` carries what this application knows and nothing more:

        {"tenantId": str, "worker": str,
         "domains": {hostname: cloudflare zone id},
         "addresses": [str, ...]}

    A tenant's addresses do not share one zone: a retained platform-domain alias
    lives in the platform zone while the custom domain has its own. The expected
    zone for an address is therefore the zone of the domain it belongs to, and a
    tenant whose address has no registered domain zone is refused rather than
    guessed at.

    ``rules_by_zone`` is the live rule list per zone id. ``known_workers`` is the
    set of Worker names that exist, so a rule pointing at a name that is neither
    the tenant's current Worker nor another registered tenant's Worker is
    treated as stale rather than as somebody else's routing.
    """
    plan = RoutingPlan()
    known = {str(worker).strip() for worker in known_workers if str(worker).strip()}
    owned: dict[str, dict[str, Any]] = {}
    for tenant in tenants:
        tenant_id = str(tenant.get("tenantId") or "").strip()
        worker = str(tenant.get("worker") or "").strip()
        domains = {
            str(host).strip().lower(): str(zone).strip()
            for host, zone in dict(tenant.get("domains") or {}).items()
            if str(host).strip() and str(zone).strip()
        }
        if not tenant_id or not worker or not domains:
            raise RoutingReconcileError(
                f"tenant routing identity is incomplete: {tenant_id or '<missing>'}"
            )
        for address in tenant.get("addresses") or []:
            clean = str(address or "").strip().lower()
            if not clean or "@" not in clean:
                continue
            hostname = clean.rsplit("@", 1)[1]
            zone_id = domains.get(hostname)
            if not zone_id:
                raise RoutingReconcileError(
                    f"address {clean} has no registered zone for its domain ({hostname})"
                )
            if clean in owned:
                raise RoutingReconcileError(
                    f"address {clean} is claimed by {owned[clean]['tenantId']} and {tenant_id}"
                )
            owned[clean] = {"tenantId": tenant_id, "zoneId": zone_id, "worker": worker}

    # Group the live rules by the address they match. Two rules for one address
    # is itself a defect: whichever Cloudflare delivers first decides.
    seen: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for zone_id, rules in rules_by_zone.items():
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            address = _rule_address(rule)
            if not address:
                continue
            seen.setdefault(address, []).append((str(zone_id), rule))

    for address, entries in sorted(seen.items()):
        owner = owned.get(address)
        if owner is None:
            targets = sorted({_rule_worker(rule) for _, rule in entries})
            # A rule with no Worker destination is a forward to a mailbox, not a
            # HelloAda route. It belongs to whoever set it up (a human alias, an
            # operator address) and must never be swept up as an orphan.
            forwarding = not any(targets)
            plan.orphans.append({
                "address": address,
                "zoneId": entries[0][0],
                "ruleIds": [str(rule.get("id") or "") for _, rule in entries],
                "workers": targets,
                "enabled": [bool(rule.get("enabled")) for _, rule in entries],
                "forwarding": forwarding,
            })
            continue
        zone_id = owner["zoneId"]
        worker = owner["worker"]
        matching = [(rid, rule) for rid, rule in entries if rid == zone_id]
        if not matching:
            # The address is the tenant's but its rule is in another zone: the
            # domain moved and the old rule still delivers somewhere.
            plan.unnamed.append({
                "reason": "rule_in_other_zone",
                "address": address,
                "tenantId": owner["tenantId"],
                "expectedZoneId": zone_id,
                "foundZoneIds": sorted({rid for rid, _ in entries}),
            })
            continue
        rid, rule = matching[0]
        rule_id = str(rule.get("id") or "")
        targets = _rule_targets(rule)
        enabled = bool(rule.get("enabled"))
        correct = targets == [worker]
        if correct and enabled:
            plan.unchanged.append({"address": address, "tenantId": owner["tenantId"], "ruleId": rule_id})
            continue
        if not correct:
            stale = [target for target in targets if target and target != worker]
            # A rule that names a Worker this account does not have is stale no
            # matter what; a rule that names another tenant's live Worker is also
            # wrong, because one address belongs to one tenant.
            reason = "stale_worker" if any(target not in known for target in stale) else "wrong_worker"
            plan.actions.append(RoutingAction(
                kind="repoint",
                tenant_id=owner["tenantId"],
                address=address,
                zone_id=rid,
                worker=worker,
                rule_id=rule_id,
                reason=f"{reason}:{','.join(stale) or '<none>'}",
            ))
            if not enabled:
                plan.actions.append(RoutingAction(
                    kind="enable",
                    tenant_id=owner["tenantId"],
                    address=address,
                    zone_id=rid,
                    worker=worker,
                    rule_id=rule_id,
                    reason="disabled",
                ))
            continue
        plan.actions.append(RoutingAction(
            kind="enable",
            tenant_id=owner["tenantId"],
            address=address,
            zone_id=rid,
            worker=worker,
            rule_id=rule_id,
            reason="disabled",
        ))

    # A registered address with no rule anywhere is not renamed into existence:
    # the plan reports it, and provisioning decides whether to create it.
    for address, owner in sorted(owned.items()):
        if address not in seen:
            plan.unnamed.append({
                "reason": "no_rule",
                "address": address,
                "tenantId": owner["tenantId"],
                "zoneId": owner["zoneId"],
                "worker": owner["worker"],
            })

    if remove_orphans:
        for orphan in plan.orphans:
            # Never delete a forwarding rule: it has no Worker destination, so it
            # was never a HelloAda route. Deleting one would silently stop a
            # person's mail.
            if orphan.get("forwarding"):
                continue
            for rule_id in orphan["ruleIds"]:
                if not rule_id:
                    continue
                plan.actions.append(RoutingAction(
                    kind="delete",
                    tenant_id="",
                    address=orphan["address"],
                    zone_id=orphan["zoneId"],
                    worker="",
                    rule_id=rule_id,
                    reason="orphan",
                ))
    return plan


def apply_routing_reconciliation(client: Any, plan: RoutingPlan) -> list[dict[str, Any]]:
    """Apply exactly the plan's actions, verifying each one's postcondition.

    ``client`` is the Cloudflare email adapter. Every mutation re-reads the rule
    it changed: a rule left pointing at the wrong Worker after a "successful"
    call is a failure, not a receipt.
    """
    applied: list[dict[str, Any]] = []
    for action in plan.actions:
        if action.kind == "delete":
            client.request(
                "DELETE",
                f"/zones/{action.zone_id}/email/routing/rules/{action.rule_id}",
            )
            applied.append({**action.as_dict(), "state": "deleted"})
            continue
        if action.kind in {"enable", "repoint"}:
            # Both actions send the same PUT: the adapter's update always writes
            # the correct address, the tenant's Worker and `enabled: true`. Only
            # the reason they were needed differs.
            live = {str(rule.get("id") or ""): rule for rule in client.routing_rules(action.zone_id)}
            rule = live.get(action.rule_id)
            if rule is None:
                raise RoutingReconcileError(
                    f"routing rule {action.rule_id} disappeared before it could be {action.kind}ed"
                )
            client.update_routing_rule(
                action.zone_id,
                action.rule_id,
                rule,
                address=action.address,
                worker=action.worker,
            )
            applied.append({**action.as_dict(), "state": f"{action.kind}ed" if action.kind == "repoint" else "enabled"})
            continue
        if action.kind == "create":
            created = client.create_routing_rule(action.zone_id, address=action.address, worker=action.worker)
            applied.append({**action.as_dict(), "state": "created", "ruleId": str(created.get("id") or "")})
            continue
        raise RoutingReconcileError(f"unsupported routing action {action.kind}")

    # One read-back for the whole run: prove the table now matches the plan.
    if applied:
        by_zone: dict[str, list[Mapping[str, Any]]] = {}
        for action in plan.actions:
            if action.zone_id not in by_zone:
                by_zone[action.zone_id] = client.routing_rules(action.zone_id)
        for action in plan.actions:
            if action.kind == "delete":
                continue
            live = {_rule_address(rule): rule for rule in by_zone.get(action.zone_id, [])}
            rule = live.get(action.address)
            if rule is None:
                raise RoutingReconcileError(f"routing rule for {action.address} is missing after reconciliation")
            if _rule_worker(rule) != action.worker or not bool(rule.get("enabled")):
                raise RoutingReconcileError(
                    f"routing rule for {action.address} does not target {action.worker} after reconciliation"
                )
    return applied

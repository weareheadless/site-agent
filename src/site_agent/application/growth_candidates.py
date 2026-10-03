"""Growth candidates use canonical Payload drafts and the existing owner draft API."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ..brain import growth as brain_growth
from ..core.contracts import ActionPriority, ActionRequirement, Artifact, ArtifactKind, EffectClass, OwnerAction
from .approvals import ApprovalService
from .actions import OwnerActionService


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def document_content(document: Mapping[str, Any], fields) -> dict[str, Any]:
    """Exclude transport timestamps; include every canonical editable field."""
    return {key: document.get(key) for key in sorted(fields)}


def prepare_payload_candidate(context: Mapping[str, Any], initiative: Mapping[str, Any], opportunity: Mapping[str, Any], inventory: list[dict[str, Any]], evidence: Mapping[str, Any]) -> dict[str, Any]:
    memory = context["memory"]
    payload = context.get("payload_gateway")
    if payload is None:
        raise RuntimeError("The canonical Payload gateway is unavailable")
    payload.require_growth_contract()
    collection, document_id = str(opportunity.get("collection") or ""), str(opportunity.get("documentId") or "")
    entry = next((row for row in inventory if row["collection"] == collection and str(row["document"]["id"]) == document_id), None)
    if entry is None:
        raise ValueError("Ada selected a document outside the canonical inventory")
    fields = payload.contract.collection_fields[collection]
    editable = sorted(set(fields) - {"id", "sourceId", "slug", "published", "publishedAt", "modifiedAt", "canonicalUrl", "_status"})
    live = payload.read(collection, identifier=document_id, identifier_kind="id", draft=False)
    draft = payload.read(collection, identifier=document_id, identifier_kind="id", draft=True)
    current = document_content(draft, fields)
    base = document_content(live, fields)
    stored = (initiative.get("validation") or {}).get("preparation")
    changes = stored.get("changes") if isinstance(stored, Mapping) else None
    resumed = isinstance(changes, Mapping) and current == {**base, **changes} and stored.get("baseHash") == content_hash(base)
    if current != base and not resumed:
        raise ValueError("This document already has owner draft changes. Ada will not overwrite them.")
    if changes is None:
        changes = brain_growth.prepare(context, opportunity=opportunity, document=current, fields=editable, evidence=evidence)
        if all(current.get(key) == value for key, value in changes.items()):
            raise ValueError("Ada proposed no actual change")
        preparation = {"changes": changes, "baseHash": content_hash(base), "collection": collection, "documentId": document_id}
        memory.update_strategy_initiative(int(initiative["id"]), validation={"preparation": preparation})
    elif stored.get("baseHash") != content_hash(base):
        raise ValueError("The published document changed during preparation")
    expected = {**base, **changes}
    candidate_hash = content_hash(expected)
    actual = draft
    package = {"tenant": context.get("tenant_id") or context["config"].get("instance_name"),
        "initiativeId": initiative["id"], "goalRevision": initiative["goal_revision"], "originRevision": initiative["origin_revision"],
        "policyVersion": evidence["policy"]["policy_version"], "evidenceHash": evidence["evidenceHash"],
        "collection": collection, "documentId": document_id, "fields": sorted(fields), "before": base, "after": expected,
        "baseHash": content_hash(base), "candidateHash": candidate_hash, "changes": changes,
        "sourceId": draft.get("sourceId"), "slug": draft.get("slug"), "route": entry.get("route"),
        "why": opportunity["why"], "scope": opportunity["scope"], "metric": opportunity.get("metric") or "gsc.clicks"}
    package_hash = content_hash(package)
    if not resumed:
        payload.apply_growth_candidate(package, package_hash)
        actual = payload.read(collection, identifier=document_id, identifier_kind="id", draft=True)
    if document_content(actual, fields) != expected:
        raise ValueError("Payload did not save the exact prepared candidate")
    memory.transition_strategy_initiative(int(initiative["id"]), "validating")
    proof = payload.validate_growth_candidate(package, package_hash)
    existing_draft = next((row for row in memory.list_drafts(limit=500) if (row.get("meta") or {}).get("review_package_hash") == package_hash), None)
    draft_id = existing_draft["id"] if existing_draft else memory.save_draft(title=opportunity["title"], body=opportunity["scope"], kind="payload_content", meta={"growth_package": package, "review_package_hash": package_hash})
    action = OwnerActionService(memory).create(OwnerAction(
        capability_id="growth.candidate.review", provider_id="site-agent", title=opportunity["title"], summary=opportunity["why"],
        action_label="Review this version", priority=ActionPriority.NORMAL, requirement=ActionRequirement.OWNER_DECISION,
        source_ref=f"growth-initiative:{initiative['id']}", dedupe_key=f"growth-initiative:{initiative['id']}", draft_id=draft_id))
    artifact = memory.create_artifact(Artifact(
        kind=ArtifactKind.SITE_CHANGE, title=opportunity["title"], summary=opportunity["scope"], renderer="site_change",
        capability_id="growth.publish", provider_id="payload", content_hash=package_hash,
        preview_data={"before": base, "after": expected, "route": entry.get("route"), "why": opportunity["why"]},
        source_action_id=action.id,
    ))
    approval = ApprovalService(memory, actions=OwnerActionService(memory)).create(
        artifact, owner_action_label="Publish this exact version", effect_class=EffectClass.SITE_MUTATION, action_id=action.id,
    )
    memory.update_strategy_initiative(int(initiative["id"]), draft_id=draft_id, owner_action_id=action.id, candidate_hash=candidate_hash,
        artifact_id=artifact.artifact_id, approval_id=approval.approval_id, review_package_hash=package_hash,
        validation={**proof, "preparation": {"changes": changes, "baseHash": content_hash(base)}})
    return memory.transition_strategy_initiative(int(initiative["id"]), "ready_for_review")

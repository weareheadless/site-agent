"""Tenant Growth engineering journal; existing approvals/receipts own execution.

An uncertain write is reconciled by marker, never blindly dispatched again.
These checkpoints deliberately do not merge, publish, schedule or grant approval.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from urllib.parse import quote

from ..core.contracts import ProviderReceipt, ReceiptStatus, safe_provider_message
from ..credentials import github_api_token
from ..hands.github_static import API, _request


class GrowthDeliveryError(RuntimeError):
    """Required journal checkpoint is not proven; stop at the current boundary."""


class GrowthDelivery:
    def __init__(self, context: Mapping[str, Any]):
        self.memory = context["memory"]
        config = context["config"]
        self.tenant = str(context.get("tenant_id") or "").strip()
        self.repository = str((config.get("site") or {}).get("repository") or "").strip()
        if not self.tenant or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise GrowthDeliveryError("Growth journal requires the registered tenant and repository")
        self.token = github_api_token(config, context.get("env"))
        if not self.token:
            raise GrowthDeliveryError(f"Growth journal credentials unavailable: tenant={self.tenant}")
        _, repo = _request("GET", f"{API}/repos/{self.repository}", self.token)
        if not isinstance(repo, Mapping) or repo.get("full_name", "").lower() != self.repository.lower() or repo.get("private") is not True:
            raise GrowthDeliveryError("Growth journal requires the exact registered private repository")

    def _key(self, initiative: Mapping[str, Any], stage: str, refs: Mapping[str, Any]) -> str:
        identity = [self.tenant, self.repository.lower(), int(initiative["id"]), stage, refs]
        return "growth-journal:" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _matching(self, path: str, marker: str) -> Mapping[str, Any] | None:
        matches = []
        for page in range(1, 21):
            _, rows = _request("GET", f"{API}/repos/{self.repository}/{path}&per_page=100&page={page}", self.token)
            if not isinstance(rows, list):
                raise GrowthDeliveryError("Growth journal reconciliation returned no list")
            matches.extend(row for row in rows if marker in str(row.get("body") or "") and not row.get("pull_request"))
            if len(rows) < 100:
                break
        else:
            raise GrowthDeliveryError("Growth journal reconciliation exceeded its bounded page limit")
        if len(matches) > 1:
            raise GrowthDeliveryError("Growth journal has duplicate stable checkpoint markers")
        return matches[0] if matches else None

    def _write(self, initiative, stage, refs, *, path, listing, payload):
        key = self._key(initiative, stage, refs)
        marker = f"<!-- {key} -->"
        receipt = self.memory.get_provider_receipt_by_idempotency_key(key)
        if receipt and receipt.status == ReceiptStatus.SUCCESS:
            return receipt
        existing = self._matching(listing, marker)
        if existing is not None:
            if receipt is None:
                receipt = self.memory.create_provider_receipt(ProviderReceipt(
                    provider_id="github", capability_id="growth.journal", idempotency_key=key,
                    status=ReceiptStatus.UNCERTAIN))
            return self._settle(receipt, existing)
        if receipt is not None:
            raise GrowthDeliveryError(f"Growth journal write remains uncertain; reconcile before retry: {key}")
        try:
            receipt = self.memory.create_provider_receipt(ProviderReceipt(
                provider_id="github", capability_id="growth.journal", idempotency_key=key,
                status=ReceiptStatus.UNCERTAIN, approval_id=refs.get("approvalId"),
                safe_message=f"tenant={self.tenant} work={initiative['id']} stage={stage}"))
        except sqlite3.IntegrityError as exc:
            raise GrowthDeliveryError("Growth journal checkpoint is already claimed; reconcile it") from exc
        body = {**payload, "body": marker + "\n" + payload["body"]}
        try:
            _, result = _request("POST", f"{API}/repos/{self.repository}/{path}", self.token, body)
            return self._settle(receipt, result)
        except Exception as exc:
            # Persisted uncertain claim survives timeout/process death; no automatic POST retry.
            raise GrowthDeliveryError(f"Growth journal recording pending: tenant={self.tenant} work={initiative['id']} stage={stage}") from exc

    def _settle(self, receipt, result):
        url = str(result.get("html_url") or "")
        if not url.startswith(f"https://github.com/{self.repository}/issues/") or not result.get("id"):
            raise GrowthDeliveryError("Growth journal returned an invalid repository/object identity")
        return self.memory.settle_provider_receipt(receipt.receipt_id, replace(
            receipt, status=ReceiptStatus.SUCCESS,
            external_object_id=str(result.get("number") or result["id"]), external_url=url))

    def issue(self, initiative):
        # The root ID is durable; changing candidate versions cannot create a new issue.
        return self._write(initiative, "issue", {}, path="issues", listing="issues?state=all", payload={
            "title": f"Ada Growth improvement {int(initiative['id'])}",
            "body": "\n".join((
                f"Tenant: `{self.tenant}` · Work: `{initiative['id']}`",
                f"Assessment: `{initiative.get('growth_run_id') or 'not recorded'}`",
                "Problem: " + safe_provider_message(str(initiative.get("title") or ""), max_chars=180),
                "Business rationale: " + safe_provider_message(str(initiative.get("rationale") or ""), max_chars=300),
                "Scope: " + safe_provider_message(str(initiative.get("summary") or ""), max_chars=300),
                "Evidence references: " + ", ".join(str(ref)[:100] for ref in initiative.get("evidence", []) if isinstance(ref, str))[:500],
                "Acceptance: exact candidate review, explicit owner decision, canonical publication/release and live technical verification.",
                "GitHub activity is not owner authorisation. This issue stays open until verified acceptance.",
            )),
        })

    def checkpoint(self, initiative, stage: str, refs: Mapping[str, Any]):
        if stage not in {"preparing", "prepared", "owner_decision", "source_promotion", "release_queued", "release_verified", "publication_recorded", "publication_verified", "technical_acceptance", "blocked", "impact_observed"}:
            raise GrowthDeliveryError("Unknown Growth journal checkpoint")
        allowed = {"candidateHash", "packageHash", "approvalId", "decision", "actor", "decidedAt", "draftId", "baseSha", "candidateSha", "collection", "documentId", "operationId", "publishedRevision", "releaseId", "sourceSha", "verificationHash", "outcomeId", "blockingIssue", "treeSha"}
        if not refs or set(refs) - allowed or any(isinstance(value, (dict, list)) for value in refs.values()):
            raise GrowthDeliveryError("Growth journal accepts bounded identity references only")
        if any(isinstance(value, str) and (len(value) > 300 or "\n" in value or "\r" in value) for value in refs.values()):
            raise GrowthDeliveryError("Growth journal reference exceeds its identity bound")
        issue = self.issue(initiative)
        number = int(issue.external_object_id)
        return self._write(initiative, stage, dict(refs), path=f"issues/{number}/comments",
            listing=f"issues/{number}/comments?", payload={"body": f"Checkpoint: **{stage}**\n```json\n{json.dumps(dict(refs), sort_keys=True)}\n```"})

    def close(self, initiative, reason, refs):
        """Close only after the caller proves persisted acceptance/decline.

        PATCH of a fixed state is idempotent. Reconcile its state after an
        ambiguous response before another PATCH; never create another comment.
        """
        if reason not in {"completed", "not_planned"}:
            raise GrowthDeliveryError("Unknown Growth issue closure reason")
        issue = self.issue(initiative)
        key = self._key(initiative, "close:" + reason, refs)
        receipt = self.memory.get_provider_receipt_by_idempotency_key(key)
        if receipt and receipt.status == ReceiptStatus.SUCCESS:
            return receipt
        path = f"{API}/repos/{self.repository}/issues/{int(issue.external_object_id)}"
        _, remote = _request("GET", path, self.token)
        root_marker = f"<!-- {self._key(initiative, 'issue', {})} -->"
        if root_marker not in str(remote.get("body") or ""):
            raise GrowthDeliveryError("Growth issue closure lost its registered work marker")
        if receipt is None:
            receipt = self.memory.create_provider_receipt(ProviderReceipt(
                provider_id="github", capability_id="growth.journal", idempotency_key=key,
                status=ReceiptStatus.UNCERTAIN))
        if remote.get("state") == "closed":
            if remote.get("state_reason") != reason:
                raise GrowthDeliveryError("Growth issue already closed with a different disposition")
            return self._settle(receipt, remote)
        try:
            _, closed = _request("PATCH", path, self.token, {"state": "closed", "state_reason": reason})
            if closed.get("state") != "closed" or closed.get("state_reason") != reason:
                raise GrowthDeliveryError("GitHub did not confirm the exact issue closure")
            return self._settle(receipt, closed)
        except Exception as exc:
            raise GrowthDeliveryError(f"Growth issue closure recording pending: tenant={self.tenant} work={initiative['id']}") from exc


def journal(context: Mapping[str, Any]) -> GrowthDelivery:
    return GrowthDelivery(context)


def require_owner_actor(actor_id):
    if not isinstance(actor_id, str) or not re.fullmatch(r"(?:payload|helloada):[A-Za-z0-9_.:-]{1,180}", actor_id):
        raise GrowthDeliveryError("Growth decision requires the actual authenticated owner actor ID")
    return actor_id


def journal_reference(context, initiative):
    """Side-effect-free owner projection of an existing issue-link receipt.

    No credential resolution, GitHub request or issue creation on read.
    """
    tenant = str(context.get("tenant_id") or "").strip()
    repository = str((context.get("config", {}).get("site") or {}).get("repository") or "").strip()
    if not tenant or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return {"status": "configuration_required", "repository": repository or None}
    identity = [tenant, repository.lower(), int(initiative["id"]), "issue", {}]
    key = "growth-journal:" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = context["memory"].get_provider_receipt_by_idempotency_key(key)
    if receipt is None:
        return {"status": "not_linked", "repository": repository}
    return {"status": "linked" if receipt.status == ReceiptStatus.SUCCESS else "recording_pending",
        "repository": repository, "issueNumber": receipt.external_object_id,
        "issueUrl": receipt.external_url, "receiptId": receipt.receipt_id}


def candidate_checkpoint(context, initiative, package_hash, package, *, draft_id=None, stage="prepared"):
    if package.get("tenant") != context.get("tenant_id") or int(package.get("initiativeId") or 0) != int(initiative["id"]):
        raise GrowthDeliveryError("Growth journal candidate does not belong to this tenant/work")
    refs = {"packageHash": package_hash, "candidateHash": package.get("candidateHash") or package_hash}
    if draft_id is not None:
        refs["draftId"] = int(draft_id)
    for key in ("collection", "documentId"):
        if package.get(key) is not None:
            refs[key] = str(package[key])
    for key in ("baseSha", "candidateSha"):
        if (package.get("source") or {}).get(key):
            refs[key] = package["source"][key]
    return journal(context).checkpoint(initiative, stage, refs)


def decision_checkpoint(context, initiative, package_hash, approval, *, actor_id):
    if approval.artifact_hash != package_hash or approval.status.value not in {"approved", "declined"} or not approval.decided_ts:
        raise GrowthDeliveryError("Growth journal requires the persisted exact owner decision")
    require_owner_actor(actor_id)
    memory = context["memory"]
    draft_id = int(initiative["draft_id"])
    draft = next((row for row in memory.list_drafts(limit=500) if int(row["id"]) == draft_id), None)
    if draft is None:
        raise GrowthDeliveryError("Growth decision draft is missing")
    meta = dict(draft.get("meta") or {})
    decision = {"packageHash": package_hash, "approvalId": approval.approval_id,
        "decision": approval.status.value, "actor": actor_id.strip(), "decidedAt": approval.decided_ts, "draftId": draft_id}
    previous = meta.get("growth_owner_decision")
    if previous is not None and previous != decision:
        raise GrowthDeliveryError("Growth decision actor or exact approved scope changed")
    if previous is None:
        memory.update_draft_meta(draft_id, {**meta, "growth_owner_decision": decision})
    return journal(context).checkpoint(initiative, "owner_decision", {
        **decision,
    })


def publication_checkpoint(context, initiative, package_hash, publication):
    """Record an existing immutable result, never execute publication here."""
    verification = publication.get("liveVerification")
    if publication.get("status") != "published" or not isinstance(verification, Mapping) or verification.get("status") != "passed" or publication.get("packageHash") != package_hash:
        raise GrowthDeliveryError("Growth publication lacks live verification; cannot record completion")
    digest = hashlib.sha256(json.dumps(verification, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    published = publication.get("published") or {}
    if not published.get("collection") or not published.get("documentId") or not published.get("updatedAt"):
        raise GrowthDeliveryError("Growth publication lacks its exact destination revision")
    refs = {"packageHash": package_hash, "draftId": int(initiative["draft_id"]),
        "publishedRevision": str(published.get("updatedAt") or ""), "verificationHash": "sha256:" + digest}
    # This is the existing growth-operations.ts idempotency identity, not a new operation.
    refs["operationId"] = f"publish:{context['tenant_id']}:{published['collection']}:{published['documentId']}:{package_hash}"
    return journal(context).checkpoint(initiative, "publication_verified", refs)


def article_candidate_checkpoint(context, initiative, draft):
    """Hook for core.jobs._update_article_strategy_candidate, before reviewability.

    The parent owns that hook and the existing exact ApprovalRequest creation;
    this adapter only records the already validated candidate references.
    """
    meta = draft.get("meta") or {}
    sync = meta.get("payload_sync") or {}
    package_hash = meta.get("review_package_hash")
    if sync.get("state") != "ready_for_review" or (sync.get("validation") or {}).get("status") != "passed" or not package_hash or not sync.get("draft_hash"):
        raise GrowthDeliveryError("Article journal requires the exact validated Payload candidate")
    return journal(context).checkpoint(initiative, "prepared", {
        "packageHash": package_hash, "candidateHash": str(sync["draft_hash"]),
        "draftId": int(draft["id"]), "collection": "posts", "documentId": str(sync["document_id"]),
    })


def article_publication_checkpoint(context, initiative, package_hash, receipt):
    """A canonical CMS publication receipt is not yet a public-render proof."""
    document = receipt.get("document") or {}
    if receipt.get("packageHash") != package_hash or not document.get("_helloadaRevision") or not document.get("id"):
        raise GrowthDeliveryError("Article publication lacks its exact canonical Payload revision")
    return journal(context).checkpoint(initiative, "publication_recorded", {
        "packageHash": package_hash, "draftId": int(initiative["draft_id"]),
        "collection": "posts", "documentId": str(document["id"]),
        "publishedRevision": str(document["_helloadaRevision"]),
    })


def release_checkpoint(context, initiative, package_hash, receipt):
    """Projection of the actual release service receipt, never a release trigger."""
    release_id = str(receipt.get("release_id") or "")
    source_sha = str(receipt.get("commit") or "")
    if not release_id or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise GrowthDeliveryError("Growth journal requires the canonical release ID and full source SHA")
    # Deployed is not live technical acceptance; only record the execution link.
    refs = {
        "packageHash": package_hash, "draftId": int(initiative["draft_id"]),
        "releaseId": release_id, "sourceSha": source_sha,
    }
    adapter = journal(context)
    recorded = adapter.checkpoint(initiative, "release_queued", refs)
    if receipt.get("status") == "deployed":
        proof = receipt.get("release_receipt") or {}
        if receipt.get("live") is not True or receipt.get("verified_commit") != source_sha or not proof.get("connectionVerifiedAt") or not proof.get("uploadedVersion"):
            raise GrowthDeliveryError("Growth release lacks its canonical live verification proof")
        refs["verificationHash"] = "sha256:" + hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return adapter.checkpoint(initiative, "release_verified", refs)
    return recorded


def verify_source_promotion(context, initiative, package_hash, package, source_sha):
    """Before queueing, prove a merge commit did not change reviewed contents."""
    candidate_sha = str((package.get("source") or {}).get("candidateSha") or "")
    if package.get("tenant") != context.get("tenant_id") or int(package.get("initiativeId") or 0) != int(initiative["id"]):
        raise GrowthDeliveryError("Growth source promotion scope changed")
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (candidate_sha, source_sha)):
        raise GrowthDeliveryError("Growth source promotion requires exact reviewed and merged Git SHAs")
    adapter = journal(context)
    trees = []
    for commit in (candidate_sha, source_sha):
        _, result = _request("GET", f"{API}/repos/{adapter.repository}/git/commits/{commit}", adapter.token)
        tree = str((result.get("tree") or {}).get("sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", tree):
            raise GrowthDeliveryError("Growth source promotion has no exact Git tree proof")
        trees.append(tree)
    if trees[0] != trees[1]:
        raise GrowthDeliveryError("Merged source differs from the reviewed candidate; revalidation and renewed owner review required")
    refs = {
        "packageHash": package_hash, "candidateSha": candidate_sha, "sourceSha": source_sha,
        "treeSha": trees[0], "draftId": int(initiative["draft_id"]),
    }
    adapter.checkpoint(initiative, "source_promotion", refs)
    # Return the locally verified proof fields. The journal writer returns a
    # provider receipt, which deliberately contains identities only and does
    # not expose the proof payload needed by the upstream publication receipt.
    return {"refs": refs}


def reconcile_source_merge(context, initiative, package_hash, package):
    """Read-only recovery of a timed-out merge; never issue another merge."""
    adapter = journal(context)
    branch = str((context["config"].get("site") or {}).get("branch") or "main")
    _, ref = _request("GET", f"{API}/repos/{adapter.repository}/git/ref/heads/{quote(branch, safe='')}", adapter.token)
    source_sha = str((ref.get("object") or {}).get("sha") or "")
    verify_source_promotion(context, initiative, package_hash, package, source_sha)
    return {"merged": True, "commit_sha": source_sha, "reconciled": True}


def complete_work(context, initiative):
    """Close only with the same work's persisted technical/live acceptance.

    Approval, release status and traffic observations cannot substitute for
    this gate. The verifier owns technicalAcceptance, not GitHub or this adapter.
    """
    validation = initiative.get("validation") or {}
    live = validation.get("liveVerification") or {}
    package_hash = str(initiative.get("review_package_hash") or "")
    draft = next((row for row in context["memory"].list_drafts(limit=500) if int(row["id"]) == int(initiative.get("draft_id") or 0)), None)
    meta = (draft or {}).get("meta") or {}
    receipt = meta.get("growth_publication_receipt") or {}
    # Existing CMS verifier proves exact schema/candidate, public readback and
    # actual public routes. Source/artifact-specific acceptance remains explicit.
    checks = live.get("checks") or []
    accepted = (receipt.get("packageHash") == package_hash and receipt.get("status") == "published"
        and (receipt.get("liveVerification") or {}) == live and bool(checks)
        and all(isinstance(check, Mapping) and check.get("status") == 200 for check in checks))
    article = meta.get("growth_article_publication_receipt") or {}
    article_document = article.get("document") or {}
    article_proof = meta.get("growth_article_verification") or {}
    accepted = accepted or (article.get("packageHash") == package_hash
        and article_proof.get("revision") == article_document.get("_helloadaRevision")
        and article_proof.get("packageHash") == package_hash
        and article_proof.get("liveVerification") == live and live.get("status") == "passed"
        and bool(checks) and all(isinstance(check, Mapping) and check.get("status") == 200 for check in checks))
    source = validation.get("sourceTechnicalAcceptance") or {}
    source_checks = source.get("technicalChecks") or []
    accepted = accepted or (source.get("status") == "passed" and source.get("packageHash") == package_hash
        and source.get("tenant") == context.get("tenant_id") and source.get("sourceSha") == live.get("commit")
        and source.get("releaseId") == live.get("releaseId") and source.get("verifiedAt")
        and bool(source_checks) and all(isinstance(check, Mapping) and check.get("status") == "passed"
            and check.get("criterion") and check.get("evidence") for check in source_checks))
    if not accepted:
        raise GrowthDeliveryError("Growth issue awaits persisted technical acceptance of the exact reviewed package")
    if not initiative.get("published_revision") or not (live.get("status") == "passed" or live.get("verified") is True):
        raise GrowthDeliveryError("Growth issue cannot complete before live verification")
    approval = context["memory"].get_approval_request(int(initiative.get("approval_id") or 0))
    if approval is None or approval.status.value != "approved" or approval.artifact_hash != package_hash:
        raise GrowthDeliveryError("Growth issue cannot complete without the exact owner approval")
    refs = {"packageHash": package_hash, "approvalId": approval.approval_id,
        "publishedRevision": str(initiative["published_revision"]), "verificationHash": "sha256:" + hashlib.sha256(json.dumps(live, sort_keys=True).encode()).hexdigest()}
    adapter = journal(context)
    adapter.checkpoint(initiative, "technical_acceptance", refs)
    return adapter.close(initiative, "completed", refs)


def close_declined(context, initiative, package_hash, approval):
    if approval.status.value != "declined" or approval.artifact_hash != package_hash:
        raise GrowthDeliveryError("Growth issue decline is not the exact persisted owner decision")
    return journal(context).close(initiative, "not_planned", {"packageHash": package_hash, "approvalId": approval.approval_id})


def reconcile_delivery(context):
    """Recording-only hook for growth_pending; never starts an external effect.

    Keep this on the durable pending-work invocation, never the Growth GET path.
    Failures are returned by work identity for that invocation's diagnostics.
    """
    memory = context["memory"]
    drafts = {int(row["id"]): row for row in memory.list_drafts(limit=500)}
    results = []
    deployer = context.get("source_deployment")
    if deployer is not None:
        results.extend(deployer.reconcile_growth_delivery())
    for initiative in memory.list_strategy_initiatives(limit=None):
        draft = drafts.get(int(initiative.get("draft_id") or 0))
        if draft is None:
            continue
        meta = draft.get("meta") or {}
        try:
            publication = meta.get("growth_publication_receipt")
            article = meta.get("growth_article_publication_receipt")
            package = meta.get("growth_package") or {}
            package_hash = str(meta.get("review_package_hash") or "")
            if publication:
                publication_checkpoint(context, initiative, package_hash, publication)
            elif article:
                finalize_article_publication(context, initiative, draft)
            elif package.get("candidateType") == "source_code" and draft.get("status") in {"publishing", "publish_failed", "live"}:
                if deployer is None:
                    raise GrowthDeliveryError("Growth delivery cannot read the canonical release service")
                continue  # Recorded by the existing deployment service hook above.
            else:
                continue
            results.append({"initiativeId": initiative["id"], "status": "recorded"})
        except Exception as exc:
            results.append({"initiativeId": initiative["id"], "status": "recording_pending", "error": type(exc).__name__})
    for initiative in memory.list_strategy_initiatives(limit=None):
        if initiative.get("published_revision") and journal_reference(context, initiative).get("status") == "linked":
            try:
                complete_work(context, initiative)
                results.append({"initiativeId": initiative["id"], "status": "technically_complete"})
            except GrowthDeliveryError as exc:
                results.append({"initiativeId": initiative["id"], "status": "acceptance_pending", "error": str(exc)[:200]})
    memory.kv_set("growth_delivery_diagnostics", results)
    return results


def finalize_article_publication(context, initiative, draft):
    """Resume exact readback and local finalisation, never repeat publication."""
    memory = context["memory"]
    meta = draft.get("meta") or {}
    receipt = meta.get("growth_article_publication_receipt") or {}
    document = receipt.get("document") or {}
    package_hash = str(meta.get("review_package_hash") or "")
    if receipt.get("packageHash") != package_hash or not document.get("_helloadaRevision"):
        raise GrowthDeliveryError("Article publication receipt is not the reviewed package")
    current = context["payload_gateway"].read("posts", identifier=str(document.get("id") or ""), identifier_kind="id", draft=False,
        locale=str((meta.get("payload_sync") or {}).get("locale") or "").strip() or None)
    if current.get("_helloadaRevision") != document["_helloadaRevision"]:
        raise GrowthDeliveryError("Published article differs from its exact saved publication receipt")
    locale = str((meta.get("payload_sync") or {}).get("locale") or "").strip()
    if not locale:
        raise GrowthDeliveryError("Article verification requires its canonical configured locale")
    live = context["payload_gateway"].verify_publication("posts", str(document["id"]), str(document["_helloadaRevision"]), locale=locale)
    if not isinstance(live, Mapping) or live.get("status") != "passed" or not live.get("checks"):
        raise GrowthDeliveryError("Article public-render verification is incomplete")
    proof = {"packageHash": package_hash, "revision": document["_helloadaRevision"], "liveVerification": dict(live)}
    memory.update_draft_meta(int(draft["id"]), {**meta, "growth_article_verification": proof})
    memory.update_draft_status(int(draft["id"]), "approved")
    if initiative.get("state") in {"publishing", "uncertain"}:
        memory.transition_strategy_initiative(int(initiative["id"]), "verifying_live")
    memory.update_strategy_initiative(int(initiative["id"]),
        published_revision=f"payload:posts:{document['id']}:{document['_helloadaRevision']}",
        validation={**(initiative.get("validation") or {}), "publicationReadback": {"status": "passed", "revision": document["_helloadaRevision"]}, "liveVerification": dict(live)},
        last_error="")
    current_initiative = memory.update_strategy_initiative(int(initiative["id"]))
    if current_initiative.get("state") == "verifying_live":
        memory.transition_strategy_initiative(int(initiative["id"]), "measuring")
    action_service = context.get("owner_action_service")
    if action_service is not None:
        action_service.reconcile(draft_id=int(draft["id"]), succeeded=True)
    article_publication_checkpoint(context, initiative, package_hash, receipt)
    return {"ok": True, "draft_id": int(draft["id"]), "status": "published", "idempotent": True}

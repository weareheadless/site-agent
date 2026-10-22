from types import SimpleNamespace
import re

import pytest

from site_agent.application import growth_delivery as delivery
from site_agent.core.contracts import ApprovalStatus
from site_agent.core.memory import Memory


class GitHub:
    def __init__(self):
        self.issues = []
        self.comments = []
        self.writes = []
        self.fail = False
        self.ambiguous = False
        self.private = True

    def __call__(self, method, url, token, payload=None):
        if method == "GET" and "/issues" not in url:
            return 200, {"full_name": "owner/customer", "private": self.private}
        rows = self.comments if "/comments" in url else self.issues
        if re.search(r"/issues/[0-9]+$", url):
            issue = self.issues[int(url.rsplit("/", 1)[-1]) - 1]
            if method == "GET":
                return 200, dict(issue)
            if method == "PATCH":
                self.writes.append((url, payload))
                issue.update(payload)
                if self.ambiguous:
                    self.ambiguous = False
                    raise TimeoutError("closure response lost")
                return 200, dict(issue)
        if method == "GET":
            return 200, list(rows)
        self.writes.append((url, payload))
        if self.fail:
            raise TimeoutError("unavailable")
        record = {**payload, "state": "open", "state_reason": None, "number": len(self.issues) + 1, "id": len(rows) + 10,
            "html_url": "https://github.com/owner/customer/issues/1" + ("#issuecomment-10" if "/comments" in url else "")}
        rows.append(record)
        if self.ambiguous:
            self.ambiguous = False
            raise TimeoutError("response lost after committed write")
        return 201, record


@pytest.fixture
def setup(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    github = GitHub()
    monkeypatch.setattr(delivery, "_request", github)
    monkeypatch.setattr(delivery, "github_api_token", lambda *_args: "test-token")
    context = {"memory": memory, "config": {"site": {"repository": "owner/customer"}}, "tenant_id": "customer"}
    memory.save_draft("Unrelated", "")
    memory.save_draft("Candidate", "", kind="payload_content", meta={"review_package_hash": "exact"})
    initiative = {"id": 7, "draft_id": 2, "growth_run_id": "assessment-3"}
    yield context, initiative, github
    memory.close()


def test_missing_repository_and_public_repository_fail_closed(setup):
    context, initiative, github = setup
    github.private = False
    with pytest.raises(delivery.GrowthDeliveryError, match="private"):
        delivery.journal(context).issue(initiative)
    context["config"] = {}
    with pytest.raises(delivery.GrowthDeliveryError, match="registered"):
        delivery.journal(context)
    assert not github.writes


def test_issue_reused_across_restarts_and_candidate_versions(setup):
    context, initiative, github = setup
    first = delivery.journal(context).issue(initiative)
    assert delivery.journal(context).issue(initiative) == first
    for package in ("hash1", "hash2"):
        delivery.journal(context).checkpoint(initiative, "prepared", {"packageHash": package})
    assert len(github.issues) == 1
    assert len(github.comments) == 2


def test_ambiguous_issue_create_reconciled_without_second_post(setup):
    context, initiative, github = setup
    github.ambiguous = True
    with pytest.raises(delivery.GrowthDeliveryError, match="pending"):
        delivery.journal(context).issue(initiative)
    result = delivery.journal(context).issue(initiative)
    assert result.status.value == "success"
    assert len(github.writes) == 1


def test_absent_uncertain_write_never_blindly_replayed(setup):
    context, initiative, github = setup
    github.fail = True
    context["memory"].update_draft_status(2, "discarded")
    with pytest.raises(delivery.GrowthDeliveryError):
        delivery.journal(context).issue(initiative)
    github.fail = False
    with pytest.raises(delivery.GrowthDeliveryError, match="uncertain"):
        delivery.journal(context).issue(initiative)
    assert len(github.writes) == 1


def test_ambiguous_comment_reconciles_marker(setup):
    context, initiative, github = setup
    delivery.journal(context).issue(initiative)
    github.ambiguous = True
    with pytest.raises(delivery.GrowthDeliveryError):
        delivery.journal(context).checkpoint(initiative, "prepared", {"packageHash": "exact"})
    delivery.journal(context).checkpoint(initiative, "prepared", {"packageHash": "exact"})
    assert len(github.comments) == 1


def test_stale_approval_or_foreign_candidate_cannot_be_journalled(setup):
    context, initiative, github = setup
    approval = SimpleNamespace(artifact_hash="old", status=ApprovalStatus.APPROVED, decided_ts="2026-10-21", approval_id=12)
    with pytest.raises(delivery.GrowthDeliveryError, match="exact owner"):
        delivery.decision_checkpoint(context, initiative, "new", approval, actor_id="payload:customer:11")
    with pytest.raises(delivery.GrowthDeliveryError, match="belong"):
        delivery.candidate_checkpoint(context, initiative, "new", {"tenant": "another", "initiativeId": 7})
    assert not github.writes


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.DECLINED])
def test_exact_persisted_owner_decision_is_reference_not_permission(setup, status):
    context, initiative, github = setup
    approval = SimpleNamespace(artifact_hash="exact", status=status, decided_ts="2026-10-21T23:00:00Z", approval_id=12)
    delivery.decision_checkpoint(context, initiative, "exact", approval, actor_id="payload:customer:11")
    assert '"approvalId": 12' in github.comments[0]["body"]
    assert status.value in github.comments[0]["body"]
    assert '"actor": "payload:customer:11"' in github.comments[0]["body"]
    assert not any(method.endswith("/merges") for method, _ in github.writes)


def test_publication_without_live_proof_cannot_record_completion(setup):
    context, initiative, github = setup
    with pytest.raises(delivery.GrowthDeliveryError, match="live verification"):
        delivery.publication_checkpoint(context, initiative, "exact", {"status": "published"})
    assert not github.writes


def test_release_requires_canonical_release_id_not_preview_job(setup):
    context, initiative, github = setup
    with pytest.raises(delivery.GrowthDeliveryError, match="canonical release"):
        delivery.release_checkpoint(context, initiative, "exact", {"id": "preview-job", "commit": "a" * 40})
    delivery.release_checkpoint(context, initiative, "exact", {"release_id": "release-1", "commit": "a" * 40})
    assert '"releaseId": "release-1"' in github.comments[0]["body"]
    assert "closed" not in github.comments[0]["body"]


def test_source_preparation_does_not_enqueue_before_issue_checkpoint(setup, monkeypatch):
    from site_agent.application.growth_candidates import queue_source_candidate
    from site_agent.hands import opencode_runner
    context, initiative, github = setup
    monkeypatch.setattr(opencode_runner, "builder_available", lambda _config: True)
    github.fail = True
    context["memory"].update_draft_status(2, "discarded")
    with pytest.raises(delivery.GrowthDeliveryError):
        queue_source_candidate(context, initiative, {"title": "bounded", "scope": "source", "evidence": []}, {"evidenceHash": "hash"})
    assert not context["memory"].list_chat_jobs(None)


def test_successful_publication_retry_only_records_journal(setup):
    from site_agent.application.workspace import ChatService
    context, initiative, github = setup
    memory = context["memory"]
    publication = {"status": "published", "packageHash": "exact", "published": {"collection": "pages", "documentId": "1", "updatedAt": "2026-10-21"}, "liveVerification": {"status": "passed"}}
    draft_id = memory.save_draft("Owner candidate", "", kind="payload_content", meta={"review_package_hash": "exact", "growth_publication_receipt": publication})
    cycle = memory.create_strategy_cycle("test", "2026-10", "hash", {})
    memory.create_strategy_initiative(cycle["id"], kind="payload_content", title="bounded", summary="bounded", state="monitoring", draft_id=draft_id)
    memory.update_draft_status(draft_id, "approved")
    # No Payload gateway exists: even trying to publish would fail this test.
    tenant = SimpleNamespace(context=context, config=context["config"], memory=memory, tenant_id="customer")
    service = ChatService(memory=memory, llm=object())
    result = service.approve_draft(draft_id, tenant=tenant, review_package_hash="exact")
    assert result["status"] == "published" and result["idempotent"]
    service.approve_draft(draft_id, tenant=tenant, review_package_hash="exact")
    assert len(github.comments) == 1


def test_journal_failure_after_publication_is_retried_without_payload(setup):
    from site_agent.application.workspace import ChatService
    context, initiative, github = setup
    memory = context["memory"]
    publication = {"status": "published", "packageHash": "exact", "published": {"collection": "pages", "documentId": "1", "updatedAt": "2026-10-21"}, "liveVerification": {"status": "passed"}}
    draft_id = memory.save_draft("Candidate", "", kind="payload_content", meta={"review_package_hash": "exact", "growth_publication_receipt": publication})
    cycle = memory.create_strategy_cycle("test", "2026-10", "hash", {})
    root_id = memory.create_strategy_initiative(cycle["id"], kind="payload_content", title="bounded", summary="bounded", state="monitoring", draft_id=draft_id)
    delivery.journal(context).issue({"id": root_id})
    memory.update_draft_status(draft_id, "approved")
    tenant = SimpleNamespace(context=context, config=context["config"], memory=memory, tenant_id="customer")
    service = ChatService(memory=memory, llm=object())
    github.ambiguous = True
    with pytest.raises(delivery.GrowthDeliveryError, match="pending"):
        service.approve_draft(draft_id, tenant=tenant, review_package_hash="exact")
    assert memory.list_drafts()[0]["status"] == "approved"
    assert service.approve_draft(draft_id, tenant=tenant, review_package_hash="exact")["status"] == "published"
    assert len(github.comments) == 1


def test_missing_github_credentials_does_not_select_another_credential(setup, monkeypatch):
    context, initiative, github = setup
    monkeypatch.setattr(delivery, "github_api_token", lambda *_args: "")
    with pytest.raises(delivery.GrowthDeliveryError, match="credentials"):
        delivery.journal(context).issue(initiative)
    assert not github.writes


def test_duplicate_checkpoint_marker_fails_instead_of_picking_one(setup):
    context, initiative, github = setup
    key = delivery.journal(context)._key(initiative, "issue", {})
    github.issues = [{"body": f"<!-- {key} -->"}, {"body": f"<!-- {key} -->"}]
    with pytest.raises(delivery.GrowthDeliveryError, match="duplicate"):
        delivery.journal(context).issue(initiative)
    assert not github.writes


def test_tenant_identity_is_part_of_every_checkpoint(setup):
    context, initiative, github = setup
    first = delivery.journal(context).issue(initiative)
    other = {**context, "tenant_id": "another-tenant"}
    second = delivery.journal(other).issue(initiative)
    assert first.idempotency_key != second.idempotency_key
    assert len(github.issues) == 2


def test_source_promotion_proves_equal_trees_before_queue(setup, monkeypatch):
    context, initiative, github = setup
    original = github.__call__
    trees = {"a" * 40: "c" * 40, "b" * 40: "c" * 40}
    def request(method, url, token, payload=None):
        if "/git/commits/" in url:
            return 200, {"tree": {"sha": trees[url.rsplit("/", 1)[-1]]}}
        return original(method, url, token, payload)
    monkeypatch.setattr(delivery, "_request", request)
    package = {"tenant": "customer", "initiativeId": 7, "source": {"candidateSha": "a" * 40}}
    delivery.verify_source_promotion(context, initiative, "exact", package, "b" * 40)
    assert len(github.comments) == 1
    trees["b" * 40] = "d" * 40
    with pytest.raises(delivery.GrowthDeliveryError, match="differs"):
        delivery.verify_source_promotion(context, initiative, "exact", package, "b" * 40)


def test_deployed_release_requires_actual_live_receipt_proof(setup):
    context, initiative, github = setup
    receipt = {"status": "deployed", "release_id": "release-1", "commit": "a" * 40}
    with pytest.raises(delivery.GrowthDeliveryError, match="live verification"):
        delivery.release_checkpoint(context, initiative, "exact", receipt)
    receipt.update(live=True, verified_commit="a" * 40,
        release_receipt={"connectionVerifiedAt": "2026-10-21", "uploadedVersion": "version-1"})
    delivery.release_checkpoint(context, initiative, "exact", receipt)
    assert len(github.comments) == 2
    assert "release_verified" in github.comments[-1]["body"]


def test_actual_actor_required_and_cannot_change_after_persisted_decision(setup):
    context, initiative, github = setup
    approval = SimpleNamespace(artifact_hash="exact", status=ApprovalStatus.APPROVED, decided_ts="2026-10-21", approval_id=12)
    with pytest.raises(delivery.GrowthDeliveryError, match="actor"):
        delivery.decision_checkpoint(context, initiative, "exact", approval, actor_id=None)
    delivery.decision_checkpoint(context, initiative, "exact", approval, actor_id="payload:customer:11")
    with pytest.raises(delivery.GrowthDeliveryError, match="actor"):
        delivery.decision_checkpoint(context, initiative, "exact", approval, actor_id="payload:customer:12")


def test_article_publication_record_is_not_claimed_live_verified(setup):
    context, initiative, github = setup
    receipt = {"packageHash": "exact", "document": {"id": "4", "_helloadaRevision": "sha256:revision"}}
    delivery.article_publication_checkpoint(context, initiative, "exact", receipt)
    assert "publication_recorded" in github.comments[0]["body"]
    assert "publication_verified" not in github.comments[0]["body"]


def test_source_journal_failure_preserves_success_and_retries_without_deploy(setup, monkeypatch, tmp_path):
    import threading
    from site_agent.application.source_deployment import SourceDeploymentService
    monkeypatch.setattr("site_agent.application.source_deployment.release_root", lambda _config: tmp_path)
    context, initiative, github = setup
    memory = context["memory"]
    context["config"]["instance_name"] = "customer"
    draft_id = 2
    cycle = memory.create_strategy_cycle("source", "2026-10", "hash", {})
    root = memory.create_strategy_initiative(cycle["id"], kind="code", title="bounded", summary="bounded", state="measuring", draft_id=draft_id)
    memory.update_draft_meta(draft_id, {"review_package_hash": "exact", "growth_package": {"tenant": "customer", "initiativeId": root, "candidateType": "source_code"}})
    memory.update_draft_status(draft_id, "live")
    service = SourceDeploymentService.__new__(SourceDeploymentService)
    service.config, service.memory, service.env = context["config"], memory, {}
    service._lock = threading.RLock()
    receipt = {"id": "job-1", "mode": "production", "draft_id": draft_id, "status": "deployed", "release_id": "release-1", "commit": "a" * 40,
        "live": True, "verified_commit": "a" * 40, "release_receipt": {"connectionVerifiedAt": "2026-10-21", "uploadedVersion": "version-1"}}
    service._jobs = {"job-1": receipt}
    monkeypatch.setattr(service, "status", lambda _job: dict(receipt))
    # Issue creation succeeds; first checkpoint POST is accepted but its response is lost.
    delivery.journal(context).issue({"id": root})
    github.ambiguous = True
    first = service.reconcile_growth_delivery()
    assert first[0]["status"] == "recording_pending"
    assert service._jobs["job-1"]["status"] == "deployed"
    assert service.reconcile_growth_delivery()[0]["status"] == "acceptance_pending"
    assert len(github.comments) == 2  # queued + verified, no duplicate queued comment
    assert memory.list_drafts()[0]["status"] == "live"


def test_journal_reference_is_pure_even_when_github_is_unavailable(setup, monkeypatch):
    context, initiative, github = setup
    delivery.journal(context).issue(initiative)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Growth GET must not call GitHub or resolve credentials")
    monkeypatch.setattr(delivery, "_request", forbidden)
    monkeypatch.setattr(delivery, "github_api_token", forbidden)
    reference = delivery.journal_reference(context, initiative)
    assert reference["status"] == "linked" and reference["issueNumber"] == "1"


def test_completion_gate_rejects_approval_or_release_without_acceptance(setup):
    context, initiative, github = setup
    with pytest.raises(delivery.GrowthDeliveryError, match="technical acceptance"):
        delivery.complete_work(context, {**initiative, "published_revision": "git:source"})
    assert not github.writes


def test_declined_issue_closes_not_planned_and_ambiguous_close_reconciles(setup):
    context, initiative, github = setup
    approval = SimpleNamespace(artifact_hash="exact", status=ApprovalStatus.DECLINED, decided_ts="2026-10-21", approval_id=12)
    delivery.decision_checkpoint(context, initiative, "exact", approval, actor_id="payload:customer:11")
    github.ambiguous = True
    with pytest.raises(delivery.GrowthDeliveryError, match="closure recording pending"):
        delivery.close_declined(context, initiative, "exact", approval)
    writes = len(github.writes)
    delivery.close_declined(context, initiative, "exact", approval)
    assert len(github.writes) == writes
    assert github.issues[0]["state_reason"] == "not_planned"


def test_actual_trusted_actor_header_is_scoped_and_body_actor_is_ignored():
    from starlette.requests import Request
    from fastapi import HTTPException
    from site_agent.web.workspace import authenticated_owner_actor
    tenant = SimpleNamespace(tenant_id="customer")
    request = Request({"type": "http", "headers": [(b"x-helloada-owner-id", b"payload:customer:11")]})
    assert authenticated_owner_actor(request, tenant) == "payload:customer:11"
    assert authenticated_owner_actor(Request({"type": "http", "headers": []}), tenant) is None
    with pytest.raises(HTTPException) as error:
        authenticated_owner_actor(Request({"type": "http", "headers": [(b"x-helloada-owner-id", b"payload:other:11")]}), tenant)
    assert error.value.status_code == 403


def test_article_saved_publication_recovers_state_and_action_before_journal(setup):
    context, _, github = setup
    memory = context["memory"]
    document = {"id": "4", "_helloadaRevision": "sha256:exact-revision"}
    receipt = {"packageHash": "exact", "document": document}
    memory.update_draft_meta(2, {"review_package_hash": "exact", "payload_sync": {"locale": "en"}, "growth_article_publication_receipt": receipt})
    cycle = memory.create_strategy_cycle("article-finalizer", "2026-10", "hash", {})
    root = memory.create_strategy_initiative(cycle["id"], kind="article", title="Article", summary="Bounded article", state="publishing", draft_id=2)
    calls = []
    class Payload:
        def read(self, *_args, **_kwargs):
            return document
        def publish(self, *_args, **_kwargs):
            raise AssertionError("Saved publication must not be replayed")
        def verify_publication(self, collection, document_id, expected_revision, *, locale):
            assert (collection, document_id, expected_revision, locale) == ("posts", "4", "sha256:exact-revision", "en")
            return {"status": "passed", "checks": [{"route": "/blog/article", "status": 200}, {"route": "/blog", "status": 200}]}
    context["payload_gateway"] = Payload()
    context["owner_action_service"] = SimpleNamespace(reconcile=lambda **kwargs: calls.append(kwargs))
    initiative = memory.update_strategy_initiative(root)
    draft = next(row for row in memory.list_drafts() if row["id"] == 2)
    delivery.journal(context).issue(initiative)
    github.ambiguous = True
    with pytest.raises(delivery.GrowthDeliveryError):
        delivery.finalize_article_publication(context, initiative, draft)
    assert memory.update_strategy_initiative(root)["state"] == "measuring"
    assert next(row for row in memory.list_drafts() if row["id"] == 2)["status"] == "approved"
    assert calls == [{"draft_id": 2, "succeeded": True}]
    delivery.finalize_article_publication(context, memory.update_strategy_initiative(root), draft)
    assert len(github.comments) == 1
    assert github.issues[0]["state"] == "open"  # CMS readback is not live-render acceptance.

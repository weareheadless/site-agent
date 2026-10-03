import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from site_agent.application.approvals import ApprovalService
from site_agent.core.contracts import Artifact, ArtifactKind, EffectClass, ProviderReceipt, ReceiptStatus, ContractError
from site_agent.core.memory import Memory
from site_agent.core.growth_contracts import GrowthGoalRevision


def approved(memory, provider):
    service = ApprovalService(memory, providers={"provider": provider})
    approval = service.create(Artifact(kind=ArtifactKind.SITE_CHANGE, title="Exact candidate",
        summary="Reviewed change", renderer="site_change", capability_id="growth.publish",
        provider_id="provider", content_hash="sha256:exact"), owner_action_label="Publish",
        effect_class=EffectClass.SITE_MUTATION)
    service.decide(approval.approval_id, True)
    return service, approval.approval_id


def test_independent_process_connections_claim_before_provider_effect(tmp_path):
    first, second = Memory(tmp_path / "tenant.db"), Memory(tmp_path / "tenant.db")
    entered, finish = threading.Event(), threading.Event()
    calls = []
    def provider(artifact, approval, key):
        calls.append(key)
        entered.set()
        assert finish.wait(5)
        return ProviderReceipt(provider_id="provider", capability_id="growth.publish", idempotency_key=key, status=ReceiptStatus.SUCCESS)
    service, approval_id = approved(first, provider)
    other = ApprovalService(second, providers={"provider": provider})
    with ThreadPoolExecutor(max_workers=2) as pool:
        execution = pool.submit(service.dispatch, approval_id)
        assert entered.wait(5)
        observed = other.dispatch(approval_id)
        assert observed.status == ReceiptStatus.UNCERTAIN
        finish.set()
        settled = execution.result(timeout=5)
    assert calls == [settled.idempotency_key]
    assert settled.receipt_id == observed.receipt_id
    assert other.dispatch(approval_id).status == ReceiptStatus.SUCCESS
    first.close()
    second.close()


def test_crash_after_provider_effect_is_reconciled_without_redispatch(tmp_path):
    memory = Memory(tmp_path / "tenant.db")
    class Provider:
        calls = 0
        def __call__(self, artifact, approval, key):
            self.calls += 1
            raise SystemExit("simulate crash after remote success")
        def reconcile(self, artifact, approval, key):
            return ProviderReceipt(provider_id="provider", capability_id="growth.publish", idempotency_key=key,
                status=ReceiptStatus.SUCCESS, external_object_id="remote-operation-1")
    provider = Provider()
    service, approval_id = approved(memory, provider)
    with pytest.raises(SystemExit):
        service.dispatch(approval_id)
    memory.close()
    restored = Memory(tmp_path / "tenant.db")
    service = ApprovalService(restored, providers={"provider": provider})
    assert service.dispatch(approval_id).status == ReceiptStatus.UNCERTAIN
    assert service.reconcile_dispatch(approval_id).status == ReceiptStatus.SUCCESS
    assert service.dispatch(approval_id).external_object_id == "remote-operation-1"
    assert provider.calls == 1
    restored.close()


def test_superseded_run_cannot_write_late_phase_state(tmp_path):
    memory = Memory(tmp_path / "tenant.db")
    goal = memory.create_growth_goal(GrowthGoalRevision.default().to_dict())
    memory.create_growth_run(run_id="run-1", run_key="week-1", trigger="weekly", goal_revision=goal["revision"], timezone="UTC", phase="collecting", status="pending")
    assert memory.claim_growth_run("run-1", lease_owner="old")
    assert memory.claim_growth_run("run-1", lease_owner="other") is None
    memory.update_growth_run("run-1", lease_until="2000-01-01T00:00:00+00:00")
    assert memory.claim_growth_run("run-1", lease_owner="new")
    with pytest.raises(ContractError, match="superseded or expired"):
        memory.update_growth_run("run-1", phase="complete", completed=True, expected_lease="old")
    assert memory.get_growth_run("run-1")["lease_owner"] == "new"
    memory.close()


def test_settled_receipt_recovers_owner_action_after_projection_crash(tmp_path):
    memory = Memory(tmp_path / "tenant.db")
    calls = []
    class Actions:
        def reconcile(self, *, approval_id):
            calls.append(approval_id)
            if len(calls) == 1:
                raise SystemExit("crash after durable provider success")
    effects = []
    def provider(artifact, approval, key):
        effects.append(key)
        return ProviderReceipt(provider_id="provider", capability_id="growth.publish", idempotency_key=key, status=ReceiptStatus.SUCCESS)
    service, approval_id = approved(memory, provider)
    service.actions = Actions()
    with pytest.raises(SystemExit):
        service.dispatch(approval_id)
    assert service.dispatch(approval_id).status == ReceiptStatus.SUCCESS
    assert calls == [approval_id, approval_id]
    assert len(effects) == 1
    memory.close()

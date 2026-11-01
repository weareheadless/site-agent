from site_agent.application.onboarding_report import persist_initial_onboarding_report
from site_agent.application.workspace import ChatService, Journey, Tenant
from site_agent.core.design_contracts import DesignContextSnapshot, SiteIntake, canonical_hash
from site_agent.core.memory import Memory
from site_agent.core.contracts import ContractError
from site_agent.core.design_contracts import MAX_QUALITY_REPORT_BYTES
import pytest


def _run(memory: Memory):
    intake = SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear and warm."},
        "site": {"required_pages": ["home", "about", "contact"]},
    })
    run = memory.create_design_run(
        run_id="onboarding-report-test",
        mode="production_candidate",
        status="created",
        intake_json=intake.to_dict(),
        intake_hash=canonical_hash(intake.to_dict()),
        base_sha="a" * 40,
        publishable=True,
        owner_request="Build a welcoming first page for the studio.",
        intake_session_id="intake-report-test",
        intake_revision_id=4,
    )
    snapshot = DesignContextSnapshot.from_dict({
        "schema_version": 1,
        "captured_at": "2026-10-05T12:00:00+00:00",
        "owner_request": "Build a welcoming first page for the studio.",
        "base_sha": "a" * 40,
        "research": [
            {"text": "Customers compare hand-crafted lighting before booking a repair.", "source": "web", "meta": {"title": "Customer research", "url": "https://research.example.test/lighting"}},
            {"text": "An untrusted HTTP citation must not be shown as a verified source.", "source": "web", "meta": {"url": "http://insecure.example.test/"}},
        ],
    })
    memory.update_design_run(run["run_id"], context_snapshot=snapshot, context_snapshot_hash=snapshot.content_hash)
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "ready_for_review"):
        if status == "candidate_ready":
            memory.update_design_run(run["run_id"], candidate_sha="b" * 40, candidate_ref="codex/onboarding-report-test")
        if status == "ready_for_review":
            memory.update_design_run(
                run["run_id"],
                quality_report_json={"state": "passed", "gates": {"build": "passed", "browser": "passed"}},
            )
        run = memory.transition_design_run(run["run_id"], status)
    return memory.get_design_run(run["run_id"])


def test_initial_report_is_persisted_once_and_bound_to_exact_inputs(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        run = _run(memory)
        first = persist_initial_onboarding_report(memory, run)
        second = persist_initial_onboarding_report(memory, run)

        assert first["status"] == "completed"
        assert second["id"] == first["id"]
        assert second["output_hash"] == first["output_hash"]
        assert first["payload"]["brief_hash"] == run["intake_hash"]
        assert first["payload"]["candidate_sha"] == run["candidate_sha"]
        assert first["payload"]["business"]["name"] == "North Star Studio"
        assert first["payload"]["planned_pages"] == ["about", "contact"]
        assert first["payload"]["first_page"]["route"] == "/"
        assert "book a consultation" in first["payload"]["summary"].lower()
        assert first["payload"]["evidence"]["research_available"] is True
        assert first["payload"]["evidence"]["research"] == [{
            "summary": "Customers compare hand-crafted lighting before booking a repair.",
            "source": "web",
            "title": "Customer research",
            "url": "https://research.example.test/lighting",
        }]
        assert first["payload"]["limits"]["live_metrics_available"] is False
        assert memory.get_artifact(first["artifact_id"]).content_hash == first["output_hash"]
        assert len(memory.list_design_phase_artifacts(run["run_id"], phase="onboarding_report")) == 1
    finally:
        memory.close()


def test_onboarding_report_is_not_created_for_unverified_candidate(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    try:
        run = _run(memory)
        memory.update_design_run(run["run_id"], quality_report_json={"state": "failed", "gates": {}})

        assert persist_initial_onboarding_report(memory, memory.get_design_run(run["run_id"])) is None
        assert memory.list_design_phase_artifacts(run["run_id"], phase="onboarding_report") == []
    finally:
        memory.close()


def test_new_site_progress_uses_persisted_milestones_only(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    tenant = Tenant(
        tenant_id="new-site",
        config={},
        memory=memory,
        runtime=None,
        context={"journey": Journey(website_present=False, incubation_needed=False)},
        api_token="test-token",
    )
    intake_status = {
        "session_id": "intake-report-test",
        "confirmed": True,
        "confirmed_revision_id": 4,
    }
    try:
        before_candidate = ChatService._new_site_onboarding(memory, intake_status, tenant)
        assert before_candidate["current_stage"] == 2
        assert before_candidate["completed_stages"] == [1]
        assert before_candidate["report"] is None

        run = _run(memory)
        intake_status["session_id"] = run["intake_session_id"]
        intake_status["confirmed_revision_id"] = run["intake_revision_id"]
        before_report = ChatService._new_site_onboarding(memory, intake_status, tenant)
        assert before_report["current_stage"] == 3
        assert before_report["completed_stages"] == [1, 2]
        assert before_report["report_state"] == "preparing"

        persist_initial_onboarding_report(memory, run)
        after_report = ChatService._new_site_onboarding(memory, intake_status, tenant)
        assert after_report["current_stage"] == 4
        assert after_report["completed_stages"] == [1, 2, 3]
        assert after_report["report_state"] == "ready"
        assert after_report["report"]["candidate_sha"] == run["candidate_sha"]
        assert ChatService._new_site_onboarding(memory, intake_status, None) is None
    finally:
        memory.close()


@pytest.mark.parametrize('quality_state', ['passed', 'failed'])
def test_onboarding_projection_and_report_share_the_quality_evidence_size_bound(tmp_path, quality_state):
    memory = Memory(tmp_path / 'memory.db')
    tenant = Tenant(tenant_id='new-site', config={}, memory=memory, runtime=None,
                    context={'journey': Journey(website_present=False, incubation_needed=False)}, api_token='test-token')
    try:
        run = _run(memory)
        quality = {'state': quality_state, 'gates': {'build': quality_state, 'browser': quality_state},
                   'evidence': {'browser': 'observed evidence ' * 30_000}}
        with pytest.raises(ContractError, match='contract exceeds'):
            canonical_hash(quality)
        expected_hash = canonical_hash(quality, max_bytes=MAX_QUALITY_REPORT_BYTES)
        memory.update_design_run(run['run_id'], quality_report_json=quality)
        run = memory.get_design_run(run['run_id'])
        phase = persist_initial_onboarding_report(memory, run)
        status = {'session_id': run['intake_session_id'], 'confirmed': True, 'confirmed_revision_id': run['intake_revision_id']}
        projected = ChatService._new_site_onboarding(memory, status, tenant)
        if quality_state == 'passed':
            assert phase['payload']['quality_evidence_hash'] == expected_hash
            assert projected['report_state'] == 'ready'
            assert projected['report']['quality_evidence_hash'] == expected_hash
            quality['evidence']['browser'] += ' changed'
            memory.update_design_run(run['run_id'], quality_report_json=quality)
            assert ChatService._new_site_onboarding(memory, status, tenant)['report_state'] == 'preparing'
        else:
            assert phase is None
            assert projected['report'] is None
            assert projected['completed_stages'] == [1]
    finally:
        memory.close()

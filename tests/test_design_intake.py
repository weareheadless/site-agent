import pytest

import json

from site_agent.application.design_intake import DesignIntakeService, DesignIntakeServiceError
from site_agent.application.customer_genesis import CustomerGenesisService
from site_agent.brain.design_intake import (
    DesignIntakeAdvisorError,
    UnavailableDesignIntakeAdvisor,
    _advisor_prompt,
)
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import (
    DesignIntakeDraft,
    IntakeDisposition,
    IntakeFieldUpdate,
    IntakeFieldProvenance,
    IntakeTurnResult,
    merge_intake_turn,
)
from site_agent.core.chat_jobs import run_job
from site_agent.core.memory import Memory
from site_agent.core.media_contracts import MediaAsset, MediaKind, MediaStatus


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Brand strategy for independent businesses.",
            "primary_services": ["Brand strategy"],
            "location": "North Shore",
        },
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear, thoughtful, and warm."},
        "site": {"required_pages": ["index.html"]},
    })


class _Advisor:
    def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
        return IntakeTurnResult(
            schema_version=1,
            assistant_message="I recorded that direction. Confirm the brief when it feels right.",
            field_updates=(IntakeFieldUpdate(
                path="brand.vibe",
                value="Quiet, editorial, and tactile",
                basis="owner_statement",
            ),),
            suggested_readiness="ready_to_build",
        )


def test_conversational_turn_is_durable_and_message_bound(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_Advisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Keep the direction quiet and tactile.")
    job = memory.claim_chat_job("test-worker")

    result = run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "test-worker",
    )

    assert result["operation_kind"] == "design_intake_advice"
    assert result["intake_revision"] == 2
    stored = service.get_session(session["session_id"])
    assert stored["draft"]["fields"]["brand"]["vibe"] == "Quiet, editorial, and tactile"
    assert stored["draft"]["provenance"]["brand.vibe"]["origin"] == "confirmed"
    assert stored["messages"][-1]["role"] == "assistant"
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    memory.close()


def test_malformed_scalar_field_update_does_not_break_intake_turn():
    turn = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "I recorded the direction and will keep working through the brief.",
        "field_updates": [
            {
                "path": "business.offer_summary",
                "value": "A quiet, editorial website for independent businesses.",
                "basis": "owner_statement",
            },
            {
                "path": "conversion.primary_action",
                "value": {"label": "Book a consultation"},
                "basis": "owner_statement",
            },
        ],
    })

    assert [item.path for item in turn.field_updates] == ["business.offer_summary"]


def test_malformed_scalar_field_update_does_not_block_genesis_revision(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _MalformedAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="I recorded the direction and will keep working through the brief.",
                field_updates=(
                    IntakeFieldUpdate(
                        path="business.offer_summary",
                        value="A quiet, editorial website for independent businesses.",
                        basis="owner_statement",
                    ),
                    IntakeFieldUpdate(
                        path="conversion.primary_action",
                        value={"label": "Book a consultation"},
                        basis="owner_statement",
                    ),
                ),
            )

    service = DesignIntakeService(
        memory,
        advisor=_MalformedAdvisor(),
        genesis_service=CustomerGenesisService(memory),
    )
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "Keep the direction quiet and editorial.")
        job = memory.claim_chat_job("malformed-field-worker")

        result = run_job(
            {
                "memory": memory,
                "design_intake_service": service,
                "config": {},
                "llm": object(),
            },
            job,
            "malformed-field-worker",
        )

        assert "error" not in result
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
        stored = service.get_session(session["session_id"])
        assert stored["draft"]["fields"]["business"]["offer_summary"] == (
            "A quiet, editorial website for independent businesses."
        )
        assert stored["draft"]["fields"].get("conversion", {}).get("primary_action") is None
        assert CustomerGenesisService(memory).current().business_world["purpose"] == (
            "A quiet, editorial website for independent businesses."
        )
    finally:
        memory.close()


def test_malformed_persisted_scalar_is_removed_when_draft_is_reloaded(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    try:
        service = DesignIntakeService(memory)
        session = service.create_session()
        malformed = DesignIntakeDraft.empty().with_value(
            "business.offer_summary",
            "A quiet, editorial website for independent businesses.",
            IntakeFieldProvenance(path="business.offer_summary", origin="confirmed"),
        ).with_value(
            "conversion.primary_action",
            {"label": "Book a consultation"},
            IntakeFieldProvenance(path="conversion.primary_action", origin="confirmed"),
        )
        memory.save_design_intake_revision(
            session["session_id"],
            malformed,
            expected_revision=session["revision"],
        )

        reloaded = memory.get_design_intake_session(session["session_id"])

        assert reloaded is not None
        assert reloaded["draft"]["fields"].get("conversion", {}).get("primary_action") is None
        assert "conversion.primary_action" not in reloaded["draft"]["provenance"]
    finally:
        memory.close()


def test_confirmation_requires_offer_summary_before_building(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory)
    try:
        session = service.create_session()

        with pytest.raises(DesignIntakeServiceError, match=r"business\.offer_summary is required before building"):
            service.confirm(
                session["session_id"],
                revision=session["revision"],
                draft_hash=session["draft_hash"],
                idempotency_key="missing-offer",
            )
    finally:
        memory.close()


def test_creative_insights_from_an_intake_turn_persist_as_incubation_insights(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _AdvisorWithInsights:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="Noted — the quieter the surface, the stronger the trust.",
                creative_insights=(
                    {
                        "kind": "creative_implication",
                        "summary": "A quieter opening may make the technical offer easier to trust.",
                        "basis": "recommendation",
                        "related_intake_paths": ["brand.voice", "audience.concerns"],
                        "confidence": 0.6,
                    },
                    {
                        "kind": "creative_implication",
                        "summary": "Soft material cues could signal warmth before the first sentence.",
                        "basis": "recommendation",
                        "related_intake_paths": ["brand.colors"],
                        "confidence": 0.5,
                    },
                ),
                suggested_readiness="needs_more",
            )

    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_AdvisorWithInsights())
    session = service.create_session()
    service.send_message(session["session_id"], "Keep the direction quiet and tactile.")
    job = memory.claim_chat_job("test-worker")

    run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "test-worker",
    )

    insights = memory.list_incubation_insights(limit=10)
    assert len(insights) == 2
    summaries = [item["summary"] for item in insights]
    assert any("quieter opening" in summary for summary in summaries)
    assert any("material cues" in summary for summary in summaries)
    assert all(item["kind"] == "creative_implication" for item in insights)
    memory.close()


def test_build_composes_creative_direction_from_confirmed_intake(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(prompt)
            return {"run_id": "intake-lab-" + "c" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            if not self.submissions:
                return None
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-direction",
    )
    final_revision = confirmed["session"]["confirmed_revision_id"]

    result = service.build(session["session_id"], confirmed_revision=final_revision, idempotency_key="build-direction")

    assert len(lab.submissions) == 1
    prompt = lab.submissions[0]
    assert "North Star Studio" in prompt
    assert "Brand strategy for independent businesses." in prompt
    assert "Independent business owners" in prompt
    assert "Clear, thoughtful, and warm." in prompt
    assert "distinctive, high-end, and one of a kind" in prompt
    assert "design skills define the quality bar" in prompt
    assert "EXECUTION BAR" not in prompt
    assert "cenote" not in prompt.casefold()
    assert "shaft of daylight" not in prompt.casefold()
    assert "Build the first visual website candidate" not in prompt
    assert result["session"]["design_run_id"] == "intake-lab-" + "c" * 32
    memory.close()


def test_build_uses_explicit_owner_design_request_when_provided(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(prompt)
            return {"run_id": "intake-lab-" + "e" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            if not self.submissions:
                return None
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-explicit",
    )
    final_revision = confirmed["session"]["confirmed_revision_id"]

    explicit = "Make the first viewport feel like a quiet underground cenote with a single shaft of light."
    service.build(session["session_id"], confirmed_revision=final_revision, owner_request=explicit, idempotency_key="build-explicit")

    assert lab.submissions == [explicit]
    memory.close()


def test_asset_request_notes_extract_only_owner_suppliable_imagery_gaps():
    from site_agent.application.design_intake import asset_request_notes

    critique = {
        "findings": [
            {
                "id": "A2",
                "severity": "high",
                "category": "imagery",
                "summary": "The site presents no imagery of the jungle camp or Mayan food; only cave photos are used.",
                "evidence": "Screenshots show only cave imagery.",
            },
            {
                "id": "A3",
                "severity": "medium",
                "category": "composition",
                "summary": "Body text over a dark cave image has marginal contrast.",
                "evidence": "Text overlaps the figure.",
            },
        ]
    }

    notes = asset_request_notes(critique)

    assert len(notes) == 1
    assert "no imagery of the jungle camp" in notes[0]


def test_asset_request_notes_ignore_subjective_and_conversion_findings():
    from site_agent.application.design_intake import asset_request_notes

    critique = {
        "findings": [
            {
                "id": "A1",
                "severity": "high",
                "category": "conversion-path-integration",
                "summary": "The primary CTA is hidden in the footer.",
            },
            {
                "id": "A3",
                "severity": "medium",
                "category": "imagery",
                "summary": "Crop the lighthouse photo for better framing.",
            },
        ]
    }

    assert asset_request_notes(critique) == ()


def test_surface_review_asset_requests_posts_one_durable_chat_request(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()
    conversation_id = session["conversation_id"]
    memory.create_design_run(
        run_id="intake-lab-" + "f" * 32,
        mode="local_experiment",
        status="needs_repair",
        intake_json=_intake().to_dict(),
        intake_hash="a" * 64,
        base_sha="b" * 40,
        publishable=False,
        candidate_ref="refs/ada-design-lab/run",
        conversation_id=conversation_id,
        intake_session_id=session["session_id"],
    )
    run_id = "intake-lab-" + "f" * 32
    memory.update_design_run(run_id, quality_report_json={
        "state": "passed",
        "visual_critique": {
            "findings": [{
                "id": "A2",
                "severity": "high",
                "category": "imagery",
                "summary": "The site presents no imagery of the local Mayan kitchen; only cave photos are used.",
            }],
        },
    })

    first = service.surface_review_asset_requests(run_id)
    second = service.surface_review_asset_requests(run_id)

    assert first == ["The site presents no imagery of the local Mayan kitchen; only cave photos are used."]
    assert second == first
    messages = memory.get_messages(conversation_id)
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert "no imagery of the local Mayan kitchen" in messages[0]["text"]
    assert "send them over" in messages[0]["text"] or "happen to have any" in messages[0]["text"]
    events = memory.list_design_run_events(run_id, limit=50)
    surfaced = [e for e in events if e.get("stage") == "asset_request_surfaced"]
    assert len(surfaced) == 1
    memory.close()


def test_asset_request_message_uses_advisor_voice_when_available(tmp_path):
    from site_agent.application.design_intake import DesignIntakeService

    class _Advisor:
        def advise(self, *args, **kwargs):
            raise AssertionError("advise must not be called")

        def request_owner_assets(self, *, business_name, context):
            assert business_name == "North Star Studio"
            assert context
            return "Tu n'as pas une photo de la cuisine maya ? Ca donnerait vraiment vie au site."

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_Advisor())
    written = service._asset_request_message("North Star Studio", ("Mayan kitchen imagery",))

    assert written == "Tu n'as pas une photo de la cuisine maya ? Ca donnerait vraiment vie au site."
    memory.close()


def test_surface_review_asset_requests_is_silent_without_asset_gaps(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()
    conversation_id = session["conversation_id"]
    run_id = "intake-lab-" + "g" * 32
    memory.create_design_run(
        run_id=run_id,
        mode="local_experiment",
        status="needs_repair",
        intake_json=_intake().to_dict(),
        intake_hash="a" * 64,
        base_sha="b" * 40,
        publishable=False,
        candidate_ref="refs/ada-design-lab/run",
        conversation_id=conversation_id,
        intake_session_id=session["session_id"],
    )
    memory.update_design_run(run_id, quality_report_json={
        "state": "passed",
        "visual_critique": {"findings": [{
            "id": "A1",
            "severity": "high",
            "category": "conversion-path-integration",
            "summary": "The CTA is buried; move it into the header.",
        }]},
    })

    result = service.surface_review_asset_requests(run_id)

    assert result == []
    assert memory.get_messages(conversation_id) == []
    memory.close()


def test_incomplete_advisor_turn_can_persist_before_offer_summary_exists(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(
        memory,
        advisor=_Advisor(),
        genesis_service=CustomerGenesisService(memory),
    )
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "I am still shaping the offer.")
        job = memory.claim_chat_job("test-worker")

        result = run_job(
            {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
            job,
            "test-worker",
        )

        assert result["operation_kind"] == "design_intake_advice"
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
        assert memory.list_customer_genesis_revisions() == []
    finally:
        memory.close()


def test_advisor_turn_keeps_the_owner_facing_message_natural(tmp_path):
    class _NaturalConversationAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message=(
                    "Je vois deja une direction claire. Quel usage veux-tu privilegier pour les images ?"
                ),
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=_NaturalConversationAdvisor())
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "Je veux continuer.")
        job = memory.claim_chat_job("natural-question-worker")

        result = run_job(
            {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
            job,
            "natural-question-worker",
        )

        assert result["reply"] == "Je vois deja une direction claire. Quel usage veux-tu privilegier pour les images ?"
        assert "Open questions:" not in result["reply"]
        assert "open_questions" not in result
        assert "open_questions" not in service.get_session(session["session_id"])["readiness"]
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    finally:
        memory.close()


def test_saved_revision_invokes_research_hook_without_making_it_part_of_intake_state(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    calls = []

    def on_revision_saved(session_id, draft, revision):
        stored = memory.get_design_intake_session(session_id)
        calls.append((session_id, draft.content_hash, revision["revision"]))
        assert stored["revision"] == revision["revision"]
        return {"status": "queued", "request_id": "research_" + "a" * 32}

    service = DesignIntakeService(
        memory,
        default_intake=_intake(),
        advisor=_Advisor(),
        on_revision_saved=on_revision_saved,
    )
    try:
        session = service.create_session()
        queued = service.send_message(session["session_id"], "Keep the direction quiet and tactile.")
        job = memory.claim_chat_job("test-worker")
        result = run_job(
            {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
            job,
            "test-worker",
        )

        assert result["research"]["status"] == "queued"
        assert calls == [(session["session_id"], result["intake_hash"], 2)]
        assert memory.get_design_intake_session(session["session_id"])["revision"] == 2
        assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    finally:
        memory.close()


def test_confirm_freezes_revision_and_hands_off_one_local_run(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def submit(self, prompt, raw_intake, **kwargs):
            assert raw_intake["provenance"]["intake_session_id"].startswith("intake-")
            return {"run_id": "intake-lab-" + "a" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=_Lab())
    session = service.create_session()
    result = service.confirm_and_build(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
    )

    assert result["session"]["status"] == "confirmed"
    assert result["session"]["design_run_id"] == "intake-lab-" + "a" * 32
    assert result["run"]["publishable"] is False
    memory.close()


def test_confirmation_and_build_are_separate_and_build_retry_is_idempotent(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append((prompt, raw_intake, kwargs))
            return {"run_id": "intake-lab-" + "b" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()

    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-test",
    )

    assert confirmed["confirmed"] is True
    assert confirmed["session"]["status"] == "confirmed"
    assert not lab.submissions
    final_revision = confirmed["session"]["confirmed_revision_id"]

    first = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-test",
    )
    second = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-test",
    )

    assert len(lab.submissions) == 1
    assert first["run"]["run_id"] == second["run"]["run_id"]
    assert second["idempotent"] is True
    assert first["session"]["design_run_id"] == "intake-lab-" + "b" * 32
    memory.close()


def test_build_recovers_a_stale_reservation_without_creating_a_second_run(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.submissions.append(kwargs)
            return {"run_id": kwargs["run_id"], "status": "building", "publishable": False}

        def get_run(self, run_id):
            if not self.submissions:
                return None
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-stale-reservation",
    )
    revision_id = confirmed["session"]["confirmed_revision_id"]

    original_reserve = memory.reserve_design_intake_build

    def reserve_then_interrupt(*args, **kwargs):
        original_reserve(*args, **kwargs)
        raise KeyboardInterrupt("simulated process death after reservation")

    memory.reserve_design_intake_build = reserve_then_interrupt
    with pytest.raises(KeyboardInterrupt):
        service.build(
            session["session_id"],
            confirmed_revision=revision_id,
            idempotency_key="build-stale-reservation",
        )
    memory.reserve_design_intake_build = original_reserve
    memory.conn.execute(
        "UPDATE design_intake_operations SET updated_ts = ? WHERE session_id = ? AND operation = 'build'",
        ("2000-01-01T00:00:00+00:00", session["session_id"]),
    )
    memory.conn.commit()

    recovered = service.build(
        session["session_id"],
        confirmed_revision=revision_id,
        idempotency_key="build-stale-reservation",
    )

    assert len(lab.submissions) == 1
    assert recovered["run"]["run_id"] == lab.submissions[0]["run_id"]
    assert recovered["run"]["run_id"].startswith("intake-lab-")
    assert memory.get_design_intake_operation(
        session["session_id"], "build", "build-stale-reservation"
    )["state"] == "submitted"
    memory.close()


def test_failed_candidate_is_not_reused_and_a_fresh_build_is_started(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            run_id = "intake-lab-" + ("z" * 32 if self.submissions else "b" * 32)
            self.submissions.append(run_id)
            return {"run_id": run_id, "status": "building", "publishable": False}

        def get_run(self, run_id):
            if run_id == "intake-lab-" + "b" * 32:
                return {"run_id": run_id, "status": "failed", "publishable": False}
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-retry",
    )
    final_revision = confirmed["session"]["confirmed_revision_id"]

    first = service.build(session["session_id"], confirmed_revision=final_revision, idempotency_key="build-retry")
    assert first["run"]["run_id"] == "intake-lab-" + "b" * 32

    fresh = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-retry-fresh",
        force_new=True,
    )
    assert fresh.get("idempotent") is not True
    assert fresh["run"]["run_id"] == "intake-lab-" + "z" * 32
    assert fresh["session"]["design_run_id"] == "intake-lab-" + "z" * 32
    assert len(lab.submissions) == 2
    memory.close()


def test_bound_assets_are_frozen_into_the_confirmed_site_intake(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    asset_id = memory.create_media_asset(MediaAsset(
        asset_id=0,
        status=MediaStatus.READY,
        media_kind=MediaKind.IMAGE,
        source_kind="owner_upload",
        original_name="hero.webp",
        content_type="image/webp",
        original_size=4,
        original_sha256="a" * 64,
        storage_id="hero",
        original_key="media/hero/original/hero.webp",
        normalized_key="media/hero/normalized/hero.webp",
        thumbnail_key="media/hero/thumbnail/hero.webp",
        created_ts="now",
        updated_ts="now",
    ))

    class _Lab:
        def __init__(self):
            self.intakes = []

        def submit(self, prompt, raw_intake, **kwargs):
            self.intakes.append(raw_intake)
            return {"run_id": "intake-lab-" + "d" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    updated = service.update_assets(session["session_id"], [{
        "asset_id": asset_id,
        "position": 0,
        "usage": "website",
        "reference_aspects": ["hero composition"],
    }])

    confirmed = service.confirm(
        session["session_id"],
        revision=updated["revision"],
        draft_hash=updated["draft_hash"],
    )
    built = service.build(
        session["session_id"],
        confirmed_revision=confirmed["session"]["confirmed_revision_id"],
    )

    assert built["run"]["publishable"] is False
    assert lab.intakes[0]["assets"] == [{
        "id": str(asset_id),
        "usage": "website",
        "position": 0,
        "reference_aspects": ["hero composition"],
        "owner_note": "",
    }]
    memory.close()


def test_uploaded_asset_is_available_to_build_without_owner_usage_decision(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    asset_id = memory.create_media_asset(MediaAsset(
        asset_id=0,
        status=MediaStatus.READY,
        media_kind=MediaKind.IMAGE,
        source_kind="owner_upload",
        original_name="reference.webp",
        content_type="image/webp",
        original_size=4,
        original_sha256="b" * 64,
        storage_id="reference",
        original_key="media/reference/original/reference.webp",
        normalized_key="media/reference/normalized/reference.webp",
        thumbnail_key="media/reference/thumbnail/reference.webp",
        created_ts="now",
        updated_ts="now",
    ))
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()

    updated = service.update_assets(session["session_id"], [{
        "asset_id": asset_id,
        "position": 0,
        "usage": "undecided",
    }])

    assert updated["readiness"]["state"] == "ready_to_build"
    assert updated["readiness"]["undecided_asset_ids"] == []
    confirmed = service.confirm(
        session["session_id"],
        revision=updated["revision"],
        draft_hash=updated["draft_hash"],
    )
    assert confirmed["confirmed"] is True
    memory.close()


def test_message_after_confirmation_clears_current_build_for_a_new_revision(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def submit(self, prompt, raw_intake, **kwargs):
            return {"run_id": "intake-lab-" + "c" * 32, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "building", "publishable": False}

    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=_Lab())
    session = service.create_session()
    built = service.confirm_and_build(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
    )
    assert built["session"]["design_run_id"] == "intake-lab-" + "c" * 32

    queued = service.send_message(session["session_id"], "I want to revisit the type scale.")
    current = service.get_session(session["session_id"])

    assert queued["job_id"] > 0
    assert current["status"] == "collecting"
    assert current["design_run_id"] is None
    assert current["confirmed_revision"] == built["session"]["confirmed_revision"]
    memory.close()


def test_explicit_confirmation_reconciles_a_stale_post_confirmation_job(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake())
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-stale-job",
    )

    # Queueing a new owner turn intentionally reopens the conversation. If its
    # worker loses the revision race before saving anything, the frozen intake
    # remains safe to confirm and build again.
    service.send_message(session["session_id"], "Please keep the confirmed direction.")
    current = service.get_session(session["session_id"])
    assert current["status"] == "collecting"
    assert current["revision"] == confirmed["session"]["confirmed_revision"]

    resumed = service.confirm(
        session["session_id"],
        revision=current["revision"],
        draft_hash=current["draft_hash"],
        idempotency_key="confirm-stale-job-retry",
    )

    assert resumed["confirmed"] is True
    assert resumed["session"]["status"] == "confirmed"
    assert resumed["session"]["confirmed_revision"] == current["revision"]
    memory.close()


def test_empty_draft_stays_collecting_without_inventing_facts(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=UnavailableDesignIntakeAdvisor())
    session = service.create_session()

    assert session["readiness"]["state"] == "collecting"
    assert session["draft"]["fields"] == {}
    memory.close()


def test_llm_failure_completes_with_truthful_safe_follow_up(tmp_path):
    class _FailingLLM:
        api_key = "configured"

        def chat(self, messages, **kwargs):
            raise RuntimeError("model returned an empty completion")

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, llm=_FailingLLM())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "I am starting a retreat business.")
    job = memory.claim_chat_job("fallback-worker")

    result = run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "fallback-worker",
    )

    assert result["advisor_fallback"] is True
    assert "I have the direction so far" in result["reply"]
    assert "open_questions" not in result
    assert "open_questions" not in service.get_session(session["session_id"])["readiness"]
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    stored = service.get_session(session["session_id"])
    assert stored["messages"][-1]["role"] == "assistant"
    assert stored["draft"]["fields"] == {}
    memory.close()


def test_non_llm_advisor_errors_are_not_hidden(tmp_path):
    class _FailingAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            raise DesignIntakeAdvisorError("broken test advisor")

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=_FailingAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Keep going.")
    job = memory.claim_chat_job("error-worker")

    result = run_job(
        {
            "memory": memory,
            "design_intake_service": service,
            "config": {},
            "llm": object(),
        },
        job,
        "error-worker",
    )

    assert result == {"error": "broken test advisor"}
    assert memory.get_chat_job(queued["job_id"])["status"] == "error"
    memory.close()


def test_intake_advisor_can_use_a_separate_chat_model():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append(kwargs)
            return '{"schema_version": 1, "assistant_message": "Tell me who this is for.", "field_updates": [{"path": "business.name", "value": "Workshop", "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(
        _LLM(),
        {"intake_advisor": {"model": "fast-chat", "timeout_seconds": 12, "max_retries": 0, "max_tokens": 400}},
    )
    result = advisor.advise(DesignIntakeDraft.empty(), [], "I am starting a business.")

    assert result.assistant_message == "Tell me who this is for."
    assert result.field_updates[0].path == "business.name"
    assert calls == [{
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 400,
        "timeout_seconds": 12.0,
        "max_retries": 0,
        "model": "fast-chat",
    }]


def test_intake_advisor_skips_entrim_thinking_knob_on_openrouter_client():
    calls = []

    class _LLM:
        base_url = "https://openrouter.ai/api/v1"

        def chat(self, messages, **kwargs):
            calls.append(kwargs)
            return '{"schema_version": 1, "assistant_message": "Tell me who this is for.", "field_updates": [{"path": "business.name", "value": "Claro Oscuro", "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(
        _LLM(),
        {"intake_advisor": {
            "model": "openai/gpt-4.1-mini",
            "timeout_seconds": 90,
            "max_retries": 1,
            "max_tokens": 4096,
            "enable_thinking": False,
        }},
    )
    advisor.advise(DesignIntakeDraft.empty(), [], "I am starting a business.")

    assert calls == [{
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 4096,
        "timeout_seconds": 90.0,
        "max_retries": 1,
        "model": "openai/gpt-4.1-mini",
    }]


def test_intake_advisor_keeps_entrim_thinking_knob_on_entrim_client():
    calls = []

    class _LLM:
        base_url = "https://api.entrim.ai/v1"

        def chat(self, messages, **kwargs):
            calls.append(kwargs)
            return '{"schema_version": 1, "assistant_message": "Tell me who this is for.", "field_updates": [{"path": "business.name", "value": "Claro Oscuro", "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(
        _LLM(),
        {"intake_advisor": {"enable_thinking": False, "max_retries": 1}},
    )
    advisor.advise(DesignIntakeDraft.empty(), [], "I am starting a business.")

    assert calls == [{
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 1200,
        "timeout_seconds": 45.0,
        "max_retries": 1,
        "enable_thinking": False,
    }]


def test_intake_advisor_client_is_scoped_when_configured():
    from site_agent.main import _intake_advisor_client

    client = _intake_advisor_client(
        {
            "design_engine": {
                "intake_advisor": {
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                    "model": "openai/gpt-4.1-mini",
                },
            },
            "llm": {
                "base_url": "https://api.entrim.ai/v1",
                "model": "deepseek-ai/DeepSeek-V4-Flash",
                "timeout_seconds": 300,
                "max_retries": 2,
                "max_tokens": 16384,
            },
            "env": {"llm_api_key": "ENTRIM_API_KEY"},
        },
        memory=None,
        env={"ENTRIM_API_KEY": "entrim-key", "OPENROUTER_API_KEY": "openrouter-key"},
    )

    assert client is not None
    assert client.base_url == "https://openrouter.ai/api/v1"
    assert client.model == "openai/gpt-4.1-mini"
    assert client.api_key == "openrouter-key"
    assert client.enable_thinking is False

    assert _intake_advisor_client(
        {"design_engine": {}, "llm": {}, "env": {}}, memory=None, env={}
    ) is None


def test_intake_turn_discards_legacy_question_metadata():
    result = IntakeTurnResult.from_dict({
        "schema_version": 1,
        "assistant_message": "We can keep shaping this together.",
        "field_updates": [],
        "assumption_updates": [],
        "deferred_updates": [],
        "contradictions": [],
        "topics_addressed": ["business"],
        "next_topics": ["brand"],
        "open_questions": ["What should change next?"],
        "suggested_readiness": "collecting",
    })

    assert "open_questions" not in result.to_dict()
    assert "next_topics" not in result.to_dict()


def test_merge_intake_turn_keeps_assumption_and_deferred_mutually_exclusive():
    draft = DesignIntakeDraft.empty()
    draft = merge_intake_turn(draft, IntakeTurnResult(
        schema_version=1,
        assistant_message="assume",
        assumption_updates=(IntakeDisposition(path="design.content_readiness", note="working", value="copy"),),
    ), source_message_id=1)
    draft = merge_intake_turn(draft, IntakeTurnResult(
        schema_version=1,
        assistant_message="defer",
        deferred_updates=(IntakeDisposition(path="design.content_readiness", note="wait", value=None),),
    ), source_message_id=2)

    assert draft.validate() is None
    assert any(item.path == "design.content_readiness" for item in draft.deferred)
    assert not any(item.path == "design.content_readiness" for item in draft.assumptions)


def test_intake_advisor_makes_exactly_one_call_per_turn():
    calls = []

    class _ForgetfulLLM:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return '{"schema_version": 1, "assistant_message": "Merci ! Je note la restauration de tapisserie et les ateliers.", "field_updates": [{"path": "business.primary_services", "value": ["Restauration de tapisserie", "Ateliers"], "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_ForgetfulLLM(), {}).advise(
        DesignIntakeDraft.empty(),
        [],
        "Je suis tapissiere restauratrice et j'organise des ateliers.",
    )

    assert len(calls) == 1
    assert [item.path for item in result.field_updates] == ["business.primary_services"]
    assert result.assistant_message == "Merci ! Je note la restauration de tapisserie et les ateliers."


def test_intake_advisor_makes_exactly_one_call_for_acknowledgements():
    calls = []

    class _AckLLM:
        def chat(self, messages, **kwargs):
            calls.append(True)
            return '{"schema_version": 1, "assistant_message": "Super !", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_AckLLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "les 2"
    )

    assert len(calls) == 1
    assert result.assistant_message == "Super !"


def test_intake_advisor_uses_qwen_visual_summary_for_text_only_chat_models():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return '{"schema_version": 1, "assistant_message": "Je note la palette du logo.", "field_updates": [{"path": "brand.existing_palette", "value": ["#D97A35", "#29455C"], "basis": "owner_statement", "note": ""}], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(_LLM(), {"intake_advisor": {"model": "deepseek-ai/DeepSeek-V4-Flash"}})
    result = advisor.advise(
        DesignIntakeDraft.empty(),
        [],
        "Inspire-toi de mon logo joint, mais plus doux.",
        assets=[{
            "asset_id": 7,
            "name": "logo.png",
            "description": "A warm rust-orange band over slate bars",
            "tags": ["pattern", "stripes"],
            "dominant_colors": ["#D97A35", "#29455C"],
        }],
    )

    assert result.field_updates[0].path == "brand.existing_palette"
    content = calls[0][-1]["content"]
    assert isinstance(content, list)
    assert content[-1]["type"] == "text"
    assert all(part.get("type") != "image_url" for part in content)
    assert "#D97A35" in content[1]["text"]
    assert "pattern" in content[1]["text"]


def test_intake_advisor_uses_stored_media_summary_instead_of_raw_images():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return '{"schema_version": 1, "assistant_message": "I can see the reference.", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(_LLM(), {"intake_advisor": {"model": "vision-chat"}})
    result = advisor.advise(
        DesignIntakeDraft.empty(),
        [],
        "Use these references to guide the direction.",
        assets=[{"asset_id": 7, "name": "logo.webp", "image_data_url": "data:image/webp;base64,AA=="}],
    )

    assert result.assistant_message == "I can see the reference."
    assert "open_questions" not in result.to_dict()
    content = calls[0][0][-1]["content"]
    assert isinstance(content, list)
    assert all(part.get("type") != "image_url" for part in content if isinstance(part, dict))


def test_intake_advisor_does_not_reupload_already_tagged_images():
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return '{"schema_version": 1, "assistant_message": "I will use the stored visual tags.", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    advisor = LLMDesignIntakeAdvisor(_LLM(), {"intake_advisor": {"model": "vision-chat"}})
    advisor.advise(
        DesignIntakeDraft.empty(),
        [],
        "Use the stored reference analysis.",
        assets=[{
            "asset_id": 7,
            "name": "logo.webp",
            "description": "A warm rust-orange band over slate bars",
            "tags": ["pattern", "stripes"],
            "image_data_url": "data:image/webp;base64,AA==",
        }],
    )

    content = calls[0][0][-1]["content"]
    assert all(part.get("type") != "image_url" for part in content if isinstance(part, dict))
    assert "rust-orange" in content[1]["text"]


def test_intake_advisor_preserves_provider_prose_without_question_metadata():
    class _LLM:
        def chat(self, messages, **kwargs):
            return (
                "Based on the reference, here are the next questions:\n\n"
                "1. Which colors do you envision for the brand?\n"
                "2. Are there styles you want to avoid?"
            )

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "Continue with the visual direction."
    )

    assert result.field_updates == ()
    assert result.assistant_message.startswith("Based on the reference")
    assert "open_questions" not in result.to_dict()


def test_intake_advisor_keeps_natural_prose_without_forcing_a_question():
    class _LLM:
        def chat(self, messages, **kwargs):
            return "The contrast between light and darkness is a strong starting point for the visual direction."

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(), [], "I want the site to feel more atmospheric."
    )

    assert result.assistant_message.startswith("The contrast between light and darkness")
    assert "open_questions" not in result.to_dict()


def test_intake_turn_does_not_rewrite_a_natural_advisor_message(tmp_path):
    class _GenericAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message=(
                    "I've updated the audience and primary actions. "
                    "Which colors should the site use?"
                ),
                suggested_readiness="collecting",
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_GenericAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Yes, continue.")
    job = memory.claim_chat_job("question-worker")

    result = run_job(
        {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
        job,
        "question-worker",
    )

    assert "Which colors should the site use" in result["reply"]
    assert "Open questions:" not in result["reply"]
    assert "open_questions" not in result
    assert "open_questions" not in service.get_session(session["session_id"])["readiness"]
    stored_job = memory.get_chat_job(queued["job_id"])
    assert stored_job["status"] == "done"
    step_text = [step["text"] for step in stored_job["steps"]]
    assert "intake / asking Ada for the next useful step" in step_text
    assert "intake / validating the proposed intake turn" in step_text
    memory.close()


def test_intake_turn_does_not_expose_internal_topic_lists(tmp_path):
    class _NaturalAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="That gives us a clear foundation to work from.",
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_NaturalAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Keep going.")
    job = memory.claim_chat_job("natural-worker")
    result = run_job(
        {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
        job,
        "natural-worker",
    )

    assert result["reply"] == "That gives us a clear foundation to work from."
    assert "open_questions" not in result
    assert "open_questions" not in service.get_session(session["session_id"])["readiness"]
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    memory.close()


def test_latest_advisor_message_is_durable_without_a_question_list(tmp_path):
    class _DirectConversationAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=()):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="I reviewed the direction. Which color should lead the first screen?",
            )

    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, advisor=_DirectConversationAdvisor())
    session = service.create_session()
    queued = service.send_message(session["session_id"], "Continue with the visual direction.")
    job = memory.claim_chat_job("reload-worker")
    run_job(
        {"memory": memory, "design_intake_service": service, "config": {}, "llm": object()},
        job,
        "reload-worker",
    )

    reloaded = service.get_session(session["session_id"])

    assert reloaded["messages"][-1]["text"] == "I reviewed the direction. Which color should lead the first screen?"
    assert "open_questions" not in reloaded["readiness"]
    assert memory.get_chat_job(queued["job_id"])["status"] == "done"
    memory.close()


def test_advisor_prompt_exposes_uploaded_images_as_context():
    from site_agent.brain.design_intake import _advisor_prompt
    from site_agent.brain.design_guidance import load_design_skills

    prompt = _advisor_prompt(DesignIntakeDraft.empty(), [], load_design_skills().content)
    assert "Available uploaded images" in prompt
    assert "read them as visual evidence" in prompt
    assert "bounded summary" in prompt
    assert "do not invent" in prompt


def test_advisor_prompt_reads_vision_summary_as_grounded_evidence():
    from site_agent.brain.design_intake import _advisor_prompt
    from site_agent.brain.design_guidance import load_design_skills

    prompt = _advisor_prompt(DesignIntakeDraft.empty(), [], load_design_skills().content)
    assert "bounded summary" in prompt
    assert "do not invent" in prompt


def test_advisor_prompt_makes_imagery_request_optional_and_non_blocking():
    from site_agent.brain.design_intake import _advisor_prompt
    from site_agent.brain.design_guidance import load_design_skills

    prompt = _advisor_prompt(DesignIntakeDraft.empty(), [], load_design_skills().content)

    assert "Optional imagery conversation" in prompt
    assert "photos, a logo, or visual references" in prompt
    assert "must never block readiness or research" in prompt
    assert "asking" in prompt and "again" in prompt


def test_truncated_intake_json_is_never_echoed_verbatim(tmp_path):
    from site_agent.brain.design_intake import (
        DesignIntakeAdvisorError,
        LLMDesignIntakeAdvisor,
        _looks_jsonish,
    )

    assert _looks_jsonish('{"schema_version": 1, "assistant_message": "x", "field_')
    assert _looks_jsonish("```json\n{\"a\": 1}")
    assert not _looks_jsonish("Merci, dites m'en plus.")
    assert not _looks_jsonish("")

    class _TruncatingLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            # A completion the model was forced to cut off mid-field_updates.
            return '{"schema_version":1,"assistant_message":"Claro Oscuro — un bel univers.",' \
                   '"field_updates":[{"path":"business.name","value":"Claro Oscuro","basis":"owner_statement"},{"path":"brand.'

    llm = _TruncatingLLM()
    advisor = LLMDesignIntakeAdvisor(llm, {"intake_advisor": {}})
    try:
        advisor.advise(DesignIntakeDraft.empty(), [], "Je lance une retraite de plongee appelée Claro Oscuro.")
        raise AssertionError("truncated JSON must raise, not be echoed")
    except DesignIntakeAdvisorError as exc:
        assert "JSON" in str(exc) or "truncated" in str(exc)
    assert llm.calls == 1


def test_short_requests_are_handled_by_the_model_not_the_host():
    """There is no host-side nudge/echo heuristic anymore; every turn is exactly
    one advisor call and the model decides how to respond."""
    calls = []

    class _LLM:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return '{"schema_version": 1, "assistant_message": "Bien sûr. Continuez quand vous êtes prêt.", "field_updates": [], "assumption_updates": [], "deferred_updates": [], "contradictions": [], "suggested_readiness": "collecting"}'

    from site_agent.brain.design_intake import LLMDesignIntakeAdvisor

    result = LLMDesignIntakeAdvisor(_LLM(), {}).advise(
        DesignIntakeDraft.empty(),
        [],
        "continuez, donnez-moi la suite ?",
    )

    assert len(calls) == 1
    assert result.assistant_message.startswith("Bien sûr.")


def test_force_new_build_creates_a_fresh_candidate_from_a_reviewable_prior(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def __init__(self):
            self.submissions = []

        def submit(self, prompt, raw_intake, **kwargs):
            run_id = f"intake-lab-{len(self.submissions):032x}"
            self.submissions.append((prompt, run_id))
            return {"run_id": run_id, "status": "building", "publishable": False}

        def get_run(self, run_id):
            return {"run_id": run_id, "status": "ready_for_review", "publishable": False}

    lab = _Lab()
    service = DesignIntakeService(memory, default_intake=_intake(), lab_service=lab)
    session = service.create_session()
    confirmed = service.confirm(
        session["session_id"],
        revision=session["revision"],
        draft_hash=session["draft_hash"],
        idempotency_key="confirm-force",
    )
    assert confirmed["confirmed"] is True
    final_revision = confirmed["session"]["confirmed_revision_id"]

    first = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-force",
    )
    reuse = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-force",
    )
    assert reuse["idempotent"] is True
    assert reuse["run"]["run_id"] == first["run"]["run_id"]
    assert len(lab.submissions) == 1

    fresh = service.build(
        session["session_id"],
        confirmed_revision=final_revision,
        idempotency_key="build-force-fresh",
        force_new=True,
    )
    assert fresh["run"]["run_id"] != first["run"]["run_id"]
    assert len(lab.submissions) == 2
    memory.close()


def test_resolve_ui_action_only_opens_lineage_runs(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def get_run(self, run_id):
            return {
                "run_id": run_id,
                "status": "ready_for_review",
                "preferred_run_id": run_id,
                "revisions": [
                    {"run_id": "rev-a", "number": 1, "reviewable": False},
                    {"run_id": "rev-b", "number": 2, "reviewable": True},
                ],
            }

    service = DesignIntakeService(memory, lab_service=_Lab())
    confirmed = {"design_run_id": "rev-root", "status": "confirmed"}
    collecting = {"design_run_id": "rev-root", "status": "collecting"}

    resolved = service._resolve_ui_action({"action": "open_preview", "run_id": "rev-b"}, confirmed)
    assert resolved == {"action": "open_preview", "run_id": "rev-b"}
    assert service._resolve_ui_action({"action": "open_preview", "run_id": "rev-root"}, confirmed) == {
        "action": "open_preview", "run_id": "rev-root"
    }
    assert service._resolve_ui_action({"action": "open_preview", "run_id": "not-in-lineage"}, confirmed) is None
    assert service._resolve_ui_action({"action": "nonsense"}, confirmed) is None

    assert service._resolve_ui_action({"action": "start_build"}, confirmed) == {"action": "start_build", "fresh": True}
    assert service._resolve_ui_action({"action": "start_build"}, collecting) is None
    memory.close()


def test_customer_view_json_is_compact_and_omits_run_detail(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _Lab:
        def get_run(self, run_id):
            return {
                "run_id": "rev-root",
                "status": "validating",
                "preferred_run_id": "rev-b",
                "revisions": [
                    {"run_id": "rev-a", "number": 1, "operation_kind": "initial_build", "status": "validating", "reviewable": False},
                    {"run_id": "rev-b", "number": 2, "operation_kind": "visual_refinement", "status": "ready_for_review", "reviewable": True},
                ],
            }

    service = DesignIntakeService(memory, lab_service=_Lab())
    view = service._customer_view_json({"design_run_id": "rev-root"})
    assert "rev-root" in view
    assert "ready_for_review" in view
    assert "rev-b" in view
    assert "quality_report" not in view
    assert service._customer_view_json({}) == ""
    memory.close()


def test_existing_site_customer_view_carries_the_owner_visible_page(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(
        memory,
        config={
            "site": {
                "payload": {"enabled": True, "url": "https://atelier.example.test"},
            },
            "customer_profile": {
                "business": {"observed_site_settings": {"website_url": "https://atelier-harmonie.com"}},
            },
            "atelier_intake": {"database_only": True},
        },
    )
    view = json.loads(service._customer_view_json({}, owner_context={
        "phase": "incubation",
        "route": "/",
        "scope": "selected_page_reference",
        "target": {
            "mode": "incubation",
            "route": {"path": "/", "kind": "page", "sourceId": "home-source"},
            "site": {
                "name": "atelier-harmonie",
                "routes": [{"path": "/", "kind": "home", "collection": "pages", "sourceId": "home-source"}],
            },
        },
    }))
    prompt = _advisor_prompt(
        DesignIntakeDraft.empty(),
        (),
        "",
        customer_view=json.dumps(view),
        database_only=True,
    )

    assert view["existing_site"]["status"] == "existing_live_website"
    assert view["owner_visible_surface"]["target"]["route"]["path"] == "/"
    assert view["owner_visible_surface"]["target"]["site"]["routes"][0]["path"] == "/"
    assert "existing live website" in prompt
    assert "selected_page_reference" in prompt
    assert "The first build is the MAIN PAGE only." not in prompt
    memory.close()


def test_intake_advice_job_persists_owner_surface_context(tmp_path):
    memory = Memory(tmp_path / "intake.db")
    service = DesignIntakeService(memory, default_intake=_intake(), advisor=_Advisor())
    session = service.create_session()
    queued = service.send_message(
        session["session_id"],
        "Continue with the current page.",
        owner_context={"phase": "incubation", "route": "/", "scope": "selected_page_reference"},
    )
    job = memory.get_chat_job(queued["job_id"])

    assert job["payload"]["owner_context"] == {
        "phase": "incubation",
        "route": "/",
        "scope": "selected_page_reference",
    }
    memory.close()


def test_synthesized_brand_name_does_not_unlock_readiness():
    def set_name(basis):
        return merge_intake_turn(
            DesignIntakeDraft.empty(),
            IntakeTurnResult(
                schema_version=1,
                assistant_message="name note",
                field_updates=(IntakeFieldUpdate(
                    path="business.name",
                    value="Mel - Cave Diving Retreats",
                    basis=basis,
                    note="working name",
                ),),
            ),
            source_message_id=1,
        )

    recommended = set_name("recommendation")
    assert "business.name" in recommended.unresolved_core_paths

    stated = set_name("owner_statement")
    assert "business.name" not in stated.unresolved_core_paths

    accepted = set_name("owner_acceptance")
    assert "business.name" not in accepted.unresolved_core_paths


def test_location_context_requires_owner_location_or_explicit_non_applicable_choice():
    def set_field(path, value, basis="owner_statement"):
        return merge_intake_turn(
            DesignIntakeDraft.empty(),
            IntakeTurnResult(
                schema_version=1,
                assistant_message="location note",
                field_updates=(IntakeFieldUpdate(path=path, value=value, basis=basis),),
            ),
            source_message_id=1,
        )

    assert "business.location" in DesignIntakeDraft.empty().unresolved_core_paths
    assert "business.location" in set_field("business.location", "Lyon", "recommendation").unresolved_core_paths
    assert "business.location" not in set_field("business.location", "Lyon").unresolved_core_paths
    assert "business.location" not in set_field("business.service_area", "Worldwide").unresolved_core_paths
    assert "business.location" in set_field("business.location_not_applicable", True, "recommendation").unresolved_core_paths
    assert "business.location" not in set_field("business.location_not_applicable", True).unresolved_core_paths


def test_advisor_prompt_enforces_brand_name_integrity_and_honest_readiness():
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(DesignIntakeDraft.empty(), [], "applied guidance", "applied guidance")
    assert "business.name is the name the OWNER wants displayed" in prompt
    assert "Never derive a brand" in prompt
    assert "synthesize a compound name" in prompt
    assert "The prose and the readiness must always agree" in prompt
    assert "business.location_not_applicable" in prompt
    assert "Location context is required" in prompt


def test_advisor_prompt_embeds_logo_ocr_as_context_but_not_as_a_name():
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(
        DesignIntakeDraft.empty(),
        [{"tags": ["logo", "branding"], "ocr_text": "CENOTE RETREATS", "description": "Block letters on black", "usage": "website"}],
        "applied guidance",
        "applied guidance",
    )
    assert "CENOTE RETREATS" in prompt
    assert '"is_logo":true' in prompt
    assert "that is not the" in prompt and "owner stating the name" in prompt
    # No scripted conversational examples, no hardcoded languages, no injected
    # host language detection: the model answers from context.
    assert "Worked example:" not in prompt
    assert "Merci" not in prompt
    assert "OWNER LANGUAGE:" not in prompt


def test_background_notes_compose_from_this_turns_evidence_only():
    service = DesignIntakeService(Memory("/tmp/bn-notes.db"))

    notes = service._background_notes(
        [
            {"name": "logo.webp", "tags": ["logo"], "ocr_text": "CLAR OSCURO", "description": "Block letters on black",
             "usage": "website", "width": 375, "height": 285},
            {"name": "cenote.webp", "tags": ["cave"], "description": "Diver in a light shaft", "usage": "website"},
        ],
        ["Cenote diving attracts experienced tech divers."],
        IntakeTurnResult(schema_version=1, assistant_message="x", creative_insights=(
            type("CI", (), {"summary": "Dark logotype implies a serious tone."})(),
        )),
    )
    assert "BACKGROUND ANALYSIS" in notes
    assert 'logo reads "CLAR OSCURO"' in notes
    assert "Diver in a light shaft" in notes
    assert "Cenote diving attracts" in notes
    assert "Dark logotype implies" in notes

    assert service._background_notes([], [], IntakeTurnResult(schema_version=1, assistant_message="x")) == ""


def test_background_analysis_is_persisted_into_the_conversation(tmp_path):
    memory = Memory(tmp_path / "intake.db")

    class _AnalysisAdvisor:
        def advise(self, draft, history, owner_message, *, assets=(), knowledge_briefing=(), **kwargs):
            return IntakeTurnResult(
                schema_version=1,
                assistant_message="I noted the dark logotype.",
                creative_insights=(type("CI", (), {"summary": "Dark logotype implies a serious tone."})(),),
            )

    service = DesignIntakeService(memory, advisor=_AnalysisAdvisor(), lab_service=_FakeLab())
    session = service.create_session()
    service.send_message(session["session_id"], "Here is my logo.")
    job = memory.claim_chat_job("analysis-worker")
    from site_agent.core.chat_jobs import run_job

    run_job({"memory": memory, "design_intake_service": service, "config": {}, "llm": object()}, job, "analysis-worker")
    messages = service.get_session(session["session_id"])["messages"]
    system = [m for m in messages if m.get("role") == "system"]
    assert any("BACKGROUND ANALYSIS" in str(m.get("text") or "") for m in system)
    memory.close()


def test_advisor_prompt_contains_no_owner_message_kind_block():
    """The question/critique distinction is handled by the model from the
    conversation; the host no longer classifies messages or injects a block."""
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(DesignIntakeDraft.empty(), [], "guidance", "guidance")
    assert "LATEST OWNER MESSAGE TYPE" not in prompt
    assert "owner_message_kind" not in prompt
    assert "OWNER LANGUAGE" not in prompt


def test_advisor_prompt_keeps_reply_language_grounded_in_conversation_context():
    from site_agent.brain import design_intake as intake_brain

    prompt = intake_brain._advisor_prompt(
        DesignIntakeDraft.empty(),
        [],
        "guidance",
        ["Background evidence may be written in another language."],
    )
    assert "Keep the visible reply in the language of the owner's latest message" in prompt
    assert "Proper names are not language signals" in prompt
    assert "Do not infer reply language from research, source text, OCR, or field values" in prompt
    assert "Only change languages when the owner clearly changes languages or asks for translation" in prompt
    assert "When the current owner turn is language-neutral, inherit the established language from recent owner turns" in prompt
    assert "FINAL RESPONSE CONTRACT" in prompt
    assert "A standalone proper name or other language-neutral fragment does not reset that language" in prompt


class _FakeLab:
    def get_run(self, run_id):
        return {"run_id": run_id, "status": "building", "revisions": []}

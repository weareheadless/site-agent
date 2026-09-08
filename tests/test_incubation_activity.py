import pytest

from site_agent.application.incubation_activity import IncubationActivityService
from site_agent.application.incubation_research import IncubationResearchService
from site_agent.core.contracts import ContractError
from site_agent.core.incubation_contracts import (
    IncubationActivity,
    IncubationInsight,
    ResearchJob,
    ResearchRequest,
)
from site_agent.core.memory import Memory


def _activity(number: int) -> IncubationActivity:
    return IncubationActivity.from_dict({
        "activity_id": f"activity_{number:032x}",
        "occurred_at": "2026-09-03T12:00:00+00:00",
        "category": "research",
        "kind": "bounded_read",
        "state": "completed",
        "summary": f"Read public source {number}.",
        "provenance": "public_source",
        "confidence": 0.7,
        "detail": {"source_language": "fr", "item_count": number},
        "research_request_id": "research_" + "a" * 32,
        "source_id": "src_" + "b" * 32,
        "finding_ids": ["finding_" + "c" * 32],
    })


def _request() -> ResearchRequest:
    return ResearchRequest.from_dict({
        "request_id": "research_" + "d" * 32,
        "dedupe_key": "e" * 64,
        "created_at": "2026-09-03T12:00:00+00:00",
        "updated_at": "2026-09-03T12:00:00+00:00",
        "status": "needs_attention",
        "trigger": "owner_request",
        "intake_revision": 2,
        "owner_language": "fr",
        "subjects": ["plongee en grotte"],
        "markets": ["France"],
        "candidate_communities": [{"name": "r/cave_diving", "status": "candidate"}],
        "query_terms_by_language": {"fr": ["plongee", "grotte"], "en": ["cave diving"]},
        "source_ids": [],
        "finding_ids": [],
        "error": "",
    })


def test_activity_contract_rejects_unredacted_detail():
    payload = _activity(1).to_dict()
    payload["detail"] = {"source_title": "https://example.com/private"}

    with pytest.raises(ContractError, match="prohibited"):
        IncubationActivity.from_dict(payload)


def test_activity_is_append_only_and_cursor_paginated(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    try:
        for number in range(1, 4):
            memory.append_incubation_activity(_activity(number))

        first = memory.list_incubation_activity(after_id=0, limit=2)
        assert [item["summary"] for item in first["activities"]] == [
            "Read public source 1.",
            "Read public source 2.",
        ]
        assert first["has_more"] is True
        assert first["next_cursor"] == "2"

        second = memory.list_incubation_activity(after_id=first["next_cursor"], limit=2)
        assert [item["summary"] for item in second["activities"]] == ["Read public source 3."]
        assert second["has_more"] is False
        assert memory.get_incubation_activity(second["activities"][0]["activity_id"])["id"] == 3
    finally:
        memory.close()


def test_research_request_job_and_insight_round_trip(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    request = _request()
    job = ResearchJob.from_dict({
        "job_id": "research_job_" + "f" * 32,
        "request_id": request.request_id,
        "status": "queued",
        "attempt": 0,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
        "started_at": None,
        "completed_at": None,
        "error": "",
    })
    insight = IncubationInsight.from_dict({
        "insight_id": "insight_" + "1" * 32,
        "kind": "audience_language",
        "summary": "The audience uses precise technical vocabulary.",
        "owner_language": "fr",
        "source_languages": ["en"],
        "finding_ids": ["finding_" + "c" * 32],
        "supports_paths": ["research_identity.subjects"],
        "contradicts_paths": [],
        "confidence": 0.45,
        "status": "inferred",
        "created_at": request.created_at,
    })
    try:
        assert memory.save_research_request(request)["request_id"] == request.request_id
        assert memory.save_research_job(job)["job_id"] == job.job_id
        assert memory.save_incubation_insight(insight)["insight_id"] == insight.insight_id
        assert memory.get_research_request(request.request_id)["dedupe_key"] == "e" * 64
        assert memory.get_research_job(job.job_id)["request_id"] == request.request_id
        assert memory.list_incubation_insights()[0]["status"] == "inferred"
    finally:
        memory.close()


def test_research_intent_is_durable_without_a_source_url(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    service = IncubationResearchService(memory)
    try:
        result = service.request({
            "query": "What language do French cave divers use?",
            "owner_language": "fr",
            "subjects": ["cave diving"],
            "markets": ["France"],
            "trigger": "owner_request",
            "intake_revision": 2,
        })

        assert result["status"] == "awaiting_source_approval"
        assert result["request"]["status"] == "needs_attention"
        assert result["request"]["subjects"] == ["cave diving"]
        assert len(memory.list_research_requests()) == 1

        repeated = service.request({
            "query": "What language do French cave divers use?",
            "owner_language": "fr",
            "subjects": ["cave diving"],
            "markets": ["France"],
            "trigger": "owner_request",
            "intake_revision": 2,
        })
        assert repeated["request"]["request_id"] == result["request"]["request_id"]
        assert len(memory.list_research_requests()) == 1
    finally:
        memory.close()


def test_activity_service_redacts_owner_facing_summary(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    service = IncubationActivityService(memory)
    try:
        item = service.record(
            category="system",
            kind="diagnostic",
            state="completed",
            summary="Checked https://example.com and secret=abc123.",
            provenance="system",
        )
        assert "https://" not in item["summary"]
        assert "example.com" not in item["summary"]
    finally:
        memory.close()

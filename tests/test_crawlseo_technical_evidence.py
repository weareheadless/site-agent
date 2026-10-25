import datetime
import hashlib
import json

import pytest

from site_agent.application.growth_workflow import _technical_crawl_evidence_sources


def _contract(*, now: datetime.datetime, site_id: str = "site-1") -> dict:
    crawl_id = "crawl-1"
    issue_ids = ["issue-1"]
    fingerprint = hashlib.sha256(json.dumps({"siteId": site_id, "crawlId": crawl_id,
        "issueIds": issue_ids}, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {
        "technicalEvidenceComplete": True,
        "technicalEvidenceStale": False,
        "invalidTechnicalEvidenceReferences": False,
        "unavailableTechnicalEvidenceIds": [],
        "technicalEvidence": {
            "schemaVersion": "1.0", "sourceKind": "crawl", "siteId": site_id,
            "canonicalContextRevision": "ctx-4", "canonicalOrigin": "https://example.com/",
            "crawlId": crawl_id, "completedAt": (now - datetime.timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "recencyLimitDays": 7, "sourceFingerprint": fingerprint,
            "issueRefs": [{"id": "issue-1", "url": "https://example.com/", "type": "MISSING_TITLE",
                "severity": "WARNING", "message": "Missing title"}],
            "pageRefs": [{"id": "page-1", "url": "https://example.com/", "statusCode": 200,
                "title": None, "description": "Description", "canonical": None, "h1Count": 1,
                "wordCount": 20, "contentScore": 60, "hasSchema": False, "indexable": True}],
        },
    }


def test_technical_crawl_evidence_stays_typed_and_distinct_from_research_sources():
    now = datetime.datetime(2026, 10, 25, 12, tzinfo=datetime.timezone.utc)
    sources = _technical_crawl_evidence_sources(_contract(now=now), site_id="site-1",
        context_snapshot={"revision": "ctx-4", "canonicalOrigin": "https://example.com/"},
        target_url="https://example.com/", source_path="", required_capabilities=["content.prepare"], now=now)

    assert [source["id"] for source in sources] == ["crawl_issue:crawl-1:issue-1", "crawl_page:crawl-1:page-1"]
    assert [source["sourceKind"] for source in sources] == ["crawl_issue", "crawl_page"]
    assert all(source["observedAt"].endswith("Z") for source in sources)
    assert all("freshnessDays" not in source and "recencyLimitDays" not in source for source in sources)


@pytest.mark.parametrize("mutation,match", [
    (lambda body: body.update(technicalEvidenceComplete=False), "incomplete or invalid"),
    (lambda body: body["technicalEvidence"].update(canonicalContextRevision="ctx-old"), "context changed"),
    (lambda body: body["technicalEvidence"].update(canonicalOrigin="https://other.example/"), "canonical site origin"),
    (lambda body: body["technicalEvidence"].update(canonicalOrigin="https://example.com/private"), "canonical site origin"),
    (lambda body: body["technicalEvidence"].update(canonicalOrigin="https://example.com/?q=x"), "canonical site origin"),
    (lambda body: body["technicalEvidence"].update(schemaVersion="2.0"), "version or identity"),
    (lambda body: body["technicalEvidence"]["issueRefs"][0].update(type="MADE_UP"), "issue reference is malformed"),
    (lambda body: body["technicalEvidence"]["pageRefs"][0].update(statusCode=True), "page reference is malformed"),
    (lambda body: body["technicalEvidence"].update(sourceFingerprint="0" * 64), "fingerprint does not match"),
])
def test_technical_crawl_evidence_rejects_unverified_contract(mutation, match):
    now = datetime.datetime(2026, 10, 25, 12, tzinfo=datetime.timezone.utc)
    body = _contract(now=now)
    mutation(body)

    with pytest.raises(ValueError, match=match):
        _technical_crawl_evidence_sources(body, site_id="site-1",
            context_snapshot={"revision": "ctx-4", "canonicalOrigin": "https://example.com/"},
            target_url="https://example.com/", source_path="", required_capabilities=["content.prepare"], now=now)


def test_technical_crawl_evidence_requires_recent_completed_crawl():
    now = datetime.datetime(2026, 10, 25, 12, tzinfo=datetime.timezone.utc)
    body = _contract(now=now)
    body["technicalEvidence"]["completedAt"] = "2026-10-01T12:00:00Z"

    with pytest.raises(ValueError, match="outside its explicit 7-day recency limit"):
        _technical_crawl_evidence_sources(body, site_id="site-1",
            context_snapshot={"revision": "ctx-4", "canonicalOrigin": "https://example.com/"},
            target_url="https://example.com/", source_path="", required_capabilities=["content.prepare"], now=now)

    body = _contract(now=now)
    body["technicalEvidence"]["completedAt"] = "2026-10-25T11:00:00"
    with pytest.raises(ValueError, match="invalid crawl completion time"):
        _technical_crawl_evidence_sources(body, site_id="site-1",
            context_snapshot={"revision": "ctx-4", "canonicalOrigin": "https://example.com/"},
            target_url="https://example.com/", source_path="", required_capabilities=["content.prepare"], now=now)

    body = _contract(now=now)
    body["technicalEvidence"]["completedAt"] = "2026-10-25T12:00:01Z"
    with pytest.raises(ValueError, match="outside its explicit 7-day recency limit"):
        _technical_crawl_evidence_sources(body, site_id="site-1",
            context_snapshot={"revision": "ctx-4", "canonicalOrigin": "https://example.com/"},
            target_url="https://example.com/", source_path="", required_capabilities=["content.prepare"], now=now)


def test_technical_crawl_evidence_must_authorize_exact_target():
    now = datetime.datetime(2026, 10, 25, 12, tzinfo=datetime.timezone.utc)
    with pytest.raises(ValueError, match="does not cite an exact supported Payload metadata target"):
        _technical_crawl_evidence_sources(_contract(now=now), site_id="site-1",
            context_snapshot={"revision": "ctx-4", "canonicalOrigin": "https://example.com/"},
            target_url="https://example.com/unrelated", source_path="", required_capabilities=["content.prepare"], now=now)

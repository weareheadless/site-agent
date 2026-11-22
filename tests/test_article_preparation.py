"""A targetless article opportunity becomes one owner-reviewable draft.

CrawlSEO says why the piece should exist. The writing service researches the
subject and writes it. Site-agent lands the result as a pending Payload draft
with the existing approval, and never publishes.

These tests use the real preparation path with a stub writing service, so they
prove the wiring — run, initiative, draft, review report — rather than a mock of
it.
"""

from __future__ import annotations

import json

import pytest

from site_agent.application import growth_workflow
from site_agent.core.memory import Memory
from site_agent.hands.editorial import EditorialPost

ARTICLE = {
    "text": (
        "## El look\n\nEl maquillaje se jugó en dos zonas: los labios y la cuenca del ojo. "
        "Las fuentes coinciden en el brillo controlado y el labio marcado. El peinado fue "
        "un recogido tirante con mechones sueltos enmarcando el rostro, y el gesto clave es "
        "fijar sin apelmazar el cabello."
    ),
    "title": "Los looks de la alfombra roja",
    "slug": "los-looks-de-la-alfombra-roja",
    "body_markdown": "",
    "excerpt": "Los looks y los productos exactos.",
    "meta_title": "Los looks de la alfombra roja",
    "meta_description": "Los looks y los productos exactos de la noche.",
    "primary_keyword": "maquillaje alfombra roja",
    "content_hash": "sha256:" + "a" * 64,
    "revision": 1,
    "sources": [
        {"url": "https://news.example/looks", "title": "Looks", "sha256": "sha256:" + "b" * 64}
    ],
    "claims": [{"text": "Los labios y la cuenca", "verdict": "supported"}],
    "assets": [
        {
            "id": "img_1",
            "role": "cover",
            "source": "unsplash",
            "photo_id": "photo-1",
            "url": "https://images.example/photo-1.jpg",
            "alt": "Red carpet staircase",
            "credit": "Photo by Someone on Unsplash",
        }
    ],
    "editorial": {"model": "test-model"},
}
ARTICLE["body_markdown"] = ARTICLE.pop("text")


ENGLISH = {
    "title": "The red carpet looks",
    "slug": "the-red-carpet-looks",
    "body_markdown": (
        "## The look\n\nThe makeup was decided in two places: the lips and the eye socket. "
        "The sources agree on controlled shine and a marked lip."
    ),
    "excerpt": "The looks and the exact products.",
    "meta_description": "The looks and the exact products of the night.",
    "primary_keyword": "red carpet makeup",
}


class StubEditorial:
    def __init__(self, *, state="ready", error="", refusal=None):
        self.state = state
        self.error = error
        self.refusal = refusal or {}
        self.written = []

    def configured(self):
        return True

    def write(self, brief, *, deadline_seconds):
        self.written.append((brief, deadline_seconds))
        if self.state == "held":
            return EditorialPost(
                post_id="post_1",
                state=self.state,
                artifacts={},
                error=self.error,
                refusal=self.refusal,
            )
        # One editorial act, one evidence set, an edition per locale.
        artifacts = {}
        for locale in brief["locales"]:
            artifacts[locale] = {**ARTICLE, **ENGLISH} if locale == "en" else ARTICLE
        return EditorialPost(
            post_id="post_1", state=self.state, artifacts=artifacts, error=self.error,
        )


class Payload:
    base_url = "https://payload.example"

    def require_authoring_contract(self):
        return {
            "locales": ["en", "es"],
            "defaultLocale": "es",
            "enabled": {"collections": ["pages", "posts"], "globals": []},
            "authoring": {"collections": {"posts": [{"name": f} for f in
                          ("title", "slug", "summary", "body", "featuredImage", "seo", "published", "canonicalUrl")]}},
        }

    def authoring_fields(self, kind, slug, *, authoring_contract=None):
        return tuple(
            row["name"] for row in authoring_contract["authoring"]["collections"]["posts"]
        )

    def list(self, collection, *, draft=True, limit=100, locale=None):
        return []

    def create(self, collection, data, *, locale=None):
        return {**data, "id": "doc_1", "sourceId": f"posts:{data['slug']}", "published": False}

    def read(self, collection, *, identifier, identifier_kind, draft, locale=None):
        return {"id": "doc_1", "slug": ARTICLE["slug"], "title": ARTICLE["title"],
                "sourceId": f"posts:{ARTICLE['slug']}", "published": False}

    def list_media(self, *, draft=True, limit=100):
        return []

    def read_media(self, identifier, *, identifier_kind="id", draft=True):
        return {"id": "media-1", "sourceId": "article-cover:photo-1", "alt": "Red carpet staircase",
                "url": "/api/media/file/red.jpg", "analysisStatus": "pending",
                "_helloadaRevision": "sha256:" + "c" * 64}

    def upload_media(self, **kwargs):
        return {"id": "media-1", "asset_id": "media-1"}


class Connector:
    def __init__(self):
        self.reports = []

    def connector_context(self, site_id=None):
        return {"snapshot": {"canonicalOrigin": "https://business.example", "websiteInventory": []}}

    def connector_action(self, action_id, site_id=None):
        return {"id": action_id, "revision": 7, "preparationStatus": "queued",
                "preparationRequestId": "prep-1"}

    def connector_record_execution(self, action_id, report):
        self.reports.append((action_id, dict(report)))
        return {"recorded": True}


def _context(tmp_path, monkeypatch, editorial, *, landed=True):
    memory = Memory(tmp_path / "growth.db")
    monkeypatch.setattr(growth_workflow, "_inventory", lambda _context: [])
    monkeypatch.setattr(
        "site_agent.hands.editorial.build_editorial_client", lambda config: editorial
    )
    # The GitHub engineering journal is a side effect of preparing a candidate,
    # not part of what these tests prove. No network and no credential here.
    class RecordingJournal:
        def issue(self, initiative):
            memory.update_strategy_initiative(
                int(initiative["id"]),
                validation={**(initiative.get("validation") or {}), "journal": {"status": "recorded"}},
            )
            return {"recorded": True}

        def checkpoint(self, initiative, state, refs=None):
            return {"state": state}

    monkeypatch.setattr(
        "site_agent.application.growth_delivery.journal",
        lambda context: RecordingJournal(),
    )
    monkeypatch.setattr(
        "site_agent.core.jobs._article_cover_image",
        lambda context, payload, draft, meta: (
            "media-1",
            {"id": "media-1", "alt": "Red carpet staircase", "analysisStatus": "pending",
             "sourceId": "article-cover:photo-1", "url": "/api/media/file/red.jpg",
             "_helloadaRevision": "sha256:" + "c" * 64},
            {"media_id": "media-1", "media_revision": "sha256:" + "c" * 64,
             "reason": "Article cover", "source_id": "article-cover:photo-1",
             "alt": "Red carpet staircase"},
        ),
    )

    def fake_mirror(context, draft_id):
        draft = memory.get_draft(int(draft_id))
        meta = dict(draft["meta"])
        meta["payload_sync"] = {
            "state": "ready_for_review",
            "collection": "posts",
            "document_id": "doc_1",
            "draft_hash": "sha256:" + "d" * 64,
            "source_hash": "sha256:" + "e" * 64,
            "slug": ARTICLE["slug"],
            "locale": "es",
            "editions": [
                {"locale": "es", "slug": ARTICLE["slug"], "document_id": "doc_1",
                 "draft_hash": "sha256:" + "d" * 64},
                {"locale": "en", "slug": ENGLISH["slug"], "document_id": "doc_2",
                 "draft_hash": "sha256:" + "a" * 64},
            ],
            "validation": {"status": "passed", "checks": {"title": True}},
        }
        meta["review_package_hash"] = "sha256:" + "f" * 64
        memory.update_draft_meta(int(draft_id), meta)
        return True

    if landed:
        monkeypatch.setattr("site_agent.core.jobs._mirror_article_draft_to_workspace", fake_mirror)

    return {
        "memory": memory,
        "config": {
            "instance_name": "site-ff8e9af06f56201f",
            "editorial": {"enabled": True},
            "site": {
                "payload": {"url": "https://payload.example"},
                "repository": "weareheadless/astrid-rincon-website",
            },
        },
        "payload_gateway": Payload(),
        "crawlseo_service": Connector(),
        "tenant_id": "site-ff8e9af06f56201f",
    }


def _action(**overrides):
    action = {
        "id": "action_1",
        "revision": 7,
        "preparationRequestId": "prep-1",
        "problem": "No coverage of red carpet beauty",
        "recommendation": "Write about the awards looks and the products used",
        "expectedOutcome": "Readers find the site for the trend",
        "primaryQuery": "maquillaje alfombra roja",
        "target": {},
        "requiredCapabilities": ["article.create"],
        "evidence": [{"id": "s1", "url": "https://news.example/looks",
                      "freshnessDays": 2, "recencyLimitDays": 30}],
    }
    action.update(overrides)
    return action


def _run(context, action=None, request_id="prep-1"):
    memory = context["memory"]
    continuation, _ = memory.claim_crawlseo_execution_binding(
        "site-ff8e9af06f56201f", "action_1", 7, 9, state="preparing",
        detail={"ownerActionId": 1, "preparationRequestId": request_id},
    )
    binding = continuation or memory.get_crawlseo_execution_binding(
        "site-ff8e9af06f56201f", "action_1", 7
    )
    return growth_workflow._execute_crawlseo_preparation(
        context, action or _action(), binding,
        site_id="site-ff8e9af06f56201f", generation=9,
    )


def test_an_article_opportunity_produces_one_pending_draft(tmp_path, monkeypatch):
    editorial = StubEditorial()
    context = _context(tmp_path, monkeypatch, editorial)

    result = _run(context)

    assert result["status"] == "ready", result
    drafts = context["memory"].list_drafts()
    assert len(drafts) == 1
    assert drafts[0]["kind"] == "article"
    assert drafts[0]["title"] == ARTICLE["title"]
    assert drafts[0]["status"] == "pending"
    # The cover the article brought is recorded with the draft, not discarded.
    assert drafts[0]["meta"]["article_assets"][0]["role"] == "cover"


def test_every_language_the_brief_asked_for_is_carried_to_the_landing(tmp_path, monkeypatch):
    """One article, not one article per language and not just the first."""
    editorial = StubEditorial()
    context = _context(tmp_path, monkeypatch, editorial)

    _run(context)

    editions = context["memory"].list_drafts()[0]["meta"]["article_editions"]
    assert [row["locale"] for row in editions] == ["es", "en"]
    assert editions[0]["title"] == ARTICLE["title"]
    assert editions[1]["title"] == ENGLISH["title"]
    assert editions[1]["slug"] == ENGLISH["slug"]
    assert editions[1]["body"] == ENGLISH["body_markdown"]


def test_a_missing_edition_blocks_rather_than_publishing_one_language(tmp_path, monkeypatch):
    """A bilingual request that comes back monolingual is not a bilingual article."""
    class HalfWritten(StubEditorial):
        def write(self, brief, *, deadline_seconds):
            self.written.append((brief, deadline_seconds))
            return EditorialPost(post_id="post_1", state="ready", artifacts={"es": ARTICLE}, error="")

    context = _context(tmp_path, monkeypatch, HalfWritten())

    result = _run(context)

    assert result["status"] == "blocked"
    assert "no edition for: en" in result["error"]
    assert context["memory"].list_drafts() == []


def test_the_brief_names_why_and_leaves_the_subject_to_be_researched(tmp_path, monkeypatch):
    editorial = StubEditorial()
    context = _context(tmp_path, monkeypatch, editorial)

    _run(context)

    brief, deadline = editorial.written[0]
    assert brief["topic"]["question"] == "No coverage of red carpet beauty"
    assert "source_urls" not in brief["evidence"]
    assert brief["metadata"]["research"] == "subject"
    assert brief["locales"][0] == "es"
    # The budget covers both editions, so the service is not cut off mid-second.
    assert deadline >= 1800


def test_the_owner_approval_exists_and_nothing_is_published(tmp_path, monkeypatch):
    editorial = StubEditorial()
    context = _context(tmp_path, monkeypatch, editorial)

    _run(context)

    initiatives = context["memory"].list_strategy_initiatives(limit=10)
    assert len(initiatives) == 1
    initiative = initiatives[0]
    assert initiative["kind"] == "article"
    assert initiative["draft_id"] == context["memory"].list_drafts()[0]["id"]
    assert initiative["state"] == "ready_for_review"
    assert initiative["approval_id"]


def test_the_connector_is_told_the_candidate_is_ready_with_its_review(tmp_path, monkeypatch):
    editorial = StubEditorial()
    context = _context(tmp_path, monkeypatch, editorial)

    result = _run(context)

    reports = context["crawlseo_service"].reports
    assert reports[0][1]["status"] == "preparation_ready"
    assert reports[0][1]["candidateRef"] == "article-growth:action_1:7:9"
    assert reports[0][1]["reviewUrl"] == "https://payload.example/admin"
    assert result["candidateRef"] == "article-growth:action_1:7:9"


def test_a_held_article_is_reported_and_never_retried_as_an_outage(tmp_path, monkeypatch):
    editorial = StubEditorial(state="held", error="only 1 readable source")
    context = _context(tmp_path, monkeypatch, editorial)

    result = _run(context)

    assert result["status"] == "held"
    assert "only 1 readable source" in result["error"]
    # No draft, no review, nothing for the owner to approve.
    assert context["memory"].list_drafts() == []


def test_a_refused_article_reports_why_and_is_not_retryable(tmp_path, monkeypatch):
    """A considered pass must be distinguishable from a broken job.

    The owner has to see that a person-shaped decision was made about this
    opportunity, and the caller has to know that repeating it unchanged would
    produce the same judgement for the same money.
    """
    editorial = StubEditorial(
        state="held",
        error="declined at commission/es (unsupported_by_business): this studio does not perform clinical treatments",
        refusal={
            "decision": "refuse",
            "reason": "unsupported_by_business",
            "rationale": "This studio does not perform clinical treatments.",
            "stage": "commission/es",
        },
    )
    context = _context(tmp_path, monkeypatch, editorial)

    result = _run(context)

    assert result["status"] == "held"
    assert result["refusalReason"] == "unsupported_by_business"
    assert result["refusalStage"] == "commission/es"
    assert result["retryable"] is False
    assert context["memory"].list_drafts() == []


def test_a_refused_article_closes_the_opportunity_instead_of_looking_stuck(
    tmp_path, monkeypatch
):
    editorial = StubEditorial(
        state="held",
        error="declined at verdict/es (no_distinct_value): competent and empty",
        refusal={
            "decision": "refuse",
            "reason": "no_distinct_value",
            "rationale": "Competent and empty: nothing here comes from this business.",
            "stage": "verdict/es",
        },
    )
    context = _context(tmp_path, monkeypatch, editorial)

    result = _run(context)

    assert result["status"] == "held"
    initiative = next(iter(context["memory"].list_strategy_initiatives(limit=50)))
    # Leave it in "preparing" and the owner is told to wait for work that will
    # never arrive, with no reason attached.
    assert initiative["state"] == "rejected"
    assert "Declined by editorial (no_distinct_value)" in initiative["last_error"]
    assert "Competent and empty" in initiative["last_error"]
    reports = context["crawlseo_service"].reports
    assert reports[-1][1]["status"] == "preparation_blocked"
    assert reports[-1][1]["detail"]["declined"] is True
    assert reports[-1][1]["detail"]["reason"] == "no_distinct_value"


def test_a_research_gap_is_reported_as_worth_another_pass(tmp_path, monkeypatch):
    editorial = StubEditorial(
        state="held",
        error="declined at verdict/es (evidence_insufficient): the sources cannot carry it",
        refusal={
            "decision": "refuse",
            "reason": "evidence_insufficient",
            "rationale": "The sources cannot carry it yet.",
            "stage": "verdict/es",
        },
    )
    context = _context(tmp_path, monkeypatch, editorial)

    result = _run(context)

    assert result["status"] == "held"
    # The only reason another research pass could change.
    assert result["retryable"] is True


def test_an_unconfigured_writing_service_blocks_with_a_named_setting(tmp_path, monkeypatch):
    class Unconfigured(StubEditorial):
        def configured(self):
            return False

    context = _context(tmp_path, monkeypatch, Unconfigured())

    result = _run(context)

    assert result["status"] == "blocked"
    assert "not configured" in result["error"]


def test_the_article_capability_is_declared_only_when_writing_is_enabled(tmp_path, monkeypatch):
    """CrawlSEO may only route article work the platform can actually perform."""
    captured = {}

    class Service:
        def connector_context(self, site_id=None):
            return {"snapshot": {"canonicalOrigin": "https://business.example", "websiteInventory": []}}

        def connector_sync(self, snapshot=None):
            captured["snapshot"] = snapshot
            return {"capabilities": {"binding": {"generation": 1}}, "actions": []}

    from site_agent.core.memory import Memory

    memory = Memory(tmp_path / "sync.db")
    base = {
        "memory": memory,
        "crawlseo_service": Service(),
        "payload_gateway": Payload(),
        "connector_site_id": "site-1",
        "config": {"instance_name": "site-1", "editorial": {"enabled": True},
                   "site": {"payload": {"url": "https://payload.example"},
                            "repository": "weareheadless/example"}},
    }
    monkeypatch.setattr(growth_workflow, "_inventory", lambda _c: [])
    monkeypatch.setattr(growth_workflow, "require_connector_dispatch_enabled", lambda _m: None)
    growth_workflow._sync_crawlseo_actions(base)
    assert "article.create" in captured["snapshot"]["capabilities"]["supported"]

    captured.clear()
    base["config"]["editorial"] = {"enabled": False}
    growth_workflow._sync_crawlseo_actions(base)
    assert "article.create" not in captured["snapshot"]["capabilities"]["supported"]

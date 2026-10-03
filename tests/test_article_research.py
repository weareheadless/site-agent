import pytest

from site_agent.brain import article_research
from site_agent.core.memory import Memory


DEFAULT_IDEA = {
    "working_title": "A useful guide",
    "audience_need": "Readers need clarity.",
    "reader_question": "How do I make the right choice?",
    "reader_situation": "A reader is comparing options and wants to avoid an expensive mistake.",
    "reader_intent": "Choose a suitable next step with confidence.",
    "business_relevance": "The business can clarify the decision before the reader asks for help.",
    "market_context": "Readers are comparing alternatives and cost before committing to a provider.",
    "expert_angle": "Explain the conditions that make each option appropriate.",
    "expertise_basis": ["Owner-confirmed practice and approved source material."],
    "technical_watchouts": ["Do not treat context-dependent options as a universal ranking."],
    "scope_boundaries": ["Do not diagnose a specific case without the required facts."],
    "thesis": "Explain the practical answer.",
    "why_now": "A recurring community question",
    "origin": "community_question",
    "source_urls": ["https://example.com/question"],
    "candidate_queries": [
        "reader question basics",
        "how to answer the reader question",
        "reader question for beginners",
        "why the reader question matters",
        "reader question local guide",
    ],
    "language": "en",
    "market": "US",
}

SERP_RESULT = {
    "query": "reader question basics",
    "checked_at": "2026-08-29 10:00:00 +00:00",
    "item_types": ["organic", "related_searches"],
    "organic": [
        {"rank": 1, "domain": "school.example", "title": "Reader question guide",
         "url": "https://school.example", "description": "A guide."},
    ],
    "peopleAlsoAsk": [],
    "relatedSearches": ["reader question near me"],
    "localPack": [],
}


class TwoStageService:
    """Overview completed, then a completed SERP once the note selects a query."""

    def __init__(self, result=None, serp_result=None, serp_request_failures=0):
        self.result = result or [{"keyword": "reader question basics", "search_volume": 20}]
        self.serp_result = serp_result or SERP_RESULT
        self.serp_request_failures = serp_request_failures
        self.requests = []

    def request_article_keyword_research(self, **kwargs):
        self.requests.append(("overview", kwargs))
        return {"run_id": "run-overview", "status": "requested"}

    def article_keyword_research_status(self, _run_id):
        return {"status": "completed", "provider_task_id": "task-overview", "cost_micros": 12000}

    def article_keyword_research(self, _run_id):
        return {"provider_task_id": "task-overview", "cost_micros": 12000, "result": self.result}

    def request_article_serp_research(self, **kwargs):
        self.requests.append(("serp", kwargs))
        if self.serp_request_failures > 0:
            self.serp_request_failures -= 1
            raise RuntimeError("CrawlSEO article SERP research request is unavailable")
        return {"run_id": "run-serp", "status": "requested"}

    def article_serp_research_status(self, _run_id):
        return {"status": "completed", "provider_task_id": "task-serp", "cost_micros": 2000}

    def article_serp_research(self, _run_id):
        return {"provider_task_id": "task-serp", "cost_micros": 2000, "result": self.serp_result}


class IdeaLLM:
    def __init__(self, idea=None):
        self.calls = 0
        self.idea = idea or DEFAULT_IDEA

    def chat(self, *_args, **_kwargs):
        self.calls += 1
        return __import__("json").dumps(self.idea)


class NoteLLM:
    def __init__(self, decision="keep", selected_query="reader question basics",
                 reasoning="The audience need is specific."):
        self.decision = decision
        self.selected_query = selected_query
        self.reasoning = reasoning

    def chat(self, *_args, **_kwargs):
        return __import__("json").dumps({
            "original_thesis": "Explain the practical answer.",
            "decision": self.decision,
            "selected_query": self.selected_query,
            "selected_from_query": self.selected_query,
            "reader_language": ["en"],
            "related_questions": ["Is this a beginner topic?"],
            "useful_terms": ["reader question"],
            "reframed_title": "A useful guide",
            "reframed_thesis": "Explain the practical answer.",
            "reasoning": self.reasoning,
        })


def _idea(memory, cycle="article:2026-W30", hash_value="idea-hash",
          status="research_requested", run_id="run-overview", **extra):
    idea = memory.create_article_idea(cycle, hash_value, dict(DEFAULT_IDEA))
    fields = {"status": status, "research_run_id": run_id, **extra}
    return memory.update_article_idea(idea["id"], **fields)


def test_article_research_follows_primary_research_locale():
    settings = article_research._settings({
        "seo": {
            "research": {"languages": [{"code": "fr", "markets": ["FR"], "primary": True}]},
            "article_research": {"enabled": True},
        }
    })
    assert settings["language"] == "fr"
    assert settings["market"] == "FR"


def test_article_research_explicit_locale_overrides_primary_research_locale():
    settings = article_research._settings({
        "seo": {
            "research": {"languages": [{"code": "fr", "markets": ["FR"], "primary": True}]},
            "article_research": {"enabled": True, "language": "en", "market": "US"},
        }
    })
    assert settings["language"] == "en"
    assert settings["market"] == "US"


def test_candidate_queries_are_reduced_and_duplicate_collisions_rejected():
    assert article_research._candidate_queries([
        "reader question basics",
        "how to answer the reader question",
        "reader question for beginners",
        "why the reader question matters",
        "reader question local guide",
    ]) == [
        "reader question basics",
        "how to answer the reader question",
        "reader question for beginners",
        "why the reader question matters",
        "reader question local guide",
    ]
    # A delimited value collapses to an existing candidate, so the set is rejected.
    with pytest.raises(ValueError, match="unique"):
        article_research._candidate_queries([
            "reader question basics; something else",
            "reader question basics",
            "how to answer the reader question",
            "reader question for beginners",
            "why the reader question matters",
            "reader question local guide",
        ])


def test_article_idea_must_keep_the_configured_research_market():
    config = {"seo": {"article_research": {"enabled": True, "language": "en", "market": "US"}}}
    idea = __import__("json").dumps({**DEFAULT_IDEA, "market": "MX"})
    with pytest.raises(ValueError, match="configured research locale"):
        article_research._validate_idea(idea, config)


def test_article_idea_needs_5_to_10_unique_candidate_queries():
    config = {"seo": {"article_research": {"enabled": True}}}
    too_few = __import__("json").dumps({**DEFAULT_IDEA, "candidate_queries": DEFAULT_IDEA["candidate_queries"][:4]})
    with pytest.raises(ValueError, match="5 to 10"):
        article_research._validate_idea(too_few, config)
    duplicate = __import__("json").dumps({**DEFAULT_IDEA, "candidate_queries": [
        "reader question basics", "Reader Question Basics",
        "how to answer the reader question", "why the reader question matters",
        "reader question local guide",
    ]})
    with pytest.raises(ValueError, match="unique"):
        article_research._validate_idea(duplicate, config)


def test_article_idea_requires_reader_question_and_expertise_boundary():
    config = {"seo": {"article_research": {"enabled": True}}}
    missing_question = dict(DEFAULT_IDEA)
    missing_question.pop("reader_question")
    with pytest.raises(ValueError, match="reader question"):
        article_research._validate_idea(__import__("json").dumps(missing_question), config)

    missing_basis = {**DEFAULT_IDEA, "expertise_basis": []}
    with pytest.raises(ValueError, match="expertise basis"):
        article_research._validate_idea(__import__("json").dumps(missing_basis), config)


def test_research_note_must_ground_an_editorial_alternative_in_a_candidate_query():
    alternative = {
        "decision": "reframe",
        "selected_query": "a better wording the provider did not measure",
        "selected_from_query": "",
        "reasoning": "",
    }
    with pytest.raises(ValueError, match="submitted query or justify"):
        article_research._note(__import__("json").dumps(alternative), DEFAULT_IDEA)

    justified = {
        **alternative,
        "selected_from_query": DEFAULT_IDEA["candidate_queries"][0],
        "reasoning": "The submitted wording misses the reader's actual decision.",
    }
    note = article_research._note(__import__("json").dumps(justified), DEFAULT_IDEA)
    assert note["selected_query"] == "a better wording the provider did not measure"
    assert note["selected_from_query"] == DEFAULT_IDEA["candidate_queries"][0]


def test_article_job_requests_research_when_provider_present(tmp_path, monkeypatch):
    from site_agent.core import jobs

    memory = Memory(tmp_path / "memory.db")
    memory.kv_set("journal_enabled", True)
    called = {"research": False, "draft": False}

    def fake_select(_context):
        called["research"] = True

    def fake_draft(_context, *_args, **_kwargs):
        called["draft"] = True
        return 7

    monkeypatch.setattr(jobs.brain_article_research, "select_and_request", fake_select)
    monkeypatch.setattr(jobs.brain_article, "draft_article", fake_draft)
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "llm": object(),
        "crawlseo_service": object(),
    }
    try:
        jobs._article(context)
        assert called["research"] is True
        assert called["draft"] is False
    finally:
        memory.close()


def test_article_job_blocks_research_dependent_draft_without_provider(tmp_path, monkeypatch):
    from site_agent.core import jobs

    memory = Memory(tmp_path / "memory.db")
    memory.kv_set("journal_enabled", True)
    drafted = {"called": False}

    def fake_draft(_context, *_args, **_kwargs):
        drafted["called"] = True
        return 7

    monkeypatch.setattr(jobs.brain_article, "draft_article", fake_draft)
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "llm": object(),
    }
    try:
        jobs._article(context)
        assert drafted["called"] is False
        details = [row["detail"] for row in memory.recent_actions(limit=5) if row["kind"] == "article_research"]
        assert any("no research-dependent article was drafted" in detail for detail in details)
    finally:
        memory.close()


def test_rejection_records_raw_candidate_and_reason(tmp_path):
    memory = Memory(tmp_path / "memory.db")

    class TimeSensitiveLLM:
        def chat(self, *_args, **_kwargs):
            return __import__("json").dumps({**DEFAULT_IDEA, "why_now": "Rules changed this week.", "source_urls": []})

    class Service:
        def request_article_keyword_research(self, **_kwargs):
            raise AssertionError("a rejected idea must never be requested")

    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": Service(),
        "llm": TimeSensitiveLLM(),
    }
    original_cycle_key = article_research._cycle_key
    try:
        article_research._cycle_key = lambda _config: "article:2026-W35"
        article_research.select_and_request(context)
        assert memory.get_article_idea_by_cycle("article:2026-W35") is None
        rejected = memory.list_rejected_article_ideas()
        assert len(rejected) == 1
        assert "time-sensitive" in rejected[0]["reason"]
        assert rejected[0]["parsed_json"]["working_title"] == "A useful guide"
        assert "why_now" in rejected[0]["parsed_json"]
    finally:
        article_research._cycle_key = original_cycle_key
        memory.close()


def test_pre_dispatch_request_failure_is_retried_without_reselecting_or_duplicating_idea(tmp_path):
    memory = Memory(tmp_path / "memory.db")

    class FlakyRequestService:
        def __init__(self):
            self.requests = 0

        def request_article_keyword_research(self, **kwargs):
            self.requests += 1
            if self.requests == 1:
                raise RuntimeError("CrawlSEO article keyword research request is unavailable")
            return {"run_id": "run-1", "status": "requested"}

    service = FlakyRequestService()
    llm = IdeaLLM()
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": service,
        "llm": llm,
    }
    try:
        article_research.select_and_request(context)
        first = memory.list_article_ideas(limit=1)[0]
        assert first["status"] == "selected"
        assert first["research_run_id"] is None

        article_research.select_and_request(context)
        second = memory.list_article_ideas(limit=1)[0]
        assert second["status"] == "research_requested"
        assert second["research_run_id"] == "run-1"
        assert service.requests == 2
        assert llm.calls == 1
    finally:
        memory.close()


def test_reconcile_requests_one_serp_after_metrics_then_drafts(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    idea = _idea(memory)
    service = TwoStageService()
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": service,
        "llm": NoteLLM(),
    }
    monkeypatch.setattr(article_research.brain_article, "draft_article_for_idea", lambda *_args, **_kwargs: 42)
    try:
        article_research.reconcile(context)
        after_metrics = memory.get_article_idea(idea["id"])
        assert after_metrics["status"] == "serp_requested"
        assert after_metrics["serp_run_id"] == "run-serp"
        assert after_metrics["research_result_json"] == [{"keyword": "reader question basics", "search_volume": 20}]
        assert after_metrics["draft_id"] is None
        assert ("serp", {"parent_run_id": "run-overview", "keyword": "reader question basics"}) in [
            (kind, {k: v for k, v in args.items() if k in {"parent_run_id", "keyword"}})
            for kind, args in service.requests
        ]

        article_research.reconcile(context)
        drafted = memory.get_article_idea(idea["id"])
        assert drafted["status"] == "drafted"
        assert drafted["draft_id"] == 42
        assert drafted["research_note_json"]["serp_evidence"]["query"] == "reader question basics"
        assert drafted["research_note_json"]["serp_receipt"]["run_id"] == "run-serp"
    finally:
        memory.close()


def test_reconcile_retries_serp_request_without_repeating_metrics(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    idea = _idea(memory)
    service = TwoStageService(serp_request_failures=1)
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": service,
        "llm": NoteLLM(),
    }
    monkeypatch.setattr(article_research.brain_article, "draft_article_for_idea", lambda *_args, **_kwargs: 42)
    try:
        article_research.reconcile(context)
        held = memory.get_article_idea(idea["id"])
        assert held["status"] == "research_requested"
        assert held["serp_run_id"] is None
        assert held["research_result_json"]

        article_research.reconcile(context)
        moved = memory.get_article_idea(idea["id"])
        assert moved["status"] == "serp_requested"
        assert moved["serp_run_id"] == "run-serp"

        article_research.reconcile(context)
        assert memory.get_article_idea(idea["id"])["status"] == "drafted"
        assert sum(1 for kind, _ in service.requests if kind == "serp") == 2
    finally:
        memory.close()


def test_reconcile_holds_zero_demand_without_explicit_editorial_reason(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    idea = _idea(memory, hash_value="empty-hold-hash")
    service = TwoStageService(result=[{"keyword": "reader question basics", "search_volume": 0}])
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": service,
        "llm": NoteLLM(decision="keep"),
    }
    monkeypatch.setattr(
        article_research.brain_article,
        "draft_article_for_idea",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("zero demand must not draft")),
    )
    try:
        article_research.reconcile(context)
        saved = memory.get_article_idea(idea["id"])
        assert saved["status"] == "held"
        assert saved["draft_id"] is None
        assert saved["serp_run_id"] is None
        assert "explicit editorial_despite_low_demand reason" in saved["error"]
    finally:
        memory.close()


def test_reconcile_allows_zero_demand_with_editorial_reason_then_drafts(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    idea = _idea(memory, hash_value="empty-allowed-hash")
    service = TwoStageService(result=[{"keyword": "reader question basics", "search_volume": 0}])
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": service,
        "llm": NoteLLM(
            decision="editorial_despite_low_demand",
            reasoning="Readers ask this safety question despite zero measured demand.",
        ),
    }
    monkeypatch.setattr(article_research.brain_article, "draft_article_for_idea", lambda *_args, **_kwargs: 43)
    try:
        article_research.reconcile(context)
        moved = memory.get_article_idea(idea["id"])
        assert moved["status"] == "serp_requested"
        assert moved["serp_run_id"] == "run-serp"
        article_research.reconcile(context)
        assert memory.get_article_idea(idea["id"])["status"] == "drafted"
        assert memory.get_article_idea(idea["id"])["draft_id"] == 43
    finally:
        memory.close()


def test_reconcile_retries_local_drafting_without_repeating_paid_research(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    idea = memory.create_article_idea("article:2026-W31", "draft-retry-hash", dict(DEFAULT_IDEA))
    memory.update_article_idea(
        idea["id"],
        status="researched",
        research_run_id="run-overview",
        serp_run_id="run-serp",
        research_note_json={
            "decision": "keep",
            "selected_query": "reader question basics",
            "serp_evidence": {"query": "reader question basics", "organic": []},
            "serp_receipt": {"run_id": "run-serp"},
        },
        research_result_json=[{"keyword": "reader question basics", "search_volume": 20}],
        research_cost_micros=14000,
    )
    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": TwoStageService(),
        "llm": object(),
    }
    attempts = {"count": 0}

    def draft(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("local draft interrupted")
        return 44

    monkeypatch.setattr(article_research.brain_article, "draft_article_for_idea", draft)
    try:
        article_research.reconcile(context)
        first = memory.get_article_idea(idea["id"])
        assert first["status"] == "researched"
        assert "interrupted" in first["error"]

        article_research.reconcile(context)
        second = memory.get_article_idea(idea["id"])
        assert second["status"] == "drafted"
        assert second["draft_id"] == 44
        assert attempts["count"] == 2
    finally:
        memory.close()


def test_reconcile_serp_failure_does_not_draft(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.db")
    idea = memory.create_article_idea("article:2026-W32", "serp-failure-hash", dict(DEFAULT_IDEA))
    memory.update_article_idea(
        idea["id"],
        status="serp_requested",
        research_run_id="run-overview",
        serp_run_id="run-serp",
        research_note_json={"decision": "keep", "selected_query": "reader question basics"},
    )

    class FailingSerpService:
        def article_keyword_research_status(self, _run_id):
            return {"status": "completed"}

        def article_serp_research_status(self, _run_id):
            return {"status": "failed", "error_code": "DATAFORSEO_TASK_ERROR", "cost_micros": 2000}

    context = {
        "config": {"seo": {"article_research": {"enabled": True}}},
        "memory": memory,
        "crawlseo_service": FailingSerpService(),
        "llm": object(),
    }
    monkeypatch.setattr(
        article_research.brain_article,
        "draft_article_for_idea",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("failed SERP must not draft")),
    )
    try:
        article_research.reconcile(context)
        saved = memory.get_article_idea(idea["id"])
        assert saved["status"] == "failed"
        assert saved["draft_id"] is None
        assert "DATAFORSEO_TASK_ERROR" in saved["error"]
    finally:
        memory.close()

def test_idea_summary_is_bounded_and_prioritises_the_reader_question():
    long_idea = {
        "reader_question": "Q" * 900,
        "thesis": "T" * 900,
        "reader_situation": "S" * 900,
        "market_context": "M" * 900,
        "expert_angle": "E" * 900,
    }
    summary = article_research._idea_summary(long_idea)
    assert 0 < len(summary) <= 1800
    assert summary.startswith("Reader question:")
    assert "Thesis:" in summary
    assert "Expert angle:" not in summary


def test_idea_summary_skips_missing_fields():
    assert article_research._idea_summary({"reader_question": "How do I choose?", "thesis": ""}) == "Reader question: How do I choose?"

from site_agent.application.incubation_research import IncubationResearchExecutor, IncubationResearchService
from site_agent.application.incubations import IncubationApplicationService, IncubationRuntime
from site_agent.brain.incubation_research import IncubationResearchPlan, LLMIncubationResearchPlanner, base_plan
from site_agent.config import load_intake_config
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import DesignIntakeDraft, IntakeFieldProvenance
from site_agent.core.intake_ada_store import IntakeAdaStore
from site_agent.core.memory import Memory
from site_agent.hands.feed_discovery import ResearchDocument, RedditFeedDiscovery


def _draft(*, include_location=True) -> DesignIntakeDraft:
    business = {
        "name": "North Star Studio",
        "offer_summary": "Brand strategy for independent businesses.",
        "primary_services": ["Brand strategy"],
    }
    if include_location:
        business["location"] = "Marseille"
    intake = SiteIntake.from_dict({
        "schema_version": 1,
        "business": business,
        "audience": {"primary": "Independent business owners"},
        "conversion": {"primary_action": "Book a consultation", "not_available": True},
        "brand": {"voice": "Clear and warm."},
        "site": {"required_pages": ["index.html"], "language": "fr"},
    })
    return DesignIntakeDraft.from_site_intake(intake)


def test_base_plan_derives_research_context_from_typed_intake():
    plan = base_plan(_draft(), owner_language="fr")

    assert plan.owner_language == "fr"
    assert plan.subjects == ("Brand strategy", "Independent business owners", "Brand strategy for independent businesses.")
    assert plan.markets == ("Marseille",)
    assert "Marseille" in plan.intent
    assert plan.query_terms_by_language["fr"]


def test_research_context_requires_location_or_explicit_non_applicable_choice(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    intake_store = IntakeAdaStore(tmp_path / "intake-data" / "intake-ada.db")
    service = IncubationApplicationService(
        intake_store,
        root=config["incubation"]["root"],
        config=config,
    )
    try:
        no_location = _draft(include_location=False)
        assert no_location.location_context_resolved is False
        assert service._research_context_ready(no_location) is False

        opt_out = no_location.with_value(
            "business.location_not_applicable",
            True,
            IntakeFieldProvenance(path="business.location_not_applicable", origin="confirmed"),
        )
        assert opt_out.location_context_resolved is True
        assert service._research_context_ready(opt_out) is True
        assert base_plan(opt_out).markets == ()
    finally:
        service.close()
        intake_store.close()


class _PlannerLLM:
    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return """```json
        {
          "candidate_communities": [
            {"name": "r/Scuba", "language": "en", "rationale": "A specialist discussion space."},
            {"name": "not a community", "language": "en", "rationale": "discard"},
            {"name": "https://reddit.com/r/private", "language": "en", "rationale": "discard"}
          ],
          "candidate_feeds": [
            {"url": "https://example.org/tapestry/blog", "name": "Tapestry blog", "language": "en", "rationale": "Likely RSS about upholstery."},
            {"url": "ftp://example.org/feed", "name": "FTP", "language": "en", "rationale": "discard"},
            {"url": "https://user:pass@example.org/x", "name": "Creds", "language": "en", "rationale": "discard"},
            {"url": "not a url", "name": "Junk", "language": "en", "rationale": "discard"}
          ],
          "query_terms_by_language": {
            "fr": ["plongee", "https://example.com", ""],
            "bad language": ["discard"]
          }
        }
        ```"""


def test_llm_planner_accepts_only_bounded_candidate_names_and_terms():
    llm = _PlannerLLM()
    planner = LLMIncubationResearchPlanner(llm, {"planner": {"max_tokens": 300}})

    plan = planner.plan(_draft(), owner_language="fr", excluded_communities=("r/already-read",))

    assert [item["name"] for item in plan.candidate_communities] == ["Scuba"]
    assert plan.candidate_communities[0]["status"] == "candidate"
    assert plan.candidate_communities[0]["rationale"] == "A specialist discussion space."
    assert plan.query_terms_by_language == {"fr": ("plongee",)}
    assert llm.calls[0][1]["max_tokens"] == 300
    assert [item["url"] for item in plan.candidate_feeds] == ["https://example.org/tapestry/blog"]
    assert plan.candidate_feeds[0]["status"] == "candidate"


def test_llm_planner_retries_once_before_reporting_failure():
    class _FlakyLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient provider outage")
            return '{"candidate_communities": [], "candidate_feeds": [], "query_terms_by_language": {}}'

    planner = LLMIncubationResearchPlanner(_FlakyLLM(), {"planner": {"max_tokens": 300}})

    plan = planner.plan(_draft(), owner_language="fr")

    assert planner.llm.calls == 2
    assert plan.subjects
    assert plan.candidate_feeds == ()


def test_reddit_discovery_normalizes_names_without_accepting_urls():
    sources = RedditFeedDiscovery().discover([
        {"name": "r/Scuba", "language": "en"},
        {"name": "https://reddit.com/r/private", "language": "en"},
        {"name": "Scuba", "language": "en"},
    ])

    assert len(sources) == 1
    assert sources[0].title == "r/Scuba"
    assert sources[0].trust_state == "candidate"
    assert sources[0].url == "https://www.reddit.com/r/Scuba/"
    assert sources[0].feed_url == "https://www.reddit.com/r/Scuba/.rss"


def test_repeated_community_candidate_reuses_identity_and_refreshes_language(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    service = IncubationResearchService(memory)
    try:
        first = service.request({
            "trigger": "intake_threshold",
            "intake_revision": 1,
            "intent": "freediving audience",
            "candidate_communities": [{"name": "Scuba", "language": "en", "rationale": "Specialist context."}],
        })
        second = service.request({
            "trigger": "intake_threshold",
            "intake_revision": 2,
            "intent": "freediving audience",
            "candidate_communities": [{"name": "r/SCUBA", "language": "fr", "rationale": "French context."}],
        })

        first_id = first["request"]["source_ids"][0]
        second_id = second["request"]["source_ids"][0]
        assert first_id == second_id
        assert memory.get_research_source(first_id)["language"] == "fr"
    finally:
        memory.close()


class _Reader:
    def __init__(self, documents=True):
        self.calls = []
        self.documents = documents

    def read(self, source):
        self.calls.append(source.source_id)
        if not self.documents:
            return ()
        return (ResearchDocument(
            source_id=source.source_id,
            url=source.url,
            title="A useful public discussion",
            summary="A bounded observation about the audience.",
            published_at="2026-09-03T00:00:00+00:00",
            content_hash="a" * 64,
        ),)


def test_threshold_candidate_is_read_by_policy_but_remains_unapproved(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    reader = _Reader()
    service = IncubationResearchService(memory, reader=reader)
    executor = IncubationResearchExecutor(service)
    try:
        queued = service.request({
            "trigger": "intake_threshold",
            "intake_revision": 2,
            "owner_language": "en",
            "intent": "freediving audience",
            "subjects": ["freediving"],
            "candidate_communities": [{"name": "r/Scuba", "language": "en", "rationale": "Specialist context."}],
            "fetch": True,
        }, enqueue=True)

        assert queued["status"] == "queued"
        source_id = queued["request"]["source_ids"][0]
        assert reader.calls == []

        assert executor.process_one() is True
        assert reader.calls == [source_id]
        assert memory.get_research_source(source_id)["trust_state"] == "candidate"
        request = memory.get_research_request(queued["request"]["request_id"])
        assert request["candidate_communities"][0]["status"] == "verified"
        assert request["candidate_communities"][0]["source_id"] == source_id
    finally:
        executor.stop()
        memory.close()


def test_owner_request_cannot_read_a_candidate_without_approval(tmp_path):
    memory = Memory(tmp_path / "incubation.db")
    reader = _Reader()
    service = IncubationResearchService(memory, reader=reader)
    try:
        result = service.request({
            "intake_revision": 1,
            "intent": "freediving audience",
            "candidate_communities": [{"name": "Scuba", "rationale": "Specialist context."}],
            "source_ids": [],
            "fetch": True,
        }, enqueue=True)

        assert result["status"] == "awaiting_source_approval"
        assert reader.calls == []
    finally:
        memory.close()


class _Planner:
    def __init__(self):
        self.calls = 0

    def plan(self, draft, **kwargs):
        self.calls += 1
        return IncubationResearchPlan(
            intent="brand strategy audience Marseille",
            owner_language="fr",
            subjects=("Brand strategy",),
            markets=("Marseille",),
            candidate_communities=({"name": "Scuba", "language": "en", "rationale": "Specialist context.", "status": "candidate"},),
            query_terms_by_language={"fr": ("strategie",)},
        )


class _Worker:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


def test_threshold_schedules_one_pass_per_revision(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    intake_store = IntakeAdaStore(tmp_path / "intake-data" / "intake-ada.db")
    planner = _Planner()
    worker = _Worker()
    service = IncubationApplicationService(
        intake_store,
        root=config["incubation"]["root"],
        config=config,
    )
    record = service.create_incubation()
    service.attach_runtime(record.incubation_id, IncubationRuntime(research_planner=planner, research_executor=worker))
    try:
        first = service.schedule_threshold_research(
            record.incubation_id,
            session_id="intake-" + "a" * 32,
            draft=_draft(),
            revision={"revision": 2},
        )
        # A second automatic pass on the SAME revision is throttled...
        second = service.schedule_threshold_research(
            record.incubation_id,
            session_id="intake-" + "a" * 32,
            draft=_draft(),
            revision={"revision": 2},
        )
        # ...but the owner's next message advances the revision and unlocks one
        # fresh pass, so research keeps pace with the conversation.
        third = service.schedule_threshold_research(
            record.incubation_id,
            session_id="intake-" + "a" * 32,
            draft=_draft(),
            revision={"revision": 3},
        )

        assert first["status"] == "queued"
        assert second["status"] == "owner_turn_required"
        assert third["status"] == "queued"
        assert planner.calls == 2
        assert service.get_record(record.incubation_id).status == "researching"
        sources = service.research_projection(record.incubation_id)["sources"]
        assert sources[0]["trust_state"] == "candidate"
    finally:
        service.close()
        intake_store.close()

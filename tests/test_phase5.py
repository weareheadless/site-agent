import json
from unittest import mock

import pytest

from site_agent.brain import strategist as strategist_mod
from site_agent.core import maintenance
from site_agent.core.llm import Client, LLMError
from site_agent.core.memory import Memory
from site_agent.senses import seo as seo_sense


@pytest.fixture
def env(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    config = {
        "env": {"llm_api_key": "K"},
        "persona": {"name": "Ada"},
        "llm": {
            "base_url": "https://api.test/v1",
            "model": "m",
            "max_retries": 0,
            "daily_budget_usd": 1.0,
            "price_per_mtok": {"input": 1.0, "output": 1.0},
        },
        "seo": {"enabled": True, "source": "gsc", "site_url": "https://example.com/", "key_path": "/tmp/k.json"},
    }
    yield memory, config
    memory.close()


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return self.replies.pop(0)


def test_top_queries_parses_gsc_response(env):
    _, config = env

    response = {
        "dimensionHeaders": [{"name": "keys"}],
        "rows": [
            {"keys": ["mouthfill technique"], "clicks": 12.4, "impressions": 900, "ctr": 0.0138, "position": 8.3},
            {"keys": ["freediving course playa"], "clicks": 5, "impressions": 300, "ctr": 0.0167, "position": 6.1},
        ],
    }
    with mock.patch.object(seo_sense, "_run", return_value=response) as run_mock:
        queries = seo_sense.top_queries(config)
    assert queries[0]["query"] == "mouthfill technique"
    assert queries[0]["impressions"] == 900
    assert len(queries) == 2
    body = run_mock.call_args.args[1]
    assert body["dimensions"] == ["query"]


def test_mcp_stub_and_unconfigured_raise_clearly(env):
    _, config = env
    config["seo"]["enabled"] = True
    config["seo"]["source"] = "mcp"
    with pytest.raises(SeoError := seo_sense.SeoError, match="arrives later"):
        seo_sense.summary(config)

    config["seo"]["source"] = "gsc"
    config["seo"]["site_url"] = ""
    with pytest.raises(seo_sense.SeoError, match="not configured"):
        seo_sense.summary(config)


def test_strategist_builds_cards_from_signals(env):
    memory, config = env
    memory.snapshot_metrics("ga4", {"current_week": {"activeUsers": 40}, "top_pages": [{"path": "/", "views": 30}]})
    memory.snapshot_metrics("gsc", {"top_queries": [{"query": "frenzel", "clicks": 9}]})
    memory.save_draft("Old article", "body", kind="article")
    did = memory.list_drafts(limit=1)[0]["id"]
    memory.update_draft_status(did, "approved")

    llm = FakeLLM([json.dumps({"cards": [
        {"title": "Frenzel guide", "action": "write a beginner frenzel article", "why": "top query with few clicks"},
    ]})])
    context = {"config": config, "memory": memory, "llm": llm, "persona_prompt": "You are Ada."}
    count = strategist_mod.run(context)
    assert count == 1
    stored = memory.kv_get("strategist_cards")["cards"]
    assert stored[0]["title"] == "Frenzel guide"

    block = strategist_mod.cards_block(memory)
    assert "Frenzel guide" in block


def test_weekly_report_weaves_in_cards(env):
    from site_agent.brain.report import weekly_report

    memory, config = env
    memory.kv_set("strategist_cards", {"cards": [{"title": "Tide tables", "action": "publish tide table page", "why": "queries rising"}]})
    llm = FakeLLM(["# This week on your site\n\nAll calm. Tide tables next."])
    weekly_report({"config": config, "memory": memory, "llm": llm, "persona_prompt": ""})
    user_content = llm.calls[0][1]["content"]
    assert "Tide tables" in user_content and "strategist cards" in user_content.lower()


def test_budget_guard_blocks_when_spent(env):
    memory, config = env
    memory.log_llm_cost("m", prompt_tokens=1_100_000, completion_tokens=0, cost_usd=1.10)
    client = Client(config, memory, env={"K": "sk"})
    with mock.patch("site_agent.core.llm._http_post") as never:
        with pytest.raises(LLMError, match="budget exhausted"):
            client.chat([{"role": "user", "content": "hi"}])
    assert never.call_count == 0


def test_budget_guard_also_blocks_tool_calls(env):
    memory, config = env
    memory.log_llm_cost("m", prompt_tokens=1_100_000, completion_tokens=0, cost_usd=1.10)
    client = Client(config, memory, env={"K": "sk"})
    with mock.patch("site_agent.core.llm._http_post") as never:
        with pytest.raises(LLMError, match="budget exhausted"):
            client.chat_tools([{"role": "user", "content": "hi"}], [])
    assert never.call_count == 0


def test_budget_guard_passes_under_cap(env):
    memory, config = env
    memory.log_llm_cost("m", prompt_tokens=100_000, completion_tokens=0, cost_usd=0.10)
    client = Client(config, memory, env={"K": "sk"})
    with mock.patch("site_agent.core.llm._http_post", return_value={
        "model": "m",
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }):
        assert client.chat([{"role": "user", "content": "hi"}]) == "ok"


def test_budget_disabled_with_null(env):
    _, config = env
    config["llm"]["daily_budget_usd"] = None
    client = Client(config, env={"K": "sk"})
    assert client.daily_budget_usd is None


def test_backup_creates_snapshot_and_prunes(env, tmp_path):
    memory = env[0]
    context = {"memory": memory}
    for i in range(6):
        maintenance.backup_data(context, keep=5)
    backups = sorted((tmp_path / "backups").glob("memory-*.db"))
    assert len(backups) == 5
    actions = [a for a in memory.recent_actions(limit=10) if a["kind"] == "backup"]
    assert actions and "kept 5" in actions[0]["detail"]


def test_organic_queries_parse_and_fallback(env):
    from site_agent.senses import ga as ga_sense

    response = {
        "dimensionHeaders": [{"name": "googleOrganicSearchQuery"}],
        "rows": [
            {"dimensionValues": [{"value": "frenzel technique"}], "metricValues": [
                {"value": "9"}, {"value": "7"}, {"value": "21"}]},
            {"dimensionValues": [{"value": "freediving playa del carmen"}], "metricValues": [
                {"value": "4"}, {"value": "3"}, {"value": "8"}]},
        ],
    }
    with mock.patch.object(ga_sense, "_run", return_value=response):
        queries = ga_sense.organic_queries(config=env[1])
    assert queries[0] == {"query": "frenzel technique", "sessions": 9, "users": 7, "views": 21}

    # weekly_summary must not break when the GSC link is missing
    config = env[1]
    config["ga"] = {"enabled": True, "property_id": "551030734", "key_path": ""}
    with mock.patch.object(
        ga_sense, "_totals", return_value={"totalUsers": 5}
    ), mock.patch.object(
        ga_sense, "top_pages", return_value=[]
    ), mock.patch.object(
        ga_sense, "traffic_sources", return_value=[]
    ), mock.patch.object(
        ga_sense, "organic_queries", side_effect=RuntimeError("no link yet")
    ):
        summary = ga_sense.weekly_summary(config)
    assert summary["organic_queries"] == []
    assert summary["current_week"] == {"totalUsers": 5}


def test_strategist_falls_back_to_ga4_linked_queries(env):
    memory = env[0]
    memory.snapshot_metrics("ga4", {"organic_queries": [{"query": "mouthfill", "sessions": 6}]})
    material = strategist_mod.gather(memory)
    assert material["search_queries"][0]["query"] == "mouthfill"
    assert material["query_source"] == "ga4-gsc-link"
    memory.snapshot_metrics("gsc", {"top_queries": [{"query": "frenzel", "clicks": 3}]})
    material = strategist_mod.gather(memory)
    assert material["query_source"] == "gsc"

import json
import sqlite3

import pytest

from site_agent.brain import article_research, seo_insights
from site_agent.core.memory import Memory


class InsightLLM:
    def __init__(self, payload=None):
        self.payload = payload or {
            "headline": "Your best page brings the most qualified visitors",
            "summary_md": "Traffic is steady. The homepage carries most sessions.",
            "opportunities": [
                {"title": "Improve the homepage intro", "rationale": "it is the top page", "action": "tighten the first paragraph"},
                {"title": "Add a price FAQ", "rationale": "readers ask about cost", "action": "answer cost on the services page"},
            ],
            "watchouts": ["traffic is small this week; do not over-react"],
            "next_action": "Rewrite the homepage intro",
            "focus_keyword": "retapisser un fauteuil",
        }

    def chat(self, *_args, **_kwargs):
        return json.dumps(self.payload)


def _context(memory, llm):
    return {
        "memory": memory,
        "llm": llm,
        "config": {"llm": {"model": "test-model"}, "persona": {"audience": "local owners"}},
    }


def test_generate_persists_a_bounded_owner_facing_insight(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.snapshot_metrics("ga4", {
        "current_week": {"sessions": 12},
        "previous_week": {"sessions": 9},
        "delta_pct": {"clicks": 18.5},
        "top_pages": [{"path": "/", "views": 7}, {"path": "/lampes", "views": 3}],
    })
    memory.snapshot_metrics("gsc", {"period_days": 28, "top_queries": [{"query": "abat-jour", "clicks": 2}]})

    insight_id = seo_insights.generate(_context(memory, InsightLLM()))
    assert insight_id > 0

    latest = memory.latest_seo_insight()
    assert latest["headline"].startswith("Your best page")
    assert latest["opportunities"][0]["title"] == "Improve the homepage intro"
    assert latest["next_action"] == "Rewrite the homepage intro"
    assert latest["focus_keyword"] == "retapisser un fauteuil"
    assert latest["metrics"]["sessions_current"] == 12
    assert latest["provider"] == "ada"
    assert latest["model"] == "test-model"
    assert latest["period"].startswith("seo:")
    assert memory.list_seo_insights(limit=5)[0]["id"] == insight_id
    memory.close()


def test_insight_rejects_missing_headline_or_summary():
    with pytest.raises(ValueError, match="headline"):
        seo_insights._validate(json.dumps({"summary_md": "text"}))
    with pytest.raises(ValueError, match="headline and a summary"):
        seo_insights._validate(json.dumps({"headline": "h"}))


def test_insight_caps_opportunities_and_watchouts():
    payload = {
        "headline": "h",
        "summary_md": "s",
        "opportunities": [{"title": f"o{i}"} for i in range(9)],
        "watchouts": [f"w{i}" for i in range(9)],
    }
    result = seo_insights._validate(json.dumps(payload))
    assert len(result["opportunities"]) == 5
    assert len(result["watchouts"]) == 4


def test_article_idea_prompt_reuses_the_latest_insight(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    memory.save_seo_insight(
        period="seo:2026-W40",
        headline="Focus on restoration demand",
        summary_md="summary",
        next_action="Publish the restoration price guide",
        focus_keyword="restauration fauteuil",
        opportunities=[{"title": "Price guide", "rationale": "asked often", "action": "write it"}],
    )
    context = {
        "config": {
            "persona": {"audience": "owners"},
            "seo": {"article_research": {"enabled": True}, "research": {"languages": [{"code": "fr", "markets": ["FR"], "primary": True}]}},
            "customer_profile": {"business": {"name": "Workspace"}},
        },
        "memory": memory,
    }
    messages = article_research._idea_prompt(context)
    payload = messages[1]["content"]
    assert "Focus on restoration demand" in payload
    assert "Publish the restoration price guide" in payload
    assert "Price guide" in payload
    memory.close()


def test_memory_migrates_the_insight_table(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    tables = {row[0] for row in memory.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "seo_insights" in tables
    assert memory.get_schema_version() >= 41
    memory.close()

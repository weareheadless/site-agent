from pathlib import Path

import pytest
import yaml

from site_agent.config import ConfigError, load_intake_config, validate_intake_config


def test_neutral_intake_config_has_no_customer_surface():
    config, sources = load_intake_config(env={})

    assert config["instance_name"] == "intake-ada"
    assert config["role"] == "intake"
    assert config["persona"] == {"name": "Ada", "mode": "intake_creative_director"}
    assert config["site"]["adapter"] == "neutral_scaffold"
    assert config["site"]["repository"] == ""
    assert config["site"]["clone_path"] == ""
    assert config["vision"]["enabled"] is True
    assert config["vision"]["provider"] == "openrouter"
    assert config["vision"]["model"] == "deepseek/deepseek-v4-flash-vision-exp"
    assert config["vision"]["base_url"] == "https://openrouter.ai/api/v1"
    assert config["llm"]["base_url"] == "https://openrouter.ai/api/v1"
    assert config["llm"]["model"] == "deepseek/deepseek-v4-flash-0731"
    assert config["design_engine"]["provider"] == "openrouter"
    assert config["design_engine"]["model"] == "deepseek/deepseek-v4-flash-vision-exp"
    assert config["design_engine"]["planner_model"] == "deepseek/deepseek-v4-flash-0731"
    assert config["design_engine"]["max_tokens"] == 8192
    assert config["design_engine"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert config["builder"]["model"] == "openrouter/deepseek/deepseek-v4-flash-vision-exp"
    advisor = config["design_engine"]["intake_advisor"]
    assert advisor["model"] == "deepseek/deepseek-v4-flash-0731"
    assert advisor["base_url"] == "https://openrouter.ai/api/v1"
    assert advisor["api_key_env"] == "OPENROUTER_API_KEY"
    assert config["design_engine"]["libraries"]["gsap"]["enabled"] is True
    assert config["design_engine"]["libraries"]["gsap"]["required"] is True
    assert config["env"]["llm_api_key"] == config["env"]["design_api_key"] == "OPENROUTER_API_KEY"
    assert config["env"]["vision_api_key"] == config["env"]["visual_review_api_key"] == "OPENROUTER_API_KEY"
    assert config["site"]["media"]["enabled"] is False
    assert config["site"]["media"]["site_asset_dir"] == "images/ada-media"
    assert config["sources"] == {"subreddits": [], "rss_feeds": [], "keywords": [], "min_score": 0.0, "max_per_run": 25}
    assert sources


@pytest.mark.parametrize(
    "override, message",
    [
        ({"site": {"repository": "fictional-owner/fictional-site"}}, "site.repository"),
        ({"site": {"clone_path": "/srv/site"}}, "site.clone_path"),
        ({"persona": {"spirit": "a customer-specific story"}}, "persona.spirit"),
        ({"sources": {"rss_feeds": ["https://example.test/feed.xml"]}}, "sources.rss_feeds"),
        ({"ga": {"enabled": True}}, "ga.enabled"),
    ],
)
def test_intake_config_rejects_customer_specific_values(tmp_path, override, message):
    path = tmp_path / "intake.yaml"
    path.write_text(yaml.safe_dump({"role": "intake", **override}), encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_intake_config(path, env={})


def test_intake_roots_must_be_disjoint(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake")
    config["incubation"]["root"] = str(tmp_path / "intake" / "incubations")

    with pytest.raises(ConfigError, match="disjoint"):
        validate_intake_config(config)


def test_intake_composition_has_no_known_customer_identifier():
    root = Path(__file__).parents[1] / "src" / "site_agent"
    paths = [
        root / "defaults.yaml",
        root / "config.py",
        root / "main.py",
        root / "application" / "intake_lab.py",
    ]

    text = "\n".join(path.read_text(encoding="utf-8").casefold() for path in paths)
    assert "oceanicvibes" not in text

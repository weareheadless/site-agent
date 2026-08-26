import os

import pytest
import yaml

from site_agent.config import ConfigError, deep_merge, instance_path, load, mask_secrets, resolve_env


def test_defaults_load_without_instance_file():
    config, sources = load(env={})
    assert config["instance_name"] == "default"
    assert config["site"]["adapter"] == "github_static"
    assert config["blog"]["engine"] == "pelican"
    assert sources[0] is not None


def test_instance_config_overrides_nested_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"instance_name": "oceanicvibes", "site": {"repository": "ov/repo"}}))
    config, sources = load(config_path=path, env={})
    assert config["instance_name"] == "oceanicvibes"
    assert config["site"]["repository"] == "ov/repo"
    assert config["site"]["branch"] == "main"
    assert len(sources) == 2


def test_explicit_missing_config_fails_fast(tmp_path):
    with pytest.raises(ConfigError, match="configuration file not found"):
        load(config_path=tmp_path / "missing.yaml", env={})


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"b": 1}}
    out = deep_merge(base, {"a": {"c": 2}})
    out["a"]["c"] = 3
    assert base == {"a": {"b": 1}}


def test_instance_path_prefers_env_var(tmp_path):
    env = {"SITE_AGENT_CONFIG": str(tmp_path / "custom.yaml")}
    (tmp_path / "custom.yaml").write_text("instance_name: x\n")
    assert instance_path(env) == tmp_path / "custom.yaml"


def test_resolve_env_reports_set_and_missing():
    config = {"env": {"llm_api_key": "K1", "github_token": "K2"}}
    state = resolve_env(config, env={"K1": "v"})
    assert state["llm_api_key"] == {"var": "K1", "set": True}
    assert state["github_token"] == {"var": "K2", "set": False}


def test_mask_secrets_masks_sensitive_keys_and_drops_env_map():
    config = {"llm": {"api_key": "sk-123", "model": "m"}, "admin": {"password": "pw"}, "env": {"a": "B"}}
    masked = mask_secrets(config)
    assert masked["llm"]["api_key"] == "***"
    assert masked["admin"]["password"] == "***"
    assert masked["llm"]["model"] == "m"
    assert "env" not in masked

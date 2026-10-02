import os

import pytest
import yaml

from site_agent.config import (
    ConfigError,
    deep_merge,
    instance_path,
    load,
    load_env_file,
    mask_secrets,
    resolve_env,
    validate_design_config,
)


def test_defaults_load_without_instance_file():
    config, sources = load(env={})
    assert config["instance_name"] == "default"
    assert config["site"]["adapter"] == "github_static"
    assert config["blog"]["engine"] == "payload"
    assert config["llm"]["base_url"] == "https://openrouter.ai/api/v1"
    assert config["llm"]["model"] == "deepseek/deepseek-v4-flash-0731"
    assert config["builder"]["model"] == "openrouter/deepseek/deepseek-v4.1-flash"
    assert config["design_engine"]["orchestration"] == "legacy"
    assert config["dream"]["residue_count"] == 0
    assert config["self_model"]["enabled"] is True
    # Reader-led article research is the always-on default article pipeline.
    assert config["seo"]["article_research"]["enabled"] is True
    assert sources[0] is not None


def test_article_research_enabled_by_default_inherits_primary_locale(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "seo": {"research": {"languages": [{"code": "fr", "markets": ["FR"], "primary": True}]}},
    }))
    config, _ = load(config_path=path, env={})
    assert config["seo"]["article_research"]["enabled"] is True
    from site_agent.config import primary_research_locale
    assert primary_research_locale(config) == ("fr", "FR")


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


def test_enabled_private_media_requires_r2_credentials(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "site": {"media": {"enabled": True, "account_id": "a" * 32, "bucket": "hello-media", "private": True}},
    }))
    with pytest.raises(ConfigError, match="R2 media is enabled"):
        load(config_path=path, env={})


def test_enabled_media_accepts_bounded_private_r2_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "site": {"media": {"enabled": True, "account_id": "a" * 32, "bucket": "hello-media", "private": True}},
    }))
    config, _ = load(config_path=path, env={
        "R2_ACCESS_KEY_ID": "access",
        "R2_SECRET_ACCESS_KEY": "secret",
    })
    assert config["site"]["media"]["private"] is True


def test_profile_backed_integration_credentials_are_used_during_load(tmp_path):
    profile = tmp_path / "host-credentials.yaml"
    profile.write_text(
        "credentials:\n"
        "  env_file: " + str(tmp_path / "host.env") + "\n",
        encoding="utf-8",
    )
    (tmp_path / "host.env").write_text(
        "R2_ACCESS_KEY_ID=profile-access\n"
        "R2_SECRET_ACCESS_KEY=profile-secret\n",
        encoding="utf-8",
    )
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "credentials": {"profile_file": str(profile)},
        "site": {
            "media": {
                "enabled": True,
                "account_id": "a" * 32,
                "bucket": "hello-media",
                "private": True,
            },
        },
    }))

    config, _ = load(config_path=path, env={})

    assert config["site"]["media"]["enabled"] is True


def test_isolated_load_can_skip_optional_integration_credentials(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "site": {"media": {"enabled": True, "account_id": "a" * 32, "bucket": "hello-media", "private": True}},
    }))
    config, _ = load(config_path=path, env={}, validate_integrations=False)
    assert config["site"]["media"]["enabled"] is True


def test_enabled_media_rejects_public_bucket_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({
        "site": {"media": {"enabled": True, "account_id": "a" * 32, "bucket": "hello-media", "private": False}},
    }))
    with pytest.raises(ConfigError, match="private must be true"):
        load(config_path=path, env={
            "R2_ACCESS_KEY_ID": "access",
            "R2_SECRET_ACCESS_KEY": "secret",
        })


def test_load_env_file_supports_comments_quotes_and_process_precedence(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# comment\nexport CLOUDFLARE_API_TOKEN=from-file\nOTHER='quoted value'\n")
    values = load_env_file(path, {"CLOUDFLARE_API_TOKEN": "from-process"})
    assert values["CLOUDFLARE_API_TOKEN"] == "from-process"
    assert values["OTHER"] == "quoted value"


def test_design_quality_required_content_is_a_non_empty_text_list():
    base = {"required_viewports": [{"name": "desktop", "width": 1440, "height": 1000}]}
    with pytest.raises(ConfigError, match="required_content must be a list"):
        validate_design_config({"design_engine": {**base, "quality": {"required_content": "one fact"}}})
    with pytest.raises(ConfigError, match=r"required_content\[0\] must be non-empty text"):
        validate_design_config({"design_engine": {**base, "quality": {"required_content": [""]}}})


def test_design_quality_required_content_accepts_bounded_text():
    validate_design_config({
        "design_engine": {
            "required_viewports": [{"name": "desktop", "width": 1440, "height": 1000}],
            "quality": {"required_content": ["A verified offer", "A verified service"]},
        }
    })


def test_design_orchestration_is_explicit_and_bounded():
    validate_design_config({
        "design_engine": {
            "orchestration": "specialist",
            "specialist_timeout_seconds": 300,
            "required_viewports": [{"name": "desktop", "width": 1440, "height": 1000}],
        }
    })
    validate_design_config({
        "design_engine": {
            "orchestration": "native",
            "required_viewports": [{"name": "desktop", "width": 1440, "height": 1000}],
        }
    })
    with pytest.raises(ConfigError, match="orchestration must be legacy, native, specialist, or creative"):
        validate_design_config({
            "design_engine": {
                "orchestration": "unbounded",
                "required_viewports": [{"name": "desktop", "width": 1440, "height": 1000}],
            }
        })
    with pytest.raises(ConfigError, match="specialist_timeout_seconds"):
        validate_design_config({
            "design_engine": {
                "specialist_timeout_seconds": 3,
                "required_viewports": [{"name": "desktop", "width": 1440, "height": 1000}],
            }
        })

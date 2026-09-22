import os

from site_agent.credentials import (
    credential_environment,
    credential_profile,
    credential_profile_file,
    credential_status,
    github_remote,
    github_ssh_command,
)


def test_host_credential_files_are_loaded_without_overriding_process_values(tmp_path):
    env_file = tmp_path / "platform.env"
    env_file.write_text("GITHUB_PERSONAL_ACCESS_TOKEN=from-file\nCLOUDFLARE_API_TOKEN=cf-token\n")
    config = {
        "credentials": {
            "github": {"env_file": str(env_file)},
            "cloudflare": {"env_file": str(env_file)},
        }
    }

    resolved = credential_environment(config, {"GITHUB_PERSONAL_ACCESS_TOKEN": "from-process"})

    assert resolved["GITHUB_PERSONAL_ACCESS_TOKEN"] == "from-process"
    assert resolved["CLOUDFLARE_API_TOKEN"] == "cf-token"


def test_canonical_profile_file_is_loaded_once_with_explicit_overrides(tmp_path):
    profile_file = tmp_path / "host-credentials.yaml"
    profile_file.write_text(
        "credentials:\n"
        "  github:\n"
        "    ssh_key_path: /host/github.key\n"
        "    api_token_env: HOST_GITHUB_TOKEN\n"
        "  cloudflare:\n"
        "    env_file: /host/cloudflare.env\n"
        "    api_token_env: HOST_CLOUDFLARE_TOKEN\n",
        encoding="utf-8",
    )
    config = {
        "credentials": {
            "profile_file": str(profile_file),
            "github": {"api_token_env": "TENANT_GITHUB_TOKEN"},
        }
    }

    assert credential_profile_file(config) == profile_file.resolve()
    assert credential_profile(config, "github")["ssh_key_path"] == "/host/github.key"
    assert credential_profile(config, "github")["api_token_env"] == "TENANT_GITHUB_TOKEN"
    assert credential_profile(config, "cloudflare")["api_token_env"] == "HOST_CLOUDFLARE_TOKEN"


def test_github_profile_provides_ssh_transport_and_remote_upgrade(tmp_path):
    key = tmp_path / "github_ed25519"
    key.write_text("private-key-placeholder")
    os.chmod(key, 0o600)
    config = {"credentials": {"github": {"ssh_key_path": str(key)}}}

    command = github_ssh_command(config, {})

    assert str(key) in command
    assert github_remote("https://github.com/acme/site.git", config) == "git@github.com:acme/site.git"


def test_credential_status_is_non_secret_and_reports_file_readiness(tmp_path):
    key = tmp_path / "github_ed25519"
    key.write_text("private-key-placeholder")
    os.chmod(key, 0o600)
    env_file = tmp_path / "cloudflare.env"
    env_file.write_text("CLOUDFLARE_API_TOKEN=cf-secret-123\nCLOUDFLARE_ACCOUNT_ID=account-secret-456\n")
    config = {
        "credentials": {
            "github": {"ssh_key_path": str(key)},
            "cloudflare": {"env_file": str(env_file)},
        }
    }

    status = credential_status(config, {})

    assert status["github"]["ssh_key_available"] is True
    assert status["github"]["ssh_key_permissions_secure"] is True
    assert status["cloudflare"]["env_file_available"] is True
    assert status["cloudflare"]["api_token_configured"] is True
    assert status["cloudflare"]["account_id_configured"] is True
    assert "cf-secret-123" not in str(status)
    assert "account-secret-456" not in str(status)

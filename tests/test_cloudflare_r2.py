from pathlib import Path

from site_agent.hands.cloudflare_r2 import (
    CloudflareR2Provisioner,
    R2ProvisioningResult,
    write_instance_r2_config,
)


def test_provision_creates_bucket_and_scoped_token(monkeypatch):
    calls = []
    client = CloudflareR2Provisioner("a" * 32, "cf-token")

    def request(method, path, body=None):
        calls.append((method, path, body))
        if path.endswith("/r2/buckets"):
            return {"success": True, "result": {"name": "hello-media"}}
        if path.endswith("/permission_groups"):
            return {"success": True, "result": [{"id": "group-id", "name": "Workers R2 Storage Bucket Item Write"}]}
        return {"success": True, "result": {"id": "access-id", "value": "token-value"}}

    monkeypatch.setattr(client, "_request", request)
    result = client.provision("hello-media", token_name="site-agent-hello")

    assert result.bucket_created is True
    assert result.access_key_id == "access-id"
    assert result.secret_access_key
    token_call = calls[-1]
    assert token_call[0] == "POST"
    assert "hello-media" in str(token_call[2])
    assert "site-agent-hello" in str(token_call[2])
    assert calls[1][1] == "/accounts/" + ("a" * 32) + "/tokens/permission_groups"


def test_provision_reuses_existing_credentials(monkeypatch):
    client = CloudflareR2Provisioner("a" * 32, "cf-token")
    monkeypatch.setattr(client, "ensure_bucket", lambda *args, **kwargs: False)
    monkeypatch.setattr(client, "create_bucket_token", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("rotated")))
    result = client.provision("hello-media", existing_credentials=("access", "secret"))
    assert result.token_created is False
    assert result.access_key_id == "access"


def test_write_instance_r2_config_preserves_other_env_values(tmp_path):
    config = tmp_path / "config.yaml"
    env = tmp_path / ".env"
    config.write_text("instance_name: cafe\n")
    env.write_text("SITE_AGENT_ADMIN_PASSWORD=pw\n")
    write_instance_r2_config(config, env, R2ProvisioningResult(
        account_id="a" * 32,
        bucket="hello-media",
        jurisdiction="default",
        access_key_id="access",
        secret_access_key="secret",
        token_name="token",
        bucket_created=True,
        token_created=True,
    ))
    assert "instance_name: cafe" in config.read_text()
    assert "SITE_AGENT_ADMIN_PASSWORD=pw" in env.read_text()
    assert "R2_ACCESS_KEY_ID=access" in env.read_text()
    assert oct(env.stat().st_mode & 0o777) == "0o600"

import base64
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("helloada_app_release_test", ROOT / "scripts/deploy-helloada-app.py")
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_helloada_app_queue_is_one_exact_release_or_null():
    assert release.validate_helloada_app_queue({"schema": 1, "release": None}) is None
    assert release.validate_helloada_app_queue({
        "schema": 1,
        "release": {"id": "20261006-helloada-app-1", "sha": "a" * 40},
    }) == {"id": "20261006-helloada-app-1", "sha": "a" * 40}
    for queue in (
        {"schema": 1, "release": {"id": "bad", "sha": "a" * 40, "force": True}},
        {"schema": 1, "release": {"id": "bad", "sha": "a" * 39}},
        {"schema": True, "release": None},
    ):
        with pytest.raises(ValueError):
            release.validate_helloada_app_queue(queue)


def test_helloada_app_registry_points_to_its_one_official_worker_and_secret_file():
    config = json.loads((ROOT / "deploy/helloada-app.json").read_text())
    assert config == release.HELLOADA_APP_CONFIG
    queue = json.loads((ROOT / "deploy/desired-helloada-app-release.json").read_text())
    assert queue["schema"] == 1
    release.validate_helloada_app_queue(queue)


@pytest.mark.skipif(not shutil.which("openssl"), reason="OpenSSL is required by the production release contract")
def test_helloada_release_requires_matching_rsa_pkcs8_and_site_agent_public_key(tmp_path):
    openssl = shutil.which("openssl")
    assert openssl
    private_der = subprocess.run(
        [openssl, "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-outform", "DER"],
        check=True,
        capture_output=True,
    ).stdout
    private_key = base64.urlsafe_b64encode(private_der).decode().rstrip("=")
    private_path = tmp_path / "secrets.json"
    private_path.write_text(json.dumps({"HELLOADA_HANDOFF_PRIVATE_KEY": private_key}))
    private_path.chmod(0o600)
    der_path = tmp_path / "private.der"
    der_path.write_bytes(private_der)
    der_path.chmod(0o600)
    public_der = subprocess.run(
        [openssl, "pkey", "-inform", "DER", "-in", str(der_path), "-pubout", "-outform", "DER"],
        check=True,
        capture_output=True,
    ).stdout
    public_key = base64.urlsafe_b64encode(public_der).decode().rstrip("=")
    api_env = tmp_path / "site-agent-api.env"
    api_env.write_text(f"HELLOADA_HANDOFF_PUBLIC_KEY={public_key}\n")
    config = {
        "privateKeyFile": str(private_path),
        "privateKeyName": "HELLOADA_HANDOFF_PRIVATE_KEY",
        "publicKeyName": "HELLOADA_HANDOFF_PUBLIC_KEY",
        "apiEnvFile": str(api_env),
    }

    assert release._load_handoff_secret(config, tmp_path) == private_key
    api_env.write_text("HELLOADA_HANDOFF_PUBLIC_KEY=" + "A" * 392 + "\n")
    with pytest.raises(RuntimeError, match="keys do not match"):
        release._load_handoff_secret(config, tmp_path)
    private_path.chmod(0o644)
    with pytest.raises(RuntimeError, match="mode-0600"):
        release._load_handoff_secret(config, tmp_path)


def test_release_source_hash_ignores_only_build_caches(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/page.tsx").write_text("owner source")
    (tmp_path / ".open-next/assets").mkdir(parents=True)
    (tmp_path / ".open-next/assets/worker.js").write_text("build output")
    first = release._source_tree_hash(tmp_path)
    (tmp_path / ".open-next/assets/worker.js").write_text("different build output")
    assert release._source_tree_hash(tmp_path) == first
    (tmp_path / "src/page.tsx").write_text("modified source")
    assert release._source_tree_hash(tmp_path) != first


def test_release_snapshot_contains_only_the_requested_helloada_commit(tmp_path):
    reconciler_spec = importlib.util.spec_from_file_location(
        "helloada_release_reconciler_test", ROOT / "scripts/reconcile-payload-releases.py",
    )
    assert reconciler_spec is not None and reconciler_spec.loader is not None
    reconciler = importlib.util.module_from_spec(reconciler_spec)
    reconciler_spec.loader.exec_module(reconciler)

    repository = tmp_path / "helloada"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    (repository / "src").mkdir()
    (repository / "src/page.tsx").write_text("first exact app source\n")
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "first"], check=True)
    first_sha = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True,
    ).strip()
    bare = tmp_path / "helloada.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repository), str(bare)], check=True)

    snapshot = reconciler.snapshot_helloada_source(bare, tmp_path / "releases", first_sha)
    assert (snapshot / ".helloada-source-sha").read_text().strip() == first_sha
    assert (snapshot / "src/page.tsx").read_text() == "first exact app source\n"
    assert reconciler.snapshot_helloada_source(bare, tmp_path / "releases", first_sha) == snapshot

    (snapshot / ".helloada-source-sha").write_text("b" * 40 + "\n")
    with pytest.raises(RuntimeError, match="snapshot identity mismatch"):
        reconciler.snapshot_helloada_source(bare, tmp_path / "releases", first_sha)

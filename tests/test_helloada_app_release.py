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


def test_helloada_source_is_materialized_only_in_a_job_workspace(tmp_path):
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

    first_workspace = tmp_path / "work" / "job-one"
    first_snapshot = reconciler.snapshot_helloada_source(bare, first_workspace / "source", first_sha)
    assert (first_snapshot / ".helloada-source-sha").read_text().strip() == first_sha
    assert (first_snapshot / "src/page.tsx").read_text() == "first exact app source\n"

    second_workspace = tmp_path / "work" / "job-two"
    second_snapshot = reconciler.snapshot_helloada_source(bare, second_workspace / "source", first_sha)
    assert first_snapshot != second_snapshot
    assert (second_snapshot / "src/page.tsx").read_text() == "first exact app source\n"
    assert not (tmp_path / "releases" / "helloada-sources").exists()

    with pytest.raises(RuntimeError, match="destination must be a new workspace path"):
        reconciler.snapshot_helloada_source(bare, first_snapshot, first_sha)


def test_legacy_helloada_build_cache_cleanup_removes_only_generated_caches(tmp_path):
    reconciler_spec = importlib.util.spec_from_file_location(
        "helloada_release_cache_cleanup_test", ROOT / "scripts/reconcile-payload-releases.py",
    )
    assert reconciler_spec is not None and reconciler_spec.loader is not None
    reconciler = importlib.util.module_from_spec(reconciler_spec)
    reconciler_spec.loader.exec_module(reconciler)

    (tmp_path / "helloada-sources" / ("a" * 40)).mkdir(parents=True)
    (tmp_path / "npm-cache" / "_cache").mkdir(parents=True)
    mirror = tmp_path / "helloada-control.git"
    mirror.mkdir()
    stale_control = tmp_path / "control" / ("b" * 40)
    stale_control.mkdir(parents=True)
    (stale_control / "old-source.txt").write_text("reproducible from GitHub")

    reconciler.cleanup_legacy_helloada_build_caches(tmp_path)
    reconciler.cleanup_stale_control_snapshots(tmp_path, "a" * 40)

    assert not (tmp_path / "helloada-sources").exists()
    assert not (tmp_path / "npm-cache").exists()
    assert not stale_control.exists()
    assert mirror.is_dir()


def test_app_upload_uses_its_own_variables_and_private_ephemeral_secrets(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    sha = 'a' * 40
    version = '12345678-1234-1234-1234-123456789abc'
    calls = []

    def run(command, cwd, env):
        secret_path = Path(command[command.index('--secrets-file') + 1])
        assert secret_path.stat().st_mode & 0o777 == 0o600
        assert json.loads(secret_path.read_text()) == {'HELLOADA_HANDOFF_PRIVATE_KEY': 'test-key'}
        assert cwd == source
        assert env == {'CLOUDFLARE_API_TOKEN': 'test-token'}
        calls.append((command, secret_path))
        return 'Uploaded Worker Version ID: ' + version

    monkeypatch.setattr(release._WORKER_RELEASE, 'run', run)
    result = release._upload_app_version(source, sha, 'app-test', tmp_path, 'test-key', {'CLOUDFLARE_API_TOKEN': 'test-token'})
    assert result == version
    command, secret_path = calls[0]
    assert command == [str(source / 'node_modules/.bin/opennextjs-cloudflare'), 'upload',
                       '--secrets-file', str(secret_path), '--var', 'HELLOADA_RELEASE_SHA:' + sha, '--tag', 'app-test']
    assert not secret_path.exists()


def test_app_upload_removes_temporary_secret_file_when_upload_fails(tmp_path, monkeypatch):
    paths = []

    def run(command, cwd, env):
        paths.append(Path(command[command.index('--secrets-file') + 1]))
        raise RuntimeError('upload failed')

    monkeypatch.setattr(release._WORKER_RELEASE, 'run', run)
    with pytest.raises(RuntimeError, match='upload failed'):
        release._upload_app_version(tmp_path, 'a' * 40, 'app-test', tmp_path, 'test-key', {})
    assert len(paths) == 1
    assert not paths[0].exists()


def test_helloada_app_requires_the_registered_screenshot_browser_binding(tmp_path, monkeypatch):
    config = release.HELLOADA_APP_CONFIG
    worker = {
        'name': config['worker'], 'main': '.open-next/worker.js',
        'site': config['siteUrl'], 'api': config['siteAgentUrl'],
        'd1': [config['d1']], 'r2': [config['r2Bucket']],
        'required': [config['privateKeyName']], 'browser': 'BROWSER',
    }
    package = {'packageManager': 'npm@11.13.0', 'scripts': {key: 'test' for key in ('test','lint','typecheck','build')}, 'dependencies': {}}
    (tmp_path / 'package.json').write_text(json.dumps(package))
    (tmp_path / 'package-lock.json').write_text(json.dumps({'packages': {'': {'dependencies': {}}}}))
    (tmp_path / 'src/app/api/health').mkdir(parents=True)
    (tmp_path / 'src/app/api/health/route.ts').write_text('test health route')
    monkeypatch.setattr(release, '_run', lambda *args: json.dumps(worker))
    assert release._validate_app_config(tmp_path, config, 'node', {}, '11.13.0') == worker
    worker['browser'] = None
    with pytest.raises(RuntimeError, match='contract differs'):
        release._validate_app_config(tmp_path, config, 'node', {}, '11.13.0')

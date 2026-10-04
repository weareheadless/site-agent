"""Release safety boundaries: provenance, canonical routes and immutable requests."""
import importlib.util
import json
import sys
import zipfile
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_script("deploy-payload-customer")
queue = load_script("reconcile-payload-releases")
api_deploy = load_script("deploy-site-agent-api")
SHA = "a" * 40
REGISTRY = json.loads((ROOT / "deploy/payload-customers.json").read_text())
TEMPLATE = ROOT / "src/site_agent/templates/next-payload"
TEMPLATE_MANIFEST = json.loads((TEMPLATE / "template-manifest.json").read_text())
CUSTOMER = {
    **REGISTRY["customers"]["oceanicvibes"],
    "migrationHead": TEMPLATE_MANIFEST["migrationHead"],
    "d1DatabaseId": "56d3f277-fbaf-43d4-91e5-b3a195653a05",
    "d1DatabaseName": "oceanicvibes-content",
    "r2BucketName": "helloada-oceanicvibes-media",
}


def test_committed_queue_is_valid():
    queue.validate_queue(json.loads((ROOT / "deploy/desired-releases.json").read_text()), REGISTRY)


def test_api_release_queue_requires_one_immutable_source_identity():
    api_deploy.validate_api_queue(json.loads((ROOT / "deploy/desired-api-release.json").read_text()))
    assert api_deploy.validate_api_queue({"schema": 1, "release": {"id": "api-1", "sha": SHA}}) == {
        "id": "api-1", "sha": SHA,
    }
    for invalid in (
        {"schema": 1, "release": {"id": "../escape", "sha": SHA}},
        {"schema": 1, "release": {"id": "api-1", "sha": "main"}},
        {"schema": 1, "release": {"id": "api-1", "sha": SHA, "command": "restart"}},
        {"schema": 2, "release": None},
        {"schema": True, "release": None},
    ):
        with pytest.raises(ValueError):
            api_deploy.validate_api_queue(invalid)


def test_api_wheel_dependency_audit_is_independent_of_pip_install_flags(tmp_path):
    def wheel_with_requirement(filename, requirement):
        wheel = tmp_path / filename
        requirements = "\n".join(f"Requires-Dist: {item}" for item in requirement.splitlines())
        metadata = (
            "Metadata-Version: 2.1\n"
            "Name: site-agent\n"
            "Version: 0.1.0\n"
            f"{requirements}\n"
        )
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("site_agent-0.1.0.dist-info/METADATA", metadata)
        return wheel

    env = {}
    log_path = tmp_path / "dependency-audit.log"
    installed = wheel_with_requirement(
        "installed.whl", "pip>=1\nhelloada-release-test-extra; extra == 'optional'"
    )
    api_deploy._verify_wheel_runtime_dependencies(
        sys.executable, installed, cwd=tmp_path, env=env, log_path=log_path
    )

    missing = wheel_with_requirement("missing.whl", "helloada-release-test-missing>=1")
    with pytest.raises(RuntimeError, match="helloada-release-test-missing"):
        api_deploy._verify_wheel_runtime_dependencies(
            sys.executable, missing, cwd=tmp_path, env=env, log_path=log_path
        )


def test_api_source_snapshot_is_immutable_and_sha_marked(tmp_path):
    import subprocess

    repository = tmp_path / "source"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.name", "Test"], check=True)
    (repository / "source.txt").write_text("first\n")
    subprocess.run(["git", "-C", str(repository), "add", "source.txt"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "first"], check=True)
    first_sha = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip()
    bare = tmp_path / "control.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repository), str(bare)], check=True)

    snapshot = queue.snapshot_api_source(bare, tmp_path / "releases", first_sha)
    assert (snapshot / ".site-agent-source-sha").read_text().strip() == first_sha
    assert (snapshot / "source.txt").read_text() == "first\n"
    assert queue.snapshot_api_source(bare, tmp_path / "releases", first_sha) == snapshot


def test_release_toolchain_is_exact_and_absolute():
    release.validate_toolchain_manifest(REGISTRY)
    for invalid in (
        {**REGISTRY, "npmVersion": "latest"},
        {**REGISTRY, "nodeVersion": "22"},
        {**REGISTRY, "npmBin": "npm"},
        {key: value for key, value in REGISTRY.items() if key != "npmVersion"},
    ):
        with pytest.raises(ValueError, match="toolchain"):
            release.validate_toolchain_manifest(invalid)


def test_schema_initialization_queue_is_exactly_registered_and_cannot_be_an_approval():
    registry = {"customers": {"demo": {"migrationHead": "c" * 64}}}
    request = {"id": "bootstrap-1", "sha": SHA, "initializeSchema": {"migrationHead": "c" * 64}}
    queue.validate_queue({"schema": 1, "releases": {"demo": request}}, registry)
    for invalid in (
        {**request, "initializeSchema": {"migrationHead": "d" * 64}},
        {**request, "approvalId": 7},
    ):
        with pytest.raises(ValueError, match="release|initialization"):
            queue.validate_queue({"schema": 1, "releases": {"demo": invalid}}, registry)


def test_schema_migration_queue_requires_exact_old_and_registered_target_heads():
    registry = {"customers": {"demo": {"migrationHead": "c" * 64}}}
    request = {"id": "schema-2", "sha": SHA, "schemaMigration": {
        "fromLedgerIdentity": "b" * 64, "targetMigrationHead": "c" * 64,
    }}
    queue.validate_queue({"schema": 1, "releases": {"demo": request}}, registry)
    for invalid in (
        {**request, "schemaMigration": {"fromLedgerIdentity": "b" * 64, "targetMigrationHead": "d" * 64}},
        {**request, "schemaMigration": {"fromLedgerIdentity": "c" * 64, "targetMigrationHead": "c" * 64}},
        {**request, "approvalId": 9},
        {**request, "schemaMigration": {"fromLedgerIdentity": "bad", "targetMigrationHead": "c" * 64}},
    ):
        with pytest.raises(ValueError, match="release|schema migration"):
            queue.validate_queue({"schema": 1, "releases": {"demo": invalid}}, registry)


def test_interrupted_receipts_are_terminal_even_after_the_queue_moves_on(tmp_path):
    interrupted = tmp_path / "runs/oceanicvibes/old-request/receipt.json"
    interrupted.parent.mkdir(parents=True)
    interrupted.write_text(json.dumps({"status": "running", "sourceSha": SHA, "stage": "build"}))
    completed = tmp_path / "runs/oceanicvibes/completed/receipt.json"
    completed.parent.mkdir(parents=True)
    completed.write_text(json.dumps({"status": "deployed", "sourceSha": SHA}))
    queue.mark_interrupted_runs(tmp_path)
    result = json.loads(interrupted.read_text())
    assert result["status"] == "interrupted" and result["finishedAt"]
    assert json.loads(completed.read_text())["status"] == "deployed"
    first = interrupted.read_bytes()
    queue.mark_interrupted_runs(tmp_path)
    assert interrupted.read_bytes() == first


@pytest.mark.parametrize("tenant,release_request", [
    ("unknown", {"id": "release-1", "sha": SHA}),
    ("oceanicvibes", {"id": "../escape", "sha": SHA}),
    ("oceanicvibes", {"id": "release-1", "sha": "main"}),
    ("oceanicvibes", {"id": "release-1", "sha": SHA, "command": "arbitrary"}),
])
def test_invalid_requests_never_execute(tenant, release_request):
    with pytest.raises(ValueError):
        queue.validate_queue({"schema": 1, "releases": {tenant: release_request}}, REGISTRY)


def test_external_customer_repository_is_rejected():
    customer = {**CUSTOMER, "repository": "https://github.com/stranger/site.git"}
    with pytest.raises(ValueError, match="official"):
        release.validate_target(customer, "oceanicvibes", SHA, "release-1")


def test_customer_without_a_committed_migration_identity_cannot_be_released():
    customer = {**REGISTRY["customers"]["oceanicvibes"], "migrationHead": ""}
    with pytest.raises(ValueError, match="migration-chain identity"):
        release.validate_target(customer, "oceanicvibes", SHA, "release-1")


@pytest.mark.parametrize("field", ["payloadAdmin", "payloadCore", "contentContract", "schemaRevision", "schemaIdentity"])
def test_release_registry_requires_exact_shared_payload_versions(field):
    customer = {**CUSTOMER, field: ""}
    with pytest.raises(ValueError, match="version|contract|schema"):
        release.validate_target(customer, "oceanicvibes", SHA, "release-1")


def test_worker_contract_requires_the_registered_tenant_and_all_shared_versions():
    customer = CUSTOMER
    worker = {"name": "oceanicvibes", "tenant": "oceanicvibes", "d1Count": 1, "r2Count": 1,
        "admin": customer["payloadAdmin"], "core": customer["payloadCore"],
        "contract": customer["contentContract"], "schemaRevision": customer["schemaRevision"],
        "schemaIdentity": customer["schemaIdentity"], "migrationHead": customer["migrationHead"],
        "d1DatabaseId": customer["d1DatabaseId"], "d1DatabaseName": customer["d1DatabaseName"],
        "r2BucketName": customer["r2BucketName"]}
    release.validate_worker_contract(worker, customer, "oceanicvibes")
    with pytest.raises(RuntimeError, match="shared Payload contract"):
        release.validate_worker_contract({**worker, "core": "0.0.9"}, customer, "oceanicvibes")


def test_promotion_uses_the_uploaded_version_and_rejects_ambiguous_output():
    version = "12345678-1234-1234-1234-123456789abc"
    output = f"Uploaded Worker\nWorker Version ID: {version}\n"
    assert release.uploaded_version_id(output) == version
    for invalid in ("Upload failed", output + output):
        with pytest.raises(RuntimeError, match="exactly one"):
            release.uploaded_version_id(invalid)


def test_same_admin_version_does_not_prove_new_source(monkeypatch):
    customer = CUSTOMER
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"ok": True, "tenant": "oceanicvibes", "payloadAdmin": customer["payloadAdmin"],
                               "payloadCore": customer["payloadCore"], "contentContract": customer["contentContract"],
                               "schemaRevision": customer["schemaRevision"], "schemaIdentity": customer["schemaIdentity"],
                               "migrationHead": customer["migrationHead"],
                               "releaseSha": "b" * 40}).encode()

    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="release SHA"):
        release.check_health("https://oceanicvibes.com/api/health", "oceanicvibes",
                             CUSTOMER, SHA)


@pytest.mark.parametrize("key,value", [
    ("payloadAdmin", "0.8.5"),
    ("payloadCore", "0.0.9"),
    ("contentContract", "helloada-content-v0"),
    ("schemaRevision", 99),
    ("schemaIdentity", "f" * 64),
])
def test_live_health_requires_the_exact_shared_payload_contract(monkeypatch, key, value):
    customer = CUSTOMER
    body = {"ok": True, "tenant": "oceanicvibes", "payloadAdmin": customer["payloadAdmin"],
            "payloadCore": customer["payloadCore"], "contentContract": customer["contentContract"],
            "schemaRevision": customer["schemaRevision"], "schemaIdentity": customer["schemaIdentity"],
            "migrationHead": customer["migrationHead"],
            "releaseSha": SHA}
    body[key] = value

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps(body).encode()

    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="shared Payload contract"):
        release.check_health("https://oceanicvibes.com/api/health", "oceanicvibes",
                             CUSTOMER, SHA)


def artifact(tmp_path):
    customer = CUSTOMER
    shutil.copytree(TEMPLATE / "src/migrations", tmp_path / "src/migrations")
    files = {
        "payload.config.ts": "import { createHelloAdaSchema } from '@weareheadless/helloada-payload-core/schema';\nconst schema = createHelloAdaSchema(guard);\n",
        ".open-next/worker.js": "import './server-functions/default/handler.mjs'",
        ".open-next/server-functions/default/handler.mjs": "route('/growth/contract')",
        ".next/server/app-paths-manifest.json": json.dumps({
            "/api/helloada/[...path]/route": "helloada.js",
            "/api/workspace/content/route": "content.js",
            "/api/workspace/global/route": "global.js",
            "/api/workspace/media/route": "media.js",
            "/api/health/route": "health.js",
        }),
        "node_modules/@weareheadless/helloada-payload-admin/package.json": json.dumps({"version": customer["payloadAdmin"]}),
        "node_modules/@weareheadless/helloada-payload-core/package.json": json.dumps({"version": customer["payloadCore"]}),
        "helloada-content-contract.json": json.dumps({"contract": customer["contentContract"]}),
        "template-manifest.json": json.dumps(TEMPLATE_MANIFEST),
        ".open-next/assets/helloada-release.json": json.dumps({"sourceSha": SHA,
            "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
            "contentContract": customer["contentContract"], "schemaRevision": customer["schemaRevision"],
            "schemaIdentity": customer["schemaIdentity"], "migrationHead": customer["migrationHead"]}),
    }
    for name, value in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return tmp_path


def test_checks_compiled_server_instead_of_thin_worker_entry(tmp_path):
    checkout = artifact(tmp_path)
    hashes = release.inspect_artifact(checkout, CUSTOMER, SHA)
    assert "server-functions/default/handler.mjs" in hashes


def test_release_rejects_a_tenant_local_payload_schema(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / "payload.config.ts").write_text("export default buildConfig({ collections: [TenantPages] });\n")
    with pytest.raises(RuntimeError, match="shared site-agent schema factory"):
        release.inspect_artifact(checkout, CUSTOMER, SHA)


def test_stale_release_marker_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / ".open-next/assets/helloada-release.json").write_text(json.dumps({"sourceSha": "b" * 40}))
    with pytest.raises(RuntimeError, match="marker"):
        release.inspect_artifact(checkout, CUSTOMER, SHA)


def test_shared_core_version_must_match_release_registry(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / "node_modules/@weareheadless/helloada-payload-core/package.json").write_text(json.dumps({"version": "0.0.9"}))
    with pytest.raises(RuntimeError, match="core version"):
        release.inspect_artifact(checkout, CUSTOMER, SHA)


def test_browser_bridge_does_not_substitute_for_service_content_gateway(tmp_path):
    checkout = artifact(tmp_path)
    path = checkout / ".next/server/app-paths-manifest.json"
    routes = json.loads(path.read_text())
    del routes["/api/workspace/content/route"]
    path.write_text(json.dumps(routes))
    with pytest.raises(RuntimeError, match="service content"):
        release.inspect_artifact(checkout, CUSTOMER, SHA)


def test_obsolete_route_in_built_manifest_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    path = checkout / ".next/server/app-paths-manifest.json"
    routes = json.loads(path.read_text())
    routes["/api/atelier/ada/route"] = "old.js"
    path.write_text(json.dumps(routes))
    with pytest.raises(RuntimeError, match="obsolete"):
        release.inspect_artifact(checkout, CUSTOMER, SHA)


def test_empty_tenant_database_requires_explicit_bootstrap_initialization(monkeypatch):
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: ([], []))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *args: {"PAYLOAD_SECRET": "secret"})
    with pytest.raises(RuntimeError, match="explicit bootstrap initialization"):
        release.enforce_payload_migrations(TEMPLATE, CUSTOMER, {}, None, None, {}, {}, "oceanicvibes", lambda _: None)
    assert calls == []


def test_existing_database_never_receives_a_schema_mutation(monkeypatch):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], expected))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *args: pytest.fail("existing D1 must not load migration secrets"))
    result = release.enforce_payload_migrations(TEMPLATE, CUSTOMER, {}, None, None, {}, {}, "oceanicvibes", lambda _: None)
    assert result == expected and calls == []


def test_payload_migration_uses_the_pinned_package_script():
    package = json.loads((TEMPLATE / "package.json").read_text())
    assert release.payload_migration_command(REGISTRY) == [
        str(Path(REGISTRY["npmBin"]) / "npm"), "run", "payload", "--", "migrate",
    ]
    assert "PAYLOAD_CLI=1" in package["scripts"]["payload"]


def test_new_site_initialization_is_exact_and_idempotent(monkeypatch):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    calls = []
    queries = iter([([], []), (["pages", "payload_migrations"], expected)])
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: next(queries))
    monkeypatch.setattr(release, "run", lambda command, *args: calls.append(command) or "migration complete")
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *args: {"PAYLOAD_SECRET": "secret"})
    stages = []
    result = release.enforce_payload_migrations(
        TEMPLATE, CUSTOMER, {}, CUSTOMER["migrationHead"], None, {}, REGISTRY, "oceanicvibes", stages.append,
    )
    assert result == expected
    assert stages == ["initialize-schema"]
    assert calls == [[str(Path(REGISTRY["npmBin"]) / "npm"), "run", "payload", "--", "migrate"]]


def test_tenant_token_is_mapped_to_the_canonical_worker_binding(tmp_path):
    tenant = "atelier-harmonie"
    tenant_token_name = "PROVISIONED_ATELIER_HARMONIE_TOKEN"
    provisioned_root = tmp_path / "websites"
    tenant_dir = provisioned_root / tenant
    tenant_dir.mkdir(parents=True)
    config_path = tenant_dir / "config.yaml"
    config_path.write_text(f"instance_name: {tenant}\n")
    (tenant_dir / "tenant.env").write_text(
        f"PAYLOAD_SECRET=payload-secret-for-test\n"
        f"{tenant_token_name}=site-agent-token-for-test\n"
    )
    (provisioned_root / "tenants.json").write_text(json.dumps({
        tenant: {"config_path": str(config_path), "api_token_env": tenant_token_name},
    }))
    host_config = tmp_path / "host.yaml"
    host_config.write_text(f"workspace_api:\n  provisioned_root: {provisioned_root}\n")

    secrets = release.tenant_runtime_secrets(
        {"connectionGate": {"config": str(host_config)}}, tenant,
    )

    assert secrets == {
        "PAYLOAD_SECRET": "payload-secret-for-test",
        "HELLOADA_SITE_AGENT_TOKEN": "site-agent-token-for-test",
    }



def test_worker_secrets_file_is_private_and_contains_only_explicit_bindings(tmp_path):
    expected = {
        "PAYLOAD_SECRET": "payload-secret-for-test",
        "HELLOADA_SITE_AGENT_TOKEN": "site-agent-token-for-test",
    }
    path = release.worker_secrets_file(tmp_path, expected)
    try:
        assert path.stat().st_mode & 0o777 == 0o600
        assert json.loads(path.read_text()) == expected
    finally:
        path.unlink(missing_ok=True)


def test_worker_upload_bundles_secrets_with_immutable_candidate_and_cleans_file(monkeypatch, tmp_path):
    version_id = "01234567-89ab-cdef-0123-456789abcdef"
    secrets = {"PAYLOAD_SECRET": "payload-secret-for-test"}
    commands = []

    def fake_run(command, cwd, env):
        commands.append(command)
        return f"Worker Version ID: {version_id}\n"

    monkeypatch.setattr(release, "run", fake_run)
    result = release.upload_worker_version(TEMPLATE, SHA, "release-1", tmp_path, secrets, {})

    assert result == version_id
    command = commands[0]
    secret_path = Path(command[command.index("--secrets-file") + 1])
    assert command == [
        str(TEMPLATE / "node_modules/.bin/opennextjs-cloudflare"), "upload",
        "--secrets-file", str(secret_path), "--var", f"HELLOADA_RELEASE_SHA:{SHA}",
        "--tag", "release-1",
    ]
    assert not secret_path.exists()
    assert "payload-secret-for-test" not in " ".join(command)


def test_worker_upload_cleans_secrets_file_when_upload_fails(monkeypatch, tmp_path):
    commands = []

    def fake_run(command, cwd, env):
        commands.append(command)
        raise RuntimeError("upload failed")

    monkeypatch.setattr(release, "run", fake_run)
    with pytest.raises(RuntimeError, match="upload failed"):
        release.upload_worker_version(
            TEMPLATE, SHA, "release-1", tmp_path,
            {"PAYLOAD_SECRET": "payload-secret-for-test"}, {},
        )

    secret_path = Path(commands[0][commands[0].index("--secrets-file") + 1])
    assert not secret_path.exists()


def test_tenant_secret_mapping_rejects_a_noncanonical_worker_binding(tmp_path, monkeypatch):
    tenant = "oceanicvibes"
    token_name = "PROVISIONED_OCEANICVIBES_TOKEN"
    provisioned_root = tmp_path / "websites"
    tenant_dir = provisioned_root / tenant
    tenant_dir.mkdir(parents=True)
    config_path = tenant_dir / "config.yaml"
    config_path.write_text(f"instance_name: {tenant}\n")
    (tenant_dir / "tenant.env").write_text(
        f"PAYLOAD_SECRET=payload-secret-for-test\n{token_name}=site-agent-token-for-test\n"
    )
    (provisioned_root / "tenants.json").write_text(json.dumps({
        tenant: {"config_path": str(config_path), "api_token_env": token_name},
    }))
    host_config = tmp_path / "host.yaml"
    host_config.write_text(f"workspace_api:\n  provisioned_root: {provisioned_root}\n")
    worker_manifest = json.loads((TEMPLATE / "template-manifest.json").read_text())
    monkeypatch.setattr(release, "ROOT", tmp_path)
    (tmp_path / "src/site_agent/templates/next-payload").mkdir(parents=True)
    (tmp_path / "src/site_agent/templates/next-payload/template-manifest.json").write_text(
        json.dumps({**worker_manifest, "workerTokenEnv": "TENANT_SPECIFIC_TOKEN"})
    )

    with pytest.raises(RuntimeError, match="canonical Worker token binding"):
        release.tenant_runtime_secrets(
            {"connectionGate": {"config": str(host_config)}}, tenant,
        )


def test_partial_or_unexpected_database_never_triggers_a_migration(monkeypatch):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["users", "payload_migrations"], []))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    with pytest.raises(RuntimeError, match="non-empty D1"):
        release.enforce_payload_migrations(
            TEMPLATE, CUSTOMER, {}, CUSTOMER["migrationHead"], None, {}, {}, "oceanicvibes", lambda _: None,
        )
    assert calls == []


def test_existing_tenant_migration_requires_the_exact_nonempty_ledger_prefix(monkeypatch):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    applied = expected[:1]
    from_head = release.migration_ledger_head(applied)
    calls, stages = [], []
    queries = iter([
        (["pages", "payload_migrations"], applied),
        (["pages", "payload_migrations"], expected),
    ])
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: next(queries))
    monkeypatch.setattr(release, "run", lambda command, *args: calls.append(command) or "migration complete")
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *args: {"PAYLOAD_SECRET": "secret"})

    result = release.enforce_payload_migrations(
        TEMPLATE, CUSTOMER, {}, None, from_head, {}, REGISTRY, "oceanicvibes", stages.append,
    )

    assert result == expected
    assert stages == ["migrate-schema"]
    assert calls == [[str(Path(REGISTRY["npmBin"]) / "npm"), "run", "payload", "--", "migrate"]]


@pytest.mark.parametrize("applied,requested_head", [
    ([], release.migration_ledger_head([])),
    (["unknown"], release.migration_ledger_head(["unknown"])),
    ([TEMPLATE_MANIFEST["migrations"][0]["name"]], "f" * 64),
])
def test_existing_tenant_migration_rejects_missing_or_changed_ledger(monkeypatch, applied, requested_head):
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], applied))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    with pytest.raises(RuntimeError, match="migration|ledger|existing tenant"):
        release.enforce_payload_migrations(
            TEMPLATE, CUSTOMER, {}, None, requested_head, {}, {}, "oceanicvibes", lambda _: None,
        )
    assert calls == []


def test_existing_tenant_migration_refuses_to_mutate_without_an_explicit_request(monkeypatch):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], expected[:1]))
    monkeypatch.setattr(release, "run", lambda *args: pytest.fail("unexpected Payload migration"))
    with pytest.raises(RuntimeError, match="explicit exact schema-migration request"):
        release.enforce_payload_migrations(
            TEMPLATE, CUSTOMER, {}, None, None, {}, {}, "oceanicvibes", lambda _: None,
        )


def test_completed_schema_migration_request_is_idempotent(monkeypatch):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    from_head = release.migration_ledger_head(expected[:1])
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], expected))
    monkeypatch.setattr(release, "run", lambda *args: pytest.fail("completed migration must not rerun"))
    assert release.enforce_payload_migrations(
        TEMPLATE, CUSTOMER, {}, None, from_head, {}, {}, "oceanicvibes", lambda _: None,
    ) == expected


def promoted_receipt(tmp_path):
    customer = CUSTOMER
    archive = tmp_path / "open-next.tar.gz"
    archive.write_bytes(b"immutable-artifact")
    result = {"tenant": "oceanicvibes", "sourceSha": SHA, "releaseId": "release-1",
              "worker": customer["worker"], "repository": customer["repository"],
              "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
              "contentContract": customer["contentContract"], "schemaRevision": customer["schemaRevision"],
              "schemaIdentity": customer["schemaIdentity"], "migrationHead": customer["migrationHead"],
              "status": "failed", "stage": "verify-connection", "error": "connection failed",
              "deployment": {"id": "deployment-1"}, "uploadedVersion": "version-1",
              "archiveSha256": release.hashlib.sha256(archive.read_bytes()).hexdigest()}
    (tmp_path / "receipt.json").write_text(json.dumps(result))
    return result, customer


def test_read_only_continuation_preserves_prior_failure(tmp_path):
    _, customer = promoted_receipt(tmp_path)
    result = release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer)
    assert result["status"] == "running" and "error" not in result
    assert result["verificationHistory"][-1]["error"] == "connection failed"


@pytest.mark.parametrize("changed", ["identity", "unpromoted", "artifact"])
def test_read_only_continuation_rejects_unproven_release(tmp_path, changed):
    result, customer = promoted_receipt(tmp_path)
    if changed == "identity":
        result["sourceSha"] = "b" * 40
    elif changed == "unpromoted":
        result["stage"] = "upload"
    else:
        (tmp_path / "open-next.tar.gz").write_bytes(b"changed")
    (tmp_path / "receipt.json").write_text(json.dumps(result))
    with pytest.raises(ValueError):
        release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer)


def test_edge_convergence_repeats_identical_checks_without_deploying(monkeypatch):
    result = {"tenant": "oceanicvibes", "sourceSha": SHA, "uploadedVersion": "version-1"}
    customer = CUSTOMER
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "version-1"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: {"ok": True})
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    commands = []

    def run(command, *args):
        commands.append(command)
        if len(commands) == 1:
            raise RuntimeError("connection gate failed")

    monkeypatch.setattr(release, "run", run)
    release.verify_live(result, customer, REGISTRY, {}, {}, lambda name: result.update(stage=name))
    assert commands[0] == commands[1] and len(commands) == 2
    assert commands[0][1].endswith("check-helloada-connections.py")
    assert result["connectionVerifiedAt"] and len(result["gateAttempts"]) == 1


def test_read_only_gate_rejects_a_different_production_version(monkeypatch):
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "other-version"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: pytest.fail("must reject before health"))
    with pytest.raises(RuntimeError, match="exact uploaded"):
        release.verify_live({"uploadedVersion": "version-1"}, {}, {}, {}, {}, lambda _: None)


def test_failed_connection_gate_is_bounded_and_remains_failed(monkeypatch):
    result = {"tenant": "oceanicvibes", "sourceSha": SHA, "uploadedVersion": "version-1"}
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "version-1"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: {"ok": True})
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    monkeypatch.setattr(release, "run", lambda *args: (_ for _ in ()).throw(RuntimeError("gate failed")))
    with pytest.raises(RuntimeError, match="gate failed"):
        release.verify_live(result, CUSTOMER, REGISTRY,
                            {}, {}, lambda name: result.update(stage=name))
    assert len(result["gateAttempts"]) == 12 and "connectionVerifiedAt" not in result

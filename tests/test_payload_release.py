"""Release safety boundaries: provenance, canonical routes and immutable requests."""
import importlib.util
import hashlib
import json
import sys
import zipfile
import shutil
from pathlib import Path

import pytest
from site_agent.application.release_queue import ReleaseQueueError, customer_release_identity
from site_agent.site_scaffold import initialize_managed_site

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
    "payloadAdmin": TEMPLATE_MANIFEST["payloadAdmin"],
    "payloadCore": TEMPLATE_MANIFEST["payloadCore"],
    "contentContract": TEMPLATE_MANIFEST["contentContract"],
    "schemaRevision": TEMPLATE_MANIFEST["schemaRevision"],
    "schemaIdentity": TEMPLATE_MANIFEST["schemaIdentity"],
    "migrationHead": TEMPLATE_MANIFEST["migrationHead"],
    "d1DatabaseId": "56d3f277-fbaf-43d4-91e5-b3a195653a05",
    "d1DatabaseName": "oceanicvibes-content",
    "mailflareD1DatabaseId": "f6d3f277-fbaf-43d4-91e5-b3a195653a05",
    "mailflareD1DatabaseName": "oceanicvibes-mail",
    "r2BucketName": "helloada-oceanicvibes-media",
    "privateEmailR2BucketName": "helloada-oceanicvibes-email",
    "mailflareR2BucketName": "helloada-oceanicvibes-mail-files",
    "mailflareInboundQueueName": "helloada-oceanicvibes-mail-inbound",
    "mailflareOutboundQueueName": "helloada-oceanicvibes-mail-outbound",
    "mailflareAgentQueueName": "helloada-oceanicvibes-mail-agent",
}
CANDIDATE_CUSTOMER = {
    **CUSTOMER,
    "payloadAdmin": TEMPLATE_MANIFEST["payloadAdmin"],
    "payloadCore": TEMPLATE_MANIFEST["payloadCore"],
    "contentContract": TEMPLATE_MANIFEST["contentContract"],
    "schemaRevision": TEMPLATE_MANIFEST["schemaRevision"],
    "schemaIdentity": TEMPLATE_MANIFEST["schemaIdentity"],
    "migrationHead": TEMPLATE_MANIFEST["migrationHead"],
}

WORKER_CONFIG = {
    "name": CUSTOMER["worker"],
    "tenant": "oceanicvibes",
    "admin": CUSTOMER["payloadAdmin"],
    "core": CUSTOMER["payloadCore"],
    "contract": CUSTOMER["contentContract"],
    "schemaRevision": CUSTOMER["schemaRevision"],
    "schemaIdentity": CUSTOMER["schemaIdentity"],
    "migrationHead": CUSTOMER["migrationHead"],
    "d1Count": 2,
    "d1Binding": "D1",
    "d1DatabaseId": CUSTOMER["d1DatabaseId"],
    "d1DatabaseName": CUSTOMER["d1DatabaseName"],
    "d1Bindings": [
        {"binding": "D1", "databaseId": CUSTOMER["d1DatabaseId"], "databaseName": CUSTOMER["d1DatabaseName"]},
        {"binding": "MAILFLARE_DB", "databaseId": CUSTOMER["mailflareD1DatabaseId"],
         "databaseName": CUSTOMER["mailflareD1DatabaseName"]},
    ],
    "mailflareD1DatabaseId": CUSTOMER["mailflareD1DatabaseId"],
    "mailflareD1DatabaseName": CUSTOMER["mailflareD1DatabaseName"],
    "mailflareMigrationsDir": ".mailflare/migrations",
    "r2Count": 3,
    "r2Binding": "R2",
    "r2BucketName": CUSTOMER["r2BucketName"],
    "privateEmailR2BucketName": CUSTOMER["privateEmailR2BucketName"],
    "mailflareR2BucketName": CUSTOMER["mailflareR2BucketName"],
    "r2Bindings": [
        {"binding": "R2", "bucketName": CUSTOMER["r2BucketName"]},
        {"binding": "PRIVATE_EMAIL", "bucketName": CUSTOMER["privateEmailR2BucketName"]},
        {"binding": "MAILFLARE_BUCKET", "bucketName": CUSTOMER["mailflareR2BucketName"]},
    ],
    "queueProducerCount": 3,
    "queueConsumerCount": 3,
    "mailflareQueueNames": {
        "MAILFLARE_INBOUND_QUEUE": CUSTOMER["mailflareInboundQueueName"],
        "MAILFLARE_OUTBOUND_QUEUE": CUSTOMER["mailflareOutboundQueueName"],
        "MAILFLARE_AGENT_QUEUE": CUSTOMER["mailflareAgentQueueName"],
    },
    "queues": {
        "consumers": [
            {"queue": CUSTOMER["mailflareInboundQueueName"], "max_batch_size": 5, "max_retries": 3,
             "max_concurrency": 1},
            {"queue": CUSTOMER["mailflareOutboundQueueName"], "max_batch_size": 5, "max_retries": 3,
             "max_concurrency": 1},
            {"queue": CUSTOMER["mailflareAgentQueueName"], "max_batch_size": 1, "max_retries": 3,
             "max_concurrency": 1},
        ],
    },
    "sendEmailBinding": True,
    "sendEmailBindingCount": 1,
    "rateLimitBindings": [
        {"name": "HELLOADA_FORM_RATE_LIMIT", "namespaceId": "2701"},
        {"name": "MAILFLARE_BOOKING_RATE_LIMIT", "namespaceId": "2703"},
        {"name": "MAILFLARE_LOGIN_RATE_LIMIT", "namespaceId": "2704"},
        {"name": "MAILFLARE_AGENT_RATE_LIMIT", "namespaceId": "2705"},
    ],
    "durableObjectBindings": [{"name": "MAILFLARE_REALTIME", "className": "RealtimeHub"}],
    "durableObjectMigrations": [{"tag": "v1", "newSqliteClasses": ["RealtimeHub"]}],
    "aiBinding": "MAILFLARE_AI",
    "turnstileSiteKey": None,
    "turnstileSecretInVars": False,
    "publicDomains": ["oceanicvibes.com"],
    "crons": ["*/5 * * * *", "0 2 * * *"],
    "main": "worker.ts",
    "handlers": ["fetch", "email", "queue", "scheduled"],
    "compatibilityDate": "2025-08-15",
    "compatibilityFlags": ["nodejs_compat", "global_fetch_strictly_public"],
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


def test_api_deploy_runs_the_snapshot_runtime_config_gate_before_service_activation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "deploy").mkdir(parents=True)
    (source / "scripts").mkdir()
    config_path = "/SOCIAL/configs/site-agent-api/config.yaml"
    (source / "deploy/payload-customers.json").write_text(json.dumps({
        "connectionGate": {"config": config_path},
    }))
    validator = source / "scripts/sync-provisioned-tenant-configs.py"
    validator.write_text("# exact snapshot validator\n")
    calls = []
    monkeypatch.setattr(api_deploy, "_run", lambda *args, **kwargs: calls.append((args, kwargs)))

    api_deploy._runtime_config_preflight(source, "/venv/bin/python", tmp_path / "deploy.log")

    command, options = calls[0][0][0], calls[0][1]
    assert command[:3] == ["/venv/bin/python", str(validator), "--config"]
    assert command[3:] == [config_path, "--manifest", str(source / "deploy/payload-customers.json"), "--validate"]
    assert options["cwd"] == source
    assert options["env"]["PYTHONPATH"] == str(source / "src")


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


def test_customer_release_uses_serial_npm_fetches_for_integrity_cache():
    assert release.NPM_INSTALL_ARGUMENTS == (
        "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline", "--maxsockets=1",
    )


def test_payload_build_requires_disk_headroom(monkeypatch, tmp_path):
    class DiskUsage:
        free = release.MINIMUM_BUILD_FREE_BYTES - 1

    monkeypatch.setattr(release.shutil, "disk_usage", lambda _: DiskUsage())
    with pytest.raises(RuntimeError, match="GiB free"):
        release.ensure_build_capacity(tmp_path)


def test_schema_initialization_queue_is_exactly_registered_and_cannot_be_an_approval():
    registry = {"customers": {"demo": {"migrationHead": "c" * 64, "sharedRuntimeUpdate": "manual"}}}
    request = {"id": "bootstrap-1", "sha": SHA, "initializeSchema": {"migrationHead": "c" * 64}}
    queue.validate_queue({"schema": 1, "releases": {"demo": request}}, registry)
    for invalid in (
        {**request, "initializeSchema": {"migrationHead": "d" * 64}},
        {**request, "approvalId": 7},
    ):
        with pytest.raises(ValueError, match="release|initialization"):
            queue.validate_queue({"schema": 1, "releases": {"demo": invalid}}, registry)


def test_release_queue_operation_selects_the_matching_content_gate():
    bootstrap_request = {
        "id": "bootstrap-1",
        "sha": SHA,
        "initializeSchema": {"migrationHead": CUSTOMER["migrationHead"]},
    }
    assert queue.release_purpose_for_request(bootstrap_request) == "workspace-bootstrap"
    assert queue.release_purpose_for_request({"id": "release-1", "sha": SHA}) == "website"


def test_release_purpose_is_bound_to_the_exact_initialization_operation():
    bootstrap_head = CUSTOMER["migrationHead"]
    release.require_release_purpose("workspace-bootstrap", bootstrap_head)
    release.require_release_purpose("website", None)
    with pytest.raises(ValueError, match="does not match"):
        release.require_release_purpose("website", bootstrap_head)
    with pytest.raises(ValueError, match="exact"):
        release.require_release_purpose("workspace-bootstrap", "not-a-head")


def test_workspace_bootstrap_contract_requires_exact_registered_schema_and_ledger(tmp_path):
    shutil.copyfile(TEMPLATE / "template-manifest.json", tmp_path / "template-manifest.json")
    manifest = json.loads((TEMPLATE / "template-manifest.json").read_text())
    migrations = [item["name"] for item in manifest["migrations"]]
    receipt = {"verifiedMigrationHead": manifest["migrationHead"], "appliedMigrations": migrations}
    release.verify_workspace_bootstrap_contract(
        tmp_path, receipt, CUSTOMER, CUSTOMER["migrationHead"],
    )
    with pytest.raises(RuntimeError, match="exact registered Payload schema"):
        release.verify_workspace_bootstrap_contract(
            tmp_path, {**receipt, "appliedMigrations": migrations[:-1]}, CUSTOMER, CUSTOMER["migrationHead"],
        )


def test_schema_migration_queue_requires_exact_old_and_registered_target_heads():
    registry = {"customers": {"demo": {"migrationHead": "c" * 64, "sharedRuntimeUpdate": "manual"}}}
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
    for name in ("source", "temporary"):
        (interrupted.parent / name).mkdir()
        (interrupted.parent / name / "partial").write_text("temporary")
    (interrupted.parent / "open-next.tar.gz").write_text("temporary")
    interrupted.write_text(json.dumps({
        "status": "running", "sourceSha": SHA, "stage": "build",
        "tenant": "oceanicvibes", "worker": CUSTOMER["worker"],
    }))
    completed = tmp_path / "runs/oceanicvibes/completed/receipt.json"
    completed.parent.mkdir(parents=True)
    completed.write_text(json.dumps({"status": "deployed", "sourceSha": SHA}))
    queue.mark_interrupted_runs(tmp_path)
    result = json.loads(interrupted.read_text())
    assert result["status"] == "interrupted" and result["finishedAt"]
    assert not (interrupted.parent / "source").exists()
    assert not (interrupted.parent / "temporary").exists()
    assert not (interrupted.parent / "open-next.tar.gz").exists()
    assert json.loads(completed.read_text())["status"] == "deployed"
    first = interrupted.read_bytes()
    queue.mark_interrupted_runs(tmp_path)
    assert interrupted.read_bytes() == first


def test_stale_build_workspaces_are_removed_only_from_the_dedicated_root(tmp_path):
    work_root = tmp_path / "work"
    workspace = work_root / "oceanicvibes-release-123"
    workspace.mkdir(parents=True)
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "partial").write_text("temporary")
    receipt = tmp_path / "runs" / "oceanicvibes" / "completed" / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"status": "deployed"}))

    queue.cleanup_stale_release_workspaces(tmp_path)

    assert list(work_root.iterdir()) == []
    assert json.loads(receipt.read_text())["status"] == "deployed"


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


def test_customer_release_identity_serializes_the_canonical_owner_repository(tmp_path):
    site_dir = initialize_managed_site(tmp_path / "site")
    manifest = json.loads((site_dir / "template-manifest.json").read_text())
    wrangler_path = site_dir / "wrangler.jsonc"
    wrangler = json.loads(wrangler_path.read_text())
    wrangler["name"] = "helloada-demo"
    wrangler["d1_databases"] = [
        {"binding": "D1", "database_id": "56d3f277-fbaf-43d4-91e5-b3a195653a05", "database_name": "helloada-demo"},
        {"binding": "MAILFLARE_DB", "database_id": "66d3f277-fbaf-43d4-91e5-b3a195653a05", "database_name": "helloada-demo-mail", "migrations_dir": ".mailflare/migrations"},
    ]
    wrangler["r2_buckets"] = [
        {"binding": "R2", "bucket_name": "helloada-demo-media"},
        {"binding": "PRIVATE_EMAIL", "bucket_name": "helloada-demo-email"},
        {"binding": "MAILFLARE_BUCKET", "bucket_name": "helloada-demo-mail-files"},
    ]
    wrangler["vars"].update({
        "HELLOADA_MAILFLARE_INBOUND_QUEUE_NAME": "helloada-demo-mail-inbound",
        "HELLOADA_MAILFLARE_OUTBOUND_QUEUE_NAME": "helloada-demo-mail-outbound",
        "HELLOADA_MAILFLARE_AGENT_QUEUE_NAME": "helloada-demo-mail-agent",
    })
    wrangler["queues"] = {
        "producers": [
            {"binding": "MAILFLARE_INBOUND_QUEUE", "queue": "helloada-demo-mail-inbound"},
            {"binding": "MAILFLARE_OUTBOUND_QUEUE", "queue": "helloada-demo-mail-outbound"},
            {"binding": "MAILFLARE_AGENT_QUEUE", "queue": "helloada-demo-mail-agent"},
        ],
        "consumers": [
            {"queue": "helloada-demo-mail-inbound"},
            {"queue": "helloada-demo-mail-outbound"},
            {"queue": "helloada-demo-mail-agent"},
        ],
    }
    wrangler["durable_objects"] = {"bindings": [{"name": "MAILFLARE_REALTIME", "class_name": "RealtimeHub"}]}
    wrangler["migrations"] = [{"tag": "v1", "new_sqlite_classes": ["RealtimeHub"]}]
    wrangler["ai"] = {"binding": "MAILFLARE_AI"}
    wrangler["triggers"] = {"crons": ["*/5 * * * *", "0 2 * * *"]}
    wrangler_path.write_text(json.dumps(wrangler), encoding="utf-8")
    config = {
        "instance_name": "demo",
        "site": {
            "website_present": False,
            "repository": "weareheadless/helloada-demo",
            "public_url": "https://helloada-demo.weareheadless.workers.dev",
            "source_deployment": {
                "worker_name": "helloada-demo",
                "clone_path": str(site_dir),
            },
            "payload": {"contract": {
                "adminVersion": manifest["payloadAdmin"],
                "coreVersion": manifest["payloadCore"],
                "contract": manifest["contentContract"],
                "schemaRevision": manifest["schemaRevision"],
                "schemaIdentity": manifest["schemaIdentity"],
                "migrationHead": manifest["migrationHead"],
            }},
        },
    }

    tenant, customer = customer_release_identity(config)

    assert tenant == "demo"
    assert customer["repository"] == "https://github.com/weareheadless/helloada-demo.git"
    assert customer["websitePresent"] is False
    assert customer["privateEmailR2BucketName"] == "helloada-demo-email"
    assert customer["mailflareD1DatabaseName"] == "helloada-demo-mail"
    assert customer["mailflareR2BucketName"] == "helloada-demo-mail-files"
    assert customer["mailflareInboundQueueName"] == "helloada-demo-mail-inbound"
    assert customer["mailflareOutboundQueueName"] == "helloada-demo-mail-outbound"
    assert customer["mailflareAgentQueueName"] == "helloada-demo-mail-agent"
    config["ada_journey"] = {"website_present": True}
    assert customer_release_identity(config)[1]["websitePresent"] is True
    config.pop("ada_journey")
    config["site"].pop("website_present")
    with pytest.raises(ReleaseQueueError, match="website-present state must be explicit"):
        customer_release_identity(config)
    config["site"]["website_present"] = False

    for invalid_repository in (
        "https://github.com/weareheadless/helloada-demo.git",
        "another-owner/helloada-demo",
    ):
        config["site"]["repository"] = invalid_repository
        with pytest.raises(ReleaseQueueError, match="official owner/repository"):
            customer_release_identity(config)


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
    worker = {
        **WORKER_CONFIG,
        "name": customer["worker"],
        "tenant": "oceanicvibes",
        "admin": customer["payloadAdmin"],
        "core": customer["payloadCore"],
        "contract": customer["contentContract"],
        "schemaRevision": customer["schemaRevision"],
        "schemaIdentity": customer["schemaIdentity"],
        "migrationHead": customer["migrationHead"],
        "d1Count": 2,
        "d1Binding": "D1",
        "d1DatabaseId": customer["d1DatabaseId"],
        "d1DatabaseName": customer["d1DatabaseName"],
        "main": "worker.ts",
        "handlers": ["fetch", "email", "queue", "scheduled"],
        "sendEmailBinding": True,
        "sendEmailBindingCount": 1,
        "crons": ["*/5 * * * *", "0 2 * * *"],
    }
    release.validate_worker_contract(worker, customer, "oceanicvibes")
    with pytest.raises(RuntimeError, match="shared Payload contract"):
        release.validate_worker_contract({**worker, "core": "0.0.9"}, customer, "oceanicvibes")
    with pytest.raises(RuntimeError, match="R2 bindings"):
        release.validate_worker_contract({**worker, "r2Count": 1}, customer, "oceanicvibes")
    with pytest.raises(RuntimeError, match="Mailflare producer names"):
        release.validate_worker_contract({**worker, "mailflareQueueNames": {}}, customer, "oceanicvibes")
    with pytest.raises(RuntimeError, match="Turnstile sitekeys"):
        release.validate_worker_contract({**worker, "turnstileSiteKey": "hard-coded"}, customer, "oceanicvibes")
    with pytest.raises(RuntimeError, match="rate-limit namespaces"):
        release.validate_worker_contract({
            **worker,
            "rateLimitBindings": [
                {"name": "HELLOADA_FORM_RATE_LIMIT", "namespaceId": "2701"},
                {"name": "MAILFLARE_BOOKING_RATE_LIMIT", "namespaceId": "2701"},
                {"name": "MAILFLARE_LOGIN_RATE_LIMIT", "namespaceId": "2704"},
                {"name": "MAILFLARE_AGENT_RATE_LIMIT", "namespaceId": "2705"},
            ],
        }, customer, "oceanicvibes")


def test_worker_contract_requires_the_canonical_mailflare_schedule():
    worker = {**WORKER_CONFIG}
    release.validate_worker_contract(worker, CUSTOMER, "oceanicvibes")
    for crons in ([], ["0 * * * *"], ["*/5 * * * *"], ["*/5 * * * *", "0 * * * *"]):
        with pytest.raises(RuntimeError, match="canonical maintenance schedules"):
            release.validate_worker_contract({**worker, "crons": crons}, CUSTOMER, "oceanicvibes")


def test_worker_contract_requires_an_exact_tenant_queue_consumer_contract():
    worker = {**WORKER_CONFIG}
    release.validate_worker_contract(worker, CUSTOMER, "oceanicvibes")
    invalid = [
        {"consumers": []},
        {"consumers": [WORKER_CONFIG["queues"]["consumers"][0]]},
        {"consumers": [
            {**WORKER_CONFIG["queues"]["consumers"][0], "dead_letter_queue": "other-dlq"},
            WORKER_CONFIG["queues"]["consumers"][1],
        ]},
        {"consumers": [
            {**WORKER_CONFIG["queues"]["consumers"][0], "max_retries": None},
            WORKER_CONFIG["queues"]["consumers"][1],
        ]},
    ]
    for queues in invalid:
        with pytest.raises(RuntimeError, match="Queue"):
            release.validate_worker_contract({**worker, "queues": queues}, CUSTOMER, "oceanicvibes")


def test_reconcile_mailflare_migrations_uses_pinned_wrangle_chain_and_is_idempotent(tmp_path, monkeypatch):
    migration_dir = tmp_path / ".mailflare/migrations"
    migration_dir.mkdir(parents=True)
    names = ["0000_initial.sql", "0001_add_label.sql"]
    contents = ["CREATE TABLE mailboxes (id TEXT PRIMARY KEY);\n", "ALTER TABLE mailboxes ADD label TEXT;\n"]
    digest = hashlib.sha256()
    for name, content in zip(names, contents):
        (migration_dir / name).write_text(content)
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\0")
    source_sha = digest.hexdigest()
    (tmp_path / ".mailflare/provenance.json").write_text(json.dumps({
        "migrationNames": names,
        "migrationsSha256": source_sha,
    }))

    state = {"tables": [], "applied": []}
    monkeypatch.setattr(release, "applied_mailflare_migrations", lambda *_args: (state["tables"], state["applied"]))
    calls = []

    def run(command, cwd, env):
        calls.append((command, cwd, env))
        state.update(tables=["d1_migrations", "mailboxes"], applied=names.copy())
        return "Applied Mailflare migrations"

    monkeypatch.setattr(release, "run", run)
    result = release.reconcile_mailflare_migrations(tmp_path, CUSTOMER, {"CLOUDFLARE_API_TOKEN": "secret"}, {})
    assert result["names"] == names
    assert result["sourceSha256"] == source_sha
    assert result["head"] == release.mailflare_migration_head(names)
    assert result["changed"] is True
    assert len(calls) == 1
    assert calls[0][0][1:6] == ["d1", "migrations", "apply", "MAILFLARE_DB", "--remote"]
    assert "--yes" not in calls[0][0]
    assert calls[0][2]["CI"] == "1"
    assert calls[0][2]["CLOUDFLARE_API_TOKEN"] == "secret"

    again = release.reconcile_mailflare_migrations(tmp_path, CUSTOMER, {}, {})
    assert again["changed"] is False
    assert len(calls) == 1
    release.verify_mailflare_migrations({
        "mailflareMigrations": result,
        "mailflare": {"migrationNames": names, "migrationsSha256": source_sha},
    }, CUSTOMER, {})


def test_reconcile_mailflare_migrations_rejects_unknown_database_history(tmp_path, monkeypatch):
    migration_dir = tmp_path / ".mailflare/migrations"
    migration_dir.mkdir(parents=True)
    (migration_dir / "0000_initial.sql").write_text("CREATE TABLE mailboxes (id TEXT PRIMARY KEY);\n")
    (tmp_path / ".mailflare/provenance.json").write_text(json.dumps({
        "migrationNames": ["0000_initial.sql"],
        "migrationsSha256": "a" * 64,
    }))
    monkeypatch.setattr(release, "applied_mailflare_migrations", lambda *_args: (
        ["d1_migrations"], ["0000_unregistered.sql"],
    ))
    monkeypatch.setattr(release, "run", lambda *_args: pytest.fail("must not mutate an unknown schema"))
    with pytest.raises(RuntimeError, match="not a prefix"):
        release.reconcile_mailflare_migrations(tmp_path, CUSTOMER, {}, {})


def test_worker_cron_reconciliation_reads_applies_and_verifies(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps(self.payload).encode()

    calls = []
    schedules = [[]]
    def open_url(request, timeout):
        assert timeout == 30
        calls.append((request.get_method(), request.full_url, request.data))
        if request.get_method() == "PUT":
            assert json.loads(request.data) == [{"cron": "*/5 * * * *"}, {"cron": "0 2 * * *"}]
            schedules[0] = ["*/5 * * * *", "0 2 * * *"]
        return Response({"success": True, "result": {"schedules": [{"cron": cron} for cron in schedules[0]]}})

    monkeypatch.setattr(release.urllib.request, "urlopen", open_url)
    result = release.reconcile_worker_cron_schedules(CUSTOMER, ["*/5 * * * *", "0 2 * * *"], {
        "CLOUDFLARE_ACCOUNT_ID": "account",
        "CLOUDFLARE_API_TOKEN": "not-printed",
    })
    assert result["before"] == []
    assert result["after"] == ["*/5 * * * *", "0 2 * * *"]
    assert result["changed"] is True
    assert [method for method, _url, _body in calls] == ["GET", "PUT", "GET"]


def test_worker_cron_reconciliation_rejects_noncanonical_schedules():
    with pytest.raises(ValueError, match="exact canonical Mailflare schedules"):
        release.reconcile_worker_cron_schedules(CUSTOMER, [], {})


def test_worker_queue_consumer_is_created_and_read_back(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps(self.payload).encode()

    calls = []
    state = []
    desired = {
        "script_name": CUSTOMER["worker"],
        "type": "worker",
        "dead_letter_queue": "tenant-test-dead-letter",
        "settings": {"batch_size": 1, "max_concurrency": 1, "max_retries": 8,
                     "max_wait_time_ms": 5000, "retry_delay": 30},
    }

    def open_url(request, timeout):
        assert timeout == 30
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "POST":
            assert json.loads(request.data) == desired
            created = {**desired, "consumer_id": "c" * 32, "queue_name": CUSTOMER["mailflareInboundQueueName"]}
            created["script"] = created.pop("script_name")
            state[:] = [created]
            return Response({"success": True, "result": state[0]})
        if request.full_url.endswith("/consumers/" + "c" * 32):
            return Response({"success": True, "result": state[0]})
        listed = [{**item, "script_name": None} for item in state]
        for item in listed:
            item.pop("script", None)
        return Response({"success": True, "result": listed})

    monkeypatch.setattr(release.urllib.request, "urlopen", open_url)
    result = release.reconcile_worker_queue_consumer(
        "q" * 32, CUSTOMER["mailflareInboundQueueName"], desired,
        {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "not-printed"},
    )
    assert result["verified"] is True and result["changed"] is True
    assert [method for method, _url in calls] == ["GET", "POST", "GET", "GET"]
    assert calls[-1][1].endswith("/consumers/" + "c" * 32)


def test_worker_queue_consumer_updates_only_the_registered_workers_drifted_settings(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps(self.payload).encode()

    desired = {
        "script_name": CUSTOMER["worker"], "type": "worker",
        "settings": {"batch_size": 1, "max_concurrency": 1, "max_retries": 8,
                     "max_wait_time_ms": 5000, "retry_delay": 30},
        "dead_letter_queue": "tenant-test-dead-letter",
    }
    state = [{**desired, "script": desired["script_name"], "consumer_id": "c" * 32,
              "settings": {**desired["settings"], "max_retries": 3}}]
    state[0].pop("script_name")
    calls = []

    def open_url(request, timeout):
        calls.append((request.get_method(), request.full_url))
        if request.get_method() == "PUT":
            assert request.full_url.endswith("/consumers/" + "c" * 32)
            assert json.loads(request.data) == desired
            state[0] = {**desired, "script": desired["script_name"], "consumer_id": "c" * 32}
            state[0].pop("script_name")
            return Response({"success": True, "result": state[0]})
        if request.full_url.endswith("/consumers/" + "c" * 32):
            return Response({"success": True, "result": state[0]})
        listed = [{**item, "script_name": None} for item in state]
        for item in listed:
            item.pop("script", None)
        return Response({"success": True, "result": listed})

    monkeypatch.setattr(release.urllib.request, "urlopen", open_url)
    result = release.reconcile_worker_queue_consumer(
        "q" * 32, CUSTOMER["mailflareInboundQueueName"], desired,
        {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "not-printed"},
    )
    assert result["changed"] is True
    assert [method for method, _url in calls] == ["GET", "GET", "PUT", "GET", "GET"]


def test_worker_queue_consumer_fails_closed_on_an_unregistered_consumer(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps(self.payload).encode()

    calls = []
    def open_url(request, timeout):
        calls.append(request)
        result = {"consumer_id": "c" * 32, "type": "worker", "script": "other-worker"}
        listed = {"consumer_id": "c" * 32, "type": "worker", "script_name": None}
        return Response({"success": True, "result": [listed]} if request.full_url.endswith("/consumers")
                        else {"success": True, "result": result})
    monkeypatch.setattr(release.urllib.request, "urlopen", open_url)
    with pytest.raises(RuntimeError, match="unexpected consumer"):
        release.reconcile_worker_queue_consumer(
            "q" * 32, CUSTOMER["mailflareInboundQueueName"],
            {"script_name": CUSTOMER["worker"], "type": "worker", "settings": {}},
            {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "not-printed"},
        )
    assert [request.get_method() for request in calls] == ["GET", "GET"]


def test_worker_queue_consumer_detail_normalizes_cloudflare_script_field(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps({"success": True, "result": {
                "consumer_id": "c" * 32, "script": CUSTOMER["worker"], "type": "worker",
                "settings": {"batch_size": 1},
            }}).encode()

    monkeypatch.setattr(release.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    result = release.worker_queue_consumer_detail(
        "q" * 32, "c" * 32,
        {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "not-printed"},
    )
    assert result["script_name"] == CUSTOMER["worker"]


def test_worker_queue_consumer_reconciliation_uses_the_registered_queue_ids(monkeypatch):
    calls = []
    monkeypatch.setattr(release, "reconcile_worker_queue_consumer", lambda queue_id, name, desired, _env:
                        calls.append((queue_id, name, desired)) or {"verified": True})
    resources = {"mailflareQueues": {
        "inbound": {"queue_id": "c" * 32},
        "outbound": {"queue_id": "d" * 32},
        "agent": {"queue_id": "e" * 32},
    }}
    result = release.reconcile_worker_queue_consumers(
        CUSTOMER, WORKER_CONFIG, resources,
        {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "not-printed"},
    )
    assert result["verified"] is True
    assert [item[:2] for item in calls] == [
        ("c" * 32, CUSTOMER["mailflareInboundQueueName"]),
        ("d" * 32, CUSTOMER["mailflareOutboundQueueName"]),
        ("e" * 32, CUSTOMER["mailflareAgentQueueName"]),
    ]
    assert all("dead_letter_queue" not in item[2] for item in calls)


def test_d1_table_inspection_uses_bound_sqlite_metadata_parameters(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps({"success": True, "result": [{"success": True, "results": []}]}).encode()

    captured = {}
    def open_url(request, timeout):
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr(release.urllib.request, "urlopen", open_url)
    release.d1_query(CUSTOMER, "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ? ORDER BY name",
                     {"CLOUDFLARE_ACCOUNT_ID": "account", "CLOUDFLARE_API_TOKEN": "not-printed"},
                     ("table", "sqlite_%"))
    assert captured["body"] == {
        "sql": "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ? ORDER BY name",
        "params": ["table", "sqlite_%"],
    }


def seed_cron_contract(receipt):
    receipt["cronTriggers"] = {
        "before": [],
        "desired": ["*/5 * * * *", "0 2 * * *"],
        "after": ["*/5 * * * *", "0 2 * * *"],
        "changed": True,
        "verifiedAt": "2026-10-08T00:00:00Z",
    }
    consumers = WORKER_CONFIG["queues"]["consumers"]
    queue_ids = ["a" * 32, "b" * 32, "c" * 32]
    consumer_ids = ["1" * 32, "2" * 32, "3" * 32]
    receipt["queueConsumers"] = {
        "verified": True,
        "consumers": [
            {"queue": config["queue"], "queueId": queue_id, "consumerId": consumer_id,
             "desired": {
                 "script_name": CUSTOMER["worker"], "type": "worker",
                 **({"dead_letter_queue": config["dead_letter_queue"]} if config.get("dead_letter_queue") else {}),
                 "settings": release.worker_queue_consumer_settings(config),
             }, "verified": True}
            for config, queue_id, consumer_id in zip(consumers, queue_ids, consumer_ids)
        ],
    }
    return receipt


def stub_canonical_cron_schedule(monkeypatch):
    schedules = ["*/5 * * * *", "0 2 * * *"]
    monkeypatch.setattr(release, "worker_cron_schedules", lambda *_args: schedules)
    monkeypatch.setattr(release, "verify_mailflare_migrations", lambda *_args: None)
    expected = {}
    queue_ids = ["a" * 32, "b" * 32, "c" * 32]
    consumer_ids = ["1" * 32, "2" * 32, "3" * 32]
    for config, queue_id, consumer_id in zip(WORKER_CONFIG["queues"]["consumers"], queue_ids, consumer_ids):
        expected[queue_id] = {
            "consumer_id": consumer_id,
            "queue_name": config["queue"],
            "script_name": CUSTOMER["worker"],
            "type": "worker",
            **({"dead_letter_queue": config["dead_letter_queue"]} if config.get("dead_letter_queue") else {}),
            "settings": release.worker_queue_consumer_settings(config),
        }
    monkeypatch.setattr(release, "worker_queue_consumers", lambda queue_id, _env: [expected[queue_id]])
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
    customer = CANDIDATE_CUSTOMER
    shutil.copytree(TEMPLATE / "src/migrations", tmp_path / "src/migrations")
    files = {
        "payload.config.ts": "import { createHelloAdaSchema } from '@weareheadless/helloada-payload-core/schema';\nconst schema = createHelloAdaSchema(guard);\n",
        ".open-next/worker.js": "import './server-functions/default/handler.mjs'",
        ".open-next/server-functions/default/handler.mjs": "route('/growth/contract')",
        "worker.ts": (TEMPLATE / "worker.ts").read_text(),
        "wrangler.jsonc": (TEMPLATE / "wrangler.jsonc").read_text(),
        "package.json": (TEMPLATE / "package.json").read_text(),
        "package-lock.json": (TEMPLATE / "package-lock.json").read_text(),
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
        ".mailflare/migrations/0000_initial.sql": "CREATE TABLE test (id TEXT PRIMARY KEY);\n",
        ".mailflare/provenance.json": json.dumps({
            "repository": "https://github.com/hieunc229/mailflare",
            "commit": "ca41c56a0781bf848b9898ddcc5615b3eacfbf8e",
            "packageVersion": "0.5.1",
            "packageLockSha256": "dcc70b0d3ac9b2ecbc7edb5199b9cf1c02064ea491e724939cdbe131f12c71de",
            "integrationPatchSet": "helloada-tenant-worker-booking-owner-branding-v10",
            "basePath": "/mail",
            "namespacedApiReferences": 1,
            "migrationNames": ["0000_initial.sql"],
            "migrationsSha256": hashlib.sha256(
                b"0000_initial.sql\0CREATE TABLE test (id TEXT PRIMARY KEY);\n\0"
            ).hexdigest(),
        }),
        ".mailflare/server/index.js": "export default {};\n",
        ".mailflare/server/ssr/index.js": "export default {};\n",
        ".open-next/assets/mail/_next/static/mailflare.js": "/* pinned Mailflare client */\n",
        ".open-next/assets/helloada-release.json": json.dumps({"sourceSha": SHA,
            "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
            "contentContract": customer["contentContract"], "schemaRevision": customer["schemaRevision"],
            "schemaIdentity": customer["schemaIdentity"], "migrationHead": customer["migrationHead"],
            "mailflareCommit": "ca41c56a0781bf848b9898ddcc5615b3eacfbf8e",
            "mailflarePatchSet": "helloada-tenant-worker-booking-owner-branding-v10"}),
    }
    for name, value in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return tmp_path


def test_checks_compiled_server_instead_of_thin_worker_entry(tmp_path):
    checkout = artifact(tmp_path)
    custom_bundle = tmp_path / "custom-worker-dry-run"
    custom_bundle.mkdir()
    (custom_bundle / "worker.js").write_text("export default {fetch(){},email(){},queue(){},scheduled(){}};\n")
    hashes = release.inspect_artifact(checkout, CANDIDATE_CUSTOMER, SHA, custom_bundle)
    assert ".open-next/server-functions/default/handler.mjs" in hashes
    assert hashes["worker.ts"]
    assert hashes["wrangler.jsonc"]
    assert hashes["package-lock.json"]
    assert hashes["custom-worker/worker.js"]


def _integrity_git_checkout(path):
    path.mkdir()
    (path / "worker.ts").write_text("export default {}\\n")
    (path / "src").mkdir()
    (path / "src/page.tsx").write_text("export default 1;\\n")
    release.subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    release.subprocess.run(["git", "config", "user.name", "Release Test"], cwd=path, check=True)
    release.subprocess.run(["git", "config", "user.email", "release-test@example.invalid"], cwd=path, check=True)
    release.subprocess.run(["git", "add", "."], cwd=path, check=True)
    release.subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)
    return path


def test_post_build_integrity_allows_only_declared_generated_outputs(tmp_path, monkeypatch):
    checkout = _integrity_git_checkout(tmp_path / "checkout")
    monkeypatch.setattr(
        release,
        "run",
        lambda command, cwd, environment: release.subprocess.run(
            command, cwd=cwd, env=environment, check=True, text=True, capture_output=True,
        ).stdout,
    )
    (checkout / "worker.ts").write_text("export default { fetch() {} };\\n")
    generated = checkout / ".mailflare/client/chunk.js"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated runtime bundle")
    marker = checkout / "public/helloada-release.json"
    marker.parent.mkdir()
    marker.write_text("{}\\n")

    assert release.tracked_changes_outside_runtime_overlay(
        checkout, ["worker.ts"], release.os.environ,
        generated_untracked_roots=(".mailflare", "public/helloada-release.json"),
    ) == []

    (checkout / "src/page.tsx").write_text("unexpected source mutation")
    assert release.tracked_changes_outside_runtime_overlay(
        checkout, ["worker.ts"], release.os.environ,
        generated_untracked_roots=(".mailflare", "public/helloada-release.json"),
    ) == ["src/page.tsx"]


def test_pre_build_integrity_rejects_build_outputs_without_explicit_allowlist(tmp_path, monkeypatch):
    checkout = _integrity_git_checkout(tmp_path / "checkout")
    monkeypatch.setattr(
        release,
        "run",
        lambda command, cwd, environment: release.subprocess.run(
            command, cwd=cwd, env=environment, check=True, text=True, capture_output=True,
        ).stdout,
    )
    generated = checkout / ".mailflare/client/chunk.js"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated runtime bundle")
    marker = checkout / "public/helloada-release.json"
    marker.parent.mkdir()
    marker.write_text("{}\\n")

    changed = release.tracked_changes_outside_runtime_overlay(checkout, [], release.os.environ)
    assert ".mailflare/client/chunk.js" in changed
    assert "public/helloada-release.json" in changed


def test_release_artifact_requires_all_custom_worker_event_handlers(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / "worker.ts").write_text("export default { fetch() {} }\n")
    with pytest.raises(RuntimeError, match="custom Worker artifact"):
        release.inspect_artifact(checkout, CANDIDATE_CUSTOMER, SHA)


def test_release_rejects_a_tenant_local_payload_schema(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / "payload.config.ts").write_text("export default buildConfig({ collections: [TenantPages] });\n")
    with pytest.raises(RuntimeError, match="shared site-agent schema factory"):
        release.inspect_artifact(checkout, CANDIDATE_CUSTOMER, SHA)


def test_stale_release_marker_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / ".open-next/assets/helloada-release.json").write_text(json.dumps({"sourceSha": "b" * 40}))
    with pytest.raises(RuntimeError, match="marker"):
        release.inspect_artifact(checkout, CANDIDATE_CUSTOMER, SHA)


def test_shared_core_version_must_match_release_registry(tmp_path):
    checkout = artifact(tmp_path)
    (checkout / "node_modules/@weareheadless/helloada-payload-core/package.json").write_text(json.dumps({"version": "0.0.9"}))
    with pytest.raises(RuntimeError, match="core version"):
        release.inspect_artifact(checkout, CANDIDATE_CUSTOMER, SHA)


def test_browser_bridge_does_not_substitute_for_service_content_gateway(tmp_path):
    checkout = artifact(tmp_path)
    path = checkout / ".next/server/app-paths-manifest.json"
    routes = json.loads(path.read_text())
    del routes["/api/workspace/content/route"]
    path.write_text(json.dumps(routes))
    with pytest.raises(RuntimeError, match="service content"):
        release.inspect_artifact(checkout, CANDIDATE_CUSTOMER, SHA)


def test_obsolete_route_in_built_manifest_is_rejected(tmp_path):
    checkout = artifact(tmp_path)
    path = checkout / ".next/server/app-paths-manifest.json"
    routes = json.loads(path.read_text())
    routes["/api/atelier/ada/route"] = "old.js"
    path.write_text(json.dumps(routes))
    with pytest.raises(RuntimeError, match="obsolete"):
        release.inspect_artifact(checkout, CANDIDATE_CUSTOMER, SHA)


def test_empty_tenant_database_requires_explicit_bootstrap_initialization(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: ([], []))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *args: {"PAYLOAD_SECRET": "secret"})
    with pytest.raises(RuntimeError, match="explicit bootstrap initialization"):
        release.enforce_payload_migrations(TEMPLATE, CUSTOMER, {}, None, None, {}, {}, "oceanicvibes", lambda _: None, WORKER_CONFIG, tmp_path)
    assert calls == []


def test_cloudflare_reserved_d1_table_is_not_application_data(monkeypatch):
    monkeypatch.setattr(release, "d1_query", lambda *_args: [{"name": "_cf_KV"}])
    assert release.applied_payload_migrations(CUSTOMER, {}) == ([], [])


def test_d1_application_table_still_counts_as_existing_state(monkeypatch):
    monkeypatch.setattr(
        release,
        "d1_query",
        lambda *_args: [{"name": "_cf_KV"}, {"name": "users"}],
    )
    assert release.applied_payload_migrations(CUSTOMER, {}) == (["users"], [])


def test_payload_migration_config_targets_only_the_exact_remote_tenant_bindings(tmp_path):
    path = release.payload_remote_bindings_config_file(tmp_path, CUSTOMER, WORKER_CONFIG)
    try:
        config = json.loads(path.read_text())
        assert path.stat().st_mode & 0o777 == 0o600
        assert config["name"] == CUSTOMER["worker"]
        assert config["compatibility_date"] == WORKER_CONFIG["compatibilityDate"]
        assert config["compatibility_flags"] == WORKER_CONFIG["compatibilityFlags"]
        assert config["d1_databases"] == [{
            "binding": "D1",
            "database_id": CUSTOMER["d1DatabaseId"],
            "database_name": CUSTOMER["d1DatabaseName"],
            "remote": True,
        }]
        assert config["r2_buckets"] == [{
            "binding": "R2",
            "bucket_name": CUSTOMER["r2BucketName"],
            "remote": True,
        }]
    finally:
        path.unlink(missing_ok=True)


def test_payload_migration_uses_remote_config_and_removes_it_afterward(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *_args: {"PAYLOAD_SECRET": "test-secret"})

    def fake_run(command, cwd, env):
        config_path = Path(env["HELLOADA_CLOUDFLARE_CONFIG_PATH"])
        config = json.loads(config_path.read_text())
        assert config["d1_databases"][0]["remote"] is True
        assert config["d1_databases"][0]["database_id"] == CUSTOMER["d1DatabaseId"]
        assert env["PAYLOAD_CLI"] == "1" and env["NODE_ENV"] == "production"
        assert env["PAYLOAD_SECRET"] == "test-secret"
        commands.append((command, config_path))
        return "migration complete"

    monkeypatch.setattr(release, "run", fake_run)
    result = release.run_payload_migration(
        TEMPLATE, CUSTOMER, WORKER_CONFIG, {"CLOUDFLARE_API_TOKEN": "configured"},
        {}, REGISTRY, "oceanicvibes", tmp_path,
    )

    assert result == "migration complete"
    assert commands[0][0] == release.payload_migration_command(REGISTRY)
    assert not commands[0][1].exists()


def test_existing_database_never_receives_a_schema_mutation(monkeypatch, tmp_path):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], expected))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *args: pytest.fail("existing D1 must not load migration secrets"))
    result = release.enforce_payload_migrations(TEMPLATE, CUSTOMER, {}, None, None, {}, {}, "oceanicvibes", lambda _: None, WORKER_CONFIG, tmp_path)
    assert result == expected and calls == []


@pytest.mark.parametrize("website_present", [True, False])
def test_payload_contract_verifier_uses_and_cleans_the_remote_binding_config(monkeypatch, tmp_path, website_present):
    commands = []
    customer = {**CUSTOMER, "websitePresent": website_present}

    def fake_run(command, cwd, env):
        config_path = Path(env["HELLOADA_CLOUDFLARE_CONFIG_PATH"])
        config = json.loads(config_path.read_text())
        assert config["d1_databases"][0]["remote"] is True
        assert config["d1_databases"][0]["database_id"] == customer["d1DatabaseId"]
        assert env["HELLOADA_WEBSITE_PRESENT"] == ("true" if website_present else "false")
        commands.append((command, config_path))
        return "contract verified"

    monkeypatch.setattr(release, "run", fake_run)
    result = release.run_payload_contract_verifier(
        TEMPLATE, customer, WORKER_CONFIG, {"CLOUDFLARE_API_TOKEN": "configured"},
        {}, tmp_path,
    )

    assert result == "contract verified"
    assert commands[0][0] == ["npm", "run", "verify:payload"]
    assert not commands[0][1].exists()


def test_payload_migration_uses_the_pinned_package_script():
    package = json.loads((TEMPLATE / "package.json").read_text())
    assert release.payload_migration_command(REGISTRY) == [
        str(Path(REGISTRY["npmBin"]) / "npm"), "run", "payload", "--", "migrate",
    ]
    assert "PAYLOAD_CLI=1" in package["scripts"]["payload"]


def test_tenant_payload_verifier_matches_the_site_agent_contract_before_mutation(tmp_path):
    package = json.loads((TEMPLATE / "package.json").read_text())
    package_path = tmp_path / "package.json"
    lock_path = tmp_path / "package-lock.json"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    package_path.write_text(json.dumps(package))
    lock = json.loads((TEMPLATE / "package-lock.json").read_text())
    lock_path.write_text(json.dumps(lock))
    shutil.copyfile(TEMPLATE / "tsconfig.json", tmp_path / "tsconfig.json")
    shutil.copyfile(TEMPLATE / "payload.config.ts", tmp_path / "payload.config.ts")
    verifier = scripts / "verify-payload-contract.ts"
    shutil.copyfile(TEMPLATE / "scripts/verify-payload-contract.ts", verifier)

    release.validate_payload_verifier(tmp_path)

    package["scripts"]["verify:payload"] = "node scripts/verify-payload-contract.ts"
    package_path.write_text(json.dumps(package))
    with pytest.raises(RuntimeError, match="command must match"):
        release.validate_payload_verifier(tmp_path)

    package["scripts"]["verify:payload"] = json.loads((TEMPLATE / "package.json").read_text())["scripts"]["verify:payload"]
    package.pop("devDependencies", None)
    package_path.write_text(json.dumps(package))
    with pytest.raises(RuntimeError, match="exact tsx version"):
        release.validate_payload_verifier(tmp_path)

    package = json.loads((TEMPLATE / "package.json").read_text())
    package_path.write_text(json.dumps(package))
    lock = json.loads((TEMPLATE / "package-lock.json").read_text())
    lock["packages"][""]["devDependencies"]["tsx"] = "4.22.3"
    lock_path.write_text(json.dumps(lock))
    with pytest.raises(RuntimeError, match="does not pin"):
        release.validate_payload_verifier(tmp_path)

    lock = json.loads((TEMPLATE / "package-lock.json").read_text())
    lock_path.write_text(json.dumps(lock))
    tsconfig_path = tmp_path / "tsconfig.json"
    tsconfig = json.loads(tsconfig_path.read_text())
    tsconfig["compilerOptions"]["paths"].pop("@payload-config")
    tsconfig_path.write_text(json.dumps(tsconfig))
    with pytest.raises(RuntimeError, match="map @payload-config"):
        release.validate_payload_verifier(tmp_path)

    tsconfig_path.write_text((TEMPLATE / "tsconfig.json").read_text())
    verifier.write_text(verifier.read_text() + "\\n// drift\\n")
    with pytest.raises(RuntimeError, match="match the site-agent template exactly"):
        release.validate_payload_verifier(tmp_path)


def test_new_site_initialization_is_exact_and_idempotent(monkeypatch, tmp_path):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    calls = []
    queries = iter([([], []), (["pages", "payload_migrations"], expected)])
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: next(queries))
    monkeypatch.setattr(release, "run", lambda command, *args: calls.append(command) or "migration complete")
    monkeypatch.setattr(release, "tenant_runtime_secrets", lambda *args: {"PAYLOAD_SECRET": "secret"})
    stages = []
    result = release.enforce_payload_migrations(
        TEMPLATE, CUSTOMER, {}, CUSTOMER["migrationHead"], None, {}, REGISTRY, "oceanicvibes", stages.append,
     WORKER_CONFIG, tmp_path)
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
        "MAILFLARE_ADDRESS=contact@atelier-harmonie.example\n"
        "MAILFLARE_ZONE_ID=zone-id-for-test\n"
        "MAILFLARE_ROUTING_STATUS=active\n"
    )
    (provisioned_root / "tenants.json").write_text(json.dumps({
        tenant: {"config_path": str(config_path), "api_token_env": tenant_token_name},
    }))
    host_config = tmp_path / "host.yaml"
    host_config.write_text(f"workspace_api:\n  provisioned_root: {provisioned_root}\n")
    manifest = {
        "connectionGate": {"config": str(host_config)},
        "customers": {tenant: {"mailflareD1DatabaseId": "mailflare-d1-for-test"}},
    }

    secrets = release.tenant_runtime_secrets(manifest, tenant)

    assert secrets == {
        "PAYLOAD_SECRET": "payload-secret-for-test",
        "HELLOADA_SITE_AGENT_TOKEN": "site-agent-token-for-test",
        "MAILFLARE_ADDRESS": "contact@atelier-harmonie.example",
        "MAILFLARE_ZONE_ID": "zone-id-for-test",
        "MAILFLARE_ROUTING_STATUS": "active",
    }


def test_mailflare_worker_release_rejects_missing_runtime_settings(tmp_path):
    tenant = "oceanicvibes"
    tenant_token_name = "PROVISIONED_OCEANICVIBES_TOKEN"
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
    manifest = {
        "connectionGate": {"config": str(host_config)},
        "customers": {tenant: {"mailflareD1DatabaseId": "mailflare-d1-for-test"}},
    }

    with pytest.raises(RuntimeError, match="registered Mailflare tenant runtime settings are incomplete"):
        release.tenant_runtime_secrets(manifest, tenant)


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
    result = release.upload_worker_version(
        TEMPLATE, SHA, "release-1", tmp_path, secrets, {},
        {"HELLOADA_TURNSTILE_SITE_KEY": "turnstile-public-key"},
    )

    assert result == version_id
    command = commands[0]
    secret_path = Path(command[command.index("--secrets-file") + 1])
    assert command == [
        str(TEMPLATE / "node_modules/.bin/opennextjs-cloudflare"), "upload",
        "--secrets-file", str(secret_path),
        "--var", "HELLOADA_TURNSTILE_SITE_KEY:turnstile-public-key",
        "--var", f"HELLOADA_RELEASE_SHA:{SHA}",
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
            {"HELLOADA_TURNSTILE_SITE_KEY": "turnstile-public-key"},
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


def test_partial_or_unexpected_database_never_triggers_a_migration(monkeypatch, tmp_path):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["users", "payload_migrations"], []))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    with pytest.raises(RuntimeError, match="non-empty D1"):
        release.enforce_payload_migrations(
            TEMPLATE, CUSTOMER, {}, CUSTOMER["migrationHead"], None, {}, {}, "oceanicvibes", lambda _: None,
         WORKER_CONFIG, tmp_path)
    assert calls == []


def test_existing_tenant_migration_requires_the_exact_nonempty_ledger_prefix(monkeypatch, tmp_path):
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
     WORKER_CONFIG, tmp_path)

    assert result == expected
    assert stages == ["migrate-schema"]
    assert calls == [[str(Path(REGISTRY["npmBin"]) / "npm"), "run", "payload", "--", "migrate"]]


@pytest.mark.parametrize("applied,requested_head", [
    ([], release.migration_ledger_head([])),
    (["unknown"], release.migration_ledger_head(["unknown"])),
    ([TEMPLATE_MANIFEST["migrations"][0]["name"]], "f" * 64),
])
def test_existing_tenant_migration_rejects_missing_or_changed_ledger(monkeypatch, tmp_path, applied, requested_head):
    calls = []
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], applied))
    monkeypatch.setattr(release, "run", lambda *args: calls.append(args) or "")
    with pytest.raises(RuntimeError, match="migration|ledger|existing tenant"):
        release.enforce_payload_migrations(
            TEMPLATE, CUSTOMER, {}, None, requested_head, {}, {}, "oceanicvibes", lambda _: None,
         WORKER_CONFIG, tmp_path)
    assert calls == []


def test_existing_tenant_migration_refuses_to_mutate_without_an_explicit_request(monkeypatch, tmp_path):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], expected[:1]))
    monkeypatch.setattr(release, "run", lambda *args: pytest.fail("unexpected Payload migration"))
    with pytest.raises(RuntimeError, match="explicit exact schema-migration request"):
        release.enforce_payload_migrations(
            TEMPLATE, CUSTOMER, {}, None, None, {}, {}, "oceanicvibes", lambda _: None,
         WORKER_CONFIG, tmp_path)


def test_completed_schema_migration_request_is_idempotent(monkeypatch, tmp_path):
    expected = [entry["name"] for entry in TEMPLATE_MANIFEST["migrations"]]
    from_head = release.migration_ledger_head(expected[:1])
    monkeypatch.setattr(release, "applied_payload_migrations", lambda *args: (["pages", "payload_migrations"], expected))
    monkeypatch.setattr(release, "run", lambda *args: pytest.fail("completed migration must not rerun"))
    assert release.enforce_payload_migrations(
        TEMPLATE, CUSTOMER, {}, None, from_head, {}, {}, "oceanicvibes", lambda _: None,
     WORKER_CONFIG, tmp_path) == expected


def promoted_receipt(tmp_path):
    customer = CUSTOMER
    result = seed_cron_contract({"tenant": "oceanicvibes", "sourceSha": SHA, "releaseId": "release-1",
              "worker": customer["worker"], "repository": customer["repository"],
              "payloadAdmin": customer["payloadAdmin"], "payloadCore": customer["payloadCore"],
              "contentContract": customer["contentContract"], "schemaRevision": customer["schemaRevision"],
              "schemaIdentity": customer["schemaIdentity"], "migrationHead": customer["migrationHead"],
              "websitePresent": customer["websitePresent"],
              "mailflareD1DatabaseId": customer["mailflareD1DatabaseId"],
              "mailflareD1DatabaseName": customer["mailflareD1DatabaseName"],
              "privateEmailR2BucketName": customer["privateEmailR2BucketName"],
              "mailflareR2BucketName": customer["mailflareR2BucketName"],
              "mailflareInboundQueueName": customer["mailflareInboundQueueName"],
              "mailflareOutboundQueueName": customer["mailflareOutboundQueueName"],
              "mailflareAgentQueueName": customer["mailflareAgentQueueName"],
              "mailflare": {
                  "sourceCommit": "ca41c56a0781bf848b9898ddcc5615b3eacfbf8e",
                  "packageVersion": "0.5.1",
                  "integrationPatchSet": "helloada-tenant-worker-booking-owner-branding-v10",
                  "basePath": "/mail",
                  "namespacedApiReferences": 307,
                  "migrationNames": ["0000_initial.sql"],
                  "migrationsSha256": "a" * 64,
              },
              "mailflareMigrations": {
                  "names": ["0000_initial.sql"],
                  "head": release.mailflare_migration_head(["0000_initial.sql"]),
                  "sourceSha256": "a" * 64,
              },
              "status": "failed", "stage": "verify-connection", "error": "connection failed",
              "deployment": {"id": "deployment-1"}, "uploadedVersion": "version-1",
              "artifactHashes": {"worker.js": "b" * 64}})
    (tmp_path / "receipt.json").write_text(json.dumps(result))
    return result, customer


def test_read_only_continuation_preserves_prior_failure(tmp_path):
    _, customer = promoted_receipt(tmp_path)
    result = release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer, "website")
    assert result["status"] == "running" and "error" not in result
    assert result["verificationHistory"][-1]["error"] == "connection failed"


def test_read_only_continuation_requires_the_same_explicit_release_purpose(tmp_path):
    receipt, customer = promoted_receipt(tmp_path)
    receipt["initialSchemaHead"] = customer["migrationHead"]
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="purpose differs"):
        release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer, "website")


@pytest.mark.parametrize("changed", ["identity", "unpromoted", "artifact"])
def test_read_only_continuation_rejects_unproven_release(tmp_path, changed):
    result, customer = promoted_receipt(tmp_path)
    if changed == "identity":
        result["sourceSha"] = "b" * 40
    elif changed == "unpromoted":
        result["stage"] = "upload"
    else:
        result["artifactHashes"] = {"../worker.js": "not-a-sha256"}
    (tmp_path / "receipt.json").write_text(json.dumps(result))
    with pytest.raises(ValueError):
        release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer, "website")


def test_edge_convergence_repeats_identical_checks_without_deploying(monkeypatch):
    result = seed_cron_contract({"tenant": "oceanicvibes", "sourceSha": SHA, "releaseId": "release-1",
              "uploadedVersion": "version-1", "initialSchemaHead": CUSTOMER["migrationHead"]})
    customer = CUSTOMER
    stub_canonical_cron_schedule(monkeypatch)
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "version-1"}]})
    events = []
    monkeypatch.setattr(release, "check_health", lambda *args: events.append("health") or {"ok": True})
    monkeypatch.setattr(release, "control_plane_token", lambda *_args: "control-token")
    monkeypatch.setattr(
        release,
        "activate_tenant_runtime",
        lambda *args: events.append(("activate", args[1], args[2], args[3])),
    )
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    commands = []

    def run(command, *args):
        commands.append(command)
        events.append("connection")
        if len(commands) == 1:
            raise RuntimeError("connection gate failed")

    monkeypatch.setattr(release, "run", run)
    release.verify_live(result, customer, REGISTRY, {}, {}, lambda name: result.update(stage=name))
    assert commands[0] == commands[1] and len(commands) == 2
    assert commands[0][1].endswith("check-helloada-connections.py")
    assert result["connectionVerifiedAt"] and len(result["gateAttempts"]) == 1
    assert events == [
        "health", ("activate", "oceanicvibes", "release-1", SHA), "connection",
        "health", ("activate", "oceanicvibes", "release-1", SHA), "connection",
    ]


def test_read_only_gate_rejects_a_different_production_version(monkeypatch):
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "other-version"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: pytest.fail("must reject before health"))
    with pytest.raises(RuntimeError, match="exact uploaded"):
        release.verify_live({"uploadedVersion": "version-1"}, {}, {}, {}, {}, lambda _: None)


def test_worker_version_identity_ignores_secret_values_but_binds_code_and_public_bindings():
    def version(etag, secret_value, public_value):
        return {
            "resources": {
                "script": {"etag": etag},
                "bindings": [
                    {"name": "API_KEY", "type": "secret_text", "text": secret_value},
                    {"name": "SITE_NAME", "type": "plain_text", "text": public_value},
                ],
            },
        }

    baseline = release.worker_version_identity(version("a" * 64, "old-secret", "Oceanic"))
    rotated_secret = release.worker_version_identity(version("a" * 64, "new-secret", "Oceanic"))
    changed_code = release.worker_version_identity(version("b" * 64, "old-secret", "Oceanic"))
    changed_public_binding = release.worker_version_identity(version("a" * 64, "old-secret", "Other"))

    assert baseline == rotated_secret
    assert baseline != changed_code
    assert baseline != changed_public_binding


def test_read_only_gate_accepts_secret_rotation_only_with_identical_code_and_bindings(monkeypatch):
    result = {
        "tenant": "oceanicvibes",
        "sourceSha": SHA,
        "releaseId": "release-1",
        "uploadedVersion": "version-1",
        "deployment": {"id": "original-deployment"},
    }
    seed_cron_contract(result)
    deployment = {
        "id": "secret-rotation-deployment",
        "annotations": {"workers/triggered_by": "secret"},
        "versions": [{"percentage": 100, "version_id": "version-2"}],
    }
    identity = {"script_etag": "a" * 64, "binding_identity": "b" * 64}
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *_args: deployment)
    monkeypatch.setattr(release, "cloudflare_worker_version_identity", lambda *_args: identity)
    stub_canonical_cron_schedule(monkeypatch)
    monkeypatch.setattr(release, "workers_dev_provisioner", lambda *_args: None)
    monkeypatch.setattr(release, "check_health", lambda *_args: {"ok": True, "tenant": "oceanicvibes"})
    monkeypatch.setattr(release, "control_plane_token", lambda *_args: "control-token")
    activations = []
    monkeypatch.setattr(release, "activate_tenant_runtime", lambda *args: activations.append(args))
    monkeypatch.setattr(release, "run", lambda *_args: None)
    monkeypatch.setattr(release.time, "sleep", lambda *_args: None)

    release.verify_live(
        result, CUSTOMER, REGISTRY, {}, {}, lambda name: result.update(stage=name),
        verify_only=True,
    )

    assert result["deployment"] == {"id": "original-deployment"}
    assert result["currentVerification"] == {
        "releaseId": "release-1",
        "sourceSha": SHA,
        "uploadedVersion": "version-1",
        "workerVersion": "version-2",
        "deploymentId": "secret-rotation-deployment",
        "trafficPercentage": 100,
        "uploadedScriptEtag": "a" * 64,
        "activeScriptEtag": "a" * 64,
        "uploadedBindingIdentity": "b" * 64,
        "activeBindingIdentity": "b" * 64,
        "mode": "secret_rotation",
        "verifiedAt": result["currentVerification"]["verifiedAt"],
    }
    assert activations[0][-1]["releaseId"] == result["currentVerification"]["releaseId"]
    assert activations[0][-1]["workerVersion"] == result["currentVerification"]["workerVersion"]
    assert activations[0][-1]["uploadedScriptEtag"] == result["currentVerification"]["activeScriptEtag"]
    assert activations[0][-1]["uploadedBindingIdentity"] == result["currentVerification"]["activeBindingIdentity"]
    assert activations[0][-1]["verifiedAt"]


def test_read_only_gate_rejects_code_drift_and_resolves_active_deployment_changes(monkeypatch):
    deployment = {
        "id": "secret-rotation-deployment",
        "annotations": {"workers/triggered_by": "secret"},
        "versions": [{"percentage": 100, "version_id": "version-2"}],
    }
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *_args: deployment)

    def mismatched_identity(_customer, version_id, _env):
        return {
            "script_etag": "a" * 64 if version_id == "version-1" else "c" * 64,
            "binding_identity": "b" * 64,
        }

    monkeypatch.setattr(release, "cloudflare_worker_version_identity", mismatched_identity)
    with pytest.raises(RuntimeError, match="code or non-secret bindings differ"):
        release.verify_live(
            {"uploadedVersion": "version-1"}, CUSTOMER, REGISTRY, {}, {}, lambda _: None,
            verify_only=True,
        )

    changed_deployment = {
        **deployment,
        "id": "next-secret-rotation",
        "versions": [{"percentage": 100, "version_id": "version-3"}],
    }
    deployments = iter((deployment, changed_deployment, changed_deployment, changed_deployment,
                        changed_deployment, changed_deployment))
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *_args: next(deployments))
    monkeypatch.setattr(release, "cloudflare_worker_version_identity", lambda *_args: {
        "script_etag": "a" * 64, "binding_identity": "b" * 64,
    })
    monkeypatch.setattr(release, "workers_dev_provisioner", lambda *_args: None)
    monkeypatch.setattr(release, "check_health", lambda *_args: {"ok": True, "tenant": "oceanicvibes"})
    monkeypatch.setattr(release, "control_plane_token", lambda *_args: "control-token")
    monkeypatch.setattr(release, "activate_tenant_runtime", lambda *_args: None)
    monkeypatch.setattr(release, "run", lambda *_args: None)
    monkeypatch.setattr(release.time, "sleep", lambda *_args: None)
    result = seed_cron_contract({"tenant": "oceanicvibes", "sourceSha": SHA, "releaseId": "release-1",
              "uploadedVersion": "version-1"})
    stub_canonical_cron_schedule(monkeypatch)

    release.verify_live(result, CUSTOMER, REGISTRY, {}, {}, lambda _: None, verify_only=True)

    assert result["currentVerification"]["workerVersion"] == "version-3"
    assert result["currentVerification"]["deploymentId"] == "next-secret-rotation"


def test_read_only_gate_rejects_worker_change_during_connection_check(monkeypatch):
    stable = {
        "id": "secret-rotation-deployment",
        "annotations": {"workers/triggered_by": "secret"},
        "versions": [{"percentage": 100, "version_id": "version-2"}],
    }
    changed = {
        **stable,
        "id": "next-secret-rotation",
        "versions": [{"percentage": 100, "version_id": "version-3"}],
    }
    active = {"deployment": stable}
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *_args: active["deployment"])
    monkeypatch.setattr(release, "cloudflare_worker_version_identity", lambda *_args: {
        "script_etag": "a" * 64, "binding_identity": "b" * 64,
    })
    stub_canonical_cron_schedule(monkeypatch)
    monkeypatch.setattr(release, "workers_dev_provisioner", lambda *_args: None)
    health_checks = []

    def check_health(*_args):
        health_checks.append(True)
        if len(health_checks) == 1:
            active["deployment"] = changed
        return {"ok": True, "tenant": "oceanicvibes"}

    monkeypatch.setattr(release, "check_health", check_health)
    monkeypatch.setattr(release, "control_plane_token", lambda *_args: "control-token")
    monkeypatch.setattr(release, "activate_tenant_runtime", lambda *_args: None)
    monkeypatch.setattr(release, "run", lambda *_args: None)

    result = seed_cron_contract({
        "tenant": "oceanicvibes", "sourceSha": SHA, "releaseId": "release-1",
        "uploadedVersion": "version-1",
    })
    stub_canonical_cron_schedule(monkeypatch)
    release.verify_live(
        result, CUSTOMER, REGISTRY, {}, {}, lambda name: result.update(stage=name),
        verify_only=True,
    )
    assert len(health_checks) == 2
    assert result["currentVerification"]["workerVersion"] == "version-3"
    assert result["connectionVerifiedAt"]


def test_failed_connection_gate_is_bounded_and_remains_failed(monkeypatch):
    result = seed_cron_contract({"tenant": "oceanicvibes", "sourceSha": SHA, "releaseId": "release-1",
              "uploadedVersion": "version-1"})
    stub_canonical_cron_schedule(monkeypatch)
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *args: {
        "versions": [{"percentage": 100, "version_id": "version-1"}]})
    monkeypatch.setattr(release, "check_health", lambda *args: {"ok": True})
    monkeypatch.setattr(release, "control_plane_token", lambda *_args: "control-token")
    activations = []
    monkeypatch.setattr(release, "activate_tenant_runtime", lambda *args: activations.append(args))
    monkeypatch.setattr(release.time, "sleep", lambda _: None)
    monkeypatch.setattr(release, "run", lambda *args: (_ for _ in ()).throw(RuntimeError("gate failed")))
    with pytest.raises(RuntimeError, match="gate failed"):
        release.verify_live(result, CUSTOMER, REGISTRY,
                            {}, {}, lambda name: result.update(stage=name))
    assert len(activations) == 12
    assert len(result["gateAttempts"]) == 12 and "connectionVerifiedAt" not in result


def test_workers_dev_health_url_must_match_the_cloudflare_account_subdomain(monkeypatch):
    from site_agent.hands import cloudflare_resources

    class Provisioner:
        def __init__(self, account_id, token):
            assert account_id == "a" * 32
            assert token == "token"

        def workers_dev_url(self, worker):
            assert worker == "helloada-demo"
            return "https://helloada-demo.weareheadless.workers.dev"

    monkeypatch.setattr(cloudflare_resources, "CloudflareResourceProvisioner", Provisioner)
    env = {"CLOUDFLARE_ACCOUNT_ID": "a" * 32, "CLOUDFLARE_API_TOKEN": "token"}
    customer = {
        "worker": "helloada-demo",
        "health": "https://helloada-demo.weareheadless.workers.dev/api/health",
    }
    assert isinstance(release.workers_dev_provisioner(customer, env), Provisioner)
    with pytest.raises(RuntimeError, match="does not match the Cloudflare account subdomain"):
        release.workers_dev_provisioner({
            **customer,
            "health": "https://helloada-demo.workers.dev/api/health",
        }, env)
    assert release.workers_dev_provisioner({
        **customer,
        "health": "https://example.com/api/health",
    }, env) is None


@pytest.mark.parametrize("initial_bootstrap", [True, False])
def test_live_verification_enables_only_the_exact_promoted_workers_dev_route(monkeypatch, initial_bootstrap):
    result = seed_cron_contract({"tenant": "demo", "sourceSha": SHA, "releaseId": "release-1",
              "uploadedVersion": "version-1"})
    stub_canonical_cron_schedule(monkeypatch)
    if initial_bootstrap:
        result["initialSchemaHead"] = CUSTOMER["migrationHead"]
    customer = {
        **CUSTOMER,
        "worker": "helloada-demo",
        "health": "https://helloada-demo.weareheadless.workers.dev/api/health",
    }
    for consumer in result["queueConsumers"]["consumers"]:
        consumer["desired"]["script_name"] = customer["worker"]
    monkeypatch.setattr(release, "worker_queue_consumers", lambda queue_id, _env: [{
        **next(item["desired"] for item in result["queueConsumers"]["consumers"]
               if item["queueId"] == queue_id),
        "consumer_id": next(item["consumerId"] for item in result["queueConsumers"]["consumers"]
                             if item["queueId"] == queue_id),
    }])
    calls = []

    class Provisioner:
        def ensure_workers_dev_route(self, worker):
            calls.append(worker)

    monkeypatch.setattr(release, "workers_dev_provisioner", lambda *_args: Provisioner())
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *_args: {
        "versions": [{"percentage": 100, "version_id": "version-1"}],
    })
    monkeypatch.setattr(release, "check_health", lambda *_args: {"ok": True})
    monkeypatch.setattr(release, "control_plane_token", lambda *_args: "control-token")
    activations = []
    monkeypatch.setattr(release, "activate_tenant_runtime", lambda *args: activations.append(args))
    monkeypatch.setattr(release, "run", lambda *_args: None)
    stages = []

    release.verify_live(
        result, customer, REGISTRY,
        {"CLOUDFLARE_API_TOKEN": "token", "CLOUDFLARE_ACCOUNT_ID": "a" * 32}, {}, stages.append,
    )

    assert calls == ["helloada-demo"]
    assert stages.index("enable-workers-dev") < stages.index("verify-connection")
    assert activations == [(
        REGISTRY["connectionGate"]["apiUrl"], "demo", "release-1", SHA, "control-token",
    )]
    assert result["connectionVerifiedAt"]


def test_turnstile_pair_is_written_only_to_the_exact_registered_tenant_env(tmp_path):
    tenant = "oceanicvibes"
    root = tmp_path / "websites"
    tenant_dir = root / tenant
    tenant_dir.mkdir(parents=True)
    config_path = tenant_dir / "config.yaml"
    config_path.write_text(f"instance_name: {tenant}\n", encoding="utf-8")
    env_path = tenant_dir / "tenant.env"
    env_path.write_text(
        "PAYLOAD_SECRET=payload-secret\nPROVISIONED_OCEANICVIBES_TOKEN=site-agent-token\n",
        encoding="utf-8",
    )
    (root / "tenants.json").write_text(json.dumps({
        tenant: {"config_path": str(config_path), "api_token_env": "PROVISIONED_OCEANICVIBES_TOKEN"},
    }), encoding="utf-8")
    host_config = tmp_path / "host.yaml"
    host_config.write_text(f"workspace_api:\n  provisioned_root: {root}\n", encoding="utf-8")
    manifest = {"connectionGate": {"config": str(host_config)}}

    release.write_tenant_environment(manifest, tenant, {
        "HELLOADA_TURNSTILE_SITE_KEY": "public-site-key",
        "HELLOADA_TURNSTILE_SECRET_KEY": "private-site-secret",
    })

    values = release.read_tenant_environment(env_path)
    assert values == {
        "PAYLOAD_SECRET": "payload-secret",
        "PROVISIONED_OCEANICVIBES_TOKEN": "site-agent-token",
        "HELLOADA_TURNSTILE_SITE_KEY": "public-site-key",
        "HELLOADA_TURNSTILE_SECRET_KEY": "private-site-secret",
    }
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_read_only_continuation_requires_mailflare_migration_provenance_to_match_package(tmp_path):
    result, customer = promoted_receipt(tmp_path)
    result["mailflare"]["migrationsSha256"] = "c" * 64
    (tmp_path / "receipt.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="Mailflare migration provenance"):
        release.verification_receipt(tmp_path, "oceanicvibes", SHA, "release-1", customer, "website")


def test_shared_runtime_release_queue_requires_an_exact_fingerprint():
    registry = {"customers": {"demo": {"sharedRuntimeUpdate": "canary"}}}
    valid = {"schema": 1, "releases": {"demo": {
        "id": "runtime-20261010000000-abcd1234",
        "sha": "a" * 40,
        "sharedRuntimeFingerprint": "b" * 64,
    }}}
    queue.validate_queue(valid, registry)

    invalid = {"schema": 1, "releases": {"demo": {
        **valid["releases"]["demo"],
        "sharedRuntimeFingerprint": "short",
    }}}
    with pytest.raises(ValueError, match="SHA-256"):
        queue.validate_queue(invalid, registry)


def test_durable_object_migration_identity_and_release_mode_are_receipt_driven(tmp_path):
    migrations = WORKER_CONFIG["durableObjectMigrations"]
    identity = release.durable_object_migration_identity(migrations)
    assert len(identity) == 64
    assert release.durable_object_migration_identity(json.loads(json.dumps(migrations))) == identity
    assert release.durable_object_migration_identity([]) is None
    assert release.durable_object_migration_identity([{**migrations[0], "tag": "v2"}]) != identity

    tenant_runs = tmp_path / "runs" / "oceanicvibes"
    tenant_runs.mkdir(parents=True)
    assert release.select_worker_rollout_mode(tenant_runs, identity) == ("atomic", None)

    prior_dir = tenant_runs / "runtime-1"
    prior_dir.mkdir()
    prior_path = prior_dir / "receipt.json"
    prior = {
        "releaseId": "runtime-1",
        "durableObjectLifecycle": {
            "identity": identity, "state": "planned", "strategy": "atomic",
        },
    }
    prior_path.write_text(json.dumps(prior))
    assert release.select_worker_rollout_mode(tenant_runs, identity) == ("atomic", None)

    prior["durableObjectLifecycle"]["state"] = "applying"
    prior_path.write_text(json.dumps(prior))
    with pytest.raises(RuntimeError, match="outcome is unresolved"):
        release.select_worker_rollout_mode(tenant_runs, identity)

    prior["durableObjectLifecycle"].update({"state": "applied", "strategy": "atomic"})
    prior_path.write_text(json.dumps(prior))
    assert release.select_worker_rollout_mode(tenant_runs, identity) == ("versioned", "runtime-1")

    from site_agent.application.durable_object_reconciliation import reconciliation_path

    prior.update({
        "tenant": "oceanicvibes",
        "sourceSha": SHA,
        "sharedRuntimeFingerprint": "f" * 64,
        "worker": "oceanicvibes",
        "status": "failed",
        "rolloutMode": "atomic",
    })
    prior["durableObjectLifecycle"].update({"state": "outcome-unknown", "strategy": "atomic"})
    receipt_bytes = (json.dumps(prior, sort_keys=True) + "\n").encode()
    prior_path.write_bytes(receipt_bytes)
    evidence = {
        "schema": 1,
        "tenant": "oceanicvibes",
        "releaseId": "runtime-1",
        "receiptSha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "sourceSha": SHA,
        "sharedRuntimeFingerprint": "f" * 64,
        "migrationIdentity": identity,
        "pipelineSha": "b" * 40,
        "status": "verified",
        "verifiedAt": "2026-10-11T04:00:00+00:00",
        "proof": {
            "deployment": {"id": "new-deployment", "versionId": "new-version", "percentage": 100},
            "version": {"id": "new-version", "releaseSha": SHA, "tenant": "oceanicvibes"},
            "namespace": {
                "id": "namespace-id", "class": "RealtimeHub",
                "name": "oceanicvibes_RealtimeHub", "binding": "MAILFLARE_REALTIME",
            },
            "health": {
                "tenant": "oceanicvibes", "releaseSha": SHA,
                "ok": True, "payloadSchema": "ready",
            },
        },
    }
    evidence_path = reconciliation_path(tmp_path, "oceanicvibes", "runtime-1")
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(json.dumps(evidence))
    assert release.select_worker_rollout_mode(tenant_runs, identity) == ("versioned", "runtime-1")

    assert release.select_worker_rollout_mode(
        tenant_runs, release.durable_object_migration_identity([{**migrations[0], "tag": "v2"}]),
    ) == ("atomic", None)


def test_durable_object_release_mode_rejects_unproven_receipt_states(tmp_path):
    tenant_runs = tmp_path / "runs" / "tenant"
    receipt_dir = tenant_runs / "release-1"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "receipt.json").write_text(json.dumps({
        "releaseId": "release-1",
        "durableObjectLifecycle": {"identity": "a" * 64, "state": "future-state"},
    }))
    with pytest.raises(RuntimeError, match="unknown Durable Object lifecycle state"):
        release.select_worker_rollout_mode(tenant_runs, "a" * 64)


def test_atomic_worker_deploy_bundles_secrets_and_records_same_release_identity(monkeypatch, tmp_path):
    secrets = {"PAYLOAD_SECRET": "payload-secret-for-test"}
    commands = []

    def fake_run(command, cwd, env):
        commands.append(command)
        return "deployed"

    monkeypatch.setattr(release, "run", fake_run)
    release.deploy_worker_with_lifecycle(
        TEMPLATE, SHA, "release-atomic", tmp_path, secrets, {},
        {"HELLOADA_TURNSTILE_SITE_KEY": "turnstile-public-key"},
    )

    command = commands[0]
    secret_path = Path(command[command.index("--secrets-file") + 1])
    assert command == [
        str(TEMPLATE / "node_modules/.bin/opennextjs-cloudflare"), "deploy",
        "--secrets-file", str(secret_path),
        "--var", "HELLOADA_TURNSTILE_SITE_KEY:turnstile-public-key",
        "--var", f"HELLOADA_RELEASE_SHA:{SHA}",
        "--tag", "release-atomic",
    ]
    assert not secret_path.exists()
    assert "payload-secret-for-test" not in " ".join(command)


def test_atomic_worker_deploy_cleans_secrets_when_cloudflare_rejects_it(monkeypatch, tmp_path):
    commands = []

    def fake_run(command, cwd, env):
        commands.append(command)
        raise RuntimeError("atomic deploy failed")

    monkeypatch.setattr(release, "run", fake_run)
    with pytest.raises(RuntimeError, match="atomic deploy failed"):
        release.deploy_worker_with_lifecycle(
            TEMPLATE, SHA, "release-atomic", tmp_path,
            {"PAYLOAD_SECRET": "payload-secret-for-test"}, {},
            {"HELLOADA_TURNSTILE_SITE_KEY": "turnstile-public-key"},
        )

    secret_path = Path(commands[0][commands[0].index("--secrets-file") + 1])
    assert not secret_path.exists()


def test_atomic_deployment_requires_a_new_exact_100_percent_version():
    version_id = "01234567-89ab-cdef-0123-456789abcdef"
    assert release.deployed_worker_version_id(
        {"id": "deployment-new", "versions": [{"percentage": 100, "version_id": version_id}]},
        {"id": "deployment-old"},
    ) == version_id

    with pytest.raises(RuntimeError, match="did not create a new"):
        release.deployed_worker_version_id(
            {"id": "deployment-old", "versions": [{"percentage": 100, "version_id": version_id}]},
            {"id": "deployment-old"},
        )
    with pytest.raises(RuntimeError, match="one version at 100%"):
        release.deployed_worker_version_id(
            {"id": "deployment-new", "versions": [{"percentage": 50, "version_id": version_id}]},
            {"id": "deployment-old"},
        )
    with pytest.raises(RuntimeError, match="exact immutable version"):
        release.deployed_worker_version_id(
            {"id": "deployment-new", "versions": [{"percentage": 100, "version_id": "not-a-uuid"}]},
            {"id": "deployment-old"},
        )

def test_atomic_deployment_waits_for_the_exact_cloudflare_version(monkeypatch):
    version_id = "01234567-89ab-cdef-0123-456789abcdef"
    deployments = iter([
        {"id": "deployment-old", "versions": [{"percentage": 100, "version_id": "11111111-1111-1111-1111-111111111111"}]},
        {"id": "deployment-new", "versions": [{"percentage": 100, "version_id": version_id}]},
    ])
    monkeypatch.setattr(release, "cloudflare_deployment", lambda *_args: next(deployments))
    monkeypatch.setattr(release.time, "sleep", lambda _seconds: None)

    deployment, selected_version = release.wait_for_atomic_worker_version(
        CUSTOMER, {}, {"id": "deployment-old"},
    )

    assert deployment["id"] == "deployment-new"
    assert selected_version == version_id

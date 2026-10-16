from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from site_agent.application.shared_runtime import (
    SharedRuntimeError,
    apply_shared_runtime_overlay,
    shared_package_versions,
    shared_runtime_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/site_agent/templates/next-payload"
CUSTOMER = {
    "tenantId": "oceanicvibes",
    "worker": "oceanicvibes",
    "payloadAdmin": "0.10.11",
    "payloadCore": "0.5.7",
    "contentContract": "helloada-content-v3",
    "schemaRevision": 7,
    "schemaIdentity": "a" * 64,
    "migrationHead": "b" * 64,
    "d1DatabaseId": "9496d871-ab28-42ee-9d38-3f38471f953d",
    "d1DatabaseName": "oceanicvibes-content",
    "mailflareD1DatabaseId": "5e503625-c5a5-4a9a-ad28-be26dd602fd7",
    "mailflareD1DatabaseName": "helloada-oceanicvibes-mail",
    "r2BucketName": "helloada-oceanicvibes-media",
    "privateEmailR2BucketName": "helloada-oceanicvibes-email",
    "mailflareR2BucketName": "helloada-oceanicvibes-mail-files",
    "mailflareInboundQueueName": "helloada-oceanicvibes-mail-inbound",
    "mailflareOutboundQueueName": "helloada-oceanicvibes-mail-outbound",
    "mailflareAgentQueueName": "helloada-oceanicvibes-mail-agent",
}


def _tenant_checkout(root: Path) -> Path:
    checkout = root / "tenant"
    shutil.copytree(TEMPLATE, checkout)
    config_path = checkout / "wrangler.jsonc"
    config = json.loads(config_path.read_text())
    config["name"] = CUSTOMER["worker"]
    config["routes"] = [{"pattern": "oceanicvibes.com", "custom_domain": True}]
    config["vars"].update({
        "SITE_AGENT_URL": "https://api.helloada.app/v1",
        "NEXT_PUBLIC_SITE_URL": "https://oceanicvibes.com",
        "HELLOADA_TENANT_ID": CUSTOMER["tenantId"],
        "HELLOADA_SITE_NAME": "OceanicVibes",
        "CUSTOM_TENANT_VAR": "keep-me",
        "HELLOADA_MESSAGES_QUEUE_NAME": "legacy-messages",
        "HELLOADA_MESSAGES_DLQ_NAME": "legacy-dead-letter",
    })
    config["d1_databases"] = [config["d1_databases"][0]]
    config["d1_databases"][0].update(
        database_id=CUSTOMER["d1DatabaseId"],
        database_name=CUSTOMER["d1DatabaseName"],
    )
    config["r2_buckets"] = config["r2_buckets"][:2]
    config["r2_buckets"][0]["bucket_name"] = CUSTOMER["r2BucketName"]
    config["r2_buckets"][1]["bucket_name"] = CUSTOMER["privateEmailR2BucketName"]
    config["r2_buckets"][1]["preview_bucket_name"] = CUSTOMER["privateEmailR2BucketName"]
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    (checkout / "src/app/api/helloada/bookings").mkdir(parents=True)
    (checkout / "src/app/api/helloada/bookings/route.ts").write_text("legacy")
    (checkout / "src/components/site").mkdir(parents=True, exist_ok=True)
    (checkout / "src/components/site/TenantSections.tsx").write_text("tenant design")
    (checkout / "src/migrations").mkdir(parents=True, exist_ok=True)
    (checkout / "src/migrations/tenant-migration.ts").write_text("tenant migration")
    return checkout


def test_shared_overlay_updates_runtime_and_preserves_tenant_owned_content(tmp_path: Path):
    checkout = _tenant_checkout(tmp_path)
    preview_path = checkout / "src/app/(frontend)/helloada-preview/[token]/page.tsx"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text("tenant-specific preview renderer")
    preview_renderer_path = checkout / "src/lib/helloada-preview-renderer.tsx"
    preview_renderer_path.write_text("tenant-specific preview adapter")
    preview_renderer_before = preview_renderer_path.read_bytes()
    manifest_before = (checkout / "template-manifest.json").read_bytes()
    design_before = (checkout / "src/components/site/TenantSections.tsx").read_bytes()
    migration_before = (checkout / "src/migrations/tenant-migration.ts").read_bytes()

    result = apply_shared_runtime_overlay(
        ROOT,
        checkout,
        CUSTOMER,
        shared_vars={"HELLOADA_HANDOFF_PUBLIC_KEY": "public-key"},
    )

    config = json.loads((checkout / "wrangler.jsonc").read_text())
    assert config["name"] == CUSTOMER["worker"]
    assert config["routes"] == [{"pattern": "oceanicvibes.com", "custom_domain": True}]
    assert config["vars"]["HELLOADA_TENANT_ID"] == CUSTOMER["tenantId"]
    assert config["vars"]["HELLOADA_HANDOFF_PUBLIC_KEY"] == "public-key"
    assert config["vars"]["CUSTOM_TENANT_VAR"] == "keep-me"
    assert "HELLOADA_MESSAGES_QUEUE_NAME" not in config["vars"]
    assert "HELLOADA_MESSAGES_DLQ_NAME" not in config["vars"]
    assert config["d1_databases"][0]["database_id"] == CUSTOMER["d1DatabaseId"]
    assert config["d1_databases"][1]["database_id"] == CUSTOMER["mailflareD1DatabaseId"]
    assert config["r2_buckets"][0]["bucket_name"] == CUSTOMER["r2BucketName"]
    assert config["r2_buckets"][1]["bucket_name"] == CUSTOMER["privateEmailR2BucketName"]
    assert config["r2_buckets"][2]["bucket_name"] == CUSTOMER["mailflareR2BucketName"]
    assert [item["queue"] for item in config["queues"]["producers"]] == [
        CUSTOMER["mailflareInboundQueueName"],
        CUSTOMER["mailflareOutboundQueueName"],
        CUSTOMER["mailflareAgentQueueName"],
    ]
    assert not (checkout / "src/app/api/helloada/bookings/route.ts").exists()
    assert (checkout / "worker.ts").read_bytes() == (TEMPLATE / "worker.ts").read_bytes()
    assert (checkout / "src/lib/cloudflare-context.ts").read_bytes() == (TEMPLATE / "src/lib/cloudflare-context.ts").read_bytes()
    assert (checkout / "src/app/api/workspace/growth/[...path]/route.ts").read_bytes() == (TEMPLATE / "src/app/api/workspace/growth/[...path]/route.ts").read_bytes()
    assert (checkout / "src/lib/growth-operations.ts").read_bytes() == (TEMPLATE / "src/lib/growth-operations.ts").read_bytes()
    assert "src/lib/cloudflare-context.ts" in result["changedPaths"]
    assert (checkout / "template-manifest.json").read_bytes() == manifest_before
    assert (checkout / "src/components/site/TenantSections.tsx").read_bytes() == design_before
    assert preview_path.read_bytes() == (TEMPLATE / "src/app/(frontend)/helloada-preview/[token]/page.tsx").read_bytes()
    assert "src/app/(frontend)/helloada-preview/[token]/page.tsx" in result["copiedPaths"]
    assert preview_renderer_path.read_bytes() == preview_renderer_before
    assert "src/lib/helloada-preview-renderer.tsx" not in result["copiedPaths"]
    assert (checkout / "src/migrations/tenant-migration.ts").read_bytes() == migration_before
    package = json.loads((checkout / "package.json").read_text())
    manifest = json.loads((TEMPLATE / "template-manifest.json").read_text())
    admin_version = manifest["payloadAdmin"]
    assert f"payload-admin-v{admin_version}" in package["dependencies"]["@weareheadless/helloada-payload-admin"]
    assert result["payloadAdmin"] == admin_version
    assert len(result["fingerprint"]) == 64
    assert "worker.ts" in result["changedPaths"]
    assert "template-manifest.json" in result["changedPaths"]
    assert "helloada-content-contract.json" in result["changedPaths"]


def test_shared_package_versions_are_taken_from_pinned_canonical_lock():
    versions = shared_package_versions(ROOT)

    manifest = json.loads((TEMPLATE / "template-manifest.json").read_text())

    assert versions == {"@weareheadless/helloada-payload-admin": manifest["payloadAdmin"],
                        "@weareheadless/helloada-payload-core": manifest["payloadCore"]}


def test_runtime_fingerprint_covers_contract_generator_and_payload_schema_source(tmp_path: Path):
    control = tmp_path / "control"
    overlay_source = ROOT / "deploy/shared-runtime-overlay.json"
    overlay = json.loads(overlay_source.read_text())
    (control / "deploy").mkdir(parents=True)
    shutil.copyfile(overlay_source, control / "deploy/shared-runtime-overlay.json")

    (control / "src/site_agent/application").mkdir(parents=True)
    shutil.copyfile(ROOT / "src/site_agent/application/shared_runtime.py",
                    control / "src/site_agent/application/shared_runtime.py")
    (control / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/generate-payload-contract.mjs",
                    control / "scripts/generate-payload-contract.mjs")
    (control / "pyproject.toml").write_text('[project]\\nversion = "0.0.0"\\n')

    template = control / "src/site_agent/templates/next-payload"
    for name in ("package.json", "package-lock.json", "wrangler.jsonc"):
        target = template / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATE / name, target)
    for relative in overlay["copy"]:
        target = template / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("runtime")
    for tree in overlay["fingerprintTrees"]:
        target = control / tree / "fingerprint-source.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("schema")

    original = shared_runtime_fingerprint(control)
    generator = control / "scripts/generate-payload-contract.mjs"
    generator.write_text(generator.read_text() + "\\n// changed")
    assert shared_runtime_fingerprint(control) != original

    generator.write_text((ROOT / "scripts/generate-payload-contract.mjs").read_text())
    schema_source = control / "packages/helloada-payload-core/src/fingerprint-source.ts"
    schema_source.write_text("changed schema")
    assert shared_runtime_fingerprint(control) != original


def test_shared_overlay_rejects_wrong_tenant_resource_identity(tmp_path: Path):
    checkout = _tenant_checkout(tmp_path)
    wrong = {**CUSTOMER, "d1DatabaseId": "00000000-0000-0000-0000-000000000001"}

    with pytest.raises(SharedRuntimeError, match="Payload D1 identity"):
        apply_shared_runtime_overlay(
            ROOT,
            checkout,
            wrong,
            shared_vars={"HELLOADA_HANDOFF_PUBLIC_KEY": "public-key"},
        )

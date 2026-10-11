from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from site_agent.application.shared_runtime import (
    SharedRuntimeError,
    apply_shared_runtime_overlay,
    shared_package_versions,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/site_agent/templates/next-payload"
CUSTOMER = {
    "tenantId": "oceanicvibes",
    "worker": "oceanicvibes",
    "payloadAdmin": "0.10.9",
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
    (checkout / "src/components/site").mkdir(parents=True)
    (checkout / "src/components/site/TenantSections.tsx").write_text("tenant design")
    (checkout / "src/migrations").mkdir(parents=True)
    (checkout / "src/migrations/tenant-migration.ts").write_text("tenant migration")
    return checkout


def test_shared_overlay_updates_runtime_and_preserves_tenant_owned_content(tmp_path: Path):
    checkout = _tenant_checkout(tmp_path)
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
    assert (checkout / "template-manifest.json").read_bytes() == manifest_before
    assert (checkout / "src/components/site/TenantSections.tsx").read_bytes() == design_before
    assert (checkout / "src/migrations/tenant-migration.ts").read_bytes() == migration_before
    package = json.loads((checkout / "package.json").read_text())
    assert "payload-admin-v0.10.9" in package["dependencies"]["@weareheadless/helloada-payload-admin"]
    assert result["payloadAdmin"] == "0.10.9"
    assert len(result["fingerprint"]) == 64
    assert "worker.ts" in result["changedPaths"]


def test_shared_package_versions_are_taken_from_pinned_canonical_lock():
    versions = shared_package_versions(ROOT)

    assert versions == {"@weareheadless/helloada-payload-admin": "0.10.9",
                        "@weareheadless/helloada-payload-core": "0.5.7"}


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

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
    upstream_path = checkout / "src/lib/helloada-upstream.ts"
    upstream_path.write_text("export function upstreamHeaders(request, path) {}")
    public_wrappers = (
        "src/components/PublicDocument.tsx",
        "src/app/(frontend)/[[...slug]]/page.tsx",
    )
    for relative in public_wrappers:
        (checkout / relative).write_text("tenant-approved routing and presentation adapter")
    preview_path = checkout / "src/app/(frontend)/helloada-preview/[token]/page.tsx"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text("tenant-specific preview renderer")
    preview_renderer_path = checkout / "src/lib/helloada-preview-renderer.tsx"
    preview_renderer_path.write_text("tenant-specific preview adapter")
    preview_renderer_before = preview_renderer_path.read_bytes()
    manifest_before = (checkout / "template-manifest.json").read_bytes()
    design_before = (checkout / "src/components/site/TenantSections.tsx").read_bytes()
    migration_before = (checkout / "src/migrations/tenant-migration.ts").read_bytes()

    canonical_customer = {**CUSTOMER, "payloadAdmin": "0.10.44", "payloadCore": "0.5.9"}
    result = apply_shared_runtime_overlay(
        ROOT,
        checkout,
        canonical_customer,
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
    for relative in (
        "src/app/api/helloada/admin-entry/route.ts",
        "src/app/api/helloada/handoff/route.ts",
        "src/lib/helloada-handoff.ts",
        "src/lib/helloada-admin-entry.ts",
        "src/lib/helloada-upstream.ts",
        "src/components/platform/PublicRevision.tsx",
        "src/lib/public-revision.ts",
        "src/lib/runtime-env.ts",
    ):
        assert (checkout / relative).read_bytes() == (TEMPLATE / relative).read_bytes()
        assert relative in result["copiedPaths"]
    assert (checkout / "src/lib/cloudflare-context.ts").read_bytes() == (TEMPLATE / "src/lib/cloudflare-context.ts").read_bytes()
    assert (checkout / "src/app/api/workspace/growth/[...path]/route.ts").read_bytes() == (TEMPLATE / "src/app/api/workspace/growth/[...path]/route.ts").read_bytes()
    assert (checkout / "src/lib/growth-operations.ts").read_bytes() == (TEMPLATE / "src/lib/growth-operations.ts").read_bytes()
    assert "src/lib/cloudflare-context.ts" in result["changedPaths"]
    assert (checkout / "template-manifest.json").read_bytes() == manifest_before
    assert (checkout / "src/components/site/TenantSections.tsx").read_bytes() == design_before
    for relative in public_wrappers:
        assert (checkout / relative).read_text() == "tenant-approved routing and presentation adapter"
        assert relative not in result["copiedPaths"]
    assert preview_path.read_bytes() == (TEMPLATE / "src/app/(frontend)/helloada-preview/[token]/page.tsx").read_bytes()
    assert "src/app/(frontend)/helloada-preview/[token]/page.tsx" in result["copiedPaths"]
    assert preview_renderer_path.read_bytes() == preview_renderer_before
    assert "src/lib/helloada-preview-renderer.tsx" not in result["copiedPaths"]
    assert (checkout / "src/migrations/tenant-migration.ts").read_bytes() == migration_before
    package = json.loads((checkout / "package.json").read_text())
    lock = json.loads((checkout / "package-lock.json").read_text())
    manifest = json.loads((TEMPLATE / "template-manifest.json").read_text())
    admin_version = manifest["payloadAdmin"]
    admin_url = (
        "https://github.com/weareheadless/site-agent/releases/download/"
        "payload-admin-v0.10.44/weareheadless-helloada-payload-admin-0.10.44.tgz"
    )
    assert admin_version == "0.10.44"
    assert package["dependencies"]["@weareheadless/helloada-payload-admin"] == admin_url
    assert lock["packages"][""]["dependencies"]["@weareheadless/helloada-payload-admin"] == admin_url
    assert lock["packages"]["node_modules/@weareheadless/helloada-payload-admin"] == {
        **lock["packages"]["node_modules/@weareheadless/helloada-payload-admin"],
        "version": "0.10.44",
        "resolved": admin_url,
        "integrity": "sha512-r+6ZFb061ivZlnalTCpSAfPyfSHb2WUrcmjS0IiP6x5NlN9RVlTKwFc3uHq+aWrmg6X8Dv5xL6Mzbb5+giwEQg==",
    }
    assert manifest["payloadCore"] == canonical_customer["payloadCore"]
    assert config["vars"]["HELLOADA_PAYLOAD_ADMIN_VERSION"] == "0.10.44"
    assert config["vars"]["HELLOADA_PAYLOAD_CORE_VERSION"] == "0.5.9"
    assert manifest["migrationHead"] == "63a934836e0868ac7cdea4716bb9a0935708399567e219bac6346950325deb9a"
    assert manifest["contentContract"] == "helloada-content-v4"
    assert manifest["schemaRevision"] == 8
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

    schema_source.write_text("schema")
    lockfile = template / "package-lock.json"
    lock = json.loads(lockfile.read_text())
    lock["packages"]["node_modules/@weareheadless/helloada-payload-admin"]["resolved"] += "?changed"
    lockfile.write_text(json.dumps(lock))
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


def test_overlay_requires_matching_actual_runtime_fingerprint_before_writes(tmp_path: Path):
    checkout = _tenant_checkout(tmp_path)
    before = {p.relative_to(checkout).as_posix(): p.read_bytes() for p in checkout.rglob("*") if p.is_file()}
    control = tmp_path / "control"
    shutil.copytree(ROOT, control, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
    actual = shared_runtime_fingerprint(control)
    with pytest.raises(SharedRuntimeError, match="does not match"):
        apply_shared_runtime_overlay(control, checkout, CUSTOMER,
            shared_vars={"HELLOADA_HANDOFF_PUBLIC_KEY": "public-key"}, expected_fingerprint="0" * 64)
    after = {p.relative_to(checkout).as_posix(): p.read_bytes() for p in checkout.rglob("*") if p.is_file()}
    assert after == before
    source = control / "src/site_agent/templates/next-payload/worker.ts"
    source.write_bytes(source.read_bytes() + b"// tampered")
    with pytest.raises(SharedRuntimeError, match="does not match"):
        apply_shared_runtime_overlay(control, checkout, CUSTOMER,
            shared_vars={"HELLOADA_HANDOFF_PUBLIC_KEY": "public-key"}, expected_fingerprint=actual)


def test_overlay_fingerprint_matching_and_omitted_expected(tmp_path: Path):
    actual = shared_runtime_fingerprint(ROOT)
    for expected in (actual, None):
        checkout = _tenant_checkout(tmp_path / str(expected is None))
        result = apply_shared_runtime_overlay(ROOT, checkout, CUSTOMER,
            shared_vars={"HELLOADA_HANDOFF_PUBLIC_KEY": "public-key"}, expected_fingerprint=expected)
        assert result["fingerprint"] == actual


def test_overlay_rejects_malformed_expected_fingerprint_before_writes(tmp_path: Path):
    checkout = _tenant_checkout(tmp_path)
    before = {p.relative_to(checkout).as_posix(): p.read_bytes() for p in checkout.rglob("*") if p.is_file()}
    with pytest.raises(SharedRuntimeError, match="invalid"):
        apply_shared_runtime_overlay(ROOT, checkout, CUSTOMER,
            shared_vars={"HELLOADA_HANDOFF_PUBLIC_KEY": "public-key"}, expected_fingerprint="not-a-hash")
    assert {p.relative_to(checkout).as_posix(): p.read_bytes() for p in checkout.rglob("*") if p.is_file()} == before

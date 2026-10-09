from __future__ import annotations

import json
from pathlib import Path

import pytest

from site_agent.payload_contract import _MIGRATION_NAME, PayloadContractError, validate_payload_migrations


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/site_agent/templates/next-payload"


def test_canonical_template_migration_chain_is_hash_pinned():
    manifest = validate_payload_migrations(TEMPLATE)
    assert manifest["migrations"]
    assert len(manifest["migrationHead"]) == 64


def test_canonical_migration_snapshots_are_valid_and_mailbox_precedes_calendar():
    manifest = json.loads((TEMPLATE / "template-manifest.json").read_text())
    snapshots = {}
    for migration in manifest["migrations"]:
        snapshot_path = TEMPLATE / "src/migrations" / f"{migration['name']}.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert snapshot.get("dialect") == "sqlite"
        assert isinstance(snapshot.get("tables"), dict)
        snapshots[migration["name"]] = snapshot

    owner_handoff = "20261006_061835_helloada_owner_handoff"
    calendar = "20261009_123644_helloada_mailbox_calendar"
    names = [migration["name"] for migration in manifest["migrations"]]
    assert names.index(owner_handoff) < names.index(calendar)
    mailbox_tables = snapshots[owner_handoff]["tables"]
    assert {"contacts", "messages", "message_mailbox"} <= mailbox_tables.keys()
    calendar_tables = snapshots[calendar]["tables"]
    assert {"appointment_types", "calendar_events", "calendar_slot_locks"} <= calendar_tables.keys()


@pytest.mark.parametrize(("name", "valid"), [
    ("20260917_050948", True),
    ("20261004_080109_helloada_shared_schema_additive", True),
    ("20261004_080109_", False),
    ("2026104_080109", False),
])
def test_payload_migration_names_accept_timestamp_only_or_labeled_forms(name, valid):
    assert bool(_MIGRATION_NAME.fullmatch(name)) is valid


@pytest.mark.parametrize("relative", [
    "src/migrations/20261004_021536_helloada_initial.ts",
    "src/migrations/20261004_021536_helloada_initial.json",
    "src/migrations/index.ts",
])
def test_modified_migration_artifact_fails_without_regeneration(tmp_path, relative):
    site = tmp_path / "site"
    from site_agent.site_scaffold import initialize_managed_site

    initialize_managed_site(site)
    target = site / relative
    target.write_bytes(target.read_bytes() + b"\n// unauthorised schema change\n")

    with pytest.raises(PayloadContractError, match="hash|identity|index"):
        validate_payload_migrations(site)


def test_manifest_cannot_claim_a_different_migration_head():
    manifest = json.loads((TEMPLATE / "template-manifest.json").read_text())
    manifest["migrationHead"] = "0" * 64
    with pytest.raises(PayloadContractError, match="chain identity"):
        validate_payload_migrations(TEMPLATE, manifest)

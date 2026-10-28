#!/usr/bin/env python3
"""One-time operator migration for the Astrid intake revision from UI-053.

Run with an explicit registered tenant database path. This intentionally does
not resolve tenants or credentials and never connects to production itself.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from site_agent.core.design_contracts import SiteIntake, canonical_json  # noqa: E402
from site_agent.core.design_intake_contracts import (  # noqa: E402
    DesignIntakeDraft,
    migrate_legacy_contact_destination,
)

TENANT_ID = "site-5fe73d3d38ff6f77"
SESSION_ID = "intake-befc1a0c416a48d3b9cc6074557aa5bb"
REVISION = 13
def _converted(raw: str) -> tuple[str, str, bool]:
    draft = DesignIntakeDraft.from_dict(json.loads(raw))
    migrated = migrate_legacy_contact_destination(draft)
    changed = (
        "contact_destination" in draft.fields.get("conversion", {})
        or "conversion.contact_destination" in draft.provenance
        or any(item.path == "conversion.contact_destination" for item in (*draft.assumptions, *draft.deferred, *draft.contradictions))
    )
    return canonical_json(migrated.to_dict()), migrated.content_hash, changed


def _converted_intake(raw: str) -> tuple[str, str, bool]:
    data = json.loads(raw or "{}")
    conversion = data.get("conversion") if isinstance(data, dict) else None
    if not isinstance(conversion, dict) or "contact_destination" not in conversion:
        return raw, "", False
    legacy = conversion.pop("contact_destination")
    temporary = DesignIntakeDraft.from_dict({
        "schema_version": 1,
        "fields": {"conversion": {"contact_destination": legacy}},
        "provenance": {"conversion.contact_destination": {
            "origin": "confirmed", "note": "Imported from confirmed SiteIntake provenance."
        }},
        "assumptions": [], "deferred": [], "contradictions": [], "open_topics": [], "assets": [],
    })
    migrated_draft = migrate_legacy_contact_destination(temporary)
    split = migrated_draft.fields["conversion"]
    conversion.update(split)
    split_values = {key: value for key, value in split.items() if key in {"whatsapp_url", "instagram_url"}}

    def carry_dispositions(items: object) -> object:
        if not isinstance(items, list):
            return items
        output = [item for item in items if not isinstance(item, dict) or item.get("path") != "conversion.contact_destination"]
        for key, value in split_values.items():
            output.extend(
                {**item, "path": f"conversion.{key}", "value": value if item.get("value") is not None else None}
                for item in items
                if isinstance(item, dict) and item.get("path") == "conversion.contact_destination"
            )
        return output

    design = data.get("design")
    if isinstance(design, dict):
        design["assumptions"] = carry_dispositions(design.get("assumptions", []))
        design["deferred"] = carry_dispositions(design.get("deferred", []))
        provenance = design.get("provenance")
        if isinstance(provenance, dict):
            source = provenance.pop("conversion.contact_destination", None)
            if isinstance(source, dict):
                for key in split_values:
                    provenance[f"conversion.{key}"] = {**source, "path": f"conversion.{key}"}
    provenance = data.get("provenance")
    if isinstance(provenance, dict):
        provenance["assumptions"] = carry_dispositions(provenance.get("assumptions", []))
        provenance["deferred"] = carry_dispositions(provenance.get("deferred", []))
    intake = SiteIntake.from_dict(data)
    return canonical_json(intake.to_dict()), intake.content_hash, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, choices=[TENANT_ID])
    parser.add_argument("--db", required=True, type=Path, help="registered tenant memory.db")
    args = parser.parse_args()
    if not args.db.is_file():
        raise SystemExit("registered tenant database does not exist")
    migrated_drafts = migrated_intakes = 0
    with sqlite3.connect(args.db) as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT revision, draft_json, site_intake_json FROM design_intake_revisions WHERE session_id=? ORDER BY revision",
            (SESSION_ID,),
        ).fetchall()
        if not any(int(row[0]) == REVISION for row in rows):
            raise SystemExit("target revision not found")
        for revision, draft_json, intake_json in rows:
            migrated, draft_hash, draft_changed = _converted(draft_json)
            intake, intake_hash, intake_changed = _converted_intake(intake_json)
            if draft_changed or intake_changed:
                summary = canonical_json(DesignIntakeDraft.from_dict(json.loads(migrated)).summary().to_dict()) if draft_changed else None
                db.execute(
                    "UPDATE design_intake_revisions SET draft_json=?, draft_hash=?, site_intake_json=?, site_intake_hash=CASE WHEN ? THEN ? ELSE site_intake_hash END, summary_json=CASE WHEN ? IS NULL THEN summary_json ELSE ? END WHERE session_id=? AND revision=?",
                    (migrated, draft_hash, intake if intake_changed else intake_json,
                     int(intake_changed), intake_hash, summary, summary,
                     SESSION_ID, revision),
                )
                migrated_drafts += int(draft_changed)
                migrated_intakes += int(intake_changed)
        session_row = db.execute(
            "SELECT revision, draft_json FROM design_intake_sessions WHERE session_id=?", (SESSION_ID,)
        ).fetchone()
        if session_row is None:
            raise SystemExit("target intake session not found")
        session_draft, session_hash, session_changed = _converted(session_row[1])
        if session_changed:
            db.execute(
                "UPDATE design_intake_sessions SET draft_json=?, draft_hash=?, confirmed_hash=CASE WHEN confirmed_revision=revision THEN ? ELSE confirmed_hash END WHERE session_id=?",
                (session_draft, session_hash, session_hash, SESSION_ID),
            )
            migrated_drafts += 1
    print(
        f"Migration complete: tenant={TENANT_ID} session={SESSION_ID} target_revision={REVISION} "
        f"drafts_migrated={migrated_drafts} site_intakes_migrated={migrated_intakes}."
    )


if __name__ == "__main__":
    main()

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
from site_agent.core.design_intake_contracts import DesignIntakeDraft, IntakeFieldProvenance  # noqa: E402

TENANT_ID = "site-5fe73d3d38ff6f77"
SESSION_ID = "intake-befc1a0c416a48d3b9cc6074557aa5bb"
REVISION = 13
OLD_VALUE = "+52 228 107 4716 · https://www.instagram.com/astriid_rincon"


def _converted(raw: str) -> tuple[str, str]:
    draft_raw = json.loads(raw)
    fields = draft_raw["fields"]
    conversion = fields["conversion"]
    if "contact_destination" not in conversion:
        if conversion.get("whatsapp_url") == "https://wa.me/522281077146" and conversion.get("instagram_url") == "https://instagram.com/astriid_rincon":
            return raw, DesignIntakeDraft.from_dict(draft_raw).content_hash
        raise ValueError("revision has no expected compound contact_destination")
    if conversion["contact_destination"] != OLD_VALUE:
        raise ValueError("revision contact_destination does not match the approved source value")
    conversion.pop("contact_destination")
    conversion["whatsapp_url"] = "https://wa.me/522281077146"
    conversion["instagram_url"] = "https://instagram.com/astriid_rincon"
    provenance = draft_raw.setdefault("provenance", {})
    source = provenance.pop("conversion.contact_destination", None)
    if not isinstance(source, dict):
        raise ValueError("source destination provenance is missing")
    for path, detail in (
        ("conversion.whatsapp_url", "Normalized from the phone number in the confirmed compound destination."),
        ("conversion.instagram_url", "Normalized from the Instagram URL in the confirmed compound destination."),
    ):
        provenance[path] = {**source, "path": path, "note": detail}
    draft = DesignIntakeDraft.from_dict(draft_raw)
    new = draft.to_dict()
    return json.dumps(new, ensure_ascii=False, sort_keys=True, separators=(",", ":")), draft.content_hash


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, choices=[TENANT_ID])
    parser.add_argument("--db", required=True, type=Path, help="registered tenant memory.db")
    args = parser.parse_args()
    with sqlite3.connect(args.db) as db:
        row = db.execute(
            "SELECT draft_json FROM design_intake_revisions WHERE session_id=? AND revision=?",
            (SESSION_ID, REVISION),
        ).fetchone()
        if row is None:
            raise SystemExit("target revision not found")
        migrated, content_hash = _converted(row[0])
        if migrated != row[0]:
            db.execute(
                "UPDATE design_intake_revisions SET draft_json=?, draft_hash=? WHERE session_id=? AND revision=?",
                (migrated, content_hash, SESSION_ID, REVISION),
            )
            session = db.execute(
                "SELECT revision FROM design_intake_sessions WHERE session_id=?", (SESSION_ID,)
            ).fetchone()
            if session and int(session[0]) == REVISION:
                db.execute(
                    "UPDATE design_intake_sessions SET draft_json=?, draft_hash=? WHERE session_id=?",
                    (migrated, content_hash, SESSION_ID),
                )
    print(f"Migrated {TENANT_ID} {SESSION_ID} revision {REVISION} (or already migrated).")


if __name__ == "__main__":
    main()

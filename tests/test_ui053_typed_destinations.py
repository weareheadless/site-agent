import json
import runpy
from pathlib import Path

import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.design_intake_contracts import (
    DesignIntakeDraft, IntakeFieldProvenance, IntakeTurnResult, merge_intake_turn,
    allowed_intake_field_paths,
)


def _intake(**conversion):
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {"name": "Studio", "offer_summary": "Design", "primary_services": ["Design"]},
        "audience": {"primary": "People"},
        "conversion": {"primary_action": "Contact", **conversion},
        "brand": {"voice": "Warm"}, "site": {"required_pages": ["index.html"]},
    })


@pytest.mark.parametrize("raw,expected", [
    ("+52 228 107 4716", "https://wa.me/522281074716"),
    ("(415) 555-2671", "https://wa.me/4155552671"),
    ("@Astriid_Rincon", "https://instagram.com/astriid_rincon"),
    ("astriid_rincon", "https://instagram.com/astriid_rincon"),
    ("https://www.instagram.com/Astriid_Rincon/", "https://instagram.com/astriid_rincon"),
])
def test_destination_values_are_normalized_during_intake_merge(raw, expected):
    path = "conversion.whatsapp_url" if raw.startswith(("+", "(", "1")) else "conversion.instagram_url"
    turn = IntakeTurnResult.from_dict({"schema_version": 1, "assistant_message": "Recorded.", "field_updates": [{
        "path": path, "value": raw, "basis": "owner_statement",
    }]})
    merged = merge_intake_turn(DesignIntakeDraft.empty(), turn, source_message_id=7)
    assert merged.value(path) == expected
    assert merged.provenance[path].source_message_id == 7


@pytest.mark.parametrize("key,value", [
    ("whatsapp_url", "15551234567"),
    ("whatsapp_url", "http://wa.me/15551234567"),
    ("whatsapp_url", "https://example.com/15551234567"),
    ("instagram_url", "@handle"),
    ("instagram_url", "http://instagram.com/handle"),
    ("instagram_url", "https://example.com/handle"),
])
def test_site_intake_rejects_non_absolute_or_off_host_destinations(key, value):
    with pytest.raises(ContractError):
        _intake(**{key: value})


def test_site_intake_accepts_only_allowed_https_destinations():
    assert _intake(whatsapp_url="https://api.whatsapp.com/send?phone=15551234567").conversion["whatsapp_url"]
    assert _intake(instagram_url="https://instagram.com/a_handle").conversion["instagram_url"]


def test_compound_free_text_destination_is_no_longer_an_allowed_model_output():
    assert "conversion.contact_destination" not in allowed_intake_field_paths()
    with pytest.raises(ContractError, match="allowed intake field"):
        IntakeTurnResult.from_dict({"schema_version": 1, "field_updates": [{
            "path": "conversion.contact_destination", "value": "+52 ... · instagram", "basis": "owner_statement",
        }]})
    with pytest.raises(ContractError, match="retired"):
        _intake(contact_destination="+52 ... · instagram")


def test_astrid_revision_migration_splits_and_is_idempotent():
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/migrate_ui053_contact_destinations.py"))
    provenance = {"conversion.contact_destination": {"path": "conversion.contact_destination", "origin": "confirmed", "source_message_id": 41, "note": "Owner gave both."}}
    raw = json.dumps({"schema_version": 1, "fields": {"conversion": {"contact_destination": "+52 228 107 4716 · https://www.instagram.com/astriid_rincon"}}, "provenance": provenance, "assumptions": [], "deferred": [], "contradictions": [], "open_topics": [], "assets": []})
    converted, _ = module["_converted"](raw)
    result = json.loads(converted)
    assert result["fields"]["conversion"] == {"whatsapp_url": "https://wa.me/522281077146", "instagram_url": "https://instagram.com/astriid_rincon"}
    assert result["provenance"]["conversion.whatsapp_url"]["source_message_id"] == 41
    assert result["provenance"]["conversion.instagram_url"]["source_message_id"] == 41
    assert module["_converted"](converted)[0] == converted

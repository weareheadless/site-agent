import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.incubation_contracts import CreativeEpisode, IncubationStatus
from site_agent.core.intake_ada_store import IntakeAdaStore


def _episode(episode_id="episode_a"):
    return CreativeEpisode.from_dict({
        "schema_version": 1,
        "episode_id": episode_id,
        "created_at": "2026-09-02T12:00:00+00:00",
        "engagement_outcome": "accepted",
        "design_fingerprint": {
            "layout_topology": ["single_focus", "stacked_sections"],
            "type_roles": ["editorial_display", "neutral_text"],
            "palette_shape": ["ink", "mist", "one_accent"],
            "motion_patterns": ["quiet_reveal"],
            "navigation_pattern": "compact_primary",
            "component_rhythm": ["wide_narrow_wide"],
        },
        "copy_fingerprint": {
            "opening_pattern": "specific_promise",
            "section_rhythm": ["promise", "proof", "next_step"],
            "cta_pattern": "single_clear_action",
            "repeated_motifs": ["plain_language"],
        },
        "quality": {"accepted": True, "critic_categories": ["clarity"], "revision_count": 2},
        "reflection": {
            "habits_repeated": ["stacked_sections"],
            "departures_that_worked": ["single_focus"],
            "approaches_to_avoid": ["generic_hero"],
            "techniques_to_reuse_carefully": ["quiet_reveal"],
        },
        "semantic_text": "A focused editorial landing page with restrained motion and one clear action.",
        "sanitizer_version": 1,
    })


def test_intake_ada_store_persists_registry_and_sanitized_episode(tmp_path):
    store = IntakeAdaStore(tmp_path / "intake-ada.db")
    try:
        record = store.create_incubation("inc_" + "a" * 32, tmp_path / "incubations" / ("inc_" + "a" * 32))
        assert record.status == IncubationStatus.COLLECTING.value
        assert store.get_incubation(record.incubation_id).workspace_path == record.workspace_path

        saved = store.save_episode(_episode())
        assert saved.episode_id == "episode_a"
        assert store.list_episodes()[0].semantic_text.startswith("A focused")
        assert store.search_episodes("restrained editorial landing page")[0]["episode_id"] == "episode_a"
        assert not hasattr(store, "conn")
    finally:
        store.close()


def test_intake_ada_registry_contains_no_customer_content(tmp_path):
    store = IntakeAdaStore(tmp_path / "intake-ada.db")
    try:
        record = store.create_incubation("inc_" + "b" * 32, tmp_path / "incubations" / ("inc_" + "b" * 32))
        public = record.to_dict()
        assert set(public) == {
            "schema_version", "incubation_id", "status", "created_at", "updated_at",
            "expires_at", "current_intake_revision", "current_genesis_revision",
            "accepted_candidate_sha", "provisioning_request_id", "customer_instance_id",
        }
        assert "workspace_path" not in public
    finally:
        store.close()


def test_purged_registry_identity_is_not_reopenable(tmp_path):
    store = IntakeAdaStore(tmp_path / "intake-ada.db")
    incubation_id = "inc_" + "c" * 32
    try:
        store.create_incubation(incubation_id, tmp_path / "incubations" / incubation_id)
        store.mark_purged(incubation_id, expected_status=IncubationStatus.COLLECTING.value)

        assert store.get_incubation(incubation_id) is None
        tombstone = store.get_incubation(incubation_id, include_purged=True)
        assert tombstone is not None
        assert tombstone.status == IncubationStatus.PURGED.value
        assert tombstone.workspace_path == ""
        assert store.list_incubations() == []
        assert store.list_incubations(include_purged=True)[0].incubation_id == incubation_id
        assert store.list_events(incubation_id) == []
        assert store.list_events(incubation_id, include_purged=True)[0]["status"] == IncubationStatus.PURGED.value
        with pytest.raises(ContractError, match="purged"):
            store.create_incubation(incubation_id, tmp_path / "incubations" / incubation_id)
        with pytest.raises(ContractError, match="not found"):
            store.transition_incubation(incubation_id, IncubationStatus.COLLECTING.value)
    finally:
        store.close()

from site_agent.application.novelty import NoveltyService
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.incubation_contracts import CreativeEpisode
from site_agent.core.intake_ada_store import IntakeAdaStore


def _intake():
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {"name": "Working business", "offer_summary": "A clear service", "primary_services": ["A clear service"]},
        "audience": {"primary": "People evaluating the service"},
        "conversion": {"primary_action": "Get in touch", "not_available": True},
        "brand": {"voice": "Clear and warm"},
        "site": {"required_pages": ["index.html", "about.html"]},
    })


def test_novelty_context_is_bounded_and_keeps_only_abstract_episode_ids(tmp_path):
    store = IntakeAdaStore(tmp_path / "intake-ada.db")
    try:
        store.save_episode(CreativeEpisode.from_dict({
            "episode_id": "episode_" + "a" * 32,
            "created_at": "2026-09-02T00:00:00+00:00",
            "engagement_outcome": "accepted",
            "design_fingerprint": {
                "layout_topology": ["pages:2"],
                "type_roles": ["display", "body"],
                "palette_shape": [],
                "motion_patterns": [],
                "navigation_pattern": "",
                "component_rhythm": [],
            },
            "copy_fingerprint": {
                "opening_pattern": "",
                "section_rhythm": ["intro", "proof", "action"],
                "cta_pattern": "",
                "repeated_motifs": [],
            },
            "quality": {"accepted": True, "critic_categories": [], "revision_count": 1},
            "reflection": {"habits_repeated": [], "departures_that_worked": [], "approaches_to_avoid": [], "techniques_to_reuse_carefully": []},
            "semantic_text": "website design composition with display type and clear navigation",
        }))
        context = NoveltyService(store).context_for(_intake())
        assert context.query_hash
        assert context.matches[0]["episode_id"] == "episode_" + "a" * 32
        assert "semantic_score" in context.matches[0]
        assert all("Working business" not in str(item) for item in context.to_dict()["matches"])
    finally:
        store.close()

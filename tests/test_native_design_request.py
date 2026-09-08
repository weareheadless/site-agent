from site_agent.brain.design_brief import compile_brief
from site_agent.brain.page_strategy import native_homepage_request
from site_agent.core.design_contracts import SiteIntake


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Independent design direction for thoughtful brands.",
            "primary_services": ["Brand strategy"],
        },
        "audience": {"primary": "Founders building their first serious brand."},
        "conversion": {"primary_action": "Start a conversation", "contact_destination": "mailto:hello@example.test"},
        "site": {"required_pages": ["index.html", "about.html"]},
        "brand": {"voice": "clear and considered"},
    })


def test_native_homepage_request_contains_facts_without_a_host_direction():
    intake = _intake()
    request = native_homepage_request(
        intake,
        compile_brief(intake),
        run_id="native-run",
        base_sha="a" * 40,
    )

    assert request.page_path == "index.html"
    assert request.purpose
    assert request.acceptance_criteria
    assert "direction" not in request.to_dict()
    assert "tokens" not in request.to_dict()
    assert "motion_plan" not in request.to_dict()


def test_native_homepage_request_keeps_required_content_verbatim():
    intake = _intake()
    brief = compile_brief(intake)
    request = native_homepage_request(intake, brief, run_id="native-content", base_sha="b" * 40)

    serialized = request.to_dict()
    for requirement in brief.content_requirements:
        assert requirement in serialized["acceptance_criteria"]

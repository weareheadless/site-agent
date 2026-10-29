from site_agent.brain.design_brief import compile_brief
from site_agent.brain.page_strategy import native_homepage_request
from site_agent.core.design_contracts import (
    BRAND_BEHAVIOR_NAMED_RECORD_FIELDS,
    SiteIntake,
    brand_behavior_contract_description,
)
from site_agent.hands.opencode_runner import _write_native_direction_agent


def _intake() -> SiteIntake:
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "North Star Studio",
            "offer_summary": "Independent design direction for thoughtful brands.",
            "primary_services": ["Brand strategy"],
        },
        "audience": {"primary": "Founders building their first serious brand."},
        "conversion": {"primary_action": "Start a conversation", "whatsapp_url": "https://wa.me/15551234567"},
        "site": {"required_pages": ["index.html", "about.html"]},
        "brand": {"voice": "clear and considered"},
    })


def test_structured_native_direction_prompt_uses_authoritative_behavior_contract(tmp_path):
    _write_native_direction_agent(tmp_path, structured=True)
    prompt = (tmp_path / "agent" / "native-direction.md").read_text()
    description = brand_behavior_contract_description()
    assert description in prompt
    for array_name, required_fields in BRAND_BEHAVIOR_NAMED_RECORD_FIELDS.items():
        assert f"{array_name}: each record requires {', '.join(required_fields)}" in prompt
    assert "signature_behavior is an object requiring non-empty string id and meaning" in prompt
    assert "non-empty array of non-empty string acceptance_conditions" in prompt
    assert "named arrays may be empty" in prompt
    assert "resting_state, performance_budget, and transfer_test are objects" in prompt
    assert "evidence_refs is a non-empty array of strings" in prompt
    assert "allowed_implementation_capabilities, prohibited_generic_effects, and observable_acceptance_conditions" in prompt
    assert "Required descriptive scalar fields are non-empty strings" in prompt
    _write_native_direction_agent(tmp_path, structured=False)
    plain = (tmp_path / "agent" / "native-direction.md").read_text()
    assert "BrandBehaviorSystem requirements" not in plain


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

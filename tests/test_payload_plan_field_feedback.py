import pytest
from site_agent.brain import editor


def _validated_plan():
    contract = {
        "enabled": {"collections": ["posts"]},
        "authoring": {
            "collections": {
                "posts": [
                    {"name": "slug", "type": "text", "required": True},
                    {"name": "title", "type": "text", "required": True},
                    {"name": "summary", "type": "text"},
                ]
            }
        },
    }
    raw_plan = {
        "content_effects": [
            {
                "kind": "collection",
                "operation": "create",
                "collection": "posts",
                "identifier": "job66-article",
                "identifier_kind": "slug",
                "fields": ["slug", "title", "summary"],
                "summary": "Prepare the requested article",
            }
        ],
        "source_brief": "",
    }
    return editor._validate_website_change_plan(raw_plan, contract)


def _context():
    return {"_website_change_plan": _validated_plan()}


def _args(data):
    return {"collection": "posts", "data": data}


@pytest.mark.parametrize(
    ("data", "missing", "unexpected"),
    [
        ({"slug": "job66-article"}, "summary, title", "(none)"),
        (
            {
                "slug": "job66-article",
                "title": "Draft",
                "summary": "Summary",
                "promoText": "sensitive value",
                "zeta": "another sensitive value",
            },
            "(none)",
            "promoText, zeta",
        ),
        (
            {
                "slug": "job66-article",
                "promoText": "sensitive value",
                "zeta": "another sensitive value",
            },
            "summary, title",
            "promoText, zeta",
        ),
    ],
    ids=["missing-only", "unexpected-only", "mixed"],
)
def test_field_set_refusal_reports_sorted_names_without_values(data, missing, unexpected):
    with pytest.raises(ValueError) as exc_info:
        editor._plan_effect_for_tool(_context(), "create_payload_draft", _args(data))

    message = str(exc_info.value)
    assert message.startswith("the Payload fields must exactly match the validated plan")
    assert f"missing planned fields: {missing}" in message
    assert f"unexpected data fields: {unexpected}" in message
    assert "sensitive value" not in message
    assert "another sensitive value" not in message


def test_exact_planned_field_set_is_accepted():
    effect = editor._plan_effect_for_tool(
        _context(),
        "create_payload_draft",
        _args({"slug": "job66-article", "title": "Draft", "summary": "Summary"}),
    )

    assert effect["fields"] == ["slug", "summary", "title"]

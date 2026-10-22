import pytest

from site_agent.brain.editor import _validate_website_change_plan


def authoring_contract():
    return {
        "enabled": {"collections": ["posts"]},
        "authoring": {
            "collections": {
                "posts": [
                    {"name": "slug", "type": "text", "required": True},
                    {"name": "title", "type": "text", "required": True},
                    {"name": "summary", "type": "text"},
                    {"name": "subtitle", "type": "text", "required": False},
                ]
            }
        },
    }


def content_effect(operation, fields, **overrides):
    effect = {
        "kind": "collection",
        "operation": operation,
        "collection": "posts",
        "identifier": "new-article" if operation == "create" else "post-42",
        "identifier_kind": "slug" if operation == "create" else "id",
        "fields": fields,
        "summary": "Prepare the requested article change",
    }
    effect.update(overrides)
    return effect


def validate(effect):
    return _validate_website_change_plan(
        {"content_effects": [effect], "source_brief": ""}, authoring_contract()
    )


def test_create_requires_required_fields_but_not_optional_fields():
    with pytest.raises(ValueError, match="creation plan is missing required authoring fields: title"):
        validate(content_effect("create", ["slug", "summary"]))

    accepted = validate(content_effect("create", ["slug", "title"]))
    assert accepted["content_effects"][0]["fields"] == ["slug", "title"]


def test_create_does_not_treat_required_false_as_required():
    accepted = validate(content_effect("create", ["slug", "title", "summary"]))

    assert accepted["content_effects"][0]["fields"] == ["slug", "summary", "title"]
    assert "subtitle" not in accepted["content_effects"][0]["fields"]


def test_update_does_not_require_unrelated_required_fields():
    accepted = validate(content_effect("update", ["summary"]))

    assert accepted["content_effects"][0]["fields"] == ["summary"]
    assert accepted["content_effects"][0]["identifier"] == "post-42"


def test_unknown_authoring_field_fails_closed():
    with pytest.raises(ValueError, match="fields outside the shared schema: unpublishedFlag"):
        validate(content_effect("create", ["slug", "title", "unpublishedFlag"]))

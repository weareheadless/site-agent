from __future__ import annotations

import pytest

from site_agent.brain import editor


def _contract():
    return {
        "locales": ["en"],
        "defaultLocale": "en",
        "enabled": {"collections": ["pages"], "globals": []},
        "authoring": {
            "collections": {"pages": [
                {"name": "title", "type": "text", "required": True},
                {"name": "slug", "type": "text", "required": True},
                {"name": "featuredImage", "type": "upload"},
                {"name": "gallery", "type": "upload", "hasMany": True},
            ]},
            "globals": {},
        },
    }


def _plan(fields):
    return {
        "content_effects": [{
            "kind": "collection", "operation": "create", "target": "pages",
            "collection": "pages", "global": "", "identifier": "about",
            "identifier_kind": "slug", "fields": list(fields),
            "summary": "About page", "completed_fields": [],
        }],
        "source_brief": "",
    }


class _Payload:
    def __init__(self, missing=()):
        self.missing = set(missing)
        self.created = None

    def read_media(self, identifier, *, identifier_kind, draft):
        if int(identifier) in self.missing:
            raise RuntimeError("media not found")
        return {"id": int(identifier)}

    def create(self, collection, data, **kwargs):
        self.created = {"collection": collection, "data": data}
        return {
            "id": 9, "slug": data.get("slug"), "_status": "draft",
            "_helloadaRevision": "sha256:" + "a" * 64,
        }


def test_media_references_are_found_in_every_upload_shape():
    data = {
        "featuredImage": 4,
        "gallery": [4, "7"],
        "seo": {"image": 8},
        "sections": [{"entries": [{"blockType": "helloAdaImage", "image": 11}]}],
    }

    assert editor._payload_media_references(data) == [
        ("featuredImage", 4),
        ("gallery[0]", 4),
        ("gallery[1]", 7),
        ("seo.image", 8),
        ("sections[0].entries[0].image", 11),
    ]


def test_a_missing_upload_is_refused_before_the_write_is_dispatched():
    payload = _Payload(missing={15})
    context = {
        "memory": None,
        "payload_gateway": payload,
        "_authoring_contract": _contract(),
        "_website_change_plan": _plan(["title", "slug", "featuredImage"]),
    }

    result = editor._execute_tool(
        context, None, "create_payload_draft",
        {"collection": "pages", "data": {"title": "About", "slug": "about", "featuredImage": 15}},
        lambda _text: None,
    )

    assert result.startswith("REFUSED:")
    assert "#15 at featuredImage" in result
    assert payload.created is None
    assert not context.get("_website_change_plan_dispatched")


def test_an_existing_upload_is_written():
    payload = _Payload()
    context = {
        "memory": None,
        "payload_gateway": payload,
        "_authoring_contract": _contract(),
        "_website_change_plan": _plan(["title", "slug", "featuredImage"]),
    }

    result = editor._execute_tool(
        context, None, "create_payload_draft",
        {"collection": "pages", "data": {"title": "About", "slug": "about", "featuredImage": 4}},
        lambda _text: None,
    )

    assert result.startswith("Payload draft created")
    assert payload.created == {
        "collection": "pages",
        "data": {"title": "About", "slug": "about", "featuredImage": 4},
    }


class _FailingPayload(_Payload):
    def __init__(self, status_code):
        super().__init__()
        self.status_code = status_code

    def create(self, collection, data, **kwargs):
        from site_agent.hands.payload_gateway import PayloadGatewayError

        raise PayloadGatewayError("gateway refused the write", status_code=self.status_code)


def _run_create_with_failure(status_code):
    context = {
        "memory": None,
        "payload_gateway": _FailingPayload(status_code),
        "_authoring_contract": _contract(),
        "_website_change_plan": _plan(["title", "slug", "featuredImage"]),
    }
    result = editor._execute_tool(
        context, None, "create_payload_draft",
        {"collection": "pages", "data": {"title": "About", "slug": "about", "featuredImage": 4}},
        lambda _text: None,
    )
    return context, result


def test_a_validation_refusal_reopens_the_plan_for_a_correction():
    context, result = _run_create_with_failure(409)

    assert result.startswith("REFUSED:")
    assert not context.get("_website_change_plan_dispatched")
    assert not context["_website_change_plan"]["content_effects"][0].get("_dispatched")


def test_an_unknown_outcome_keeps_the_plan_frozen():
    context, _ = _run_create_with_failure(503)

    assert context["_website_change_plan_dispatched"] is True
    assert context["_website_change_plan"]["content_effects"][0]["_dispatched"] is True


def test_a_source_only_plan_can_follow_saved_content():
    context = {"memory": None, "config": {}, "_website_change_plan_dispatched": True}

    result = editor._execute_tool(
        context, None, "plan_website_change",
        {"content_effects": [], "source_brief": "Build the About presentation."},
        lambda _text: None,
    )

    assert result.startswith("Validated website change plan")
    assert context["_website_change_plan"]["source_brief"] == "Build the About presentation."


def test_content_cannot_be_replanned_after_a_dispatch():
    context = {"memory": None, "config": {}, "_website_change_plan_dispatched": True}

    result = editor._execute_tool(
        context, None, "plan_website_change",
        {"content_effects": [{"kind": "global", "operation": "update"}], "source_brief": ""},
        lambda _text: None,
    )

    assert result.startswith("REFUSED:")

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

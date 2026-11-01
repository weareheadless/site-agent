from copy import deepcopy
from types import SimpleNamespace

import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.design_contracts import SectionComposition, page_composition_from_dict
from site_agent.hands import opencode_runner as runner
from tests.test_design_builder import _payload_first_request


def section(section_id, layout, asset_id=None):
    entries = [
        {"key": f"{section_id}.heading", "blockType": "helloAdaHeading", "label": "Heading", "text": section_id},
        {"key": f"{section_id}.body", "blockType": "helloAdaParagraph", "label": "Introduction", "text": f"Copy for {section_id}"},
    ]
    if asset_id:
        entries.append({"key": f"{section_id}.image", "blockType": "helloAdaImage", "label": "Assigned image", "asset_id": asset_id})
    return {"id": section_id, "label": f"Section {section_id}", "layout": layout,
            "direction": {"align": "split-left", "rules": True, "treatment": "colour", "scale": "compact"},
            "entries": entries}


def plan(sections):
    assets = sorted({entry["asset_id"] for item in sections for entry in item["entries"] if "asset_id" in entry})
    return SimpleNamespace(
        page_composition=page_composition_from_dict({"schema_version": 1, "sections": sections}),
        copy_deck={"meta_description": "Planned metadata"},
        asset_composition_plan=tuple(SimpleNamespace(asset_id=asset) for asset in assets),
        asset_evidence=tuple(SimpleNamespace(asset_id=asset, media_role="photograph") for asset in assets),
    )


def test_stages_every_planned_section_in_order_with_its_copy_labels_and_exact_media():
    sections = [section("opening", "hero", "media-5"), section("work", "services", "media-6"),
                section("studio", "about", "media-7"), section("invitation", "contact")]
    sections[-1]["entries"].append({"key": "invitation.action", "blockType": "helloAdaLink", "label": "Contact action",
                                   "text": "Talk to us", "href": "https://wa.me/15551234567"})
    data = runner._initial_homepage_payload_data(_payload_first_request(), plan(sections))
    assert [item["key"] for item in data["sections"]] == [item["id"] for item in sections]
    for expected, actual in zip(sections, data["sections"], strict=True):
        assert actual["label"] == expected["label"]
        assert actual["direction"] == expected["direction"]
        for source, staged in zip(expected["entries"], actual["entries"], strict=True):
            assert staged == ({**{key: value for key, value in source.items() if key != "asset_id"},
                               "image": int(source["asset_id"].split("-")[1])} if "asset_id" in source else source)
    assert data["featuredImage"] == 5
    assert data["seo"]["description"] == "Planned metadata"


def test_non_opening_layouts_can_repeat_with_distinct_stable_ids():
    selected = plan([section("opening", "hero"), section("first", "services"), section("second", "services")])
    assert len(selected.page_composition) == 3


@pytest.mark.parametrize("mutation, message", [
    (lambda items: items[1].update(id="opening"), "duplicate section id"),
    (lambda items: items[1]["entries"][0].update(key="opening.heading"), "duplicate content key"),
    (lambda items: items[1]["entries"].append(deepcopy(items[1]["entries"][0])), "duplicate content key"),
    (lambda items: items[1]["entries"][0].update(blockType="unknown"), "blockType"),
    (lambda items: items[1]["entries"][0].update(text=""), "text"),
    (lambda items: items[1]["entries"].append({"key": "extra", "blockType": "helloAdaHeading", "label": "Extra", "text": "Dropped?"}), "one heading"),
    (lambda items: items[1]["entries"].append({"key": "extra", "blockType": "helloAdaImage", "label": "Extra", "asset_id": "media-7"}), "one image"),
    (lambda items: items[1]["entries"].append({"key": "bad-link", "blockType": "helloAdaLink", "label": "Action", "text": "Click", "href": "javascript:alert(1)"}), "href"),
])
def test_plan_rejects_content_the_templates_would_drop_or_cannot_bind(mutation, message):
    items = [section("opening", "hero"), section("detail", "about", "media-6")]
    mutation(items)
    with pytest.raises(ContractError, match=message):
        plan(items)


def test_stage_refuses_missing_section_content_and_unmapped_composition_assets():
    legacy = SectionComposition.from_dict({key: value for key, value in section("opening", "hero").items()
                                           if key not in {"entries", "label"}})
    selected = plan([section("opening", "hero")])
    selected.page_composition = (legacy,)
    with pytest.raises(runner.RunnerError, match="section content"):
        runner._initial_homepage_payload_data(_payload_first_request(), selected)
    selected = plan([section("opening", "hero", "media-5")])
    selected.asset_composition_plan += (SimpleNamespace(asset_id="media-6"),)
    with pytest.raises(runner.RunnerError, match="media-6"):
        runner._initial_homepage_payload_data(_payload_first_request(), selected)


class Payload:
    def __init__(self, missing=None):
        self.media_reads = []
        self.writes = []
        self.missing = missing

    def require_authoring_contract(self):
        return {"enabled": {"collections": ["pages"]}, "locales": ["en"], "defaultLocale": "en"}

    def read_media(self, identifier, **_kwargs):
        self.media_reads.append(identifier)
        if identifier == self.missing:
            raise ValueError("missing media")
        return {"id": int(identifier)}

    def create(self, collection, data, **_kwargs):
        self.writes.append(data)
        self.document = {**data, "id": 1, "sourceId": "pages:home", "_helloadaRevision": "sha256:" + "1" * 64}
        return dict(self.document)

    def read(self, *_args, **_kwargs):
        return dict(self.document)


def test_stage_checks_all_assigned_media_before_writing_and_receipts_every_content_key():
    from site_agent.core.design_contracts import PageBuildRequest

    selected = plan([section("opening", "hero", "media-5"), section("work", "services", "media-6"),
                     section("studio", "about", "media-7")])
    request = PageBuildRequest.from_dict({**_payload_first_request().to_dict(), "supplied_media_asset_ids": [5, 6, 7]})
    payload = Payload()
    staged = runner._stage_initial_homepage_payload({"payload_gateway": payload}, request, selected)
    assert payload.media_reads == ["5", "6", "7"]
    assert len(payload.writes) == 1
    assert staged.content["payload_draft_receipts"][0]["content_keys"] == [
        entry["key"] for item in selected.page_composition for entry in item.entries
    ]
    assert [item["entries"][-1]["image"] for item in payload.writes[0]["sections"]] == [5, 6, 7]

    missing = Payload(missing="7")
    with pytest.raises(runner.RunnerError, match="media-7.*not present"):
        runner._stage_initial_homepage_payload({"payload_gateway": missing}, request, selected)
    assert not missing.writes
    unauthorized = Payload()
    with pytest.raises(runner.RunnerError, match="not an approved intake asset"):
        runner._stage_initial_homepage_payload({"payload_gateway": unauthorized}, _payload_first_request(), selected)
    assert not unauthorized.writes


def test_gallery_preserves_all_its_planned_images():
    gallery = section("work", "gallery", "media-6")
    gallery["entries"].append({"key": "work.second-image", "blockType": "helloAdaImage", "label": "Second view", "asset_id": "media-7"})
    data = runner._initial_homepage_payload_data(_payload_first_request(), plan([section("opening", "hero"), gallery]))
    assert [entry["image"] for entry in data["sections"][1]["entries"] if "image" in entry] == [6, 7]

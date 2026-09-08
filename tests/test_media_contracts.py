import pytest

from site_agent.core.contracts import ContractError
from site_agent.core.media_contracts import MediaAnalysis, MediaAsset, MediaKind, MediaStatus


def test_media_analysis_strips_unknown_fields_and_requires_knowledge_text():
    analysis = MediaAnalysis.from_mapping({
        "description": "A menu",
        "tags": ["menu"],
        "knowledge_relevant": True,
        "proposed_knowledge_markdown": "## Menu\n- Soup",
        "quality_notes": "Readable",
        "unknown": "ignored",
    })
    assert analysis.schema_version == 1
    assert "unknown" not in analysis.to_dict()
    assert analysis.quality_notes == ["Readable"]

    with pytest.raises(ContractError):
        MediaAnalysis.from_mapping({"knowledge_relevant": True})

    assert MediaAnalysis.from_mapping({
        "description": "A photo", "knowledge_relevant": "No reusable business information is visible",
    }).knowledge_relevant is False


def test_media_asset_round_trips_malformed_json_safely():
    asset = MediaAsset.from_row({
        "id": 4, "status": "queued", "media_kind": "image", "original_name": "photo.jpg",
        "content_type": "image/jpeg", "original_size": 4, "original_sha256": "hash",
        "storage_id": "storage", "original_key": "original", "page_keys_json": "not-json",
        "tags_json": "{}", "analysis_json": "[]", "created_ts": "now", "updated_ts": "now",
    })
    assert asset.status is MediaStatus.QUEUED
    assert asset.media_kind is MediaKind.IMAGE
    assert asset.page_keys == []
    assert asset.tags == []
    assert asset.analysis == {}

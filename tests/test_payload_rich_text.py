import json

import pytest

from site_agent.core.payload_rich_text import lexical_text, markdown_to_lexical


def test_markdown_article_serializes_to_payload_lexical_blocks_and_links():
    document = markdown_to_lexical(
        "## A useful heading\n\nA **bold** [source](https://example.test/story) and `code`.\n\n"
        "- First idea\n- Second idea"
    )
    root = document["root"]
    assert root["type"] == "root"
    assert [node["type"] for node in root["children"]] == ["heading", "paragraph", "list"]
    paragraph = root["children"][1]
    bold = next(node for node in paragraph["children"] if node["type"] == "text" and node["format"] & 1)
    link = next(node for node in paragraph["children"] if node["type"] == "link")
    assert bold["format"] & 1
    assert link["type"] == "link"
    assert link["fields"]["url"] == "https://example.test/story"
    assert lexical_text(document) == "A useful heading A bold source and code. First idea Second idea"
    assert "<p>" not in json.dumps(document)


def test_markdown_serializer_rejects_empty_article_body():
    with pytest.raises(ValueError, match="readable text"):
        markdown_to_lexical(" \n\n")

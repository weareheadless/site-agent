from site_agent.hands.pelican_blog import article_path, document, enabled


def test_pelican_document_has_frontmatter_and_article_metadata():
    config = {"blog": {"engine": "pelican", "articles_dir": "content/articles"}}

    payload = document(
        config,
        "Choosing a Course",
        "## Start here\n\nRead this first.",
        {"slug": "choosing-a-course", "summary": "A practical guide.", "tags": ["beginner"]},
    ).decode()

    assert payload.startswith("---\n")
    assert "Title: Choosing a Course" in payload
    assert "Slug: choosing-a-course" in payload
    assert "Summary: A practical guide." in payload
    assert "## Start here" in payload
    assert article_path(config, "choosing-a-course") == "content/articles/choosing-a-course.md"


def test_pelican_document_normalizes_title_and_removes_duplicate_leading_heading():
    config = {"blog": {"engine": "pelican"}}

    payload = document(
        config,
        "'Choosing: A Course'",
        "## Choosing: A Course\n\nRead this first.",
    ).decode()

    assert "Title: Choosing: A Course\n" in payload
    assert "## Choosing: A Course" not in payload
    assert "Read this first." in payload


def test_pelican_engine_is_default_in_merged_config_and_legacy_can_be_explicit():
    assert enabled({}) is False
    assert enabled({"blog": {"engine": "legacy"}}) is False
    assert enabled({"blog": {"engine": "pelican"}}) is True


def test_article_path_rejects_traversal():
    config = {"blog": {"engine": "pelican"}}

    for slug in ("../secret", "nested/article", "", "."):
        try:
            article_path(config, slug)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid slug: {slug}")

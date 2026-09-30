from site_agent.migrations.legacy import import_pelican_tree


def test_import_pelican_tree_maps_pages_articles_and_redirects(tmp_path):
    pages = tmp_path / "content" / "pages"
    articles = tmp_path / "content" / "articles"
    pages.mkdir(parents=True)
    articles.mkdir(parents=True)
    (pages / "about.md").write_text(
        "---\nTitle: About us\nSlug: about\n---\n# About us\n\nA short story.\n",
        encoding="utf-8",
    )
    (articles / "launch.md").write_text(
        "---\nTitle: Launch notes\nDate: 2026-09-30\nStatus: published\n---\nThe first release.\n",
        encoding="utf-8",
    )

    bundle = import_pelican_tree(tmp_path)

    assert not bundle.rejected
    assert [item["collection"] for item in bundle.documents] == ["pages", "posts"]
    assert bundle.documents[0]["data"]["body"] == "A short story."
    assert bundle.documents[1]["data"]["publishedAt"] == "2026-09-30"
    assert {item["from"] for item in bundle.redirects} == {"/about.html", "/articles/launch.html"}
    assert {item["to"] for item in bundle.redirects} == {"/about", "/articles/launch"}


def test_import_pelican_tree_rejects_duplicate_routes(tmp_path):
    pages = tmp_path / "content" / "pages"
    pages.mkdir(parents=True)
    for name in ("one.md", "two.md"):
        (pages / name).write_text("---\nSlug: same\n---\ncontent\n", encoding="utf-8")

    bundle = import_pelican_tree(tmp_path)

    assert len(bundle.documents) == 1
    assert len(bundle.rejected) == 1
    assert "duplicate legacy route" in bundle.rejected[0]["reason"]

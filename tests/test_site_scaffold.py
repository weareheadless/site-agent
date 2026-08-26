from site_agent.site_scaffold import initialize_site


def test_initialize_site_creates_pelican_pages_and_cms(tmp_path):
    root = initialize_site(tmp_path / "site", "North Star Studio", "https://north.example")

    assert (root / "pelicanconf.py").exists()
    assert (root / "content/pages/index.md").exists()
    assert (root / "content/pages/about.md").exists()
    assert (root / "content/pages/contact.md").exists()
    assert (root / "content/articles/.gitkeep").exists()
    assert (root / "themes/ada/templates/index.html").exists()
    assert (root / "build.sh").stat().st_mode & 0o111
    assert "North Star Studio" in (root / "pelicanconf.py").read_text()


def test_initialize_site_refuses_non_empty_directory(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "existing.html").write_text("owned by customer")

    try:
        initialize_site(root)
    except FileExistsError:
        pass
    else:
        raise AssertionError("overwrote a non-empty customer site")

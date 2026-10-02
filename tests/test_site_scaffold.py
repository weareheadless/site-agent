from site_agent.site_scaffold import initialize_payload_site, initialize_site


def test_initialize_payload_site_creates_canonical_helloada_template(tmp_path):
    root = initialize_payload_site(tmp_path / "site", "North Star Studio", "https://north.example")

    assert (root / "payload.config.ts").exists()
    assert (root / "src/helloada.config.ts").exists()
    assert (root / "src/app/api/helloada/[...path]/route.ts").exists()
    assert (root / "src/components/admin/HelloAdaWorkspace.tsx").exists()
    config = (root / "src/helloada.config.ts").read_text()
    wrangler = (root / "wrangler.jsonc").read_text()
    assert 'tenantId: "north-star-studio"' in config
    assert "__HELLOADA_" not in config
    assert '"HELLOADA_TENANT_ID": "north-star-studio"' in wrangler
    assert '"HELLOADA_SITE_NAME": "North Star Studio"' in wrangler
    assert "__SITE_AGENT_VERSION__" not in wrangler


def test_payload_navigation_keeps_server_only_props_out_of_client_boundary(tmp_path):
    root = initialize_payload_site(tmp_path / "site", "North Star Studio", "https://north.example")
    nav = (root / "src/components/admin/HelloAdaNav.tsx").read_text()

    # Payload sends req, payload and i18n (including functions) to server Nav
    # components. Forwarding the whole object crashes authenticated admin pages.
    assert "HelloAdaNav({ user }: ComponentProps<typeof SharedNav>)" in nav
    assert "<SharedNav user={user} />" in nav
    assert "{..." not in nav


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
    build = (root / "build.sh").read_text()
    assert "cp \"$relative\" \"output/$relative\"" in build
    assert "index.html" in build
    assert "vendor" in build
    assert "images" in build


def test_initialize_site_build_stages_the_root_homepage_into_output(tmp_path):
    import subprocess

    root = initialize_site(tmp_path / "site", "North Star Studio", "https://north.example")
    (root / "index.html").write_text("<html><body><h1>Homepage</h1></body></html>", encoding="utf-8")
    (root / "styles.css").write_text("body { color: #000; }", encoding="utf-8")
    (root / "modified").mkdir(parents=True)
    (root / "modified" / "leak.txt").write_text("leak", encoding="utf-8")

    built = subprocess.run(["bash", "build.sh"], cwd=root, capture_output=True, text=True)

    assert built.returncode == 0, built.stderr
    assert (root / "output/index.html").read_text(encoding="utf-8") == "<html><body><h1>Homepage</h1></body></html>"
    assert (root / "output/styles.css").exists()
    assert not (root / "output/modified").exists()
    assert not (root / "output/themes").exists()


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

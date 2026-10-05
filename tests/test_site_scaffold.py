from site_agent.site_scaffold import (
    initialize_managed_site,
    initialize_payload_site,
    payload_template_copy_ignore,
)


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

    manifest = (root / "template-manifest.json").read_text()
    assert '"contentContract": "helloada-content-v2"' in manifest
    assert "createHelloAdaSchema" in (root / "payload.config.ts").read_text()
    assert not (root / "src/collections/Posts.ts").exists()
    assert not (root / "src/collections/Pages.ts").exists()
    assert not (root / "src/globals/Navigation.ts").exists()
    assert (root / "helloada-content-contract.json").exists()
    template_instructions = (root / "AGENTS.md").read_text()
    assert "`/blog` is the index and" in template_instructions
    preview = (root / "src/app/(frontend)/helloada-preview/[token]/page.tsx").read_text()
    assert "pathForDocument(collection, slug)" in preview
    assert (root / "src/app/(frontend)/[[...slug]]/page.tsx").exists()
    assert (root / "src/lib/content-routes.ts").exists()
    middleware = (root / "src/middleware.ts").read_text()
    assert "helloAdaSite.routes.preview" in middleware
    assert "NextResponse.rewrite(destination)" in middleware
    assert (root / "src/lib/workspace-preview-path.ts").exists()
    assert (root / "tests/workspace-preview.test.mjs").exists()
    assert not (root / "src/app/(frontend)/articles/[slug]/page.tsx").exists()
    assert not (root / "src/app/(frontend)/articles.html/page.tsx").exists()
    assert not (root / "src/app/(frontend)/post/[slug]/page.tsx").exists()
    routes = (root / "src/helloada.config.ts").read_text()
    assert "postsIndex: '/blog'" in routes
    assert "postDetail: '/blog'" in routes


def test_payload_navigation_keeps_server_only_props_out_of_client_boundary(tmp_path):
    root = initialize_payload_site(tmp_path / "site", "North Star Studio", "https://north.example")
    nav = (root / "src/components/admin/HelloAdaNav.tsx").read_text()

    # Payload sends req, payload and i18n (including functions) to server Nav
    # components. Forwarding the whole object crashes authenticated admin pages.
    assert "HelloAdaNav({ user }: ComponentProps<typeof SharedNav>)" in nav
    assert "<SharedNav user={user} />" in nav
    assert "{..." not in nav


def test_managed_site_baseline_keeps_tenant_identity_unbound_until_bootstrap(tmp_path):
    root = initialize_managed_site(tmp_path / "site")
    config = (root / "src/helloada.config.ts").read_text()
    assert "'__HELLOADA_TENANT_ID__'" in config
    assert "'__HELLOADA_SITE_NAME__'" in config
    assert not (root / "public/content.json").exists()
    assert not (root / "node_modules").exists()
    assert not (root / ".next").exists()
    assert not (root / ".open-next").exists()


def test_payload_template_copy_policy_excludes_caches_and_local_secrets():
    names = [".next", ".open-next", ".wrangler", "node_modules", ".env", ".env.local", "src", "package.json"]

    assert payload_template_copy_ignore("/template", names) == set(names[:6])


def test_payload_page_blocks_use_canonical_payload_block_types_and_stable_ids(tmp_path):
    root = initialize_payload_site(tmp_path / "site", "North Star Studio", "https://north.example")
    renderer = (root / "src/components/site/TenantSections.tsx").read_text()
    assert "switch (entry.blockType)" in renderer
    assert "entry.type" not in renderer
    assert "section-${sectionIndex}" not in renderer
    assert "${sectionKey}-${entryIndex}" not in renderer
    assert "stableKey(section.key" in renderer

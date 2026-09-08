import subprocess
from pathlib import Path

from site_agent.web import preview
from site_agent.hands.site_build import SiteBuildResult
from site_agent.web.preview import PreviewAccess, PreviewBuildCache, rewrite_preview_css, rewrite_preview_html


def test_rewrite_preview_html_is_relative_to_rendered_page():
    html = b'''<link rel="stylesheet" href="https://example.test/theme/site.css">
    <img src="/images/logo.svg"><a href="/">Home</a>
    <script src="https://cdn.example.test/app.js"></script>'''

    root_page = rewrite_preview_html(html, 7, "articles.html", "https://example.test")
    nested_page = rewrite_preview_html(html, 7, "articles/story.html", "https://example.test")

    assert b'href="./theme/site.css"' in root_page
    assert b'src="./images/logo.svg"' in root_page
    assert b'href="./index.html"' in root_page
    assert b'href="../theme/site.css"' in nested_page
    assert b'src="../images/logo.svg"' in nested_page
    assert b'href="../index.html"' in nested_page
    assert b'https://cdn.example.test/app.js' in root_page
    assert b'/api/review/' not in root_page


def test_rewrite_preview_html_adds_isolated_runtime_and_asset_tokens():
    html = b'''<head><link rel="stylesheet" href="styles.css?v=1">
    <script src="app.js"></script><script src="https://cdn.example.test/app.js"></script></head>
    <img src="/images/logo.svg">'''

    rendered = rewrite_preview_html(html, 7, "index.html", "", "token")

    assert b'data-site-agent-preview' in rendered
    assert b'href="styles.css?v=1&preview_token=token"' in rendered
    assert b'src="./images/logo.svg?preview_token=token"' in rendered
    assert b'src="https://cdn.example.test/app.js"' in rendered
    assert b'preview_token=token' in rendered


def test_rewrite_preview_html_propagates_design_variant_to_assets_and_runtime():
    html = b'''<head><link rel="stylesheet" href="styles.css?v=1"></head>
    <img src="/images/logo.svg"><a href="/about.html">About</a>'''

    rendered = rewrite_preview_html(html, 7, "index.html", "", "token", "original")

    assert b'href="styles.css?v=1&preview_token=token&variant=original"' in rendered
    assert b'src="./images/logo.svg?preview_token=token&variant=original"' in rendered
    assert b'href="./about.html?preview_token=token&variant=original"' in rendered
    assert b'const variant = "original"' in rendered


def test_rewrite_preview_html_accepts_an_explicit_intake_lab_root():
    html = b'<head></head><a href="/articles.html">Articles</a>'

    rendered = rewrite_preview_html(
        html,
        7,
        "index.html",
        "",
        "token",
        "candidate",
        "/api/runs/intake-lab-7/preview/candidate/",
    )

    assert b'/api/runs/intake-lab-7/preview/candidate/' in rendered


def test_rewrite_preview_css_propagates_design_variant_to_assets():
    css = b'''a{background:url("/images/hero.jpg")}'''

    rendered = rewrite_preview_css(css, "theme/site.css", "token", "deepseek")

    assert b'url("../images/hero.jpg?preview_token=token&variant=deepseek")' in rendered


def test_rewrite_preview_css_keeps_assets_inside_preview_scope():
    css = b'''a{background:url("/images/hero.jpg")}b{src:url("../font.woff2")}
    c{background:url(data:image/png;base64,abc)}'''

    rendered = rewrite_preview_css(css, "theme/css/site.css", "token")

    assert b'url("../../images/hero.jpg?preview_token=token")' in rendered
    assert b'url("../font.woff2?preview_token=token")' in rendered
    assert b'url(data:image/png;base64,abc)' in rendered


def test_preview_access_is_scoped_and_expires(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(preview.time, "monotonic", lambda: clock[0])
    access = PreviewAccess(ttl=60)
    token = access.issue(("review", 7))

    assert access.valid(token, ("review", 7))
    assert not access.valid(token, ("review", 8))
    clock[0] = 160.0
    assert not access.valid(token, ("review", 7))


def test_preview_build_cache_serves_generated_assets_once(tmp_path):
    clone = tmp_path / "site"
    clone.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "preview")
    run("config", "user.email", "test@example.test")
    run("config", "user.name", "test")
    (clone / "build.sh").write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "mkdir -p output/theme/css\n"
        "printf '<link href=\"https://example.test/theme/site.css\">' > output/articles.html\n"
        "printf 'body { color: red; }' > output/theme/css/site.css\n"
    )
    (clone / "pelicanconf.py").write_text("SITEURL = 'https://example.test'\n")
    run("add", "-A")
    run("commit", "-qm", "preview")

    cache = PreviewBuildCache()
    assert cache.read_file(clone, "preview", "articles.html") == b'<link href="https://example.test/theme/site.css">'
    assert cache.read_file(clone, "preview", "theme/css/site.css") == b"body { color: red; }"
    cache.clear()


def test_preview_build_uses_the_running_python_environment_for_site_tools(tmp_path, monkeypatch):
    clone = tmp_path / "site"
    clone.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.test")
    run("config", "user.name", "test")
    (clone / "build.sh").write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "command -v pelican >/dev/null\n"
        "mkdir -p output\n"
        "printf 'generated' > output/articles.html\n"
    )
    run("add", "-A")
    run("commit", "-qm", "preview")

    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").touch()
    pelican = venv_bin / "pelican"
    pelican.write_text("#!/bin/sh\nexit 0\n")
    pelican.chmod(0o755)
    monkeypatch.setattr("site_agent.web.preview.sys.executable", str(venv_bin / "python"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    cache = PreviewBuildCache()
    assert cache.read_file(clone, "main", "articles.html") == b"generated"
    cache.clear()


def test_preview_build_uses_supplied_environment(tmp_path):
    clone = tmp_path / "site"
    clone.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.test")
    run("config", "user.name", "test")
    (clone / "build.sh").write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "mkdir -p output\n"
        "printf '%s' \"${INTAKE_LAB_MARKER:-missing}\" > output/env.txt\n"
    )
    run("add", "-A")
    run("commit", "-qm", "preview")

    cache = PreviewBuildCache(build_env={"PATH": "/usr/bin", "INTAKE_LAB_MARKER": "isolated"})
    assert cache.read_file(clone, "main", "env.txt") == b"isolated"
    cache.clear()


def test_preview_build_cache_separates_overlay_builds(tmp_path):
    clone = tmp_path / "site"
    clone.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.test")
    run("config", "user.name", "test")
    (clone / "build.sh").write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "mkdir -p output\n"
        "if [ -f content/articles/draft.md ]; then cp content/articles/draft.md output/articles.html; else printf 'base' > output/articles.html; fi\n"
    )
    (clone / "pelicanconf.py").write_text("SITEURL = 'https://example.test'\n")
    run("add", "-A")
    run("commit", "-qm", "preview")

    cache = PreviewBuildCache()
    assert cache.read_file(clone, "main", "articles.html") == b"base"
    assert cache.read_file(
        clone, "main", "articles.html", overlays={"content/articles/draft.md": b"draft one"}
    ) == b"draft one"
    assert cache.read_file(
        clone, "main", "articles.html", overlays={"content/articles/draft.md": b"draft two"}
    ) == b"draft two"
    cache.clear()


def test_preview_build_cache_uses_explicit_astro_profile_and_dist(tmp_path, monkeypatch):
    clone = tmp_path / "site"
    clone.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.test")
    run("config", "user.name", "test")
    (clone / "package.json").write_text('{"name":"preview-test"}\n')
    run("add", "-A")
    run("commit", "-qm", "astro candidate")
    calls = []

    def fake_build(root, profile, *, npm_cache=None, env=None, timeout_seconds=None):
        calls.append((root, profile.name, profile.output_dir, timeout_seconds))
        output = root / profile.output_dir
        output.mkdir(parents=True)
        (output / "index.html").write_text("astro preview")
        return SiteBuildResult(profile.name, True, profile.output_dir, (), ("index.html",))

    monkeypatch.setattr(preview, "build_site", fake_build)
    cache = PreviewBuildCache(build_env={"PATH": "/usr/bin"})

    assert cache.read_file(clone, "main", "index.html", profile="astro_react") == b"astro preview"
    assert calls and calls[0][1:] == ("astro_react", "dist", 60)
    assert cache.read_file(clone, "main", "index.html", profile="not-a-profile") == b""
    cache.clear()


def test_preview_build_cache_uses_the_configured_temp_root(tmp_path, monkeypatch):
    clone = tmp_path / "site"
    clone.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "test")
    (clone / "package.json").write_text('{"name":"preview-test"}\n')
    run("add", "-A")
    run("commit", "-qm", "astro candidate")
    preview_root = tmp_path / "preview-builds"
    build_roots = []

    def fake_build(root, profile, *, npm_cache=None, env=None, timeout_seconds=None):
        build_roots.append(Path(root))
        output = root / profile.output_dir
        output.mkdir(parents=True)
        (output / "index.html").write_text("astro preview")
        return SiteBuildResult(profile.name, True, profile.output_dir, (), ("index.html",))

    monkeypatch.setattr(preview, "build_site", fake_build)
    cache = PreviewBuildCache(temp_root=preview_root)

    assert cache.read_file(clone, "main", "index.html", profile="astro_react") == b"astro preview"
    assert build_roots and build_roots[0].parent.parent == preview_root.resolve()
    cache.clear()

import subprocess

from site_agent.web.preview import PreviewBuildCache, rewrite_preview_html


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

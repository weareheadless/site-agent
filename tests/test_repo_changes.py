from site_agent.hands.repo_changes import normalize_path, writable


def test_repository_paths_are_normalized_before_allowlisting():
    assert normalize_path("/themes/site/style.css") == "themes/site/style.css"
    assert normalize_path(r"themes\site\style.css") == "themes/site/style.css"
    assert normalize_path("themes/../.env") == ""
    assert not writable("themes/../styles.css", ["*.css"])
    assert writable("themes/site/style.css", ["*.css"])


def test_next_react_ownership_is_a_non_widenable_upper_bound():
    broad = ["**"]
    assert writable("src/components/site/presentation/PagePresentation.tsx", broad, frontend_only=True)
    assert not writable("src/app/(frontend)/[[...slug]]/page.tsx", broad, frontend_only=True)
    assert not writable("src/lib/content.ts", broad, frontend_only=True)
    assert not writable("package.json", broad, frontend_only=True)

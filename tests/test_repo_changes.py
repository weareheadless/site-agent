from site_agent.hands.repo_changes import normalize_path, writable


def test_repository_paths_are_normalized_before_allowlisting():
    assert normalize_path("/themes/site/style.css") == "themes/site/style.css"
    assert normalize_path(r"themes\site\style.css") == "themes/site/style.css"
    assert normalize_path("themes/../.env") == ""
    assert not writable("themes/../styles.css", ["*.css"])
    assert writable("themes/site/style.css", ["*.css"])

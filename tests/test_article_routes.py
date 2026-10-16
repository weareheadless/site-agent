from site_agent.core.article_routes import public_article_path


def test_public_articles_use_the_shared_blog_route():
    assert public_article_path("journal-entry") == "/blog/journal-entry"
    assert public_article_path("/journal-entry/") == "/blog/journal-entry"
    assert public_article_path("") == ""

import pytest

pytest.importorskip("yaml")


@pytest.fixture(autouse=True)
def _clear_file_cache():
    """Tests share one process; the file cache is keyed by repo+path, so clear
    it between tests to avoid cross-test staleness."""
    from site_agent.hands import file_cache

    file_cache.clear()
    yield
    file_cache.clear()

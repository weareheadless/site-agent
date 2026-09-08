"""Read-only CrawlSEO sense facade used by SEO and analytics compatibility APIs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..application.crawlseo import CrawlSEOApplicationService
from ..hands.crawlseo import CrawlSEOClient


def _use_service(config: dict[str, Any], service: Any | None, operation: Callable[[Any], Any]) -> Any:
    if service is not None:
        application = service if isinstance(service, CrawlSEOApplicationService) else CrawlSEOApplicationService(service)
        return operation(application)

    # Runtime injects the long-lived service for jobs. This fallback keeps the
    # public sense facade useful for one-off callers without retaining a thread.
    client = CrawlSEOClient.from_config(config)
    if client is None:
        raise RuntimeError("CrawlSEO source requires an enabled providers.crawlseo configuration")
    application = CrawlSEOApplicationService(client)
    try:
        return operation(application)
    finally:
        client.close()


def project(config: dict[str, Any], service: Any | None = None) -> dict[str, Any]:
    return _use_service(config, service, lambda app: app.project())


def search_summary(
    config: dict[str, Any],
    days: int = 28,
    limit: int = 10,
    service: Any | None = None,
) -> dict[str, Any]:
    return _use_service(config, service, lambda app: app.search_summary(days, limit))


def analytics_summary(config: dict[str, Any], service: Any | None = None) -> dict[str, Any]:
    return _use_service(config, service, lambda app: app.analytics_summary())


def crawl_summary(config: dict[str, Any], service: Any | None = None) -> dict[str, Any]:
    return _use_service(config, service, lambda app: app.crawl_summary())


def crawl_issues(
    config: dict[str, Any],
    severity: str | None = None,
    limit: int = 50,
    service: Any | None = None,
) -> list[dict[str, Any]]:
    return _use_service(config, service, lambda app: app.crawl_issues(severity, limit))


__all__ = ["analytics_summary", "crawl_issues", "crawl_summary", "project", "search_summary"]

"""Application service for the finite, read-only CrawlSEO contract."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ..core.contracts import (
    ContractError,
    CrawlSEOAnalyticsSummary,
    CrawlSEOCrawlSummary,
    CrawlSEOProject,
    CrawlSEOReadProvider,
    CrawlSEOSearchSummary,
    safe_payload,
)


class CrawlSEOApplicationError(RuntimeError):
    """A provider result could not be safely used by the application."""


def _bounded_int(value: int, field_name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise CrawlSEOApplicationError(f"CrawlSEO {field_name} must be between 1 and {maximum}")
    return value


class CrawlSEOApplicationService:
    """Validate provider data and expose only known application operations."""

    def __init__(self, provider: CrawlSEOReadProvider) -> None:
        self.provider = provider

    def project(self) -> dict[str, Any]:
        result = self._read("project", self.provider.project)
        return self._as_contract(CrawlSEOProject, result, "project").to_dict()

    def search_summary(self, days: int = 28, query_limit: int = 10) -> dict[str, Any]:
        days = _bounded_int(days, "days", 3660)
        query_limit = _bounded_int(query_limit, "query_limit", 100)
        result = self._read("search summary", lambda: self.provider.search_summary(days, query_limit))
        summary = self._as_contract(
            CrawlSEOSearchSummary,
            result,
            "search summary",
            default_period_days=days,
        )
        return {
            "period_days": days,
            "top_queries": [row.to_dict() for row in summary.top_queries[:query_limit]],
        }

    def analytics_summary(self) -> dict[str, Any]:
        result = self._read("analytics summary", self.provider.analytics_summary)
        return self._as_contract(CrawlSEOAnalyticsSummary, result, "analytics summary").to_dict()

    def crawl_summary(self) -> dict[str, Any]:
        result = self._read("crawl summary", self.provider.crawl_summary)
        return self._as_contract(CrawlSEOCrawlSummary, result, "crawl summary").to_dict()

    def crawl_issues(self, severity: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = _bounded_int(limit, "limit", 100)
        if severity is not None and (not isinstance(severity, str) or len(severity) > 80):
            raise CrawlSEOApplicationError("CrawlSEO severity must be short text")
        result = self._read("crawl issues", lambda: self.provider.crawl_issues(severity, limit))
        if not isinstance(result, (list, tuple)):
            raise CrawlSEOApplicationError("invalid CrawlSEO crawl issue response")
        issues: list[dict[str, Any]] = []
        try:
            for issue in result[:limit]:
                if not isinstance(issue, Mapping):
                    raise ContractError("issue must be an object")
                encoded = json.dumps(issue, ensure_ascii=False, separators=(",", ":"))
                if len(encoded.encode("utf-8")) > 25_000:
                    raise ContractError("issue is too large")
                issues.append(safe_payload(issue, max_bytes=25_000))
        except (ContractError, TypeError, ValueError) as exc:
            raise CrawlSEOApplicationError("invalid CrawlSEO crawl issue response") from exc
        return issues

    def request_research_report(self, brief: Mapping[str, Any], idempotency_key: str) -> dict[str, Any]:
        if not isinstance(brief, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO research brief must be an object")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 240:
            raise CrawlSEOApplicationError("CrawlSEO research idempotency key is invalid")
        result = self._read(
            "research request",
            lambda: self.provider.request_research_report(brief, idempotency_key.strip()),
        )
        return self._safe_mapping(result, "research request")

    def research_report_status(self, report_id: str) -> dict[str, Any]:
        report_id = self._bounded_text(report_id, "report_id", 120)
        result = self._read("research status", lambda: self.provider.research_report_status(report_id))
        return self._safe_mapping(result, "research status")

    def research_report(self, report_id: str) -> dict[str, Any]:
        report_id = self._bounded_text(report_id, "report_id", 120)
        result = self._read("research report", lambda: self.provider.research_report(report_id))
        return self._safe_mapping(result, "research report", max_bytes=150_000)

    def latest_research_report(self) -> dict[str, Any]:
        result = self._read("latest research report", self.provider.latest_research_report)
        return self._safe_mapping(result, "latest research report", max_bytes=150_000)

    def list_research_reports(self, limit: int = 12) -> dict[str, Any]:
        limit = _bounded_int(limit, "limit", 50)
        result = self._read("research report list", lambda: self.provider.list_research_reports(limit))
        return self._safe_mapping(result, "research report list", max_bytes=50_000)

    def prepare_monthly_site_evidence(
        self,
        period: str,
        idempotency_key: str,
        max_crawl_pages: int = 200,
    ) -> dict[str, Any]:
        self._period(period)
        max_crawl_pages = _bounded_int(max_crawl_pages, "max_crawl_pages", 2000)
        idempotency_key = self._bounded_text(idempotency_key, "idempotency_key", 240)
        result = self._read(
            "monthly evidence preparation",
            lambda: self.provider.prepare_monthly_site_evidence(period, idempotency_key, max_crawl_pages),
        )
        return self._safe_mapping(result, "monthly evidence preparation", max_bytes=150_000)

    def monthly_site_evidence(self, period: str) -> dict[str, Any]:
        self._period(period)
        result = self._read("monthly site evidence", lambda: self.provider.monthly_site_evidence(period))
        return self._safe_mapping(result, "monthly site evidence", max_bytes=150_000)

    def request_article_keyword_research(
        self,
        *,
        idea_key: str,
        idea_summary: str,
        queries: list[str],
        language: str,
        country: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not isinstance(queries, list) or not 5 <= len(queries) <= 10:
            raise CrawlSEOApplicationError("CrawlSEO queries must contain 5 to 10 candidates")
        bounded_queries = [self._bounded_text(query, "query", 120) for query in queries]
        if len({query.lower() for query in bounded_queries}) != len(bounded_queries):
            raise CrawlSEOApplicationError("CrawlSEO queries must be unique")
        arguments = {
            "idea_key": self._bounded_text(idea_key, "idea_key", 240),
            "idea_summary": self._bounded_text(idea_summary, "idea_summary", 2000),
            "queries": bounded_queries,
            "language": self._bounded_text(language, "language", 16),
            "country": self._bounded_text(country, "country", 2),
            "idempotency_key": self._bounded_text(idempotency_key, "idempotency_key", 240),
        }
        result = self._read(
            "article keyword research request",
            lambda: self.provider.request_article_keyword_research(**arguments),
        )
        return self._safe_mapping(result, "article keyword research request")

    def article_keyword_research_status(self, run_id: str) -> dict[str, Any]:
        run_id = self._bounded_text(run_id, "run_id", 120)
        result = self._read("article keyword research status", lambda: self.provider.article_keyword_research_status(run_id))
        return self._safe_mapping(result, "article keyword research status")

    def article_keyword_research(self, run_id: str) -> dict[str, Any]:
        run_id = self._bounded_text(run_id, "run_id", 120)
        result = self._read("article keyword research", lambda: self.provider.article_keyword_research(run_id))
        return self._safe_mapping(result, "article keyword research", max_bytes=150_000)

    def request_article_serp_research(
        self,
        *,
        parent_run_id: str,
        keyword: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        arguments = {
            "parent_run_id": self._bounded_text(parent_run_id, "parent_run_id", 120),
            "keyword": self._bounded_text(keyword, "keyword", 120),
            "idempotency_key": self._bounded_text(idempotency_key, "idempotency_key", 240),
        }
        result = self._read(
            "article SERP research request",
            lambda: self.provider.request_article_serp_research(**arguments),
        )
        return self._safe_mapping(result, "article SERP research request")

    def article_serp_research_status(self, run_id: str) -> dict[str, Any]:
        run_id = self._bounded_text(run_id, "run_id", 120)
        result = self._read("article SERP research status", lambda: self.provider.article_serp_research_status(run_id))
        return self._safe_mapping(result, "article SERP research status")

    def article_serp_research(self, run_id: str) -> dict[str, Any]:
        run_id = self._bounded_text(run_id, "run_id", 120)
        result = self._read("article SERP research", lambda: self.provider.article_serp_research(run_id))
        return self._safe_mapping(result, "article SERP research", max_bytes=150_000)

    def list_article_keyword_research(self, period: str | None = None, limit: int = 20) -> dict[str, Any]:
        if period is not None:
            self._period(period)
        limit = _bounded_int(limit, "limit", 50)
        result = self._read("article keyword research list", lambda: self.provider.list_article_keyword_research(period, limit))
        return self._safe_mapping(result, "article keyword research list", max_bytes=150_000)

    @staticmethod
    def _bounded_text(value: str, field_name: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise CrawlSEOApplicationError(f"CrawlSEO {field_name} is invalid")
        return value.strip()

    @staticmethod
    def _period(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise CrawlSEOApplicationError("CrawlSEO period must use YYYY-MM format")
        return value

    @staticmethod
    def _safe_mapping(result: Any, label: str, max_bytes: int = 50_000) -> dict[str, Any]:
        if not isinstance(result, Mapping):
            raise CrawlSEOApplicationError(f"invalid CrawlSEO {label} response")
        try:
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > max_bytes:
                raise ContractError("response is too large")
            return safe_payload(result, max_bytes=max_bytes)
        except (ContractError, TypeError, ValueError) as exc:
            raise CrawlSEOApplicationError(f"invalid CrawlSEO {label} response") from exc

    @staticmethod
    def _read(label: str, operation):
        try:
            return operation()
        except CrawlSEOApplicationError:
            raise
        except Exception as exc:  # noqa: BLE001 — provider details never cross this boundary
            raise CrawlSEOApplicationError(f"CrawlSEO {label} is unavailable") from exc

    @staticmethod
    def _as_contract(contract_type, result, label: str, **kwargs):
        if isinstance(result, contract_type):
            return result
        try:
            return contract_type.from_mapping(result, **kwargs)
        except (ContractError, TypeError, ValueError) as exc:
            raise CrawlSEOApplicationError(f"invalid CrawlSEO {label} response") from exc


# The longer name is the public composition name; these aliases keep the small
# service easy to identify from either the plan's terminology or callers.
CrawlSEOReadService = CrawlSEOApplicationService
CrawlSEOService = CrawlSEOApplicationService


__all__ = [
    "CrawlSEOApplicationError",
    "CrawlSEOApplicationService",
    "CrawlSEOReadService",
    "CrawlSEOService",
]

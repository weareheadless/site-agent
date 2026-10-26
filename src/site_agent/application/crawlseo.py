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


class CrawlSEORequestNotDispatched(CrawlSEOApplicationError):
    """A locally rejected request that is proven not to have reached a provider."""


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

    def sync_business_knowledge(self, *, workspace_id: str, project_id: str, document_id: str,
                                fields: Mapping[str, Any], idempotency_key: str, reason: str) -> dict[str, Any]:
        """Read then CAS-write a canonical business document; failures remain retryable."""
        reader = getattr(self.provider, "business_knowledge_document", None)
        writer = getattr(self.provider, "write_business_knowledge_document", None)
        if not callable(reader) or not callable(writer):
            raise CrawlSEOApplicationError("CrawlSEO business knowledge is unsupported by this connector")
        identity = {"workspaceId": workspace_id, "projectId": project_id, "documentId": document_id}
        current = self._read("business knowledge read", lambda: reader(
            workspace_id=workspace_id, project_id=project_id, document_id=document_id))
        revision = int(current.get("revision") or 0) if isinstance(current, Mapping) else 0
        body = {"schemaVersion": "business-knowledge/1", "kind": "document_write", **identity,
                "expectedRevision": revision, "idempotencyKey": idempotency_key,
                "reason": reason[:1000], "changes": dict(fields)}
        result = self._read("business knowledge write", lambda: writer(body))
        return self._safe_mapping(result, "business knowledge write")

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
        try:
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
        except CrawlSEOApplicationError as exc:
            raise CrawlSEORequestNotDispatched(str(exc)) from exc
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
        try:
            arguments = {
                "parent_run_id": self._bounded_text(parent_run_id, "parent_run_id", 120),
                "keyword": self._bounded_text(keyword, "keyword", 120),
                "idempotency_key": self._bounded_text(idempotency_key, "idempotency_key", 240),
            }
        except CrawlSEOApplicationError as exc:
            raise CrawlSEORequestNotDispatched(str(exc)) from exc
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

    def connector_capabilities(self, site_id: str | None = None) -> dict[str, Any]:
        operation = getattr(self.provider, "connector_capabilities", None)
        if not callable(operation):
            raise CrawlSEOApplicationError("CrawlSEO connector capabilities is unsupported by this configured connector")
        raw = self._read("connector capabilities", lambda: operation(site_id=site_id))
        result = self._safe_mapping(raw, "connector capabilities", max_bytes=200_000)
        # Scope names are non-secret authorization metadata. The generic payload
        # redactor treats the word "credential" as sensitive, so preserve only
        # this bounded allowlist for activation checks.
        scopes = raw.get("credentialScopes") if isinstance(raw, Mapping) else None
        if isinstance(scopes, list) and len(scopes) <= 32 and all(
            isinstance(scope, str) and re.fullmatch(r"[a-z][a-z0-9:_-]{0,63}", scope.lower())
            for scope in scopes
        ):
            result["credentialScopes"] = sorted({scope.lower() for scope in scopes})
        return result

    def connector_policy(self, site_id: str) -> dict[str, Any]:
        result = self._connector_call("connector_policy", "research policy", site_id=self._bounded_text(site_id, "site id", 120))
        value = result.get("policy") if isinstance(result.get("policy"), Mapping) else result
        return self._safe_mapping(value, "research policy")

    def connector_update_policy(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(policy, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO research policy must be an object")
        result = self._connector_call("connector_update_policy", "research policy update", policy=dict(policy))
        value = result.get("policy") if isinstance(result.get("policy"), Mapping) else result
        return self._safe_mapping(value, "research policy")

    def connector_actions(self, since: str | None = None, limit: int = 50, cursor: str | None = None,
                          site_id: str | None = None) -> dict[str, Any]:
        limit = _bounded_int(limit, "action limit", 100)
        if since is not None:
            self._bounded_text(since, "action cursor", 40)
        if cursor is not None:
            self._bounded_text(cursor, "action page cursor", 300)
        return self._connector_call("connector_actions", "connector actions", since=since, limit=limit, cursor=cursor, site_id=site_id)

    def connector_findings(self, site_id: str, *, run_id: str | None = None, since: str | None = None,
                           limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        site_id = self._bounded_text(site_id, "site id", 120)
        limit = _bounded_int(limit, "finding limit", 100)
        if run_id is not None:
            run_id = self._bounded_text(run_id, "run id", 120)
        if since is not None:
            since = self._bounded_text(since, "finding timestamp", 40)
        if cursor is not None:
            cursor = self._bounded_text(cursor, "finding page cursor", 500)
        capabilities = self.connector_capabilities(site_id)
        if capabilities.get("schemaVersion") != "1.0" or capabilities.get("siteId") != site_id:
            raise CrawlSEOApplicationError("CrawlSEO connector binding does not match the requested site")
        capability_list = capabilities.get("capabilities") if isinstance(capabilities.get("capabilities"), list) else []
        if "findings.read" not in capability_list:
            raise CrawlSEOApplicationError("CrawlSEO findings are unsupported by this connector")
        operation = getattr(self.provider, "connector_findings", None)
        if not callable(operation):
            raise CrawlSEOApplicationError("CrawlSEO connector findings are unsupported by this client")
        result = self._read("connector findings", lambda: operation(site_id=site_id, run_id=run_id,
            since=since, limit=limit, cursor=cursor))
        response = self._safe_mapping(result, "connector findings", max_bytes=2_000_000)
        if response.get("schemaVersion") != "1.0" or response.get("siteId") != site_id or response.get("projectId") != capabilities.get("projectId"):
            raise CrawlSEOApplicationError("CrawlSEO findings project/site identity does not match the selected binding")
        if (not isinstance(response.get("findings"), list)
                or (response.get("nextCursor") is not None and not isinstance(response.get("nextCursor"), str))):
            raise CrawlSEOApplicationError("CrawlSEO connector returned an invalid findings inventory")
        return response

    def connector_action(self, action_id: str, site_id: str | None = None) -> dict[str, Any]:
        result = self._connector_call("connector_action", "connector action", action_id=self._bounded_text(action_id, "action id", 120), site_id=site_id)
        action = result.get("action") if isinstance(result.get("action"), Mapping) else result
        if not isinstance(action, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO connector returned an invalid Action")
        return self._safe_mapping(action, "connector Action")

    def connector_context(self, site_id: str | None = None) -> dict[str, Any]:
        return self._connector_call("connector_context", "connector context", site_id=site_id)

    def connector_update_context(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO context snapshot must be an object")
        return self._connector_call("connector_update_context", "connector context update", snapshot=snapshot)

    def connector_operation(self, action_id: str, operation: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(operation, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO operation must be an object")
        return self._connector_call("connector_operation", "connector operation", action_id=self._bounded_text(action_id, "action id", 120), operation=operation)

    def connector_decide(self, action_id: str, operation: str, *, rationale: str = "",
                         idempotency_key: str | None = None) -> dict[str, Any]:
        action_id = self._bounded_text(action_id, "action id", 120)
        if operation not in {"accept_preparation", "decline_preparation", "request_correction", "cancel_preparation"}:
            raise CrawlSEOApplicationError("CrawlSEO preparation operation is invalid")
        action_response = self.connector_action(action_id)
        action = action_response.get("action") if isinstance(action_response.get("action"), Mapping) else action_response
        if not isinstance(action, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO connector returned an invalid Action")
        action_site = action.get("site") if isinstance(action.get("site"), Mapping) else {}
        capabilities = self.connector_capabilities(str(action_site.get("id") or "") or None)
        binding = capabilities.get("binding") if isinstance(capabilities.get("binding"), Mapping) else {}
        generation, revision = binding.get("generation"), action.get("revision")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (generation, revision)):
            raise CrawlSEOApplicationError("CrawlSEO connector binding or Action revision is invalid")
        import uuid
        key = self._bounded_text(idempotency_key, "idempotency key", 240) if idempotency_key is not None else uuid.uuid4().hex
        return self.connector_operation(action_id, {"operation": operation, "expectedRevision": revision,
            "generation": generation, "idempotencyKey": key, **({"rationale": rationale[:2000]} if rationale else {})})

    def connector_execution_status(self, action_id: str, status: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(status, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO execution status must be an object")
        return self._connector_call("connector_execution_status", "connector execution status", action_id=self._bounded_text(action_id, "action id", 120), status=status)

    def connector_record_execution(self, action_id: str, status: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(status, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO execution status must be an object")
        response = self.connector_action(action_id)
        action = response.get("action") if isinstance(response.get("action"), Mapping) else response
        if not isinstance(action, Mapping):
            raise CrawlSEOApplicationError("CrawlSEO connector returned an invalid Action")
        action_site = action.get("site") if isinstance(action.get("site"), Mapping) else {}
        capabilities = self.connector_capabilities(str(action_site.get("id") or "") or None)
        binding = capabilities.get("binding") if isinstance(capabilities.get("binding"), Mapping) else {}
        generation, revision = binding.get("generation"), action.get("revision")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (generation, revision)):
            raise CrawlSEOApplicationError("CrawlSEO connector binding or Action revision is invalid")
        import hashlib
        import json
        operation = dict(status)
        operation.update({"actionRevision": revision, "generation": generation,
            "idempotencyKey": hashlib.sha256(
                f"{action_id}:{revision}:{json.dumps(dict(status), sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)}".encode()
            ).hexdigest()})
        return self.connector_execution_status(action_id, operation)

    def connector_events(self, after: int = 0, limit: int = 100, site_id: str | None = None) -> dict[str, Any]:
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise CrawlSEOApplicationError("CrawlSEO event cursor is invalid")
        limit = _bounded_int(limit, "event limit", 100)
        return self._connector_call("connector_events", "connector events", after=after, limit=limit, site_id=site_id)

    def connector_sync(self, *, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Refresh the site snapshot, drain durable events, and read Actions."""
        expected_site = str(snapshot.get("siteId") or "")
        if not expected_site:
            raise CrawlSEOApplicationError("CrawlSEO connector snapshot omitted its site identity")
        capabilities = self.connector_capabilities(expected_site)
        if capabilities.get("schemaVersion") != "1.0":
            raise CrawlSEOApplicationError("CrawlSEO connector schema version is unsupported")
        if capabilities.get("siteId") != expected_site:
            raise CrawlSEOApplicationError("CrawlSEO connector binding does not match the requested site")
        expected_project = str(capabilities.get("projectId") or "")
        if not expected_project or not expected_site:
            raise CrawlSEOApplicationError("CrawlSEO connector omitted its project or site identity")

        def validate_action(value: Mapping[str, Any]) -> dict[str, Any]:
            project = value.get("project") if isinstance(value.get("project"), Mapping) else {}
            site = value.get("site") if isinstance(value.get("site"), Mapping) else {}
            if (value.get("schemaVersion") != "1.0" or str(project.get("id") or "") != expected_project
                    or str(site.get("id") or "") != expected_site):
                raise CrawlSEOApplicationError("CrawlSEO Action identity or schema does not match the active connector")
            if not isinstance(value.get("id"), str) or not value["id"].strip():
                raise CrawlSEOApplicationError("CrawlSEO Action omitted its stable identity")
            if "evidenceComplete" in value and not isinstance(value.get("evidenceComplete"), bool):
                raise CrawlSEOApplicationError("CrawlSEO Action evidence completeness marker is invalid")
            unavailable = value.get("unavailableEvidenceSourceIds", [])
            if (not isinstance(unavailable, list)
                    or any(not isinstance(source_id, str) or not source_id.strip() for source_id in unavailable)):
                raise CrawlSEOApplicationError("CrawlSEO Action unavailable evidence references are invalid")
            if value.get("evidenceComplete") is False or unavailable:
                raise CrawlSEOApplicationError("CrawlSEO Action has missing evidence sources and cannot enter owner work")
            return dict(value)

        current = self.connector_context(expected_site)
        candidate = dict(snapshot)
        previous = current.get("snapshot") if isinstance(current.get("snapshot"), Mapping) else current
        previous_revision = str(previous.get("revision") or "")
        candidate.update({"siteId": snapshot.get("siteId"),
                          "revision": str(int(previous_revision) + 1) if previous_revision.isdigit() else "1",
                          "expectedRevision": previous_revision or None,
                          "observedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds")})
        self.connector_update_context(candidate)
        events = self.connector_events(after=0, limit=100, site_id=expected_site)
        actions_by_id: dict[str, dict[str, Any]] = {}
        failed: list[dict[str, str]] = []
        for event in events.get("events", []):
            if not isinstance(event, Mapping):
                continue
            action_id = event.get("actionId")
            if isinstance(action_id, str):
                try:
                    action = self.connector_action(action_id, expected_site)
                    actions_by_id[action_id] = validate_action(action)
                except Exception as exc:
                    event_id = str(event.get("id") or "")
                    if event_id:
                        failed.append({"id": event_id, "message": str(exc)[:500] or "Action reconciliation failed"})
        # A connector poll is not a durable local execution receipt. The
        # coordinator acknowledges only after persisting the local binding.
        if failed:
            self.connector_ack_events([], failed, site_id=expected_site)
        cursor = None
        seen_cursors: set[str] = set()
        for _page in range(1000):
            listed = self.connector_actions(limit=100, cursor=cursor, site_id=expected_site)
            for row in listed.get("actions", []):
                if isinstance(row, Mapping) and isinstance(row.get("id"), str):
                    action = validate_action(row)
                    actions_by_id[str(action["id"])] = action
            cursor = listed.get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise CrawlSEOApplicationError("CrawlSEO Action pagination cursor is invalid")
            seen_cursors.add(cursor)
        else:
            raise CrawlSEOApplicationError("CrawlSEO Action inventory exceeds the safe pagination limit")
        result_context = self.connector_context(expected_site)
        saved = result_context.get("snapshot") if isinstance(result_context.get("snapshot"), Mapping) else {}
        return {"schemaVersion": "1.0", "contextRevision": saved.get("revision"),
                "actions": list(actions_by_id.values()), "events": list(events.get("events", [])),
                "capabilities": capabilities}

    def connector_ack_events(self, acknowledged: list[str], failed: list[Mapping[str, str]] | None = None,
                             site_id: str | None = None) -> dict[str, Any]:
        if not isinstance(acknowledged, list) or len(acknowledged) > 100:
            raise CrawlSEOApplicationError("CrawlSEO event acknowledgements are invalid")
        return self._connector_call("connector_ack_events", "connector event acknowledgement", acknowledged=acknowledged, failed=failed or [], site_id=site_id)

    def connector_budget(self, site_id: str) -> dict[str, Any]:
        site_id = self._bounded_text(site_id, "site_id", 120)
        result = self._connector_call("connector_budget", "budget", site_id=site_id)
        budget = result.get("budget") if isinstance(result.get("budget"), Mapping) else result
        return self._safe_mapping(budget, "budget")

    def connector_update_budget_policy(self, policy: Mapping[str, Any]) -> dict[str, Any]:
        result = self._connector_call("connector_update_budget_policy", "budget policy", policy=policy)
        value = result.get("policy") if isinstance(result.get("policy"), Mapping) else result
        return self._safe_mapping(value, "budget policy")

    def connector_budget_reserve(self, reservation: Mapping[str, Any]) -> dict[str, Any]:
        result = self._connector_call("connector_budget_reserve", "budget reservation", reservation=reservation)
        value = result.get("reservation") if isinstance(result.get("reservation"), Mapping) else result
        return self._safe_mapping(value, "budget reservation")

    def connector_budget_settle(self, reservation_id: str, settlement: Mapping[str, Any]) -> dict[str, Any]:
        reservation_id = self._bounded_text(reservation_id, "reservation_id", 120)
        result = self._connector_call("connector_budget_settle", "budget settlement", reservation_id=reservation_id, settlement=settlement)
        value = result.get("reservation") if isinstance(result.get("reservation"), Mapping) else result
        return self._safe_mapping(value, "budget settlement")

    def connector_budget_get_reservation(self, reservation_id: str) -> dict[str, Any]:
        reservation_id = self._bounded_text(reservation_id, "reservation_id", 120)
        result = self._connector_call("connector_budget_get_reservation", "budget reservation", reservation_id=reservation_id)
        value = result.get("reservation") if isinstance(result.get("reservation"), Mapping) else result
        return self._safe_mapping(value, "budget reservation")

    def _connector_call(self, method: str, label: str, **kwargs: Any) -> dict[str, Any]:
        operation = getattr(self.provider, method, None)
        if not callable(operation):
            raise CrawlSEOApplicationError(f"CrawlSEO {label} is unsupported by this configured connector")
        result = self._read(label, lambda: operation(**kwargs))
        return self._safe_mapping(result, label, max_bytes=200_000)

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
            if "IDEMPOTENCY_CONFLICT" in str(exc):
                raise CrawlSEOApplicationError("CrawlSEO business knowledge IDEMPOTENCY_CONFLICT") from exc
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
    "CrawlSEORequestNotDispatched",
    "CrawlSEOApplicationService",
    "CrawlSEOReadService",
    "CrawlSEOService",
]

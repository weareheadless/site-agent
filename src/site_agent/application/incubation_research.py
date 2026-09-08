"""Owner-controlled research for one customer incubation."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any, Callable

from ..core.contracts import ContractError, utc_now
from ..core.design_contracts import canonical_hash
from ..core.incubation_contracts import (
    IncubationInsight,
    ResearchFinding,
    ResearchJob,
    ResearchJobStatus,
    ResearchRequest,
    ResearchRequestStatus,
    ResearchSource,
    ResearchTrigger,
    SourceTrustState,
    SubscriptionState,
)
from ..core.memory import Memory
from ..hands.feed_discovery import (
    BoundedFeedReader,
    FeedDiscoveryError,
    RedditFeedDiscovery,
    ResearchDocument,
    ResearchReader,
    UrlFeedDiscovery,
)
from .incubation_activity import IncubationActivityError, IncubationActivityService


from urllib.parse import urlsplit as _urlsplit


class IncubationResearchError(ValueError):
    """Research could not be completed without violating source policy."""


class IncubationResearchService:
    """Discover, approve, read, and summarize bounded public research sources."""

    def __init__(
        self,
        memory: Memory,
        *,
        reader: ResearchReader | None = None,
        discovery: UrlFeedDiscovery | None = None,
        community_discovery: RedditFeedDiscovery | None = None,
        activity_service: IncubationActivityService | None = None,
        synthesizer: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
        fallback_reader: Callable[[Mapping[str, Any]], list[Mapping[str, Any]]] | None = None,
        now: Callable[[], str] = utc_now,
        max_sources_per_pass: int = 8,
        max_items_per_source: int = 15,
    ) -> None:
        self.memory = memory
        self.max_sources_per_pass = max(1, min(int(max_sources_per_pass), 50))
        self.max_items_per_source = max(1, min(int(max_items_per_source), 100))
        self.reader = reader or BoundedFeedReader(max_items=self.max_items_per_source)
        self.discovery = discovery or UrlFeedDiscovery()
        self.community_discovery = community_discovery or RedditFeedDiscovery()
        self.activity_service = activity_service
        self.synthesizer = synthesizer
        self.fallback_reader = fallback_reader
        self.now = now

    def projection(self) -> dict[str, Any]:
        return {
            "sources": self.memory.list_research_sources(limit=500),
            "findings": [item.to_dict() for item in self.memory.list_research_findings(limit=1_000)],
            "requests": self.memory.list_research_requests(limit=100),
            "jobs": self.memory.list_research_jobs(limit=100),
            "insights": self.memory.list_incubation_insights(limit=200),
        }

    def _activity(self, **kwargs: Any) -> None:
        if self.activity_service is None:
            return
        try:
            self.activity_service.record(**kwargs)
        except IncubationActivityError as exc:
            raise IncubationResearchError(str(exc)[:500]) from exc

    def _request(self, body: Mapping[str, Any]) -> dict[str, Any]:
        intent = str(body.get("query") or body.get("intent") or "").strip()[:2_000]
        owner_language = str(body.get("owner_language") or body.get("language") or "en").strip().lower()
        subjects = _text_items(body.get("subjects") or body.get("subject"))
        if not subjects and intent:
            subjects = [intent[:500]]
        markets = _text_items(body.get("markets") or body.get("market"))
        try:
            intake_revision = int(body.get("intake_revision") or body.get("revision") or 0)
        except (TypeError, ValueError) as exc:
            raise IncubationResearchError("intake_revision is invalid") from exc
        trigger = str(body.get("trigger") or ResearchTrigger.OWNER_REQUEST.value).strip().lower()
        query_terms = body.get("query_terms_by_language")
        if not isinstance(query_terms, Mapping):
            query_terms = {owner_language: sorted(_terms(intent))} if intent else {}
        candidate_communities = body.get("candidate_communities") or []
        normalized_for_hash = {
            "intake_revision": intake_revision,
            "owner_language": owner_language,
            "intent": intent.casefold(),
            "subjects": sorted(item.casefold() for item in subjects),
            "markets": sorted(item.casefold() for item in markets),
            "trigger": trigger,
        }
        dedupe_key = canonical_hash(normalized_for_hash)
        request_id = "research_" + dedupe_key[:32]
        now = self.now()
        request = ResearchRequest.from_dict({
            "request_id": request_id,
            "dedupe_key": dedupe_key,
            "created_at": now,
            "updated_at": now,
            "status": ResearchRequestStatus.NEEDS_ATTENTION.value,
            "trigger": trigger,
            "intake_revision": intake_revision,
            "owner_language": owner_language,
            "subjects": subjects,
            "markets": markets,
            "candidate_communities": candidate_communities,
            "query_terms_by_language": query_terms,
            "source_ids": [],
            "finding_ids": [],
            "insight_ids": [],
            "error": "",
            "intent": intent,
        })
        existing = self.memory.get_research_request_by_dedupe_key(dedupe_key)
        if existing is not None:
            return existing
        return self.memory.save_research_request(request)

    def _merge_request(self, request_id: str, **changes: Any) -> dict[str, Any]:
        if not changes:
            return self.memory.get_research_request(request_id) or {}
        return self.memory.update_research_request(request_id, **changes)

    def _job(self, request: Mapping[str, Any]) -> dict[str, Any]:
        request_id = str(request.get("request_id") or "")
        job_id = "research_job_" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:32]
        existing = self.memory.get_research_job(job_id)
        if existing is not None:
            return existing
        now = self.now()
        job = ResearchJob.from_dict({
            "job_id": job_id,
            "request_id": request_id,
            "status": ResearchJobStatus.QUEUED.value,
            "attempt": 0,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
            "error": "",
        })
        return self.memory.save_research_job(job)

    def enqueue(self, request_id: str) -> dict[str, Any] | None:
        """Queue one approved request without doing network work in the caller."""
        request = self.memory.get_research_request(request_id)
        if request is None:
            raise IncubationResearchError("research request was not found")
        source_ids = [str(item or "").strip() for item in list(request.get("source_ids") or [])[: self.max_sources_per_pass]]
        if not source_ids:
            return None
        allowed = False
        policy_candidates = False
        for source_id in source_ids:
            source = self.memory.get_research_source(source_id) or {}
            if source.get("trust_state") == SourceTrustState.ALLOWED.value and not source.get("excluded"):
                allowed = True
            if (
                request.get("trigger")
                in {ResearchTrigger.INTAKE_THRESHOLD.value, ResearchTrigger.INFUSION.value}
                and source.get("trust_state") == SourceTrustState.CANDIDATE.value
                and source.get("discovered_by") == "research_planner"
                and not source.get("excluded")
            ):
                policy_candidates = True
        if not allowed and not policy_candidates:
            return None
        job = self._job(request)
        if job.get("status") == ResearchJobStatus.COMPLETED.value:
            return job
        if job.get("status") not in {ResearchJobStatus.QUEUED.value, ResearchJobStatus.RUNNING.value}:
            job = self.memory.update_research_job(
                job["job_id"],
                status=ResearchJobStatus.QUEUED.value,
                started_at=None,
                completed_at=None,
                error="",
            )
        request = self.memory.update_research_request(
            request["request_id"],
            status=ResearchRequestStatus.QUEUED.value,
            error="",
        )
        return self.memory.get_research_job(job["job_id"]) or job

    def _candidate_status(self, request_id: str, source_id: str, status: str) -> None:
        request = self.memory.get_research_request(request_id)
        if request is None:
            return
        candidates = []
        changed = False
        for candidate in list(request.get("candidate_communities") or []):
            item = dict(candidate)
            if item.get("source_id") == source_id and item.get("status") != status:
                item["status"] = status
                changed = True
            candidates.append(item)
        if changed:
            self.memory.update_research_request(request_id, candidate_communities=candidates)

    def discover(self, urls: Sequence[str]) -> dict[str, Any]:
        try:
            sources = self.discovery.discover(urls)
            saved = [self._save_source(source) for source in sources]
        except (ContractError, FeedDiscoveryError, TypeError, ValueError) as exc:
            raise IncubationResearchError(str(exc)[:500]) from exc
        return {"sources": saved, "source_ids": [item["source_id"] for item in saved]}

    def _save_source(self, source: ResearchSource) -> dict[str, Any]:
        existing = self.memory.get_research_source(source.source_id)
        if existing is not None:
            same_url = existing.get("url") == source.url and existing.get("feed_url") == source.feed_url
            same_reddit_candidate = (
                existing.get("discovered_by") == source.discovered_by == "research_planner"
                and str(existing.get("url") or "").casefold() == source.url.casefold()
                and str(existing.get("feed_url") or "").casefold() == source.feed_url.casefold()
            )
            if not same_url and not same_reddit_candidate:
                raise IncubationResearchError("research source ID was used for a different URL")
            if source.language and source.language != existing.get("language"):
                return self.memory.update_research_source(source.source_id, language=source.language)
            return existing
        return self.memory.save_research_source(source)

    def update_source(self, source_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, Mapping):
            raise IncubationResearchError("source update must be an object")
        allowed = {"trust_state", "ongoing_subscription", "title", "language"}
        if set(changes) - allowed:
            raise IncubationResearchError("source update contains unsupported fields")
        normalized = dict(changes)
        current = self.memory.get_research_source(str(source_id or "").strip())
        if current is None:
            raise IncubationResearchError("research source was not found")
        if "trust_state" in normalized:
            trust = str(normalized["trust_state"] or "").strip().lower()
            if trust not in {item.value for item in SourceTrustState}:
                raise IncubationResearchError("source trust_state is invalid")
            normalized["trust_state"] = trust
        if "language" in normalized:
            language = str(normalized["language"] or "").strip().lower()
            if language and not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", language):
                raise IncubationResearchError("source language is invalid")
            normalized["language"] = language
        if "ongoing_subscription" in normalized:
            subscription = str(normalized["ongoing_subscription"] or "").strip().lower()
            if subscription not in {item.value for item in SubscriptionState}:
                raise IncubationResearchError("source ongoing_subscription is invalid")
            effective_trust = normalized.get("trust_state", current.get("trust_state"))
            if subscription == SubscriptionState.APPROVED.value and effective_trust != SourceTrustState.ALLOWED.value:
                raise IncubationResearchError("ongoing subscriptions require an allowed source")
            normalized["ongoing_subscription"] = subscription
        if normalized.get("trust_state") == SourceTrustState.ALLOWED.value:
            normalized.setdefault("ongoing_subscription", SubscriptionState.NOT_APPLICABLE.value)
        try:
            return self.memory.update_research_source(str(source_id or "").strip(), **normalized)
        except (ContractError, ValueError) as exc:
            raise IncubationResearchError(str(exc)[:500]) from exc

    def run(
        self,
        source_ids: Sequence[str],
        *,
        query: str = "",
        request_id: str | None = None,
        allow_policy_candidates: bool = False,
    ) -> dict[str, Any]:
        ids = [str(item or "").strip() for item in list(source_ids)[: self.max_sources_per_pass]]
        if not ids:
            raise IncubationResearchError("at least one approved research source is required")
        request = self.memory.get_research_request(request_id) if request_id else None
        if request is None:
            request = self._request({"query": query, "subjects": [query] if query else []})
        job = self._job(request)
        if job.get("status") == ResearchJobStatus.COMPLETED.value:
            return self._completed_result(request, job, ids)
        self.memory.update_research_job(job["job_id"], status=ResearchJobStatus.RUNNING.value, started_at=self.now(), attempt=int(job.get("attempt") or 0) + 1)
        request = self.memory.update_research_request(request["request_id"], status=ResearchRequestStatus.RUNNING.value, source_ids=sorted(set(request.get("source_ids") or []) | set(ids)))
        self._activity(
            category="research",
            kind="research_pass",
            state="started",
            summary="Started a bounded public research pass.",
            provenance="system",
            detail={"trigger": request.get("trigger"), "request_status": request.get("status")},
            research_request_id=request["request_id"],
        )
        findings: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        query_terms = _terms(query)
        for terms in (request.get("query_terms_by_language") or {}).values():
            query_terms.update(_terms(" ".join(str(item or "") for item in terms)))
        for source_id in ids:
            raw = self.memory.get_research_source(source_id)
            if raw is None:
                errors.append({"source_id": source_id, "error": "source was not found", "error_code": "not_found"})
                continue
            policy_candidate = bool(
                allow_policy_candidates
                and request.get("trigger")
                in {ResearchTrigger.INTAKE_THRESHOLD.value, ResearchTrigger.INFUSION.value}
                and raw.get("trust_state") == SourceTrustState.CANDIDATE.value
                and raw.get("discovered_by") == "research_planner"
                and not raw.get("excluded")
            )
            if (raw.get("trust_state") != SourceTrustState.ALLOWED.value or raw.get("excluded")) and not policy_candidate:
                errors.append({
                    "source_id": source_id,
                    "error": "source requires owner approval",
                    "error_code": "owner_approval_required",
                })
                continue
            try:
                if policy_candidate:
                    self._activity(
                        category="research",
                        kind="community_candidate_verification",
                        state="started",
                        summary="Verifying one model-nominated public community before reading it.",
                        provenance="host_validation",
                        detail={"candidate_name": raw.get("title") or "Public community", "candidate_status": "candidate"},
                        research_request_id=request["request_id"],
                        source_id=source_id,
                    )
                self._activity(
                    category="research",
                    kind="source_read",
                    state="started",
                    summary="Checking one owner-approved public source.",
                    provenance="host_validation",
                    detail={"source_title": raw.get("title") or "Public source"},
                    research_request_id=request["request_id"],
                    source_id=source_id,
                )
                source = ResearchSource.from_dict({
                    key: raw[key]
                    for key in (
                        "source_id", "kind", "url", "feed_url", "title", "discovered_by",
                        "language",
                        "trust_state", "ongoing_subscription", "fetched_at", "content_hash",
                    )
                })
                documents = self.reader.read(source)
                for document in documents:
                    finding = self._finding(document, query_terms)
                    self.memory.save_research_finding(finding)
                    findings.append(finding.to_dict())
                source_changes: dict[str, Any] = {"fetched_at": self.now()}
                if documents:
                    source_changes["content_hash"] = documents[-1].content_hash
                self.memory.update_research_source(source.source_id, **source_changes)
                if policy_candidate:
                    candidate_status = "verified" if documents else "readable_no_items"
                    self._candidate_status(request["request_id"], source_id, candidate_status)
                    self._activity(
                        category="research",
                        kind="community_candidate_verification",
                        state="completed",
                        summary=(
                            "Verified a public community and retained its bounded evidence."
                            if documents else
                            "Reached a readable public community with no bounded items available."
                        ),
                        provenance="host_validation",
                        confidence=1.0,
                        detail={"candidate_name": raw.get("title") or "Public community", "candidate_status": candidate_status},
                        research_request_id=request["request_id"],
                        source_id=source_id,
                    )
                self._activity(
                    category="research",
                    kind="source_read",
                    state="completed",
                    summary=f"Read {len(documents)} bounded public item(s) from the approved source.",
                    provenance="public_source",
                    confidence=0.5 if documents else 0.2,
                    detail={"item_count": len(documents)},
                    research_request_id=request["request_id"],
                    source_id=source_id,
                    finding_ids=[item["finding_id"] for item in findings if item["source_id"] == source_id],
                )
            except (ContractError, FeedDiscoveryError, OSError, TypeError, ValueError) as exc:
                errors.append({
                    "source_id": source_id,
                    "error": str(exc)[:500],
                    "error_code": _error_code(exc),
                })
                if policy_candidate:
                    self._candidate_status(request["request_id"], source_id, "rejected")
                    self._activity(
                        category="research",
                        kind="community_candidate_verification",
                        state="needs_attention",
                        summary="A model-nominated community did not pass public-source verification.",
                        provenance="host_validation",
                        confidence=1.0,
                        detail={"candidate_name": raw.get("title") or "Public community", "candidate_status": "rejected", "error_code": _error_code(exc)},
                        research_request_id=request["request_id"],
                        source_id=source_id,
                    )
                self._activity(
                    category="research",
                    kind="source_read",
                    state="needs_attention",
                    summary="A bounded public source could not be read.",
                    provenance="host_validation",
                    detail={"error_code": _error_code(exc)},
                    research_request_id=request["request_id"],
                    source_id=source_id,
                )
        if not findings:
            soft = request.get("trigger") in {
                ResearchTrigger.INTAKE_THRESHOLD.value,
                ResearchTrigger.INFUSION.value,
            }
            if soft:
                # Automatic research is optional: a pass that reads nothing must
                # never fail or block the incubation. Fall back to a bounded
                # pipeworx query on the business intent so the pass still
                # produces evidence for the advisor instead of ending empty.
                note = "optional research: no source readable yet"
                self.memory.update_research_job(job["job_id"], status=ResearchJobStatus.COMPLETED.value, completed_at=self.now(), error=note)
                request = self.memory.update_research_request(
                    request["request_id"],
                    status=ResearchRequestStatus.COMPLETED.value,
                    error=note,
                    source_ids=sorted(set(request.get("source_ids") or []) | set(ids)),
                )
                self._activity(
                    category="research",
                    kind="research_pass",
                    state="completed",
                    summary="Optional research pass found nothing readable yet; the brief is unaffected.",
                    provenance="host_validation",
                    confidence=0.2,
                    detail={"request_status": request["status"]},
                    research_request_id=request["request_id"],
                )
                fallback = self._fallback_evidence(request)
                if fallback:
                    request = self.memory.update_research_request(
                        request["request_id"],
                        finding_ids=sorted(set(request.get("finding_ids") or []) | {item["finding_id"] for item in fallback}),
                        error="",
                    )
                    insights = self._synthesize_insights(request, fallback)
                    if insights:
                        request = self.memory.update_research_request(
                            request["request_id"],
                            insight_ids=sorted(set(request.get("insight_ids") or []) | {item["insight_id"] for item in insights}),
                        )
                    findings = fallback
                return {"findings": findings, "insights": insights if fallback else [], "errors": errors, "source_ids": ids,
                        "request": request, "job": self.memory.get_research_job(job["job_id"]) or job}
            self.memory.update_research_job(job["job_id"], status=ResearchJobStatus.FAILED.value, completed_at=self.now(), error="no approved research source could be read")
            self.memory.update_research_request(request["request_id"], status=ResearchRequestStatus.NEEDS_ATTENTION.value, error="no approved research source could be read")
            raise IncubationResearchError("no approved research source could be read")
        insights = self._synthesize_insights(request, findings)
        request = self.memory.update_research_request(
            request["request_id"],
            status=ResearchRequestStatus.COMPLETED.value,
            source_ids=sorted(set(request.get("source_ids") or []) | set(ids)),
            finding_ids=sorted(set(request.get("finding_ids") or []) | {item["finding_id"] for item in findings}),
            insight_ids=sorted(set(request.get("insight_ids") or []) | {item["insight_id"] for item in insights}),
            error="" if not errors else "some sources could not be read",
        )
        job = self.memory.update_research_job(job["job_id"], status=ResearchJobStatus.COMPLETED.value, completed_at=self.now(), error="" if not errors else "some sources could not be read")
        self._activity(
            category="research",
            kind="research_pass",
            state="completed" if not errors else "needs_attention",
            summary=f"Completed a bounded research pass with {len(findings)} finding(s).",
            provenance="public_source",
            confidence=0.5 if findings else 0.2,
            detail={"item_count": len(findings), "request_status": request["status"]},
            research_request_id=request["request_id"],
            finding_ids=[item["finding_id"] for item in findings],
        )
        return {"findings": findings, "insights": insights, "errors": errors, "source_ids": ids, "request": request, "job": job}

    def _fallback_evidence(self, request: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Run one bounded pipeworx/web query when a public-source pass found
        nothing readable. The fallback reader returns bounded evidence-shaped
        mappings; each becomes a durable ResearchFinding so the advisor briefing
        and the background-analysis bubble still get real evidence."""
        if self.fallback_reader is None:
            return []
        intent = str(request.get("intent") or "").strip()[:2_000]
        if not intent:
            return []
        try:
            evidence = self.fallback_reader({
                "query": intent,
                "owner_language": str(request.get("owner_language") or "en").strip(),
                "request_id": str(request.get("request_id") or ""),
            })
        except Exception:  # noqa: BLE001 - fallback must never break a research pass
            return []
        findings: list[dict[str, Any]] = []
        for item in list(evidence or ())[:20]:
            if not isinstance(item, Mapping):
                continue
            summary = str(item.get("summary") or "").strip()[:4_000]
            if not summary:
                continue
            raw_url = str(item.get("url") or "").strip()
            source_key = str(item.get("source") or raw_url or "pipeworx").strip()[:80]
            source_id = "src_fallback_" + hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:32]
            if self.memory.get_research_source(source_id) is None:
                url = raw_url
                try:
                    parsed = _urlsplit(url) if url else None
                except Exception:
                    parsed = None
                if not url or parsed is None or parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    url = f"https://pipeworx.io/research/{hashlib.sha256(source_key.encode('utf-8')).hexdigest()[:24]}"
                source = ResearchSource.from_dict({
                    "source_id": source_id,
                    "kind": "website",
                    "url": url,
                    "feed_url": url,
                    "title": str(item.get("source") or "pipeworx")[:200],
                    "discovered_by": "research_planner",
                    "language": str(item.get("language") or "und").strip().lower() or "und",
                    "trust_state": SourceTrustState.ALLOWED.value,
                    "ongoing_subscription": SubscriptionState.NOT_APPLICABLE.value,
                    "fetched_at": self.now(),
                    "content_hash": "",
                })
                try:
                    self.memory.save_research_source(source)
                except Exception:  # noqa: BLE001
                    continue
            finding = self._finding(
                ResearchDocument(
                    source_id=source_id,
                    title=str(item.get("title") or summary)[:300],
                    summary=summary,
                    url=str(item.get("url") or ""),
                    published_at=str(item.get("published_at") or ""),
                    content_hash=hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                ),
                _terms(intent),
            )
            if str(item.get("confidence") or ""):
                try:
                    finding = finding.to_dict()
                    finding["confidence"] = max(0.0, min(1.0, float(item.get("confidence"))))
                    finding = ResearchFinding.from_dict(finding)
                except (ContractError, TypeError, ValueError):
                    pass
            try:
                self.memory.save_research_finding(finding)
            except Exception:  # noqa: BLE001
                continue
            findings.append(finding.to_dict())
        if findings:
            self._activity(
                category="research",
                kind="research_pass",
                state="completed",
                summary=f"Fell back to a bounded pipeworx query and retained {len(findings)} evidence item(s).",
                provenance="public_source",
                confidence=0.4,
                detail={"request_status": "fallback_completed"},
                research_request_id=str(request.get("request_id") or ""),
            )
        return findings

    def _completed_result(
        self,
        request: Mapping[str, Any],
        job: Mapping[str, Any],
        source_ids: Sequence[str],
    ) -> dict[str, Any]:
        finding_ids = set(request.get("finding_ids") or [])
        insight_ids = set(request.get("insight_ids") or [])
        return {
            "findings": [
                item.to_dict()
                for item in self.memory.list_research_findings(limit=1_000)
                if item.finding_id in finding_ids
            ],
            "errors": [],
            "source_ids": list(source_ids),
            "request": dict(request),
            "job": dict(job),
            "insights": [
                item for item in self.memory.list_incubation_insights(limit=200)
                if item.get("insight_id") in insight_ids
            ],
        }

    def _synthesize_insights(
        self,
        request: Mapping[str, Any],
        findings: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Turn bounded findings into evidence-linked, non-authoritative insights."""
        results: list[dict[str, Any]] = []
        owner_language = str(request.get("owner_language") or "en").strip().lower()
        for raw_finding in list(findings)[:100]:
            finding_id = str(raw_finding.get("finding_id") or "").strip()
            source_id = str(raw_finding.get("source_id") or "").strip()
            source = self.memory.get_research_source(source_id) or {}
            source_language = str(source.get("language") or "und").strip().lower() or "und"
            summary = str(raw_finding.get("summary") or "").strip()[:2_000]
            kind = "content_opportunity"
            translated = False
            if source_language != "und" and source_language != owner_language:
                kind = "audience_language"
            proposal: Mapping[str, Any] | None = None
            if self.synthesizer is not None:
                try:
                    candidate = self.synthesizer({
                        "owner_language": owner_language,
                        "source_language": source_language,
                        "finding_id": finding_id,
                        "summary": summary,
                    })
                    if isinstance(candidate, Mapping):
                        proposal = candidate
                except Exception:
                    proposal = None
            if proposal is not None:
                proposed_summary = str(proposal.get("summary") or "").strip()
                if proposed_summary:
                    summary = proposed_summary[:2_000]
                    translated = source_language != owner_language
                proposed_kind = str(proposal.get("kind") or kind).strip().lower()
                if proposed_kind in {"audience_language", "audience_concern", "audience_desire", "business_context", "content_opportunity", "creative_implication", "contradiction"}:
                    kind = proposed_kind
            if not summary:
                continue
            supports = ["audience.primary"] if kind == "audience_language" else ["site.required_pages"]
            insight_id = "insight_" + hashlib.sha256(
                canonical_hash({
                    "request_id": request.get("request_id"),
                    "finding_id": finding_id,
                    "kind": kind,
                    "summary": summary,
                    "owner_language": owner_language,
                }).encode("utf-8")
            ).hexdigest()[:32]
            insight = IncubationInsight.from_dict({
                "insight_id": insight_id,
                "kind": kind,
                "summary": summary,
                "owner_language": owner_language,
                "source_languages": [source_language],
                "finding_ids": [finding_id],
                "supports_paths": supports,
                "contradicts_paths": [],
                "confidence": float(raw_finding.get("confidence") or 0.0),
                "status": "inferred",
                "created_at": self.now(),
            })
            stored = self.memory.save_incubation_insight(insight)
            results.append(stored)
            self._activity(
                category="research",
                kind="insight_synthesized",
                state="completed",
                summary="Synthesized an evidence-linked audience or creative insight.",
                provenance="model_inference",
                confidence=stored.get("confidence"),
                detail={
                    "source_languages": [source_language],
                    "target_language": owner_language,
                    "translation_note": "translated synthesis" if translated else "source language retained",
                },
                research_request_id=str(request.get("request_id") or ""),
                source_id=source_id,
                finding_ids=[finding_id],
            )
        return results

    def request(self, body: Mapping[str, Any], *, enqueue: bool = False) -> dict[str, Any]:
        if not isinstance(body, Mapping):
            raise IncubationResearchError("research request must be an object")
        try:
            request = self._request(body)
        except (ContractError, TypeError, ValueError) as exc:
            raise IncubationResearchError(str(exc)[:500]) from exc
        result: dict[str, Any] = {"sources": [], "findings": [], "errors": [], "request": request}
        urls = body.get("feed_urls") or body.get("urls") or []
        if urls:
            discovered = self.discover(urls)
            result.update(discovered)
            result["request"] = self._merge_request(
                request["request_id"],
                source_ids=sorted(set(request.get("source_ids") or []) | set(discovered.get("source_ids") or [])),
            )
            request = result["request"]
        candidate_communities = list(request.get("candidate_communities") or [])
        if candidate_communities:
            try:
                community_sources = self.community_discovery.discover(candidate_communities)
                saved_communities = [self._save_source(source) for source in community_sources]
            except (ContractError, FeedDiscoveryError, TypeError, ValueError) as exc:
                raise IncubationResearchError(str(exc)[:500]) from exc
            source_by_name = {
                _community_key(source.get("title")): source
                for source in saved_communities
                if _community_key(source.get("title"))
            }
            linked_source_ids: list[str] = []
            normalized_candidates: list[dict[str, Any]] = []
            for candidate in candidate_communities:
                item = dict(candidate)
                source = source_by_name.get(_community_key(item.get("name")))
                if source is not None:
                    item["source_id"] = source["source_id"]
                    linked_source_ids.append(source["source_id"])
                normalized_candidates.append(item)
            result["sources"] = [*result.get("sources", []), *saved_communities]
            result["source_ids"] = sorted(set(result.get("source_ids") or []) | set(linked_source_ids))
            result["request"] = self._merge_request(
                request["request_id"],
                candidate_communities=normalized_candidates,
                source_ids=sorted(set(request.get("source_ids") or []) | set(linked_source_ids)),
            )
            request = result["request"]
            candidate_provenance = "model_inference" if request.get("trigger") == ResearchTrigger.INTAKE_THRESHOLD.value else "owner"
            for candidate in normalized_candidates:
                if candidate.get("source_id") and candidate.get("status") == "candidate":
                    self._activity(
                        category="research",
                        kind="community_candidate_selected",
                        state="completed",
                        summary="Recorded a bounded public community candidate for verification.",
                        provenance=candidate_provenance,
                        confidence=0.2 if candidate_provenance == "model_inference" else None,
                        detail={"candidate_name": candidate.get("name"), "candidate_status": "candidate"},
                        research_request_id=request["request_id"],
                        source_id=candidate["source_id"],
                    )
        approvals = body.get("approve_source_ids") or body.get("approved_source_ids") or []
        if approvals:
            for source_id in list(approvals)[:50]:
                updated = self.update_source(str(source_id), {"trust_state": SourceTrustState.ALLOWED.value})
                result.setdefault("sources", []).append(updated)
            result["request"] = self._merge_request(
                request["request_id"],
                source_ids=sorted(set(result["request"].get("source_ids") or []) | {str(item).strip() for item in list(approvals)[:50]}),
            )
        source_ids = body.get("source_ids") or body.get("approved_source_ids") or []
        if source_ids:
            normalized_source_ids = [str(item or "").strip() for item in list(source_ids)[: self.max_sources_per_pass]]
            result["request"] = self._merge_request(
                request["request_id"],
                source_ids=sorted(set(result["request"].get("source_ids") or []) | set(normalized_source_ids)),
            )
        requested_run = bool(body.get("run") or body.get("fetch"))
        if requested_run and enqueue:
            job = self.enqueue(result["request"]["request_id"])
            if job is not None:
                result["request"] = self.memory.get_research_request(result["request"]["request_id"]) or result["request"]
                result["job"] = job
                if job.get("status") == ResearchJobStatus.COMPLETED.value:
                    result.update(self._completed_result(result["request"], job, source_ids))
                    result["status"] = "complete"
                else:
                    result["status"] = "queued"
            else:
                result["status"] = "awaiting_source_approval"
        elif requested_run:
            if not source_ids:
                source_ids = result["request"].get("source_ids") or []
            result.update(self.run(source_ids, query=str(body.get("query") or body.get("intent") or ""), request_id=result["request"]["request_id"]))
        else:
            result["request"] = self.memory.get_research_request(result["request"]["request_id"]) or result["request"]
        if "status" not in result:
            result["status"] = "complete" if result.get("findings") else "awaiting_source_approval"
        activity_state = {
            "complete": "completed",
            "queued": "started",
            "awaiting_source_approval": "completed",
        }.get(result["status"], "needs_attention")
        self._activity(
            category="research",
            kind="research_request",
            state=activity_state,
            summary="Recorded a research request for the incubation.",
            provenance="owner" if str(body.get("trigger") or ResearchTrigger.OWNER_REQUEST.value) == ResearchTrigger.OWNER_REQUEST.value else "system",
            detail={"request_status": result["request"].get("status"), "trigger": result["request"].get("trigger")},
            research_request_id=result["request"]["request_id"],
        )
        return result

    @staticmethod
    def _finding(document: ResearchDocument, query_terms: set[str]) -> ResearchFinding:
        summary = " ".join(part for part in (document.title, document.summary) if part).strip()
        summary = re.sub(r"\s+", " ", summary)[:4_000]
        summary = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "", summary)
        summary = re.sub(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|co|dev|app|test)\b", "", summary, flags=re.IGNORECASE)
        summary = re.sub(r"\s+", " ", summary).strip()
        if not summary:
            summary = "Public source item provided no readable summary."
        overlap = len(query_terms & _terms(summary)) / len(query_terms) if query_terms else 0.5
        finding_id = "finding_" + hashlib.sha256(f"{document.source_id}:{document.content_hash}".encode("utf-8")).hexdigest()[:32]
        return ResearchFinding.from_dict({
            "finding_id": finding_id,
            "source_id": document.source_id,
            "published_at": document.published_at,
            "summary": summary,
            "relevance": max(0.0, min(1.0, overlap)),
            "supports": [],
            "contradicts": [],
            "confidence": 0.35,
            "content_hash": document.content_hash,
        })


def _terms(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-z0-9]{3,}", str(value or "").casefold())}


def _community_key(value: Any) -> str:
    return re.sub(r"^/?r/", "", str(value or "").strip(), flags=re.IGNORECASE).strip("/").casefold()


def _error_code(exc: Exception) -> str:
    code = str(getattr(exc, "code", "") or "").strip().lower()
    return code if re.fullmatch(r"[a-z][a-z0-9_]{1,39}", code) else type(exc).__name__


def _text_items(value: Any) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple, set)) else [value]
    return [str(item or "").strip()[:500] for item in values if str(item or "").strip()]


class IncubationResearchExecutor:
    """Run queued research jobs without blocking conversational HTTP calls."""

    def __init__(
        self,
        service: IncubationResearchService,
        *,
        interval: float = 1.0,
        on_finished: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self.service = service
        self.memory = service.memory
        self.interval = max(0.1, float(interval))
        self.on_finished = on_finished
        self.worker = f"research-{time.time_ns()}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.memory.requeue_running_research_jobs()
        self._thread = threading.Thread(target=self._loop, name="research-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def process_one(self) -> bool:
        job = self.memory.claim_research_job(self.worker)
        if job is None:
            return False
        request_id = str(job.get("request_id") or "")
        error: str | None = None
        try:
            request = self.memory.get_research_request(request_id)
            if request is None:
                raise IncubationResearchError("research request was not found")
            source_ids = list(request.get("source_ids") or [])
            if not source_ids:
                raise IncubationResearchError("approved research sources are required")
            self.service.run(
                source_ids,
                query=str(request.get("intent") or ""),
                request_id=request_id,
                allow_policy_candidates=request.get("trigger")
                in {ResearchTrigger.INTAKE_THRESHOLD.value, ResearchTrigger.INFUSION.value},
            )
        except Exception as exc:  # noqa: BLE001 - persist failure and keep worker alive
            error = str(exc)[:500]
            try:
                current = self.memory.get_research_job(job["job_id"])
                if current and current.get("status") != ResearchJobStatus.COMPLETED.value:
                    self.memory.update_research_job(
                        job["job_id"],
                        status=ResearchJobStatus.FAILED.value,
                        completed_at=self.service.now(),
                        error=error,
                    )
                request = self.memory.get_research_request(request_id)
                if request and request.get("status") != ResearchRequestStatus.COMPLETED.value:
                    self.memory.update_research_request(
                        request_id,
                        status=ResearchRequestStatus.NEEDS_ATTENTION.value,
                        error=error,
                    )
            except Exception:
                pass
            try:
                self.service._activity(
                    category="research",
                    kind="research_pass",
                    state="needs_attention",
                    summary="A queued research pass needs attention.",
                    provenance="host_validation",
                    detail={"error_code": _error_code(exc), "request_status": "needs_attention"},
                    research_request_id=request_id,
                )
            except Exception:
                pass
        finally:
            if self.on_finished is not None:
                try:
                    self.on_finished(request_id, error)
                except Exception:
                    pass
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.process_one():
                    self._stop.wait(self.interval)
            except Exception:
                self._stop.wait(self.interval)


__all__ = ["IncubationResearchError", "IncubationResearchExecutor", "IncubationResearchService"]

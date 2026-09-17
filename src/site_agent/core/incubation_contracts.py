"""Typed contracts for Intake Ada's isolated customer incubations.

These contracts intentionally keep the three persistence domains separate.  An
incubation may contain customer material, while the permanent Intake Ada
contracts only accept sanitized creative episodes.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from .contracts import ContractError, safe_payload, safe_provider_message
from .design_contracts import canonical_hash, canonical_json


SCHEMA_VERSION = 1
_ID = re.compile(r"^[a-z][a-z0-9_-]{2,119}$")
_INCUBATION_ID = re.compile(r"^inc_[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_OPAQUE = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{2,159}$")
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d(). -]{7,}\d)(?!\w)")
_PATH = re.compile(r"(?:^|\s)(?:/|[A-Za-z]:[\\/])[^\s]+")
_DOMAIN = re.compile(r"(?<![@\w])(?:[a-z0-9-]+\.)+(?:com|org|net|io|co|dev|app|test)(?!\w)", re.IGNORECASE)


class IncubationStatus(str, Enum):
    COLLECTING = "collecting"
    RESEARCHING = "researching"
    READY_TO_BUILD = "ready_to_build"
    BUILDING = "building"
    READY_FOR_FEEDBACK = "ready_for_feedback"
    ACCEPTED = "accepted"
    PROVISIONING = "provisioning"
    PROVISIONED = "provisioned"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PURGED = "purged"


class EvidenceOrigin(str, Enum):
    OWNER_STATEMENT = "owner_statement"
    OWNER_CORRECTION = "owner_correction"
    OWNER_ACCEPTANCE = "owner_acceptance"
    HOST_OBSERVATION = "host_observation"
    RESEARCH_EVIDENCE = "research_evidence"
    ADA_HYPOTHESIS = "ada_hypothesis"
    ADA_REFLECTION = "ada_reflection"
    ASSET_ANALYSIS = "asset_analysis"


class SourceTrustState(str, Enum):
    CANDIDATE = "candidate"
    ALLOWED = "allowed"
    EXCLUDED = "excluded"


class SubscriptionState(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    NOT_APPLICABLE = "not_applicable"


class IncubationActivityCategory(str, Enum):
    CONVERSATION = "conversation"
    UNDERSTANDING = "understanding"
    RESEARCH = "research"
    TRANSLATION = "translation"
    GENESIS = "genesis"
    DESIGN = "design"
    QUALITY = "quality"
    FEEDBACK = "feedback"
    PROVISIONING = "provisioning"
    SYSTEM = "system"


class IncubationActivityState(str, Enum):
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    NEEDS_ATTENTION = "needs_attention"
    CORRECTED = "corrected"
    CANCELLED = "cancelled"


class ActivityProvenance(str, Enum):
    OWNER = "owner"
    PUBLIC_SOURCE = "public_source"
    MODEL_INFERENCE = "model_inference"
    HOST_VALIDATION = "host_validation"
    OWNER_CONFIRMATION = "owner_confirmation"
    SYSTEM = "system"


class ResearchRequestStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchTrigger(str, Enum):
    INTAKE_THRESHOLD = "intake_threshold"
    OWNER_REQUEST = "owner_request"
    OWNER_CORRECTION = "owner_correction"
    DESIGN_FEEDBACK = "design_feedback"
    INFUSION = "infusion"


class DeductionKind(str, Enum):
    MARKET_CONTEXT = "market_context"
    AUDIENCE_FACT = "audience_fact"
    AUDIENCE_HYPOTHESIS = "audience_hypothesis"
    CREATIVE_LEANING = "creative_leaning"
    COMPETITOR_NOTE = "competitor_note"
    POSITIONING_NOTE = "positioning_note"
    RISK = "risk"
    OPPORTUNITY = "opportunity"


class InfusionRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class InfusionMode(str, Enum):
    OPENCODE = "opencode"
    NATIVE = "native"


class ResearchJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InsightKind(str, Enum):
    AUDIENCE_LANGUAGE = "audience_language"
    AUDIENCE_CONCERN = "audience_concern"
    AUDIENCE_DESIRE = "audience_desire"
    BUSINESS_CONTEXT = "business_context"
    CONTENT_OPPORTUNITY = "content_opportunity"
    CREATIVE_IMPLICATION = "creative_implication"
    CONTRADICTION = "contradiction"


class InsightStatus(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    OWNER_CONFIRMED = "owner_confirmed"
    CORRECTED = "corrected"
    EXCLUDED = "excluded"


_TRANSITIONS: dict[str, frozenset[str]] = {
    IncubationStatus.COLLECTING.value: frozenset({IncubationStatus.RESEARCHING.value, IncubationStatus.READY_TO_BUILD.value, IncubationStatus.REJECTED.value, IncubationStatus.EXPIRED.value, IncubationStatus.PURGED.value}),
    IncubationStatus.RESEARCHING.value: frozenset({IncubationStatus.COLLECTING.value, IncubationStatus.READY_TO_BUILD.value, IncubationStatus.REJECTED.value, IncubationStatus.EXPIRED.value, IncubationStatus.PURGED.value}),
    IncubationStatus.READY_TO_BUILD.value: frozenset({IncubationStatus.BUILDING.value, IncubationStatus.COLLECTING.value, IncubationStatus.REJECTED.value, IncubationStatus.EXPIRED.value, IncubationStatus.PURGED.value}),
    IncubationStatus.BUILDING.value: frozenset({IncubationStatus.READY_FOR_FEEDBACK.value, IncubationStatus.BLOCKED.value, IncubationStatus.COLLECTING.value, IncubationStatus.PURGED.value}),
    IncubationStatus.READY_FOR_FEEDBACK.value: frozenset({IncubationStatus.ACCEPTED.value, IncubationStatus.COLLECTING.value, IncubationStatus.BUILDING.value, IncubationStatus.REJECTED.value, IncubationStatus.EXPIRED.value, IncubationStatus.PURGED.value}),
    IncubationStatus.ACCEPTED.value: frozenset({IncubationStatus.PROVISIONING.value, IncubationStatus.COLLECTING.value}),
    IncubationStatus.PROVISIONING.value: frozenset({IncubationStatus.PROVISIONED.value, IncubationStatus.ACCEPTED.value}),
    IncubationStatus.PROVISIONED.value: frozenset(),
    IncubationStatus.BLOCKED.value: frozenset({IncubationStatus.COLLECTING.value, IncubationStatus.BUILDING.value, IncubationStatus.REJECTED.value, IncubationStatus.EXPIRED.value, IncubationStatus.PURGED.value}),
    IncubationStatus.REJECTED.value: frozenset({IncubationStatus.PURGED.value}),
    IncubationStatus.EXPIRED.value: frozenset({IncubationStatus.PURGED.value}),
    IncubationStatus.PURGED.value: frozenset(),
}


def validate_incubation_transition(current: str, target: str) -> None:
    """Validate one lifecycle transition at the domain boundary."""
    current = str(current or "").strip().lower()
    target = str(target or "").strip().lower()
    if current not in _TRANSITIONS or target not in {item.value for item in IncubationStatus}:
        raise ContractError("incubation status is invalid")
    if target not in _TRANSITIONS[current]:
        raise ContractError(f"incubation cannot transition from {current} to {target}")


def _object(value: Any, name: str, allowed: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be an object")
    result = copy.deepcopy(dict(value))
    if allowed is not None:
        unknown = set(result) - allowed
        if unknown:
            raise ContractError(f"{name} contains unsupported fields")
    return result


def _text(value: Any, name: str, *, required: bool = True, maximum: int = 20_000) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ContractError(f"{name} must be text")
    result = value.strip()
    if required and not result:
        raise ContractError(f"{name} must not be empty")
    if len(result) > maximum:
        raise ContractError(f"{name} exceeds {maximum} characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in result):
        raise ContractError(f"{name} contains control characters")
    return result


def _string_list(value: Any, name: str, *, maximum: int = 100, item_maximum: int = 500) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise ContractError(f"{name} must be a list")
    if len(value) > maximum:
        raise ContractError(f"{name} contains too many items")
    return [_text(item, f"{name}[{index}]", maximum=item_maximum) for index, item in enumerate(value)]


def _timestamp(value: Any, name: str, *, required: bool = True) -> str | None:
    result = _text(value, name, required=required, maximum=80)
    if not result:
        return None
    try:
        datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{name} must be ISO-8601") from exc
    return result


def _opaque(value: Any, name: str, *, prefix: str | None = None) -> str:
    result = _text(value, name, maximum=160)
    if not _OPAQUE.fullmatch(result) or (prefix and not result.startswith(prefix)):
        raise ContractError(f"{name} is invalid")
    return result


def _hash(value: Any, name: str, *, length: int = 64, required: bool = True) -> str:
    result = _text(value, name, required=required, maximum=length).lower()
    pattern = _SHA256 if length == 64 else _SHA1 if length == 40 else re.compile(rf"^[0-9a-f]{{{length}}}$")
    if result and not pattern.fullmatch(result):
        raise ContractError(f"{name} is not a valid content hash")
    return result


def _copy_json(value: Any, name: str, *, max_bytes: int = 100_000) -> Any:
    try:
        encoded = canonical_json(value)
    except Exception as exc:
        raise ContractError(f"{name} contains unsupported JSON values") from exc
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ContractError(f"{name} exceeds {max_bytes} bytes")
    return copy.deepcopy(value)


def _prohibited_text(value: str) -> str | None:
    if _URL.search(value):
        return "url"
    if _EMAIL.search(value):
        return "email"
    if _PHONE.search(value):
        return "phone"
    if _PATH.search(value):
        return "path"
    if _DOMAIN.search(value):
        return "domain"
    return None


def _assert_sanitized(value: Any, name: str = "value") -> None:
    if isinstance(value, str):
        reason = _prohibited_text(value)
        if reason:
            raise ContractError(f"{name} contains prohibited {reason}")
    elif isinstance(value, Mapping):
        for key, child in value.items():
            _assert_sanitized(child, f"{name}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_sanitized(child, f"{name}[{index}]")


@dataclass(frozen=True)
class IncubationRecord:
    incubation_id: str
    status: str
    created_at: str
    updated_at: str
    expires_at: str
    current_intake_revision: int = 0
    current_genesis_revision: int = 1
    accepted_candidate_sha: str | None = None
    accepted_run_id: str | None = None
    acceptance_manifest_id: str | None = None
    provisioning_request_id: str | None = None
    customer_instance_id: str | None = None
    workspace_path: str = field(default="", repr=False, compare=False)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IncubationRecord":
        value = _object(raw, "incubation", {
            "schema_version", "incubation_id", "status", "created_at", "updated_at", "expires_at",
            "current_intake_revision", "current_genesis_revision", "accepted_candidate_sha",
            "accepted_run_id", "acceptance_manifest_id", "provisioning_request_id", "customer_instance_id", "workspace_path",
        })
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("incubation.schema_version is invalid")
        incubation_id = _text(value.get("incubation_id"), "incubation.incubation_id", maximum=80)
        if not _INCUBATION_ID.fullmatch(incubation_id):
            raise ContractError("incubation.incubation_id is invalid")
        status = _text(value.get("status"), "incubation.status", maximum=30).lower()
        if status not in {item.value for item in IncubationStatus}:
            raise ContractError("incubation.status is invalid")
        revisions: dict[str, int] = {}
        for name in ("current_intake_revision", "current_genesis_revision"):
            raw_revision = value.get(name, 0 if name.endswith("intake_revision") else 1)
            if isinstance(raw_revision, bool) or not isinstance(raw_revision, int) or raw_revision < 0:
                raise ContractError(f"incubation.{name} is invalid")
            revisions[name] = raw_revision
        candidate = value.get("accepted_candidate_sha")
        accepted_candidate_sha = None if candidate in (None, "") else _hash(candidate, "incubation.accepted_candidate_sha", length=40)
        result = cls(
            incubation_id=incubation_id,
            status=status,
            created_at=str(_timestamp(value.get("created_at"), "incubation.created_at")),
            updated_at=str(_timestamp(value.get("updated_at"), "incubation.updated_at")),
            expires_at=str(_timestamp(value.get("expires_at"), "incubation.expires_at")),
            current_intake_revision=revisions["current_intake_revision"],
            current_genesis_revision=revisions["current_genesis_revision"],
            accepted_candidate_sha=accepted_candidate_sha,
            accepted_run_id=(None if value.get("accepted_run_id") in (None, "") else _opaque(value["accepted_run_id"], "incubation.accepted_run_id")),
            acceptance_manifest_id=(None if value.get("acceptance_manifest_id") in (None, "") else _opaque(value["acceptance_manifest_id"], "incubation.acceptance_manifest_id")),
            provisioning_request_id=(None if value.get("provisioning_request_id") in (None, "") else _opaque(value["provisioning_request_id"], "incubation.provisioning_request_id")),
            customer_instance_id=(None if value.get("customer_instance_id") in (None, "") else _opaque(value["customer_instance_id"], "incubation.customer_instance_id")),
            workspace_path=_text(value.get("workspace_path"), "incubation.workspace_path", required=False, maximum=1_000),
        )
        return result

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": SCHEMA_VERSION,
            "incubation_id": self.incubation_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "current_intake_revision": self.current_intake_revision,
            "current_genesis_revision": self.current_genesis_revision,
            "accepted_candidate_sha": self.accepted_candidate_sha,
            "provisioning_request_id": self.provisioning_request_id,
            "customer_instance_id": self.customer_instance_id,
        }
        if self.accepted_run_id is not None:
            result["accepted_run_id"] = self.accepted_run_id
        if self.acceptance_manifest_id is not None:
            result["acceptance_manifest_id"] = self.acceptance_manifest_id
        return result


@dataclass(frozen=True)
class GenesisEvidence:
    field_path: str
    origin: str
    source_id: str
    confidence: float
    contradicts: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "GenesisEvidence":
        value = _object(raw, "genesis.evidence", {"field_path", "origin", "source_id", "confidence", "contradicts"})
        field_path = _text(value.get("field_path"), "genesis.evidence.field_path", maximum=160)
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", field_path):
            raise ContractError("genesis.evidence.field_path is invalid")
        origin = _text(value.get("origin"), "genesis.evidence.origin", maximum=30).lower()
        if origin not in {item.value for item in EvidenceOrigin}:
            raise ContractError("genesis.evidence.origin is invalid")
        source_id = _opaque(value.get("source_id"), "genesis.evidence.source_id")
        confidence = value.get("confidence", 0.0)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ContractError("genesis.evidence.confidence must be between 0 and 1")
        contradicts = value.get("contradicts", False)
        if not isinstance(contradicts, bool):
            raise ContractError("genesis.evidence.contradicts must be boolean")
        return cls(field_path, origin, source_id, float(confidence), contradicts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "origin": self.origin,
            "source_id": self.source_id,
            "confidence": self.confidence,
            "contradicts": self.contradicts,
        }


def _genesis_section(value: Any, name: str, fields: set[str]) -> dict[str, Any]:
    section = _object(value or {}, name, fields)
    result: dict[str, Any] = {}
    for field_name in fields:
        child = section.get(field_name, [] if field_name != "purpose" and field_name != "decision_style" else "")
        if field_name in {"purpose", "decision_style"}:
            result[field_name] = _text(child, f"{name}.{field_name}", required=False, maximum=2_000)
        else:
            result[field_name] = _string_list(child, f"{name}.{field_name}", maximum=50, item_maximum=500)
    return result


@dataclass(frozen=True)
class CustomerAdaGenesis:
    revision: int
    business_world: dict[str, Any]
    relationship: dict[str, Any]
    creative_identity: dict[str, Any]
    research_identity: dict[str, Any]
    evidence: tuple[GenesisEvidence, ...] = ()

    @classmethod
    def empty(cls, revision: int = 1) -> "CustomerAdaGenesis":
        return cls(
            revision=revision,
            business_world=_genesis_section({}, "genesis.business_world", {"purpose", "values", "customer_promises", "tensions", "language"}),
            relationship=_genesis_section({}, "genesis.relationship", {"owner_preferences", "decision_style", "communication_preferences", "boundaries"}),
            creative_identity=_genesis_section({}, "genesis.creative_identity", {"principles", "developing_tastes", "patterns_to_avoid", "open_questions"}),
            research_identity=_genesis_section({}, "genesis.research_identity", {"subjects", "communities", "candidate_feeds", "excluded_sources"}),
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CustomerAdaGenesis":
        value = _object(raw, "customer_genesis", {"schema_version", "revision", "business_world", "relationship", "creative_identity", "research_identity", "evidence"})
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("customer_genesis.schema_version is invalid")
        revision = value.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ContractError("customer_genesis.revision is invalid")
        evidence_raw = value.get("evidence") or []
        if not isinstance(evidence_raw, list) or len(evidence_raw) > 200:
            raise ContractError("customer_genesis.evidence must be a bounded list")
        return cls(
            revision=revision,
            business_world=_genesis_section(value.get("business_world"), "customer_genesis.business_world", {"purpose", "values", "customer_promises", "tensions", "language"}),
            relationship=_genesis_section(value.get("relationship"), "customer_genesis.relationship", {"owner_preferences", "decision_style", "communication_preferences", "boundaries"}),
            creative_identity=_genesis_section(value.get("creative_identity"), "customer_genesis.creative_identity", {"principles", "developing_tastes", "patterns_to_avoid", "open_questions"}),
            research_identity=_genesis_section(value.get("research_identity"), "customer_genesis.research_identity", {"subjects", "communities", "candidate_feeds", "excluded_sources"}),
            evidence=tuple(GenesisEvidence.from_dict(item) for item in evidence_raw),
        )

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": self.revision,
            "business_world": copy.deepcopy(self.business_world),
            "relationship": copy.deepcopy(self.relationship),
            "creative_identity": copy.deepcopy(self.creative_identity),
            "research_identity": copy.deepcopy(self.research_identity),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    kind: str
    url: str
    feed_url: str
    title: str
    discovered_by: str
    language: str = ""
    trust_state: str = SourceTrustState.CANDIDATE.value
    ongoing_subscription: str = SubscriptionState.NOT_APPLICABLE.value
    fetched_at: str | None = None
    content_hash: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchSource":
        value = _object(raw, "research_source", {"source_id", "kind", "url", "feed_url", "title", "discovered_by", "language", "trust_state", "ongoing_subscription", "fetched_at", "content_hash"})
        source_id = _opaque(value.get("source_id"), "research_source.source_id", prefix="src_")
        kind = _text(value.get("kind"), "research_source.kind", maximum=30).lower()
        if kind not in {"rss", "atom", "website", "news_provider"}:
            raise ContractError("research_source.kind is invalid")
        urls: dict[str, str] = {}
        for name in ("url", "feed_url"):
            url = _text(value.get(name), f"research_source.{name}", maximum=2_000)
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
                raise ContractError(f"research_source.{name} must be a public HTTP(S) URL")
            urls[name] = url
        trust_state = _text(value.get("trust_state", SourceTrustState.CANDIDATE.value), "research_source.trust_state", maximum=20).lower()
        if trust_state not in {item.value for item in SourceTrustState}:
            raise ContractError("research_source.trust_state is invalid")
        ongoing = _text(value.get("ongoing_subscription", SubscriptionState.NOT_APPLICABLE.value), "research_source.ongoing_subscription", maximum=30).lower()
        if ongoing not in {item.value for item in SubscriptionState}:
            raise ContractError("research_source.ongoing_subscription is invalid")
        content_hash = _hash(value.get("content_hash"), "research_source.content_hash", required=False)
        return cls(
            source_id=source_id,
            kind=kind,
            url=urls["url"],
            feed_url=urls["feed_url"],
            title=_text(value.get("title"), "research_source.title", required=False, maximum=500),
            discovered_by=_text(value.get("discovered_by"), "research_source.discovered_by", maximum=30),
            language=_language(value.get("language"), "research_source.language", required=False),
            trust_state=trust_state,
            ongoing_subscription=ongoing,
            fetched_at=_timestamp(value.get("fetched_at"), "research_source.fetched_at", required=False),
            content_hash=content_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "url": self.url,
            "feed_url": self.feed_url,
            "title": self.title,
            "discovered_by": self.discovered_by,
            "language": self.language,
            "trust_state": self.trust_state,
            "ongoing_subscription": self.ongoing_subscription,
            "fetched_at": self.fetched_at,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ResearchFinding:
    finding_id: str
    source_id: str
    published_at: str | None
    summary: str
    relevance: float
    supports: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    confidence: float = 0.0
    content_hash: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchFinding":
        value = _object(raw, "research_finding", {"finding_id", "source_id", "published_at", "summary", "relevance", "supports", "contradicts", "confidence", "content_hash"})
        finding_id = _opaque(value.get("finding_id"), "research_finding.finding_id", prefix="finding_")
        source_id = _opaque(value.get("source_id"), "research_finding.source_id", prefix="src_")
        summary = _text(value.get("summary"), "research_finding.summary", maximum=4_000)
        _assert_sanitized(summary, "research_finding.summary")
        scores: dict[str, float] = {}
        for name in ("relevance", "confidence"):
            score = value.get(name, 0.0)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
                raise ContractError(f"research_finding.{name} must be between 0 and 1")
            scores[name] = float(score)
        return cls(
            finding_id=finding_id,
            source_id=source_id,
            published_at=_timestamp(value.get("published_at"), "research_finding.published_at", required=False),
            summary=summary,
            relevance=scores["relevance"],
            supports=tuple(_string_list(value.get("supports"), "research_finding.supports", maximum=30, item_maximum=160)),
            contradicts=tuple(_string_list(value.get("contradicts"), "research_finding.contradicts", maximum=30, item_maximum=160)),
            confidence=scores["confidence"],
            content_hash=_hash(value.get("content_hash"), "research_finding.content_hash", required=False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "source_id": self.source_id,
            "published_at": self.published_at,
            "summary": self.summary,
            "relevance": self.relevance,
            "supports": list(self.supports),
            "contradicts": list(self.contradicts),
            "confidence": self.confidence,
            "content_hash": self.content_hash,
        }


_ACTIVITY_DETAIL_KEYS = {
    "source_language", "source_languages", "target_language", "owner_language", "source_title",
    "item_count", "phase", "reason", "error_code", "changed_paths", "recommendation",
    "related_activity_id", "candidate_name", "candidate_status", "message", "status",
    "revision", "genesis_revision", "run_status", "quality_state", "trigger", "request_status", "job_status",
    "language", "languages", "translation_note", "previous_value", "new_value", "count",
    "infusion_deduction_count", "genesis_sections",
    "snapshot_id", "commit_sha", "label",
}


def _language(value: Any, name: str, *, required: bool = True) -> str:
    result = _text(value, name, required=required, maximum=24).replace("_", "-").lower()
    if result and not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", result):
        raise ContractError(f"{name} is invalid")
    return result


def _optional_int(value: Any, name: str, *, minimum: int = 0) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{name} is invalid")
    return value


def _ref_tuple(value: Any, name: str, prefix: str, *, maximum: int = 100) -> tuple[str, ...]:
    items = _string_list(value, name, maximum=maximum, item_maximum=160)
    result: list[str] = []
    for item in items:
        if not _OPAQUE.fullmatch(item) or not item.startswith(prefix):
            raise ContractError(f"{name} contains an invalid identifier")
        result.append(item)
    return tuple(result)


def _path_tuple(value: Any, name: str, *, maximum: int = 50) -> tuple[str, ...]:
    items = _string_list(value, name, maximum=maximum, item_maximum=160)
    for item in items:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", item):
            raise ContractError(f"{name} contains an invalid path")
    return tuple(items)


def _candidate_communities(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 50:
        raise ContractError("research_request.candidate_communities must be a bounded list")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item = _object(raw, f"research_request.candidate_communities[{index}]", {
            "name", "language", "rationale", "status", "source_id",
        })
        name = _text(item.get("name"), f"research_request.candidate_communities[{index}].name", maximum=160)
        language = _language(item.get("language"), f"research_request.candidate_communities[{index}].language", required=False)
        status = _text(item.get("status", "candidate"), f"research_request.candidate_communities[{index}].status", maximum=30).lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", status):
            raise ContractError("research_request candidate status is invalid")
        source_id = item.get("source_id")
        normalized = {
            "name": name,
            "language": language,
            "rationale": _text(item.get("rationale"), f"research_request.candidate_communities[{index}].rationale", required=False, maximum=500),
            "status": status,
            "source_id": None if source_id in (None, "") else _opaque(source_id, f"research_request.candidate_communities[{index}].source_id", prefix="src_"),
        }
        normalized = safe_payload(normalized, max_bytes=10_000)
        _assert_sanitized(normalized, f"research_request.candidate_communities[{index}]")
        result.append(normalized)
    return tuple(result)


def _query_terms(value: Any) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 20:
        raise ContractError("research_request.query_terms_by_language must be a bounded object")
    result: dict[str, tuple[str, ...]] = {}
    for key, terms in value.items():
        language = _language(key, "research_request.query_terms_by_language language")
        result[language] = tuple(_string_list(terms, f"research_request.query_terms_by_language.{language}", maximum=50, item_maximum=200))
    return result


@dataclass(frozen=True)
class IncubationActivity:
    """Owner-safe, append-only evidence of observable incubation work."""

    activity_id: str
    occurred_at: str
    category: str
    kind: str
    state: str
    summary: str
    provenance: str
    confidence: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    conversation_id: int | None = None
    message_id: int | None = None
    chat_job_id: int | None = None
    intake_session_id: str | None = None
    intake_revision: int | None = None
    research_request_id: str | None = None
    source_id: str | None = None
    finding_ids: tuple[str, ...] = ()
    genesis_revision: int | None = None
    design_run_id: str | None = None
    provider_id: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IncubationActivity":
        value = _object(raw, "incubation_activity", {
            "schema_version", "activity_id", "occurred_at", "category", "kind", "state", "summary",
            "provenance", "confidence", "detail", "conversation_id", "message_id", "chat_job_id",
            "intake_session_id", "intake_revision", "research_request_id", "source_id", "finding_ids",
            "genesis_revision", "design_run_id", "provider_id",
        })
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("incubation_activity.schema_version is invalid")
        category = _text(value.get("category"), "incubation_activity.category", maximum=30).lower()
        if category not in {item.value for item in IncubationActivityCategory}:
            raise ContractError("incubation_activity.category is invalid")
        state = _text(value.get("state"), "incubation_activity.state", maximum=30).lower()
        if state not in {item.value for item in IncubationActivityState}:
            raise ContractError("incubation_activity.state is invalid")
        provenance = _text(value.get("provenance"), "incubation_activity.provenance", maximum=30).lower()
        if provenance not in {item.value for item in ActivityProvenance}:
            raise ContractError("incubation_activity.provenance is invalid")
        confidence = value.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
                raise ContractError("incubation_activity.confidence must be between 0 and 1")
            confidence = float(confidence)
        elif provenance in {ActivityProvenance.PUBLIC_SOURCE.value, ActivityProvenance.MODEL_INFERENCE.value}:
            raise ContractError("incubation_activity.confidence is required for this provenance")
        detail = _object(value.get("detail") or {}, "incubation_activity.detail", _ACTIVITY_DETAIL_KEYS)
        detail = safe_payload(detail, max_bytes=20_000)
        _assert_sanitized(detail, "incubation_activity.detail")
        return cls(
            activity_id=_opaque(value.get("activity_id"), "incubation_activity.activity_id", prefix="activity_"),
            occurred_at=str(_timestamp(value.get("occurred_at"), "incubation_activity.occurred_at")),
            category=category,
            kind=_opaque(value.get("kind"), "incubation_activity.kind"),
            state=state,
            summary=_sanitized_text(value.get("summary"), "incubation_activity.summary", maximum=2_000),
            provenance=provenance,
            confidence=confidence,
            detail=detail,
            conversation_id=_optional_int(value.get("conversation_id"), "incubation_activity.conversation_id", minimum=1),
            message_id=_optional_int(value.get("message_id"), "incubation_activity.message_id", minimum=1),
            chat_job_id=_optional_int(value.get("chat_job_id"), "incubation_activity.chat_job_id", minimum=1),
            intake_session_id=(None if value.get("intake_session_id") in (None, "") else _opaque(value.get("intake_session_id"), "incubation_activity.intake_session_id")),
            intake_revision=_optional_int(value.get("intake_revision"), "incubation_activity.intake_revision"),
            research_request_id=(None if value.get("research_request_id") in (None, "") else _opaque(value.get("research_request_id"), "incubation_activity.research_request_id", prefix="research_")),
            source_id=(None if value.get("source_id") in (None, "") else _opaque(value.get("source_id"), "incubation_activity.source_id", prefix="src_")),
            finding_ids=_ref_tuple(value.get("finding_ids"), "incubation_activity.finding_ids", "finding_"),
            genesis_revision=_optional_int(value.get("genesis_revision"), "incubation_activity.genesis_revision", minimum=1),
            design_run_id=(None if value.get("design_run_id") in (None, "") else _opaque(value.get("design_run_id"), "incubation_activity.design_run_id")),
            provider_id=(None if value.get("provider_id") in (None, "") else _opaque(value.get("provider_id"), "incubation_activity.provider_id")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "activity_id": self.activity_id,
            "occurred_at": self.occurred_at,
            "category": self.category,
            "kind": self.kind,
            "state": self.state,
            "summary": self.summary,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "detail": copy.deepcopy(self.detail),
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "chat_job_id": self.chat_job_id,
            "intake_session_id": self.intake_session_id,
            "intake_revision": self.intake_revision,
            "research_request_id": self.research_request_id,
            "source_id": self.source_id,
            "finding_ids": list(self.finding_ids),
            "genesis_revision": self.genesis_revision,
            "design_run_id": self.design_run_id,
            "provider_id": self.provider_id,
        }


def _sanitized_text(value: Any, name: str, *, maximum: int) -> str:
    result = _text(value, name, maximum=maximum)
    _assert_sanitized(result, name)
    return result


@dataclass(frozen=True)
class ResearchRequest:
    request_id: str
    dedupe_key: str
    created_at: str
    updated_at: str
    status: str
    trigger: str
    intake_revision: int
    owner_language: str
    subjects: tuple[str, ...] = ()
    markets: tuple[str, ...] = ()
    candidate_communities: tuple[dict[str, Any], ...] = ()
    query_terms_by_language: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    insight_ids: tuple[str, ...] = ()
    error: str = ""
    intent: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchRequest":
        value = _object(raw, "research_request", {
            "schema_version", "request_id", "dedupe_key", "created_at", "updated_at", "status", "trigger",
            "intake_revision", "owner_language", "subjects", "markets", "candidate_communities",
            "query_terms_by_language", "source_ids", "finding_ids", "insight_ids", "error",
            "intent",
        })
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("research_request.schema_version is invalid")
        status = _text(value.get("status"), "research_request.status", maximum=30).lower()
        if status not in {item.value for item in ResearchRequestStatus}:
            raise ContractError("research_request.status is invalid")
        trigger = _text(value.get("trigger"), "research_request.trigger", maximum=30).lower()
        if trigger not in {item.value for item in ResearchTrigger}:
            raise ContractError("research_request.trigger is invalid")
        intake_revision = _optional_int(value.get("intake_revision"), "research_request.intake_revision")
        if intake_revision is None:
            raise ContractError("research_request.intake_revision is required")
        error = safe_provider_message(_text(value.get("error"), "research_request.error", required=False, maximum=1_000), max_chars=1_000)
        _assert_sanitized(error, "research_request.error")
        return cls(
            request_id=_opaque(value.get("request_id"), "research_request.request_id", prefix="research_"),
            dedupe_key=_hash(value.get("dedupe_key"), "research_request.dedupe_key"),
            created_at=str(_timestamp(value.get("created_at"), "research_request.created_at")),
            updated_at=str(_timestamp(value.get("updated_at"), "research_request.updated_at")),
            status=status,
            trigger=trigger,
            intake_revision=intake_revision,
            owner_language=_language(value.get("owner_language"), "research_request.owner_language"),
            subjects=tuple(_string_list(value.get("subjects"), "research_request.subjects", maximum=50, item_maximum=500)),
            markets=tuple(_string_list(value.get("markets"), "research_request.markets", maximum=50, item_maximum=300)),
            candidate_communities=_candidate_communities(value.get("candidate_communities")),
            query_terms_by_language=_query_terms(value.get("query_terms_by_language")),
            source_ids=_ref_tuple(value.get("source_ids"), "research_request.source_ids", "src_"),
            finding_ids=_ref_tuple(value.get("finding_ids"), "research_request.finding_ids", "finding_"),
            insight_ids=_ref_tuple(value.get("insight_ids"), "research_request.insight_ids", "insight_"),
            error=error,
            intent=_sanitized_text(value.get("intent"), "research_request.intent", maximum=2_000) if value.get("intent") else "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": self.request_id,
            "dedupe_key": self.dedupe_key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "trigger": self.trigger,
            "intake_revision": self.intake_revision,
            "owner_language": self.owner_language,
            "subjects": list(self.subjects),
            "markets": list(self.markets),
            "candidate_communities": [copy.deepcopy(item) for item in self.candidate_communities],
            "query_terms_by_language": {key: list(value) for key, value in self.query_terms_by_language.items()},
            "source_ids": list(self.source_ids),
            "finding_ids": list(self.finding_ids),
            "insight_ids": list(self.insight_ids),
            "error": self.error,
            "intent": self.intent,
        }


@dataclass(frozen=True)
class ResearchJob:
    job_id: str
    request_id: str
    status: str
    attempt: int
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchJob":
        value = _object(raw, "research_job", {
            "schema_version", "job_id", "request_id", "status", "attempt", "created_at", "updated_at",
            "started_at", "completed_at", "error",
        })
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("research_job.schema_version is invalid")
        status = _text(value.get("status"), "research_job.status", maximum=30).lower()
        if status not in {item.value for item in ResearchJobStatus}:
            raise ContractError("research_job.status is invalid")
        attempt = value.get("attempt", 0)
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 0 <= attempt <= 100:
            raise ContractError("research_job.attempt is invalid")
        error = safe_provider_message(_text(value.get("error"), "research_job.error", required=False, maximum=1_000), max_chars=1_000)
        _assert_sanitized(error, "research_job.error")
        return cls(
            job_id=_opaque(value.get("job_id"), "research_job.job_id", prefix="research_job_"),
            request_id=_opaque(value.get("request_id"), "research_job.request_id", prefix="research_"),
            status=status,
            attempt=attempt,
            created_at=str(_timestamp(value.get("created_at"), "research_job.created_at")),
            updated_at=str(_timestamp(value.get("updated_at"), "research_job.updated_at")),
            started_at=_timestamp(value.get("started_at"), "research_job.started_at", required=False),
            completed_at=_timestamp(value.get("completed_at"), "research_job.completed_at", required=False),
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "job_id": self.job_id,
            "request_id": self.request_id,
            "status": self.status,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


@dataclass(frozen=True)
class IncubationInsight:
    insight_id: str
    kind: str
    summary: str
    owner_language: str
    source_languages: tuple[str, ...]
    finding_ids: tuple[str, ...]
    supports_paths: tuple[str, ...]
    contradicts_paths: tuple[str, ...]
    confidence: float
    status: str
    created_at: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IncubationInsight":
        value = _object(raw, "incubation_insight", {
            "schema_version", "insight_id", "kind", "summary", "owner_language", "source_languages",
            "finding_ids", "supports_paths", "contradicts_paths", "confidence", "status", "created_at",
        })
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("incubation_insight.schema_version is invalid")
        kind = _text(value.get("kind"), "incubation_insight.kind", maximum=40).lower()
        if kind not in {item.value for item in InsightKind}:
            raise ContractError("incubation_insight.kind is invalid")
        status = _text(value.get("status"), "incubation_insight.status", maximum=30).lower()
        if status not in {item.value for item in InsightStatus}:
            raise ContractError("incubation_insight.status is invalid")
        confidence = value.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ContractError("incubation_insight.confidence must be between 0 and 1")
        languages = tuple(_language(item, "incubation_insight.source_languages[]") for item in _string_list(value.get("source_languages"), "incubation_insight.source_languages", maximum=20, item_maximum=24))
        return cls(
            insight_id=_opaque(value.get("insight_id"), "incubation_insight.insight_id", prefix="insight_"),
            kind=kind,
            summary=_sanitized_text(value.get("summary"), "incubation_insight.summary", maximum=4_000),
            owner_language=_language(value.get("owner_language"), "incubation_insight.owner_language"),
            source_languages=languages,
            finding_ids=_ref_tuple(value.get("finding_ids"), "incubation_insight.finding_ids", "finding_"),
            supports_paths=_path_tuple(value.get("supports_paths"), "incubation_insight.supports_paths"),
            contradicts_paths=_path_tuple(value.get("contradicts_paths"), "incubation_insight.contradicts_paths"),
            confidence=float(confidence),
            status=status,
            created_at=str(_timestamp(value.get("created_at"), "incubation_insight.created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "insight_id": self.insight_id,
            "kind": self.kind,
            "summary": self.summary,
            "owner_language": self.owner_language,
            "source_languages": list(self.source_languages),
            "finding_ids": list(self.finding_ids),
            "supports_paths": list(self.supports_paths),
            "contradicts_paths": list(self.contradicts_paths),
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class IncubationDeduction:
    deduction_id: str
    kind: str
    summary: str
    confidence: float
    basis: str
    source_refs: tuple[str, ...]
    supports_paths: tuple[str, ...]
    horizon_questions: tuple[str, ...]
    discovered_by: str
    citation_uris: tuple[str, ...]
    run_id: str
    created_at: str
    step: int = 1

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IncubationDeduction":
        value = _object(raw, "incubation_deduction", {
            "schema_version", "deduction_id", "kind", "summary", "confidence", "basis",
            "source_refs", "supports_paths", "horizon_questions", "discovered_by",
            "citation_uris", "run_id", "created_at", "step",
        })
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("incubation_deduction.schema_version is invalid")
        kind = _text(value.get("kind"), "incubation_deduction.kind", maximum=40).lower()
        if kind not in {item.value for item in DeductionKind}:
            raise ContractError("incubation_deduction.kind is invalid")
        confidence = value.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ContractError("incubation_deduction.confidence must be between 0 and 1")
        basis = _text(value.get("basis"), "incubation_deduction.basis", maximum=120)
        if basis not in {"snapshot", "source", "hypothesis", "openkey_question"} and not basis.startswith("source:"):
            raise ContractError("incubation_deduction.basis is invalid")
        discovered_by = _text(value.get("discovered_by"), "incubation_deduction.discovered_by", required=False, maximum=40) or "native"
        if not _OPAQUE.fullmatch(discovered_by):
            raise ContractError("incubation_deduction.discovered_by is invalid")
        step = value.get("step", 1)
        if isinstance(step, bool) or not isinstance(step, int) or not 1 <= step <= 10_000:
            raise ContractError("incubation_deduction.step is invalid")
        return cls(
            deduction_id=_opaque(value.get("deduction_id"), "incubation_deduction.deduction_id", prefix="deduction_"),
            kind=kind,
            summary=_sanitized_text(value.get("summary"), "incubation_deduction.summary", maximum=2_000),
            confidence=float(confidence),
            basis=basis,
            source_refs=_string_list(value.get("source_refs"), "incubation_deduction.source_refs", maximum=20, item_maximum=240),
            supports_paths=_path_tuple(value.get("supports_paths"), "incubation_deduction.supports_paths"),
            horizon_questions=_string_list(value.get("horizon_questions"), "incubation_deduction.horizon_questions", maximum=10, item_maximum=400),
            discovered_by=discovered_by,
            citation_uris=_string_list(value.get("citation_uris"), "incubation_deduction.citation_uris", maximum=20, item_maximum=240),
            run_id=_opaque(value.get("run_id"), "incubation_deduction.run_id", prefix="infusion_"),
            created_at=str(_timestamp(value.get("created_at"), "incubation_deduction.created_at")),
            step=step,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "deduction_id": self.deduction_id,
            "kind": self.kind,
            "summary": self.summary,
            "confidence": self.confidence,
            "basis": self.basis,
            "source_refs": list(self.source_refs),
            "supports_paths": list(self.supports_paths),
            "horizon_questions": list(self.horizon_questions),
            "discovered_by": self.discovered_by,
            "citation_uris": list(self.citation_uris),
            "run_id": self.run_id,
            "created_at": self.created_at,
            "step": self.step,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class InfusionRun:
    run_id: str
    trigger: str
    mode: str
    status: str
    budget_tokens: int
    snapshot_hash: str
    session_id: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str = ""

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "InfusionRun":
        value = _object(raw, "infusion_run", {
            "schema_version", "run_id", "trigger", "mode", "status", "budget_tokens",
            "snapshot_hash", "session_id", "created_at", "updated_at", "started_at",
            "finished_at", "error",
        })
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("infusion_run.schema_version is invalid")
        trigger = _text(value.get("trigger"), "infusion_run.trigger", maximum=40).lower()
        mode = _text(value.get("mode"), "infusion_run.mode", maximum=20).lower()
        if mode not in {item.value for item in InfusionMode}:
            raise ContractError("infusion_run.mode is invalid")
        status = _text(value.get("status"), "infusion_run.status", maximum=20).lower()
        if status not in {item.value for item in InfusionRunStatus}:
            raise ContractError("infusion_run.status is invalid")
        budget_tokens = value.get("budget_tokens", 0)
        if isinstance(budget_tokens, bool) or not isinstance(budget_tokens, int) or not 0 <= budget_tokens <= 100_000:
            raise ContractError("infusion_run.budget_tokens is invalid")
        return cls(
            run_id=_opaque(value.get("run_id"), "infusion_run.run_id", prefix="infusion_"),
            trigger=trigger,
            mode=mode,
            status=status,
            budget_tokens=budget_tokens,
            snapshot_hash=_text(value.get("snapshot_hash"), "infusion_run.snapshot_hash", required=False, maximum=128),
            session_id=_opaque(value.get("session_id"), "infusion_run.session_id", prefix="intake-"),
            created_at=str(_timestamp(value.get("created_at"), "infusion_run.created_at")),
            updated_at=str(_timestamp(value.get("updated_at"), "infusion_run.updated_at")),
            started_at=str(_timestamp(value.get("started_at"), "infusion_run.started_at")) if value.get("started_at") else None,
            finished_at=str(_timestamp(value.get("finished_at"), "infusion_run.finished_at")) if value.get("finished_at") else None,
            error=safe_provider_message(value.get("error") or "", max_chars=500),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "trigger": self.trigger,
            "mode": self.mode,
            "status": self.status,
            "budget_tokens": self.budget_tokens,
            "snapshot_hash": self.snapshot_hash,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


@dataclass(frozen=True)
class CreativeEpisode:
    episode_id: str
    created_at: str
    engagement_outcome: str
    design_fingerprint: dict[str, Any]
    copy_fingerprint: dict[str, Any]
    quality: dict[str, Any]
    reflection: dict[str, Any]
    semantic_text: str
    sanitizer_version: int = 1

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CreativeEpisode":
        value = _object(raw, "creative_episode", {"schema_version", "episode_id", "created_at", "engagement_outcome", "design_fingerprint", "copy_fingerprint", "quality", "reflection", "semantic_text", "sanitizer_version"})
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("creative_episode.schema_version is invalid")
        episode_id = _opaque(value.get("episode_id"), "creative_episode.episode_id", prefix="episode_")
        outcome = _text(value.get("engagement_outcome"), "creative_episode.engagement_outcome", maximum=20).lower()
        if outcome not in {"accepted", "rejected", "expired"}:
            raise ContractError("creative_episode.engagement_outcome is invalid")
        design = _object(value.get("design_fingerprint"), "creative_episode.design_fingerprint", {"layout_topology", "type_roles", "palette_shape", "motion_patterns", "navigation_pattern", "component_rhythm"})
        copy_fingerprint = _object(value.get("copy_fingerprint"), "creative_episode.copy_fingerprint", {"opening_pattern", "section_rhythm", "cta_pattern", "repeated_motifs"})
        quality = _object(value.get("quality"), "creative_episode.quality", {"accepted", "critic_categories", "revision_count"})
        reflection = _object(value.get("reflection"), "creative_episode.reflection", {"habits_repeated", "departures_that_worked", "approaches_to_avoid", "techniques_to_reuse_carefully"})
        for name, section in (("design_fingerprint", design), ("copy_fingerprint", copy_fingerprint), ("reflection", reflection)):
            for key, child in section.items():
                if key == "navigation_pattern" or key == "opening_pattern" or key == "cta_pattern":
                    section[key] = _text(child, f"creative_episode.{name}.{key}", required=False, maximum=300)
                else:
                    section[key] = _string_list(child, f"creative_episode.{name}.{key}", maximum=50, item_maximum=200)
        accepted = quality.get("accepted", False)
        if not isinstance(accepted, bool):
            raise ContractError("creative_episode.quality.accepted must be boolean")
        revision_count = quality.get("revision_count", 0)
        if isinstance(revision_count, bool) or not isinstance(revision_count, int) or not 0 <= revision_count <= 100:
            raise ContractError("creative_episode.quality.revision_count is invalid")
        quality = {"accepted": accepted, "critic_categories": _string_list(quality.get("critic_categories"), "creative_episode.quality.critic_categories", maximum=30, item_maximum=100), "revision_count": revision_count}
        semantic_text = _text(value.get("semantic_text"), "creative_episode.semantic_text", maximum=2_000)
        _assert_sanitized({"design": design, "copy": copy_fingerprint, "quality": quality, "reflection": reflection, "semantic_text": semantic_text}, "creative_episode")
        sanitizer_version = value.get("sanitizer_version", 1)
        if sanitizer_version != 1:
            raise ContractError("creative_episode.sanitizer_version is invalid")
        return cls(
            episode_id=episode_id,
            created_at=str(_timestamp(value.get("created_at"), "creative_episode.created_at")),
            engagement_outcome=outcome,
            design_fingerprint=design,
            copy_fingerprint=copy_fingerprint,
            quality=quality,
            reflection=reflection,
            semantic_text=semantic_text,
            sanitizer_version=sanitizer_version,
        )

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "episode_id": self.episode_id,
            "created_at": self.created_at,
            "engagement_outcome": self.engagement_outcome,
            "design_fingerprint": copy.deepcopy(self.design_fingerprint),
            "copy_fingerprint": copy.deepcopy(self.copy_fingerprint),
            "quality": copy.deepcopy(self.quality),
            "reflection": copy.deepcopy(self.reflection),
            "semantic_text": self.semantic_text,
            "sanitizer_version": self.sanitizer_version,
        }


@dataclass(frozen=True)
class NoveltyContext:
    query_hash: str
    constraints: tuple[str, ...]
    matches: tuple[dict[str, Any], ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "NoveltyContext":
        value = _object(raw, "novelty_context", {"schema_version", "query_hash", "constraints", "matches"})
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("novelty_context.schema_version is invalid")
        query_hash = _hash(value.get("query_hash"), "novelty_context.query_hash")
        constraints = tuple(_string_list(value.get("constraints"), "novelty_context.constraints", maximum=50, item_maximum=500))
        matches_raw = value.get("matches") or []
        if not isinstance(matches_raw, list) or len(matches_raw) > 20:
            raise ContractError("novelty_context.matches must be a bounded list")
        matches: list[dict[str, Any]] = []
        for index, item in enumerate(matches_raw):
            match = _object(item, f"novelty_context.matches[{index}]", {"episode_id", "score", "semantic_score", "structured_score", "phrase_score", "visual_score", "patterns"})
            episode_id = _opaque(match.get("episode_id"), f"novelty_context.matches[{index}].episode_id", prefix="episode_")
            score = match.get("score", 0.0)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
                raise ContractError("novelty_context match score is invalid")
            normalized_match = {
                "episode_id": episode_id,
                "score": float(score),
                "patterns": _string_list(match.get("patterns"), f"novelty_context.matches[{index}].patterns", maximum=30, item_maximum=200),
            }
            for name in ("semantic_score", "structured_score", "phrase_score", "visual_score"):
                if name not in match:
                    continue
                component = match[name]
                if isinstance(component, bool) or not isinstance(component, (int, float)) or not 0 <= float(component) <= 1:
                    raise ContractError(f"novelty_context match {name} is invalid")
                normalized_match[name] = float(component)
            matches.append(normalized_match)
        return cls(query_hash=query_hash, constraints=constraints, matches=tuple(matches))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "query_hash": self.query_hash, "constraints": list(self.constraints), "matches": [copy.deepcopy(item) for item in self.matches]}


@dataclass(frozen=True)
class ProvisioningBundle:
    bundle_id: str
    incubation_id: str
    accepted_candidate_sha: str
    intake_revision: dict[str, Any]
    genesis_revision: dict[str, Any]
    genesis_revisions: tuple[dict[str, Any], ...] = ()
    conversation: tuple[dict[str, Any], ...] = ()
    research_sources: tuple[dict[str, Any], ...] = ()
    research_findings: tuple[dict[str, Any], ...] = ()
    research_requests: tuple[dict[str, Any], ...] = ()
    research_insights: tuple[dict[str, Any], ...] = ()
    research_deductions: tuple[dict[str, Any], ...] = ()
    approved_feed_subscriptions: tuple[dict[str, Any], ...] = ()
    assets: tuple[dict[str, Any], ...] = ()
    design_history: tuple[dict[str, Any], ...] = ()
    owner_feedback: tuple[dict[str, Any], ...] = ()
    activity: tuple[dict[str, Any], ...] = ()
    unknowns: tuple[dict[str, Any], ...] = ()
    prohibited_claims: tuple[str, ...] = ()
    design_skill_set: dict[str, Any] = field(default_factory=dict)
    customer_context: dict[str, Any] = field(default_factory=dict)
    acceptance_manifest: dict[str, Any] = field(default_factory=dict)
    integrity: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProvisioningBundle":
        value = _object(raw, "provisioning_bundle", {"schema_version", "bundle_id", "incubation_id", "accepted_candidate_sha", "intake_revision", "genesis_revision", "genesis_revisions", "conversation", "research_sources", "research_findings", "research_requests", "research_insights", "research_deductions", "approved_feed_subscriptions", "assets", "design_history", "owner_feedback", "activity", "unknowns", "prohibited_claims", "design_skill_set", "customer_context", "acceptance_manifest", "integrity"})
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ContractError("provisioning_bundle.schema_version is invalid")
        bundle_id = _opaque(value.get("bundle_id"), "provisioning_bundle.bundle_id", prefix="bundle_")
        incubation_id = _text(value.get("incubation_id"), "provisioning_bundle.incubation_id", maximum=80)
        if not _INCUBATION_ID.fullmatch(incubation_id):
            raise ContractError("provisioning_bundle.incubation_id is invalid")
        intake_revision = _object(value.get("intake_revision"), "provisioning_bundle.intake_revision")
        genesis_revision = _object(value.get("genesis_revision"), "provisioning_bundle.genesis_revision")
        collections: dict[str, tuple[dict[str, Any], ...]] = {}
        for name in ("genesis_revisions", "conversation", "research_sources", "research_findings", "research_requests", "research_insights", "research_deductions", "approved_feed_subscriptions", "assets", "design_history", "owner_feedback", "activity", "unknowns"):
            items = value.get(name) or []
            if not isinstance(items, list) or len(items) > 10_000 or any(not isinstance(item, Mapping) for item in items):
                raise ContractError(f"provisioning_bundle.{name} must be a bounded object list")
            collections[name] = tuple(_copy_json(item, f"provisioning_bundle.{name}", max_bytes=500_000) for item in items)
        prohibited_claims = tuple(_string_list(value.get("prohibited_claims"), "provisioning_bundle.prohibited_claims", maximum=100, item_maximum=2_000))
        design_skill_set = _copy_json(value.get("design_skill_set") or {}, "provisioning_bundle.design_skill_set", max_bytes=20_000)
        if not isinstance(design_skill_set, dict):
            raise ContractError("provisioning_bundle.design_skill_set must be an object")
        customer_context = _copy_json(value.get("customer_context") or {}, "provisioning_bundle.customer_context", max_bytes=400_000)
        acceptance_manifest = _copy_json(value.get("acceptance_manifest") or {}, "provisioning_bundle.acceptance_manifest", max_bytes=200_000)
        if not isinstance(customer_context, dict) or not isinstance(acceptance_manifest, dict):
            raise ContractError("provisioning_bundle customer handoff records must be objects")
        integrity = _object(value.get("integrity"), "provisioning_bundle.integrity", {"content_hash", "record_counts"})
        content_hash = _hash(integrity.get("content_hash"), "provisioning_bundle.integrity.content_hash")
        record_counts = _object(integrity.get("record_counts"), "provisioning_bundle.integrity.record_counts")
        for key, count in record_counts.items():
            if not isinstance(key, str) or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ContractError("provisioning_bundle.integrity.record_counts is invalid")
        result = cls(
            bundle_id=bundle_id,
            incubation_id=incubation_id,
            accepted_candidate_sha=_hash(value.get("accepted_candidate_sha"), "provisioning_bundle.accepted_candidate_sha", length=40),
            intake_revision=intake_revision,
            genesis_revision=genesis_revision,
            genesis_revisions=collections["genesis_revisions"],
            conversation=collections["conversation"],
            research_sources=collections["research_sources"],
            research_findings=collections["research_findings"],
            research_requests=collections["research_requests"],
            research_insights=collections["research_insights"],
            research_deductions=collections["research_deductions"],
            approved_feed_subscriptions=collections["approved_feed_subscriptions"],
            assets=collections["assets"],
            design_history=collections["design_history"],
            owner_feedback=collections["owner_feedback"],
            activity=collections["activity"],
            unknowns=collections["unknowns"],
            prohibited_claims=prohibited_claims,
            design_skill_set=design_skill_set,
            customer_context=customer_context,
            acceptance_manifest=acceptance_manifest,
            integrity={"content_hash": content_hash, "record_counts": record_counts},
        )
        if result.computed_hash != content_hash:
            raise ContractError("provisioning_bundle.integrity.content_hash does not match the bundle")
        return result

    @property
    def computed_hash(self) -> str:
        data = self.to_dict()
        data["integrity"] = {"record_counts": self.integrity.get("record_counts", {})}
        return canonical_hash(data)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": SCHEMA_VERSION,
            "bundle_id": self.bundle_id,
            "incubation_id": self.incubation_id,
            "accepted_candidate_sha": self.accepted_candidate_sha,
            "intake_revision": copy.deepcopy(self.intake_revision),
            "genesis_revision": copy.deepcopy(self.genesis_revision),
            "genesis_revisions": [copy.deepcopy(item) for item in self.genesis_revisions],
            "conversation": [copy.deepcopy(item) for item in self.conversation],
            "research_sources": [copy.deepcopy(item) for item in self.research_sources],
            "research_findings": [copy.deepcopy(item) for item in self.research_findings],
            "research_requests": [copy.deepcopy(item) for item in self.research_requests],
            "research_insights": [copy.deepcopy(item) for item in self.research_insights],
            "approved_feed_subscriptions": [copy.deepcopy(item) for item in self.approved_feed_subscriptions],
            "assets": [copy.deepcopy(item) for item in self.assets],
            "design_history": [copy.deepcopy(item) for item in self.design_history],
            "owner_feedback": [copy.deepcopy(item) for item in self.owner_feedback],
            "activity": [copy.deepcopy(item) for item in self.activity],
            "unknowns": [copy.deepcopy(item) for item in self.unknowns],
            "prohibited_claims": list(self.prohibited_claims),
            "design_skill_set": copy.deepcopy(self.design_skill_set),
            "integrity": copy.deepcopy(self.integrity),
        }
        if self.customer_context:
            result["customer_context"] = copy.deepcopy(self.customer_context)
        if self.acceptance_manifest:
            result["acceptance_manifest"] = copy.deepcopy(self.acceptance_manifest)
        if self.research_deductions:
            result["research_deductions"] = [copy.deepcopy(item) for item in self.research_deductions]
        return result


@dataclass(frozen=True)
class ProvisioningReceipt:
    request_id: str
    bundle_id: str
    customer_instance_id: str
    config_path: str
    database_path: str
    imported_counts: dict[str, int]
    bundle_hash: str
    verified: bool
    created_at: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProvisioningReceipt":
        value = _object(raw, "provisioning_receipt", {"request_id", "bundle_id", "customer_instance_id", "config_path", "database_path", "imported_counts", "bundle_hash", "verified", "created_at"})
        verified = value.get("verified")
        if not isinstance(verified, bool):
            raise ContractError("provisioning_receipt.verified must be boolean")
        counts = _object(value.get("imported_counts"), "provisioning_receipt.imported_counts")
        normalized: dict[str, int] = {}
        for key, count in counts.items():
            if not isinstance(key, str) or isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ContractError("provisioning_receipt.imported_counts is invalid")
            normalized[key] = count
        return cls(
            request_id=_opaque(value.get("request_id"), "provisioning_receipt.request_id", prefix="provision_"),
            bundle_id=_opaque(value.get("bundle_id"), "provisioning_receipt.bundle_id", prefix="bundle_"),
            customer_instance_id=_opaque(value.get("customer_instance_id"), "provisioning_receipt.customer_instance_id"),
            config_path=_text(value.get("config_path"), "provisioning_receipt.config_path", maximum=1_000),
            database_path=_text(value.get("database_path"), "provisioning_receipt.database_path", maximum=1_000),
            imported_counts=normalized,
            bundle_hash=_hash(value.get("bundle_hash"), "provisioning_receipt.bundle_hash"),
            verified=verified,
            created_at=str(_timestamp(value.get("created_at"), "provisioning_receipt.created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "bundle_id": self.bundle_id,
            "customer_instance_id": self.customer_instance_id,
            "config_path": self.config_path,
            "database_path": self.database_path,
            "imported_counts": dict(self.imported_counts),
            "bundle_hash": self.bundle_hash,
            "verified": self.verified,
            "created_at": self.created_at,
        }


__all__ = [
    "ActivityProvenance",
    "CreativeEpisode",
    "CustomerAdaGenesis",
    "DeductionKind",
    "EvidenceOrigin",
    "GenesisEvidence",
    "IncubationActivity",
    "IncubationActivityCategory",
    "IncubationActivityState",
    "IncubationDeduction",
    "IncubationInsight",
    "IncubationRecord",
    "IncubationStatus",
    "InfusionMode",
    "InfusionRun",
    "InfusionRunStatus",
    "InsightKind",
    "InsightStatus",
    "NoveltyContext",
    "ProvisioningBundle",
    "ProvisioningReceipt",
    "ResearchFinding",
    "ResearchJob",
    "ResearchJobStatus",
    "ResearchRequest",
    "ResearchRequestStatus",
    "ResearchSource",
    "ResearchTrigger",
    "SCHEMA_VERSION",
    "SourceTrustState",
    "SubscriptionState",
    "validate_incubation_transition",
]

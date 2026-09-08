"""Versioned contracts for the customer state handed off from incubation.

Incubation has more information than any one runtime consumer needs.  These
contracts make the accepted customer context and its provenance one durable,
content-addressed boundary instead of a collection of lossy projections.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .contracts import ContractError
from .design_contracts import canonical_hash, canonical_json


CUSTOMER_CONTEXT_SCHEMA_VERSION = 1
ACCEPTANCE_MANIFEST_SCHEMA_VERSION = 1
RESEARCH_EVIDENCE_MANIFEST_SCHEMA_VERSION = 1
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


def _object(value: Any, path: str, *, maximum: int = 400_000) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{path} must be an object")
    try:
        encoded = canonical_json(value)
    except ContractError as exc:
        raise ContractError(f"{path} contains unsupported JSON values") from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise ContractError(f"{path} exceeds {maximum} bytes")
    return copy.deepcopy(dict(value))


def _text(value: Any, path: str, *, required: bool = True, maximum: int = 200) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ContractError(f"{path} must be text")
    result = value.strip()
    if required and not result:
        raise ContractError(f"{path} must not be empty")
    if len(result) > maximum:
        raise ContractError(f"{path} exceeds {maximum} characters")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in result):
        raise ContractError(f"{path} contains control characters")
    return result


def _id(value: Any, path: str, *, required: bool = True) -> str:
    result = _text(value, path, required=required, maximum=200)
    if result and not _ID_RE.fullmatch(result):
        raise ContractError(f"{path} is invalid")
    return result


def _hash(value: Any, path: str, pattern: re.Pattern[str]) -> str:
    result = _text(value, path, maximum=64).lower()
    if not pattern.fullmatch(result):
        raise ContractError(f"{path} is invalid")
    return result


def _optional_hash(value: Any, path: str, pattern: re.Pattern[str] = _SHA256_RE) -> str | None:
    if value in (None, ""):
        return None
    return _hash(value, path, pattern)


def _section(value: Any, path: str) -> dict[str, Any]:
    return _object(value if value is not None else {}, path, maximum=100_000)


def _list_of_objects(value: Any, path: str, maximum: int = 500) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{path} must be a list")
    if len(value) > maximum:
        raise ContractError(f"{path} contains too many items")
    return tuple(_object(item, f"{path}[{index}]", maximum=50_000) for index, item in enumerate(value))


@dataclass(frozen=True)
class CustomerAssetBinding:
    """One owner-selected asset and the reason it belongs in customer state."""

    asset_id: int
    position: int
    usage: str
    source_asset_hash: str | None = None
    content_hash: str | None = None
    role: str = ""
    required: bool = False
    placement: tuple[str, ...] = ()
    reference_aspects: tuple[str, ...] = ()
    analysis_hash: str | None = None
    source_kind: str = "incubation"
    source_id: str = ""
    owner_note: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CustomerAssetBinding":
        value = _object(raw, "asset_binding", maximum=50_000)
        allowed = {"asset_id", "position", "usage", "source_asset_hash", "content_hash", "role", "required", "placement", "reference_aspects", "analysis_hash", "source_kind", "source_id", "owner_note", "metadata"}
        if set(value) - allowed:
            raise ContractError("asset_binding contains unsupported fields")
        asset_id = value.get("asset_id")
        position = value.get("position")
        if isinstance(asset_id, bool) or not isinstance(asset_id, int) or asset_id < 1:
            raise ContractError("asset_binding.asset_id is invalid")
        if isinstance(position, bool) or not isinstance(position, int) or position < 0:
            raise ContractError("asset_binding.position is invalid")
        required = value.get("required", False)
        if not isinstance(required, bool):
            raise ContractError("asset_binding.required is invalid")
        placement = value.get("placement") or []
        reference_aspects = value.get("reference_aspects") or []
        if not isinstance(placement, list) or not all(isinstance(item, str) for item in placement):
            raise ContractError("asset_binding.placement is invalid")
        if not isinstance(reference_aspects, list) or not all(isinstance(item, str) for item in reference_aspects):
            raise ContractError("asset_binding.reference_aspects is invalid")
        return cls(
            asset_id=asset_id,
            position=position,
            usage=_text(value.get("usage"), "asset_binding.usage", maximum=80),
            source_asset_hash=_optional_hash(value.get("source_asset_hash"), "asset_binding.source_asset_hash"),
            content_hash=_optional_hash(value.get("content_hash"), "asset_binding.content_hash"),
            role=_text(value.get("role"), "asset_binding.role", required=False, maximum=120),
            required=required,
            placement=tuple(_text(item, "asset_binding.placement", maximum=200) for item in placement[:20]),
            reference_aspects=tuple(_text(item, "asset_binding.reference_aspects", maximum=200) for item in reference_aspects[:20]),
            analysis_hash=_optional_hash(value.get("analysis_hash"), "asset_binding.analysis_hash"),
            source_kind=_text(value.get("source_kind"), "asset_binding.source_kind", required=False, maximum=80) or "incubation",
            source_id=_text(value.get("source_id"), "asset_binding.source_id", required=False, maximum=200),
            owner_note=_text(value.get("owner_note"), "asset_binding.owner_note", required=False, maximum=4_000),
            metadata=_section(value.get("metadata"), "asset_binding.metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "position": self.position,
            "usage": self.usage,
            "source_asset_hash": self.source_asset_hash,
            "content_hash": self.content_hash,
            "role": self.role,
            "required": self.required,
            "placement": list(self.placement),
            "reference_aspects": list(self.reference_aspects),
            "analysis_hash": self.analysis_hash,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "owner_note": self.owner_note,
            "metadata": copy.deepcopy(self.metadata),
        }


@dataclass(frozen=True)
class ResearchEvidenceManifest:
    """Content-addressed research references admitted to customer context."""

    included_sources: tuple[dict[str, Any], ...] = ()
    source_states: tuple[dict[str, Any], ...] = ()
    findings: tuple[dict[str, Any], ...] = ()
    insights: tuple[dict[str, Any], ...] = ()
    deductions: tuple[dict[str, Any], ...] = ()
    excluded_source_ids: tuple[str, ...] = ()
    contradictions: tuple[dict[str, Any], ...] = ()
    unresolved_claims: tuple[dict[str, Any], ...] = ()
    source_languages: tuple[str, ...] = ()
    target_language: str = ""
    content_hash: str | None = None

    @staticmethod
    def _references(value: Any, path: str, identifier: str, digest: str) -> tuple[dict[str, Any], ...]:
        items = _list_of_objects(value, path)
        result: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            normalized = copy.deepcopy(item)
            normalized[identifier] = _id(item.get(identifier), f"{path}[{index}].{identifier}")
            normalized[digest] = _hash(item.get(digest), f"{path}[{index}].{digest}", _SHA256_RE)
            result.append(normalized)
        return tuple(result)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchEvidenceManifest":
        value = _object(raw, "research_evidence_manifest", maximum=200_000)
        allowed = {
            "schema_version", "included_sources", "source_states", "findings", "insights", "deductions",
            "excluded_source_ids", "contradictions", "unresolved_claims", "source_languages",
            "target_language", "content_hash",
        }
        if set(value) - allowed:
            raise ContractError("research_evidence_manifest contains unsupported fields")
        if value.get("schema_version", RESEARCH_EVIDENCE_MANIFEST_SCHEMA_VERSION) != RESEARCH_EVIDENCE_MANIFEST_SCHEMA_VERSION:
            raise ContractError("research_evidence_manifest.schema_version is invalid")
        excluded = value.get("excluded_source_ids") or []
        languages = value.get("source_languages") or []
        if not isinstance(excluded, list) or not all(isinstance(item, str) for item in excluded):
            raise ContractError("research_evidence_manifest.excluded_source_ids is invalid")
        if not isinstance(languages, list) or not all(isinstance(item, str) for item in languages):
            raise ContractError("research_evidence_manifest.source_languages is invalid")
        result = cls(
            included_sources=cls._references(value.get("included_sources"), "research_evidence_manifest.included_sources", "source_id", "source_hash"),
            source_states=cls._references(value.get("source_states"), "research_evidence_manifest.source_states", "source_id", "source_hash"),
            findings=cls._references(value.get("findings"), "research_evidence_manifest.findings", "finding_id", "finding_hash"),
            insights=cls._references(value.get("insights"), "research_evidence_manifest.insights", "insight_id", "insight_hash"),
            deductions=cls._references(value.get("deductions"), "research_evidence_manifest.deductions", "deduction_id", "deduction_hash"),
            excluded_source_ids=tuple(_id(item, "research_evidence_manifest.excluded_source_ids") for item in excluded),
            contradictions=_list_of_objects(value.get("contradictions"), "research_evidence_manifest.contradictions"),
            unresolved_claims=_list_of_objects(value.get("unresolved_claims"), "research_evidence_manifest.unresolved_claims"),
            source_languages=tuple(_text(item, "research_evidence_manifest.source_languages", maximum=40) for item in languages),
            target_language=_text(value.get("target_language"), "research_evidence_manifest.target_language", required=False, maximum=40),
            content_hash=_optional_hash(value.get("content_hash"), "research_evidence_manifest.content_hash"),
        )
        if result.content_hash is not None and result.content_hash != result.computed_hash:
            raise ContractError("research_evidence_manifest.content_hash does not match content")
        return result

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": RESEARCH_EVIDENCE_MANIFEST_SCHEMA_VERSION,
            "included_sources": copy.deepcopy(list(self.included_sources)),
            "source_states": copy.deepcopy(list(self.source_states)),
            "findings": copy.deepcopy(list(self.findings)),
            "insights": copy.deepcopy(list(self.insights)),
            "deductions": copy.deepcopy(list(self.deductions)),
            "excluded_source_ids": list(self.excluded_source_ids),
            "contradictions": copy.deepcopy(list(self.contradictions)),
            "unresolved_claims": copy.deepcopy(list(self.unresolved_claims)),
            "source_languages": list(self.source_languages),
            "target_language": self.target_language,
        }
        if include_hash:
            result["content_hash"] = self.content_hash or canonical_hash(result)
        return result

    @property
    def computed_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))


@dataclass(frozen=True)
class CustomerContextSnapshot:
    """Lossless accepted customer context with source lineage and a hash."""

    context_id: str
    revision: int
    created_at: str
    source_kind: str
    source_incubation_id: str
    source_intake_session_id: str
    source_intake_revision: int
    source_intake_revision_id: int | None
    source_intake_hash: str
    source_genesis_revision: int
    source_genesis_hash: str
    source_design_run_id: str
    source_design_run_hash: str
    previous_context_hash: str | None = None
    business: dict[str, Any] = field(default_factory=dict)
    audience: dict[str, Any] = field(default_factory=dict)
    conversion: dict[str, Any] = field(default_factory=dict)
    brand: dict[str, Any] = field(default_factory=dict)
    site: dict[str, Any] = field(default_factory=dict)
    relationship: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    research: dict[str, Any] = field(default_factory=dict)
    research_manifest: ResearchEvidenceManifest | None = None
    creative_identity: dict[str, Any] = field(default_factory=dict)
    design: dict[str, Any] = field(default_factory=dict)
    assets: tuple[CustomerAssetBinding, ...] = ()
    knowledge: tuple[dict[str, Any], ...] = ()
    open_questions: tuple[dict[str, Any], ...] = ()
    contradictions: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CustomerContextSnapshot":
        value = _object(raw, "customer_context")
        allowed = {
            "schema_version", "context_id", "revision", "created_at", "source_kind", "source_incubation_id",
            "source_intake_session_id", "source_intake_revision", "source_intake_revision_id", "source_intake_hash",
            "source_genesis_revision", "source_genesis_hash", "source_design_run_id", "source_design_run_hash", "previous_context_hash",
            "business", "audience", "conversion", "brand", "site", "relationship", "constraints", "research",
            "research_manifest", "creative_identity", "design", "assets", "knowledge", "open_questions", "contradictions", "provenance",
            "content_hash",
        }
        if set(value) - allowed:
            raise ContractError("customer_context contains unsupported fields")
        version = value.get("schema_version", CUSTOMER_CONTEXT_SCHEMA_VERSION)
        if version != CUSTOMER_CONTEXT_SCHEMA_VERSION:
            raise ContractError("customer_context.schema_version is invalid")
        revision = value.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ContractError("customer_context.revision is invalid")
        intake_revision = value.get("source_intake_revision")
        if isinstance(intake_revision, bool) or not isinstance(intake_revision, int) or intake_revision < 1:
            raise ContractError("customer_context.source_intake_revision is invalid")
        revision_id = value.get("source_intake_revision_id")
        if revision_id is not None and (isinstance(revision_id, bool) or not isinstance(revision_id, int) or revision_id < 1):
            raise ContractError("customer_context.source_intake_revision_id is invalid")
        genesis_revision = value.get("source_genesis_revision")
        if isinstance(genesis_revision, bool) or not isinstance(genesis_revision, int) or genesis_revision < 1:
            raise ContractError("customer_context.source_genesis_revision is invalid")
        assets = []
        for item in value.get("assets") or []:
            assets.append(CustomerAssetBinding.from_dict(item))
        result = cls(
            context_id=_id(value.get("context_id"), "customer_context.context_id"),
            revision=revision,
            created_at=_text(value.get("created_at"), "customer_context.created_at", maximum=100),
            source_kind=_text(value.get("source_kind"), "customer_context.source_kind", maximum=80),
            source_incubation_id=_id(value.get("source_incubation_id"), "customer_context.source_incubation_id"),
            source_intake_session_id=_id(value.get("source_intake_session_id"), "customer_context.source_intake_session_id"),
            source_intake_revision=intake_revision,
            source_intake_revision_id=revision_id,
            source_intake_hash=_hash(value.get("source_intake_hash"), "customer_context.source_intake_hash", _SHA256_RE),
            source_genesis_revision=genesis_revision,
            source_genesis_hash=_hash(value.get("source_genesis_hash"), "customer_context.source_genesis_hash", _SHA256_RE),
            source_design_run_id=_id(value.get("source_design_run_id"), "customer_context.source_design_run_id"),
            source_design_run_hash=_hash(value.get("source_design_run_hash"), "customer_context.source_design_run_hash", _SHA256_RE),
            previous_context_hash=_optional_hash(value.get("previous_context_hash"), "customer_context.previous_context_hash"),
            business=_section(value.get("business"), "customer_context.business"),
            audience=_section(value.get("audience"), "customer_context.audience"),
            conversion=_section(value.get("conversion"), "customer_context.conversion"),
            brand=_section(value.get("brand"), "customer_context.brand"),
            site=_section(value.get("site"), "customer_context.site"),
            relationship=_section(value.get("relationship"), "customer_context.relationship"),
            constraints=_section(value.get("constraints"), "customer_context.constraints"),
            research=_section(value.get("research"), "customer_context.research"),
            research_manifest=(
                ResearchEvidenceManifest.from_dict(value["research_manifest"])
                if value.get("research_manifest")
                else None
            ),
            creative_identity=_section(value.get("creative_identity"), "customer_context.creative_identity"),
            design=_section(value.get("design"), "customer_context.design"),
            assets=tuple(assets),
            knowledge=_list_of_objects(value.get("knowledge"), "customer_context.knowledge"),
            open_questions=_list_of_objects(value.get("open_questions"), "customer_context.open_questions"),
            contradictions=_list_of_objects(value.get("contradictions"), "customer_context.contradictions"),
            provenance=_section(value.get("provenance"), "customer_context.provenance"),
            content_hash=_optional_hash(value.get("content_hash"), "customer_context.content_hash"),
        )
        if result.content_hash is not None and result.content_hash != result.computed_hash:
            raise ContractError("customer_context.content_hash does not match content")
        return result

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": CUSTOMER_CONTEXT_SCHEMA_VERSION,
            "context_id": self.context_id,
            "revision": self.revision,
            "created_at": self.created_at,
            "source_kind": self.source_kind,
            "source_incubation_id": self.source_incubation_id,
            "source_intake_session_id": self.source_intake_session_id,
            "source_intake_revision": self.source_intake_revision,
            "source_intake_revision_id": self.source_intake_revision_id,
            "source_intake_hash": self.source_intake_hash,
            "source_genesis_revision": self.source_genesis_revision,
            "source_genesis_hash": self.source_genesis_hash,
            "source_design_run_id": self.source_design_run_id,
            "source_design_run_hash": self.source_design_run_hash,
            "previous_context_hash": self.previous_context_hash,
            "business": copy.deepcopy(self.business),
            "audience": copy.deepcopy(self.audience),
            "conversion": copy.deepcopy(self.conversion),
            "brand": copy.deepcopy(self.brand),
            "site": copy.deepcopy(self.site),
            "relationship": copy.deepcopy(self.relationship),
            "constraints": copy.deepcopy(self.constraints),
            "research": copy.deepcopy(self.research),
            "creative_identity": copy.deepcopy(self.creative_identity),
            "design": copy.deepcopy(self.design),
            "assets": [item.to_dict() for item in self.assets],
            "knowledge": copy.deepcopy(list(self.knowledge)),
            "open_questions": copy.deepcopy(list(self.open_questions)),
            "contradictions": copy.deepcopy(list(self.contradictions)),
            "provenance": copy.deepcopy(self.provenance),
        }
        if self.research_manifest is not None:
            result["research_manifest"] = self.research_manifest.to_dict()
        if include_hash:
            result["content_hash"] = self.content_hash or canonical_hash(result)
        return result

    @property
    def computed_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def context_revision(self) -> int:
        return self.revision


@dataclass(frozen=True)
class AcceptanceManifest:
    """The owner approval that binds context, design run, and website source."""

    manifest_id: str
    incubation_id: str
    accepted_candidate_sha: str
    accepted_run_id: str
    accepted_run_hash: str
    intake_session_id: str
    intake_revision: int
    intake_revision_id: int | None
    intake_hash: str
    genesis_revision: int
    genesis_hash: str
    context_id: str
    context_revision: int
    context_hash: str
    website_source: dict[str, Any]
    created_at: str
    content_hash: str | None = None
    accepted_by: str = "owner"
    base_sha: str = ""
    research_manifest_hash: str | None = None
    required_assets: tuple[dict[str, Any], ...] = ()
    approved_knowledge: tuple[dict[str, Any], ...] = ()
    design_manifest_hash: str = ""
    quality_report_hash: str = ""
    planning_hash: str = ""
    design_skill_set_hash: str = ""
    website_build_profile: dict[str, Any] = field(default_factory=dict)
    repository_identity: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AcceptanceManifest":
        value = _object(raw, "acceptance_manifest", maximum=200_000)
        allowed = {
            "schema_version", "manifest_id", "incubation_id", "accepted_candidate_sha", "accepted_run_id",
            "accepted_run_hash", "intake_session_id", "intake_revision", "intake_revision_id", "intake_hash",
            "genesis_revision", "genesis_hash", "context_id", "context_revision", "context_hash",
            "website_source", "created_at", "content_hash", "accepted_by", "base_sha", "research_manifest_hash",
            "required_assets", "approved_knowledge", "design_manifest_hash", "quality_report_hash", "planning_hash",
            "design_skill_set_hash", "website_build_profile", "repository_identity",
        }
        if set(value) - allowed:
            raise ContractError("acceptance_manifest contains unsupported fields")
        if value.get("schema_version", ACCEPTANCE_MANIFEST_SCHEMA_VERSION) != ACCEPTANCE_MANIFEST_SCHEMA_VERSION:
            raise ContractError("acceptance_manifest.schema_version is invalid")
        intake_revision = value.get("intake_revision")
        context_revision = value.get("context_revision")
        genesis_revision = value.get("genesis_revision")
        for number, path in (
            (intake_revision, "acceptance_manifest.intake_revision"),
            (genesis_revision, "acceptance_manifest.genesis_revision"),
            (context_revision, "acceptance_manifest.context_revision"),
        ):
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise ContractError(f"{path} is invalid")
        revision_id = value.get("intake_revision_id")
        if revision_id is not None and (isinstance(revision_id, bool) or not isinstance(revision_id, int) or revision_id < 1):
            raise ContractError("acceptance_manifest.intake_revision_id is invalid")
        result = cls(
            manifest_id=_id(value.get("manifest_id"), "acceptance_manifest.manifest_id"),
            incubation_id=_id(value.get("incubation_id"), "acceptance_manifest.incubation_id"),
            accepted_candidate_sha=_hash(value.get("accepted_candidate_sha"), "acceptance_manifest.accepted_candidate_sha", _SHA1_RE),
            accepted_run_id=_id(value.get("accepted_run_id"), "acceptance_manifest.accepted_run_id"),
            accepted_run_hash=_hash(value.get("accepted_run_hash"), "acceptance_manifest.accepted_run_hash", _SHA256_RE),
            intake_session_id=_id(value.get("intake_session_id"), "acceptance_manifest.intake_session_id"),
            intake_revision=intake_revision,
            intake_revision_id=revision_id,
            intake_hash=_hash(value.get("intake_hash"), "acceptance_manifest.intake_hash", _SHA256_RE),
            genesis_revision=genesis_revision,
            genesis_hash=_hash(value.get("genesis_hash"), "acceptance_manifest.genesis_hash", _SHA256_RE),
            context_id=_id(value.get("context_id"), "acceptance_manifest.context_id"),
            context_revision=context_revision,
            context_hash=_hash(value.get("context_hash"), "acceptance_manifest.context_hash", _SHA256_RE),
            website_source=_section(value.get("website_source"), "acceptance_manifest.website_source"),
            created_at=_text(value.get("created_at"), "acceptance_manifest.created_at", maximum=100),
            content_hash=_optional_hash(value.get("content_hash"), "acceptance_manifest.content_hash"),
            accepted_by=_text(value.get("accepted_by"), "acceptance_manifest.accepted_by", maximum=120) or "owner",
            base_sha=_text(value.get("base_sha"), "acceptance_manifest.base_sha", required=False, maximum=64).lower(),
            research_manifest_hash=_optional_hash(value.get("research_manifest_hash"), "acceptance_manifest.research_manifest_hash"),
            required_assets=_list_of_objects(value.get("required_assets"), "acceptance_manifest.required_assets"),
            approved_knowledge=_list_of_objects(value.get("approved_knowledge"), "acceptance_manifest.approved_knowledge"),
            design_manifest_hash=_text(value.get("design_manifest_hash"), "acceptance_manifest.design_manifest_hash", required=False, maximum=64).lower(),
            quality_report_hash=_text(value.get("quality_report_hash"), "acceptance_manifest.quality_report_hash", required=False, maximum=64).lower(),
            planning_hash=_text(value.get("planning_hash"), "acceptance_manifest.planning_hash", required=False, maximum=64).lower(),
            design_skill_set_hash=_text(value.get("design_skill_set_hash"), "acceptance_manifest.design_skill_set_hash", required=False, maximum=64).lower(),
            website_build_profile=_section(value.get("website_build_profile"), "acceptance_manifest.website_build_profile"),
            repository_identity=_section(value.get("repository_identity"), "acceptance_manifest.repository_identity"),
        )
        if result.content_hash is not None and result.content_hash != result.computed_hash:
            raise ContractError("acceptance_manifest.content_hash does not match content")
        return result

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        # The accepted source path is host-local handoff material. It must not
        # become part of the portable customer manifest or its content hash.
        website_source = {
            key: copy.deepcopy(value)
            for key, value in self.website_source.items()
            if key != "source_path"
        }
        result = {
            "schema_version": ACCEPTANCE_MANIFEST_SCHEMA_VERSION,
            "manifest_id": self.manifest_id,
            "incubation_id": self.incubation_id,
            "accepted_candidate_sha": self.accepted_candidate_sha,
            "accepted_run_id": self.accepted_run_id,
            "accepted_run_hash": self.accepted_run_hash,
            "intake_session_id": self.intake_session_id,
            "intake_revision": self.intake_revision,
            "intake_revision_id": self.intake_revision_id,
            "intake_hash": self.intake_hash,
            "genesis_revision": self.genesis_revision,
            "genesis_hash": self.genesis_hash,
            "context_id": self.context_id,
            "context_revision": self.context_revision,
            "context_hash": self.context_hash,
            "website_source": website_source,
            "created_at": self.created_at,
            "accepted_by": self.accepted_by,
            "base_sha": self.base_sha,
            "research_manifest_hash": self.research_manifest_hash,
            "required_assets": copy.deepcopy(list(self.required_assets)),
            "approved_knowledge": copy.deepcopy(list(self.approved_knowledge)),
            "design_manifest_hash": self.design_manifest_hash,
            "quality_report_hash": self.quality_report_hash,
            "planning_hash": self.planning_hash,
            "design_skill_set_hash": self.design_skill_set_hash,
            "website_build_profile": copy.deepcopy(self.website_build_profile),
            "repository_identity": copy.deepcopy(self.repository_identity),
        }
        if include_hash:
            result["content_hash"] = self.content_hash or canonical_hash(result)
        return result

    @property
    def computed_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def accepted_at(self) -> str:
        return self.created_at

    @property
    def candidate_sha(self) -> str:
        return self.accepted_candidate_sha

    @property
    def design_run_id(self) -> str:
        return self.accepted_run_id

    @property
    def customer_context_id(self) -> str:
        return self.context_id

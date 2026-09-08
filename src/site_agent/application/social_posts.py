"""Preparation of Cicero social posts and owner-review artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..core.contracts import (
    ActionPriority,
    ActionRequirement,
    ApprovalRequest,
    Artifact,
    ArtifactKind,
    EffectClass,
    OwnerAction,
)
from ..hands.cicero import CiceroClient, CiceroClientError, CiceroOperation
from .actions import OwnerActionService
from .approvals import ApprovalService
from .capabilities import CapabilityRegistry


class SocialPostError(RuntimeError):
    pass


class SocialBriefError(SocialPostError):
    pass


class SocialIdempotencyConflict(SocialPostError):
    pass


_FORMATS = {"single", "carousel", "diaporama", "video"}
_FIELDS = {
    "goal", "audience", "brief", "caption", "visual_message", "format", "language",
    "media_names", "animated", "source_context", "constraints",
}


def _text(value: Any, field: str, *, required: bool = False, limit: int = 5000) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise SocialBriefError(f"{field} is required")
    if len(result) > limit:
        raise SocialBriefError(f"{field} exceeds {limit} characters")
    return result


def _safe_media_name(value: Any) -> str:
    name = str(value or "")
    if not name or os.path.basename(name) != name or "/" in name or "\\" in name or ".." in name:
        raise SocialBriefError("media_names must contain safe basenames")
    return name


@dataclass(frozen=True)
class SocialPostBrief:
    """Provider-neutral, validated editorial input for one social post."""

    goal: str
    audience: str
    brief: str
    caption: str
    visual_message: str
    format: str | None = None
    language: str | None = None
    media_names: tuple[str, ...] = ()
    animated: bool = False
    source_context: tuple[dict[str, str], ...] = ()
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "goal", _text(self.goal, "goal", limit=2000))
        object.__setattr__(self, "audience", _text(self.audience, "audience", limit=1000))
        object.__setattr__(self, "brief", _text(self.brief, "brief", required=True, limit=5000))
        object.__setattr__(self, "caption", _text(self.caption, "caption", required=True, limit=20000))
        object.__setattr__(self, "visual_message", _text(self.visual_message, "visual_message", required=True, limit=2000))
        fmt = _text(self.format, "format", limit=32) if self.format else None
        if fmt is not None and fmt not in _FORMATS:
            raise SocialBriefError("format must be one of: single, carousel, diaporama, video")
        object.__setattr__(self, "format", fmt)
        language = _text(self.language, "language", limit=32) if self.language else None
        object.__setattr__(self, "language", language)
        media = tuple(_safe_media_name(name) for name in (self.media_names or ()))
        if len(media) > 20:
            raise SocialBriefError("media_names must contain at most 20 items")
        object.__setattr__(self, "media_names", media)
        if not isinstance(self.animated, bool):
            raise SocialBriefError("animated must be a boolean")
        sources = []
        for source in self.source_context or ():
            if not isinstance(source, Mapping):
                raise SocialBriefError("source_context entries must be objects")
            if set(source) != {"title", "url"}:
                raise SocialBriefError("source_context entries require only title and url")
            title = _text(source.get("title"), "source title", required=True, limit=300)
            url = _text(source.get("url"), "source url", required=True, limit=2000)
            if not url.startswith(("http://", "https://")):
                raise SocialBriefError("source url must be HTTP(S)")
            sources.append({"title": title, "url": url})
        if len(sources) > 20:
            raise SocialBriefError("source_context must contain at most 20 items")
        object.__setattr__(self, "source_context", tuple(sources))
        avoid = tuple(_text(item, "constraints.avoid", required=True, limit=300) for item in (self.constraints or ()))
        if len(avoid) > 20:
            raise SocialBriefError("constraints.avoid must contain at most 20 items")
        object.__setattr__(self, "constraints", avoid)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SocialPostBrief":
        if not isinstance(value, Mapping):
            raise SocialBriefError("social brief must be an object")
        unknown = set(value) - _FIELDS
        if unknown:
            raise SocialBriefError(f"unknown social brief fields: {', '.join(sorted(map(str, unknown)))}")
        constraints = value.get("constraints") or {}
        if not isinstance(constraints, Mapping) or set(constraints) - {"avoid"}:
            raise SocialBriefError("constraints must contain only avoid")
        return cls(
            goal=value.get("goal", ""),
            audience=value.get("audience", ""),
            brief=value.get("brief", ""),
            caption=value.get("caption", ""),
            visual_message=value.get("visual_message", ""),
            format=value.get("format"),
            language=value.get("language"),
            media_names=tuple(value.get("media_names") or ()),
            animated=value.get("animated", False),
            source_context=tuple(value.get("source_context") or ()),
            constraints=tuple(constraints.get("avoid") or ()),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "audience": self.audience,
            "brief": self.brief,
            "caption": self.caption,
            "visual_message": self.visual_message,
            "format": self.format,
            "language": self.language,
            "media_names": list(self.media_names),
            "animated": self.animated,
            "source_context": [dict(source) for source in self.source_context],
            "constraints": {"avoid": list(self.constraints)},
        }


@dataclass(frozen=True)
class SocialPreparationResult:
    artifact: Artifact
    approval: ApprovalRequest
    action: OwnerAction
    provider_operation_id: str


def approval_hash(provider_id: str, provider_post_id: str, provider_content_hash: str, target_ids: list[str] | tuple[str, ...] = ()) -> str:
    manifest = {
        "schema_version": 1,
        "provider_id": provider_id,
        "post_id": str(provider_post_id),
        "provider_content_hash": provider_content_hash,
        "target_ids": sorted(str(target_id) for target_id in target_ids),
    }
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _request_hash(payload: SocialPostBrief) -> str:
    encoded = json.dumps(payload.to_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _derived_key(payload: SocialPostBrief, action_id: int | None, job_id: int | None) -> str:
    identity = f"{action_id or 0}:{job_id or 0}:{_request_hash(payload)}"
    return f"site-agent:social-post:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


class SocialPostService:
    def __init__(
        self,
        memory,
        client: CiceroClient,
        *,
        actions: OwnerActionService | None = None,
        approvals: ApprovalService | None = None,
        capabilities: CapabilityRegistry | None = None,
        poll_interval_seconds: float = 2.0,
        preparation_timeout_seconds: float = 600.0,
    ) -> None:
        self.memory = memory
        self.client = client
        self.actions = actions or OwnerActionService(memory)
        self.approvals = approvals or ApprovalService(memory, actions=self.actions, capabilities=capabilities)
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        self.preparation_timeout_seconds = max(0.1, float(preparation_timeout_seconds))

    def prepare(
        self,
        brief: SocialPostBrief | Mapping[str, Any],
        *,
        action_id: int | None = None,
        job_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> SocialPreparationResult:
        if not isinstance(brief, SocialPostBrief):
            brief = SocialPostBrief.from_mapping(brief)
        key = str(idempotency_key or _derived_key(brief, action_id, job_id)).strip()
        if not key or len(key) > 255:
            raise SocialPostError("idempotency key must be between 1 and 255 characters")
        digest = _request_hash(brief)
        row = self.memory.get_social_preparation(key)
        if row is not None:
            if row["request_hash"] != digest:
                raise SocialIdempotencyConflict("idempotency key was already used for another brief")
        else:
            try:
                row = self.memory.create_social_preparation(
                    key, digest, json.dumps(brief.to_payload(), ensure_ascii=False, sort_keys=True),
                    action_id=action_id, job_id=job_id,
                )
            except sqlite3.IntegrityError:
                row = self.memory.get_social_preparation(key)
                if row is None:
                    raise SocialPostError("could not reserve social preparation")
                if row["request_hash"] != digest:
                    raise SocialIdempotencyConflict("idempotency key was already used for another brief")
        existing_result = self._existing_result(row)
        if existing_result is not None:
            return existing_result
        try:
            return self._resume(row, brief, key)
        except SocialPostError as exc:
            self.memory.update_social_preparation(row["id"], status="failed", error=str(exc)[:500])
            raise
        except CiceroClientError as exc:
            self.memory.update_social_preparation(row["id"], status="failed", error=str(exc)[:500])
            raise SocialPostError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — local failures are safe and resumable
            self.memory.update_social_preparation(row["id"], status="failed", error="local social preparation failed")
            raise SocialPostError("local social preparation failed") from exc

    def _existing_result(self, row: dict[str, Any]) -> SocialPreparationResult | None:
        if not (row.get("artifact_id") and row.get("approval_id") and row.get("action_id")):
            return None
        artifact = self.memory.get_artifact(row["artifact_id"])
        approval = self.memory.get_approval_request(row["approval_id"])
        action = self.actions.get(row["action_id"])
        if artifact is None or approval is None or action is None or not row.get("provider_operation_id"):
            return None
        return SocialPreparationResult(artifact, approval, action, str(row["provider_operation_id"]))

    def _resume(self, row: dict[str, Any], brief: SocialPostBrief, key: str) -> SocialPreparationResult:
        provider_operation_id = row.get("provider_operation_id")
        if not provider_operation_id:
            operation = self.client.prepare(brief.to_payload(), key)
            provider_operation_id = operation.operation_id
            self.memory.update_social_preparation(
                row["id"], provider_operation_id=provider_operation_id, status="running", error=None,
            )
        operation = self.client.wait_operation(
            provider_operation_id,
            poll_interval_seconds=self.poll_interval_seconds,
            timeout_seconds=self.preparation_timeout_seconds,
        )
        if operation.status != "completed" or not operation.artifact:
            message = ((operation.error or {}).get("message") if operation.error else None) or "Cicero preparation did not complete"
            self.memory.update_social_preparation(row["id"], status="failed", error=str(message)[:500])
            raise SocialPostError(str(message))

        provider = self._provider_artifact(operation, brief)
        self.memory.update_social_preparation(
            row["id"], provider_post_id=provider["provider_post_id"], status="finalizing", error=None,
        )
        artifact = self._ensure_artifact(row, provider, brief)
        action = self._ensure_action(row, artifact, provider, key)
        approval = self._ensure_approval(row, artifact, action)
        self.memory.update_social_preparation(
            row["id"], approval_id=approval.approval_id, action_id=action.id,
            status="completed", error=None,
        )
        return SocialPreparationResult(artifact, approval, action, provider_operation_id)

    def _provider_artifact(self, operation: CiceroOperation, brief: SocialPostBrief) -> dict[str, Any]:
        data = dict(operation.artifact or {})
        post_id = str(data.get("post_id") or "").strip()
        if not post_id.isdigit() or int(post_id) <= 0:
            raise SocialPostError("Cicero returned an invalid post id")
        try:
            current = self.client.post(post_id)
        except CiceroClientError:
            current = data
        if isinstance(current, Mapping) and current.get("content_hash"):
            data = dict(current)
        content_hash = str(data.get("content_hash") or "")
        if not content_hash.startswith("sha256:") or len(content_hash) > 200:
            raise SocialPostError("Cicero returned an invalid content hash")
        caption = data.get("caption")
        if not isinstance(caption, str) or caption != brief.caption:
            raise SocialPostError("Cicero did not preserve the supplied caption")
        fmt = str(data.get("format") or "")
        if fmt not in _FORMATS:
            raise SocialPostError("Cicero returned an invalid post format")
        previews = []
        for item in data.get("preview_assets") or []:
            if not isinstance(item, Mapping):
                continue
            name = _safe_media_name(item.get("name"))
            media_type = _text(item.get("media_type"), "preview media type", required=True, limit=120)
            previews.append({"name": name, "media_type": media_type})
        if not previews:
            raise SocialPostError("Cicero returned no preview assets")
        return {
            "provider_post_id": post_id,
            "provider_content_hash": content_hash,
            "caption": caption,
            "format": fmt,
            "preview_assets": previews,
            "sources": [dict(source) for source in brief.source_context],
        }

    def _ensure_artifact(self, row: dict[str, Any], provider: dict[str, Any], brief: SocialPostBrief) -> Artifact:
        if row.get("artifact_id"):
            artifact = self.memory.get_artifact(row["artifact_id"])
            if artifact is not None:
                stored_hash = artifact.preview_data.get("provider_content_hash")
                if stored_hash != provider["provider_content_hash"]:
                    raise SocialPostError("Cicero content changed during preparation")
                return artifact
        local_hash = approval_hash("cicero", provider["provider_post_id"], provider["provider_content_hash"])
        artifact = Artifact(
            kind=ArtifactKind.SOCIAL_POST,
            title=f"Social post: {brief.visual_message[:120]}",
            summary=f"{provider['format'].capitalize()} prepared by Cicero for owner review.",
            renderer="social_post",
            capability_id="social.post.publish",
            provider_id="cicero",
            content_hash=local_hash,
            preview_data={
                "text": provider["caption"],
                "format": provider["format"],
                "provider_post_id": provider["provider_post_id"],
                "provider_content_hash": provider["provider_content_hash"],
                "target_ids": [],
                "preview_assets": provider["preview_assets"],
                "sources": provider["sources"],
            },
        )
        return self.memory.create_social_artifact(row["id"], artifact)

    def _ensure_action(self, row: dict[str, Any], artifact: Artifact, provider: dict[str, Any], key: str) -> OwnerAction:
        if row.get("action_id"):
            action = self.actions.get(row["action_id"])
            if action is not None:
                return action
        dedupe_key = f"social-post:{key}"
        existing = self.memory.find_owner_action(dedupe_key, include_terminal=True)
        if existing is not None:
            action = existing
        else:
            action = self.actions.create(
                OwnerAction(
                    capability_id="social.post.publish",
                    provider_id="cicero",
                    title=artifact.title,
                    summary="Review the rendered social post, caption, sources, and visual assets before any publication.",
                    action_label="Review social post",
                    priority=ActionPriority.NORMAL,
                    requirement=ActionRequirement.OWNER_DECISION,
                    source_ref=f"cicero:post:{provider['provider_post_id']}",
                    dedupe_key=dedupe_key,
                    artifact_id=artifact.artifact_id,
                    payload={"provider_post_id": provider["provider_post_id"], "format": provider["format"]},
                )
            )
        self.memory.update_social_preparation(row["id"], action_id=action.id)
        return action

    def _ensure_approval(self, row: dict[str, Any], artifact: Artifact, action: OwnerAction) -> ApprovalRequest:
        if row.get("approval_id"):
            approval = self.memory.get_approval_request(row["approval_id"])
            if approval is not None:
                return approval
        approval = next(
            (
                item for item in self.memory.list_approval_requests(limit=500)
                if item.artifact_id == artifact.artifact_id
            ),
            None,
        )
        if approval is None:
            approval = self.approvals.create(
                artifact,
                owner_action_label="Review social post",
                effect_class=EffectClass.EXTERNAL_MUTATION,
                action_id=action.id,
            )
        self.memory.update_social_preparation(row["id"], approval_id=approval.approval_id)
        return approval

    def asset(self, artifact_id: int, filename: str) -> tuple[bytes, str]:
        artifact = self.memory.get_artifact(artifact_id)
        if artifact is None or artifact.kind is not ArtifactKind.SOCIAL_POST:
            raise SocialPostError("social artifact not found")
        provider_id = str(artifact.preview_data.get("provider_post_id") or "")
        allowed = {
            item.get("name") for item in artifact.preview_data.get("preview_assets") or []
            if isinstance(item, Mapping)
        }
        if filename not in allowed:
            raise SocialPostError("asset is not part of this social artifact")
        if not provider_id.isdigit() or int(provider_id) <= 0:
            raise SocialPostError("social artifact provider id is invalid")
        return self.client.asset(provider_id, filename)


__all__ = [
    "SocialBriefError",
    "SocialIdempotencyConflict",
    "SocialPostBrief",
    "SocialPostError",
    "SocialPostService",
    "SocialPreparationResult",
    "approval_hash",
]

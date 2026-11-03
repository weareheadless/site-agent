"""Publish the exact owner-reviewed Payload revision set for one candidate.

The reviewed effect set is the immutable receipt produced by the design run
(``payload_revision_manifest``). Publication must consume those exact
revisions: never the current draft, never a newer revision, and never a
different locale. The whole set is verified before the first write, so a stale
revision cannot leave a partially published site; a destination that already
exposes the exact reviewed revision is recorded as satisfied instead of
rewritten.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class PayloadPublicationError(RuntimeError):
    """The reviewed Payload effect set could not be published exactly."""


def _effect_identity(effect: Mapping[str, Any]) -> str:
    return f"{effect['kind']}:{effect['target']}:{effect['document_id']}:{effect['locale']}"


def _published(gateway: Any, effect: Mapping[str, Any]) -> dict[str, Any]:
    if effect["kind"] == "collection":
        return gateway.read(
            effect["target"],
            identifier=effect["document_id"],
            identifier_kind="id",
            draft=False,
            locale=effect["locale"],
        )
    return gateway.read_global(effect["target"], draft=False, locale=effect["locale"])


def _draft(gateway: Any, effect: Mapping[str, Any]) -> dict[str, Any]:
    if effect["kind"] == "collection":
        return gateway.read(
            effect["target"],
            identifier=effect["document_id"],
            identifier_kind="id",
            draft=True,
            locale=effect["locale"],
        )
    return gateway.read_global(effect["target"], draft=True, locale=effect["locale"])


def publish_reviewed_effects(
    gateway: Any,
    effects: Sequence[Mapping[str, Any]],
    *,
    revision_set_hash: str = "",
) -> dict[str, Any]:
    """Publish one exact reviewed revision per destination and locale."""
    if not effects:
        raise PayloadPublicationError("the approved candidate has no reviewed Payload effects to publish")
    ordered = sorted(
        effects,
        key=lambda item: (
            0 if item.get("kind") == "collection" else 1,
            str(item.get("target") or ""),
            str(item.get("document_id") or ""),
            str(item.get("locale") or ""),
        ),
    )
    # Phase one: prove the whole reviewed set is still publishable. Nothing is
    # written until every destination has been checked.
    pending: list[Mapping[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for effect in ordered:
        kind = str(effect.get("kind") or "")
        if kind not in {"collection", "global"}:
            raise PayloadPublicationError("the reviewed Payload effect set contains an unsupported destination")
        revision = str(effect.get("revision") or "")
        if not revision.startswith("sha256:"):
            raise PayloadPublicationError("a reviewed Payload effect has no exact saved revision")
        identity = _effect_identity(effect)
        try:
            current = _published(gateway, effect)
            if current.get("_helloadaRevision") == revision and current.get("_status") == "published":
                receipts.append({"effect": identity, "revision": revision, "state": "already-published"})
                continue
            draft = _draft(gateway, effect)
        except Exception as exc:  # noqa: BLE001 - keep the publication boundary bounded
            raise PayloadPublicationError(
                f"the reviewed Payload revision for {identity} could not be read: {str(exc)[:300]}"
            ) from exc
        if draft.get("_helloadaRevision") != revision:
            raise PayloadPublicationError(
                f"the reviewed Payload draft for {identity} changed before publication"
            )
        pending.append(effect)
    # Phase two: publish only the verified revisions and require each exact
    # published read-back to match the approved identity.
    for effect in pending:
        kind = str(effect["kind"])
        revision = str(effect["revision"])
        identity = _effect_identity(effect)
        try:
            if kind == "collection":
                published = gateway.publish(
                    effect["target"],
                    str(effect["document_id"]),
                    locale=str(effect["locale"]),
                    expected_hash=revision,
                    expected_fields=list(effect.get("fields") or []),
                )
            else:
                published = gateway.publish_global(
                    str(effect["target"]),
                    locale=str(effect["locale"]),
                    expected_hash=revision,
                )
        except Exception as exc:  # noqa: BLE001 - bounded, actionable diagnostic
            raise PayloadPublicationError(
                f"the reviewed Payload revision for {identity} could not be published: {str(exc)[:300]}"
            ) from exc
        if published.get("_helloadaRevision") != revision:
            raise PayloadPublicationError(
                f"Payload published a different revision for {identity} than the owner approved"
            )
        receipts.append({"effect": identity, "revision": revision, "state": "published"})
    receipts.sort(key=lambda item: item["effect"])
    return {
        "revisionSetHash": str(revision_set_hash or ""),
        "effects": receipts,
        "published": sum(1 for item in receipts if item["state"] == "published"),
        "satisfied": sum(1 for item in receipts if item["state"] == "already-published"),
    }


__all__ = ["PayloadPublicationError", "publish_reviewed_effects"]

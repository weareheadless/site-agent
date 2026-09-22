"""Typed, idempotent import of one accepted incubation into a customer instance."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import yaml

from ..core.contracts import ContractError, utc_now
from ..core.customer_context_contracts import AcceptanceManifest, CustomerContextSnapshot
from ..core.design_contracts import canonical_hash, canonical_json
from ..core.incubation_contracts import (
    CustomerAdaGenesis,
    IncubationDeduction,
    IncubationActivity,
    IncubationInsight,
    IncubationRecord,
    ProvisioningBundle,
    ProvisioningReceipt,
    ResearchFinding,
    ResearchRequest,
    ResearchSource,
    SourceTrustState,
    SubscriptionState,
)
from ..core.intake_ada_store import IntakeAdaStore
from ..core.memory import SCHEMA_VERSION, Memory
from ..hands.local_media import LocalMediaStore
from ..hands.site_build import NEXT_REACT_PROFILE
from .media import MediaService
from .customer_context import CustomerContextService, design_run_content_hash


class ProvisioningServiceError(ValueError):
    """The accepted incubation cannot be imported safely."""


class CustomerGenesisImporter:
    """Import a frozen bundle through the destination Memory contract."""

    def import_bundle(
        self,
        target: Memory,
        bundle: ProvisioningBundle,
        *,
        source_media: MediaService | None = None,
        target_media: MediaService | None = None,
    ) -> dict[str, int]:
        import_id = "import_" + hashlib.sha256(bundle.integrity["content_hash"].encode("utf-8")).hexdigest()[:32]
        marker = target.kv_get("provisioning_bundle_hash")
        if marker:
            if marker != bundle.integrity["content_hash"]:
                raise ProvisioningServiceError("customer memory was initialized from a different bundle")
            counts = target.kv_get("provisioning_import_counts", {})
            return {str(key): int(value) for key, value in (counts.items() if isinstance(counts, Mapping) else [])}

        progress = target.get_provisioning_import(import_id)
        progress_detail = dict(progress.get("detail") or {}) if progress else {}
        media_maps = {
            int(item["source_id"]): int(item["destination_id"])
            for item in target.list_provisioning_id_maps(import_id, "media_asset")
            if str(item.get("source_id") or "").isdigit() and str(item.get("destination_id") or "").isdigit()
        }
        missing_media_maps = any(
            str(binding.get("asset_id") or "") not in {str(key) for key in media_maps}
            for binding in bundle.assets
        )
        if missing_media_maps and (source_media is None or target_media is None):
            raise ProvisioningServiceError("media transfer is unavailable for this incubation")

        counts = {
            "conversations": 0,
            "messages": 0,
            "intake_revisions": 0,
            "research_sources": 0,
            "research_findings": 0,
            "research_requests": 0,
            "research_insights": 0,
            "research_deductions": 0,
            "assets": 0,
            "genesis_revisions": 0,
            "design_history": 0,
            "owner_feedback": 0,
            "activity": 0,
            "unknowns": 0,
            "customer_context": 0,
            "acceptance_manifest": 0,
        }
        progress_detail.setdefault("incubation_id", bundle.incubation_id)

        def checkpoint(stage: str, **updates: Any) -> None:
            progress_detail.update(updates)
            target.save_provisioning_import(
                import_id,
                bundle.bundle_id,
                bundle.integrity["content_hash"],
                stage,
                progress_detail,
            )

        if progress is None:
            checkpoint("started")
        if bundle.customer_context:
            context = CustomerContextSnapshot.from_dict(bundle.customer_context)
            target.save_customer_context(context, accepted=True)
            counts["customer_context"] = 1
            checkpoint("context_imported")
        if bundle.acceptance_manifest:
            manifest = AcceptanceManifest.from_dict(bundle.acceptance_manifest)
            target.save_acceptance_manifest(manifest)
            counts["acceptance_manifest"] = 1
            checkpoint("manifest_imported")
        asset_ids: dict[int, int] = {}
        for binding in bundle.assets:
            try:
                source_asset_id = int(binding.get("asset_id"))
            except (TypeError, ValueError) as exc:
                raise ProvisioningServiceError("bundle contains an invalid media binding") from exc
            if source_asset_id in media_maps:
                if target.get_media_asset(media_maps[source_asset_id]) is None:
                    raise ProvisioningServiceError("media checkpoint references a missing destination asset")
                asset_ids[source_asset_id] = media_maps[source_asset_id]
            else:
                try:
                    asset, objects = source_media.export_asset(source_asset_id)  # type: ignore[union-attr]
                    imported = target_media.import_asset(asset, objects)  # type: ignore[union-attr]
                except Exception as exc:
                    if isinstance(exc, ProvisioningServiceError):
                        raise
                    raise ProvisioningServiceError("approved media could not be transferred") from exc
                asset_ids[source_asset_id] = imported.asset_id
                media_maps[source_asset_id] = imported.asset_id
                target.save_provisioning_id_map(import_id, "media_asset", str(source_asset_id), str(imported.asset_id))
            counts["assets"] += 1
            checkpoint("media_transferred", media_assets_imported=counts["assets"])
        for knowledge in (bundle.customer_context.get("knowledge") or []) if bundle.customer_context else []:
            source_asset_id = knowledge.get("asset_id")
            if source_asset_id is None or int(source_asset_id) not in asset_ids:
                raise ProvisioningServiceError("approved business knowledge references an unimported asset")
            source_knowledge_id = str(knowledge.get("id") or "")
            if not source_knowledge_id:
                source_knowledge_id = "content_" + hashlib.sha256(
                    canonical_json({"asset_id": source_asset_id, "body": knowledge.get("body") or ""}).encode("utf-8")
                ).hexdigest()[:32]
            knowledge_maps = {
                item["source_id"]: int(item["destination_id"])
                for item in target.list_provisioning_id_maps(import_id, "business_knowledge")
            }
            imported_knowledge = target.get_business_knowledge(knowledge_maps[source_knowledge_id]) if source_knowledge_id in knowledge_maps else None
            if imported_knowledge is None:
                created = target.create_business_knowledge(asset_ids[int(source_asset_id)], str(knowledge.get("body") or ""))
                imported_knowledge = target.update_business_knowledge(
                    int(created["id"]),
                    status="approved",
                    decided_ts=str(knowledge.get("decided_ts") or utc_now()),
                ) or created
                target.save_provisioning_id_map(import_id, "business_knowledge", source_knowledge_id, str(imported_knowledge["id"]))
            counts["business_knowledge"] = counts.get("business_knowledge", 0) + 1
            checkpoint("knowledge_imported", knowledge_imported=counts["business_knowledge"])
        conversation_id = progress_detail.get("conversation_id")
        if conversation_id is None:
            conversation_id = target.create_conversation("Imported incubation", timestamp=_first_timestamp(bundle.conversation))
            checkpoint("conversation_created", conversation_id=conversation_id, messages_imported=0)
        else:
            try:
                conversation_id = int(conversation_id)
            except (TypeError, ValueError) as exc:
                raise ProvisioningServiceError("provisioning checkpoint contains an invalid conversation") from exc
        counts["conversations"] = 1
        intake = bundle.intake_revision
        if isinstance(intake.get("site_intake"), Mapping) and intake.get("session_id"):
            source_session_id = str(intake.get("session_id"))
            imported_session_id = "imported-" + hashlib.sha256(source_session_id.encode("utf-8")).hexdigest()[:32]
            imported_assets = []
            for binding in bundle.assets:
                try:
                    source_asset_id = int(binding.get("asset_id"))
                except (TypeError, ValueError) as exc:
                    raise ProvisioningServiceError("bundle contains an invalid intake asset binding") from exc
                if source_asset_id not in asset_ids:
                    raise ProvisioningServiceError("an accepted intake asset was not imported")
                imported_assets.append({
                    "asset_id": asset_ids[source_asset_id],
                    "position": binding.get("position", 0),
                    "usage": binding.get("usage") or "undecided",
                    "reference_aspects": binding.get("reference_aspects") or [],
                    "owner_note": binding.get("owner_note") or "",
                })
            target.import_confirmed_design_intake(
                imported_session_id,
                dict(intake["site_intake"]),
                source_session_id=source_session_id,
                source_revision=int(intake.get("revision") or 0),
                source_revision_id=intake.get("revision_id"),
                source_draft_hash=str(intake.get("draft_hash") or ""),
                site_intake_hash=str(intake.get("site_intake_hash") or ""),
                summary={"source_design_run_id": intake.get("design_run_id")},
                assets=imported_assets,
                conversation_id=conversation_id,
            )
            counts["intake_revisions"] = 1
        messages_imported = int(progress_detail.get("messages_imported") or 0)
        if messages_imported < 0 or messages_imported > len(bundle.conversation):
            raise ProvisioningServiceError("provisioning checkpoint contains an invalid message count")
        for item in bundle.conversation[messages_imported:]:
            target.add_message(
                conversation_id,
                str(item.get("role") or "user"),
                str(item.get("text") or "")[:20_000],
                attachments=_attachments(item.get("attachments"), asset_ids),
                timestamp=str(item.get("ts") or utc_now()),
            )
            counts["messages"] += 1
            messages_imported += 1
            checkpoint("conversation_imported", conversation_id=conversation_id, messages_imported=messages_imported)
        counts["messages"] = messages_imported
        for source in bundle.research_sources:
            source_id = str(source.get("source_id") or "")
            target.save_research_source(ResearchSource.from_dict({
                key: source[key]
                for key in (
                    "source_id", "kind", "url", "feed_url", "title", "discovered_by",
                    "language",
                    "trust_state", "ongoing_subscription", "fetched_at", "content_hash",
                )
            }))
            target.record_observation(
                "research_source",
                _json_text(source, 4_000),
                {"source_id": source_id, "trust_state": source.get("trust_state"), "provenance": "incubation"},
            )
            counts["research_sources"] += 1
        for finding in bundle.research_findings:
            target.save_research_finding(ResearchFinding.from_dict(finding))
            target.record_observation(
                "research",
                str(finding.get("summary") or "")[:4_000],
                {"finding_id": finding.get("finding_id"), "source_id": finding.get("source_id"), "confidence": finding.get("confidence", 0.0)},
                timestamp=str(finding.get("published_at") or utc_now()),
            )
            counts["research_findings"] += 1
        genesis_history = list(bundle.genesis_revisions) or [{
            "genesis": bundle.genesis_revision,
            "revision": bundle.genesis_revision.get("revision"),
            "source_kind": "provisioning_import",
            "accepted": True,
        }]
        expected_revision = 0
        for index, history_item in enumerate(genesis_history, 1):
            raw_genesis = history_item.get("genesis") if isinstance(history_item, Mapping) else None
            raw_genesis = raw_genesis if isinstance(raw_genesis, Mapping) else history_item
            genesis = CustomerAdaGenesis.from_dict(raw_genesis)
            imported_revision = int(history_item.get("revision") or genesis.revision) if isinstance(history_item, Mapping) else genesis.revision
            if imported_revision != expected_revision + 1:
                raise ProvisioningServiceError("genesis history is not a contiguous immutable sequence")
            existing_genesis = target.get_customer_genesis_revision(imported_revision)
            if existing_genesis is not None:
                if existing_genesis["genesis"].content_hash != genesis.content_hash:
                    raise ProvisioningServiceError("genesis checkpoint references different content")
            else:
                current_genesis = target.get_customer_genesis_revision()
                current_revision = int(current_genesis.get("revision") or 0) if current_genesis else 0
                if current_revision != expected_revision:
                    raise ProvisioningServiceError("genesis checkpoint is not contiguous")
                target.save_customer_genesis_revision(
                    replace(genesis, revision=imported_revision),
                    source_kind="provisioning_import",
                    expected_revision=current_revision,
                    accepted=index == len(genesis_history),
                )
            target.record_observation(
                "customer_genesis",
                _json_text(raw_genesis, 20_000),
                {"revision": genesis.revision, "provenance": "owner-approved incubation"},
            )
            expected_revision = imported_revision
            counts["genesis_revisions"] += 1
            checkpoint("genesis_imported", genesis_revisions_imported=counts["genesis_revisions"])
        for request in bundle.research_requests:
            target.save_research_request(ResearchRequest.from_dict(request))
            counts["research_requests"] += 1
        for insight in bundle.research_insights:
            stored = target.save_incubation_insight(IncubationInsight.from_dict(insight))
            target.record_observation(
                "research_insight",
                str(stored.get("summary") or "")[:4_000],
                {"insight_id": stored.get("insight_id"), "provenance": "incubation"},
            )
            counts["research_insights"] += 1
        for deduction in bundle.research_deductions:
            target.save_incubation_deduction(IncubationDeduction.from_dict(deduction))
            counts["research_deductions"] += 1
        for run in bundle.design_history:
            target.record_observation(
                "design_lineage",
                _json_text({
                    "run_id": run.get("run_id"),
                    "status": run.get("status"),
                    "candidate_sha": run.get("candidate_sha"),
                    "operation_kind": run.get("operation_kind"),
                }, 4_000),
                {"source": "incubation", "run_id": run.get("run_id")},
            )
            counts["design_history"] += 1
        for feedback in bundle.owner_feedback:
            target.record_observation(
                "owner_feedback",
                str(feedback.get("notes") or feedback.get("message") or "")[:4_000],
                {"kind": feedback.get("kind"), "run_id": feedback.get("run_id"), "provenance": "owner"},
            )
            counts["owner_feedback"] += 1
        for activity in bundle.activity:
            payload = {
                key: value
                for key, value in activity.items()
                if key != "id"
            }
            for key in ("conversation_id", "message_id", "chat_job_id", "intake_session_id", "design_run_id"):
                payload[key] = None
            target.append_incubation_activity(IncubationActivity.from_dict(payload))
            counts["activity"] += 1
        for unknown in bundle.unknowns:
            target.record_observation("open_question", _json_text(unknown, 2_000), {"provenance": "incubation"})
            counts["unknowns"] += 1
        target.record_action(
            "provisioned_from_incubation",
            json.dumps({"incubation_id": bundle.incubation_id, "bundle_id": bundle.bundle_id, "bundle_hash": bundle.integrity["content_hash"]}, separators=(",", ":")),
        )
        target.kv_set("provisioning_import_counts", counts)
        target.kv_set("provisioning_accepted_candidate_sha", bundle.accepted_candidate_sha)
        target.kv_set("provisioning_prohibited_claims", list(bundle.prohibited_claims))
        target.kv_set("provisioning_design_skill_set", bundle.design_skill_set)
        if bundle.acceptance_manifest:
            target.kv_set("provisioning_website_commit", bundle.accepted_candidate_sha)
            target.kv_set("provisioning_website_path", "site")
            target.save_website_handoff_receipt(
                "website_" + hashlib.sha256(bundle.accepted_candidate_sha.encode("utf-8")).hexdigest()[:32],
                str(bundle.acceptance_manifest.get("manifest_id") or ""),
                bundle.accepted_candidate_sha,
                "git-commit:" + bundle.accepted_candidate_sha,
                "site",
                verified=True,
                detail={"bundle_id": bundle.bundle_id},
            )
        if bundle.customer_context:
            target.kv_set("provisioning_context_id", bundle.customer_context.get("context_id"))
            target.kv_set("provisioning_context_hash", bundle.customer_context.get("content_hash"))
        if bundle.acceptance_manifest:
            target.kv_set("provisioning_acceptance_manifest_id", bundle.acceptance_manifest.get("manifest_id"))
            target.kv_set("provisioning_acceptance_manifest_hash", bundle.acceptance_manifest.get("content_hash"))
        checkpoint("completed", counts=counts)
        target.kv_set("provisioning_bundle_hash", bundle.integrity["content_hash"])
        return counts


class ProvisioningBundleService:
    """Freeze all customer-scoped evidence into one immutable bundle."""

    def __init__(self, memory: Memory, record: IncubationRecord) -> None:
        self.memory = memory
        self.record = record

    def freeze(self, request_id: str) -> ProvisioningBundle:
        if self.record.status != "accepted":
            raise ProvisioningServiceError("incubation must be accepted before provisioning")
        if not self.record.accepted_candidate_sha:
            raise ProvisioningServiceError("accepted candidate SHA is missing")
        manifest_record = (
            self.memory.get_acceptance_manifest(self.record.acceptance_manifest_id)
            if self.record.acceptance_manifest_id
            else None
        )
        manifest = manifest_record.get("manifest") if manifest_record else None
        run = self.memory.get_design_run(self.record.accepted_run_id) if self.record.accepted_run_id else None
        if manifest is not None:
            if not isinstance(manifest, AcceptanceManifest):
                raise ProvisioningServiceError("acceptance manifest is invalid")
            if manifest.accepted_candidate_sha != self.record.accepted_candidate_sha:
                raise ProvisioningServiceError("acceptance manifest candidate does not match the registry")
            run = self.memory.get_design_run(manifest.accepted_run_id)
            if run is None or design_run_content_hash(run) != manifest.accepted_run_hash:
                raise ProvisioningServiceError("accepted design run no longer matches its manifest")
        sessions = self.memory.list_design_intake_sessions(limit=500)
        if not sessions:
            raise ProvisioningServiceError("confirmed intake is missing")
        session = next(
            (item for item in sessions if run is not None and item.get("session_id") == run.get("intake_session_id")),
            sessions[0],
        )
        revisions = self.memory.list_design_intake_revisions(session["session_id"], limit=500)
        confirmed = None
        if manifest is not None:
            confirmed = next(
                (
                    item for item in revisions
                    if item.get("id") == manifest.intake_revision_id
                    and str(item.get("site_intake_hash") or "") == manifest.intake_hash
                ),
                None,
            )
        if confirmed is None and run is not None:
            confirmed = next(
                (
                    item for item in revisions
                    if item.get("id") == run.get("intake_revision_id")
                    and item.get("site_intake")
                ),
                None,
            )
        if confirmed is None:
            confirmed = next((item for item in reversed(revisions) if item.get("site_intake")), None)
        genesis_revision = manifest.genesis_revision if manifest is not None else None
        genesis = self.memory.get_customer_genesis_revision(genesis_revision)
        if confirmed is None or genesis is None:
            raise ProvisioningServiceError("accepted incubation history is incomplete")
        if run is None:
            site_intake = confirmed.get("site_intake") if isinstance(confirmed.get("site_intake"), Mapping) else {}
            run = {
                "run_id": "legacy_" + self.record.accepted_candidate_sha[:32],
                "status": "ready_for_review",
                "candidate_sha": self.record.accepted_candidate_sha,
                "intake_session_id": session["session_id"],
                "intake_revision_id": confirmed.get("id"),
                "intake_json": copy.deepcopy(site_intake),
                "intake_hash": canonical_hash(site_intake),
                "candidate_ref": "",
                "base_sha": "0" * 40,
                "operation_kind": "initial_build",
                "source_kind": "legacy_accepted_state",
                "design_manifest_path": "",
                "source_candidate_sha": "",
                "design_manifest_json": {},
                "planning_json": {},
                "quality_report_json": {},
                "context_snapshot": {},
            }
        if manifest is None:
            try:
                _context, manifest = CustomerContextService(self.memory).snapshot_for_run(
                    self.record.incubation_id,
                    run,
                    website_source={"legacy_acceptance": True},
                )
            except (ContractError, ValueError) as exc:
                raise ProvisioningServiceError(str(exc)[:500]) from exc
        context_record = self.memory.get_customer_context(manifest.context_id, manifest.context_revision)
        context = context_record.get("context") if context_record else None
        if not isinstance(context, CustomerContextSnapshot) or context.computed_hash != manifest.context_hash:
            raise ProvisioningServiceError("accepted customer context is missing or does not match its manifest")
        conversation: list[dict[str, Any]] = []
        conversation_id = session.get("conversation_id")
        if conversation_id:
            conversation = self.memory.get_messages(int(conversation_id), limit=500)
        sources = self.memory.list_research_sources(limit=500)
        findings = [item.to_dict() for item in self.memory.list_research_findings(limit=1_000)]
        requests = [_without_storage_metadata(item, {"request_hash"}) for item in self.memory.list_research_requests(limit=500)]
        insights = [_without_storage_metadata(item, {"insight_hash"}) for item in self.memory.list_incubation_insights(limit=500)]
        deductions = [dict(item) for item in self.memory.list_incubation_deductions(limit=500)]
        approved = [
            item for item in sources
            if item.get("trust_state") == SourceTrustState.ALLOWED.value
            and item.get("ongoing_subscription") == SubscriptionState.APPROVED.value
        ]
        assets = self.memory.list_design_intake_assets(session["session_id"])
        design_history = self.memory.list_design_runs(mode="local_experiment", limit=500)
        safe_design_history, design_skill_set = _safe_design_history(design_history)
        feedback = self.memory.list_design_intake_feedback(session["session_id"], limit=500)
        draft = session.get("draft") if isinstance(session.get("draft"), Mapping) else {}
        unknowns = [{"value": item} for item in (draft.get("open_topics") or [])] if isinstance(draft, Mapping) else []
        site_intake = confirmed.get("site_intake") if isinstance(confirmed.get("site_intake"), Mapping) else {}
        genesis_history = [
            {
                "genesis": item["genesis"].to_dict(),
                "revision": item.get("revision"),
                "source_kind": item.get("source_kind"),
                "accepted": bool(item.get("accepted")),
                "created_ts": item.get("created_ts"),
            }
            for item in self.memory.list_customer_genesis_revisions(limit=500)
        ]
        activity_rows = self.memory.list_incubation_activity(limit=1_000).get("activities", [])
        activity = [_safe_activity(item) for item in activity_rows]
        activity = [item for item in activity if item is not None]
        bundle_id = "bundle_" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:32]
        collections = {
            "genesis_revisions": genesis_history,
            "conversation": conversation,
            "research_sources": sources,
            "research_findings": findings,
            "research_requests": requests,
            "research_insights": insights,
            "approved_feed_subscriptions": approved,
            "assets": assets,
            "design_history": safe_design_history,
            "owner_feedback": feedback,
            "activity": activity,
            "unknowns": unknowns,
        }
        if deductions:
            collections["research_deductions"] = deductions
        counts = {name: len(items) for name, items in collections.items()}
        counts["customer_context"] = 1
        counts["acceptance_manifest"] = 1
        bundle_data = {
            "schema_version": 1,
            "bundle_id": bundle_id,
            "incubation_id": self.record.incubation_id,
            "accepted_candidate_sha": self.record.accepted_candidate_sha,
            "intake_revision": {
                "session_id": session.get("session_id"),
                "revision": confirmed.get("revision"),
                "revision_id": confirmed.get("id"),
                "draft_hash": confirmed.get("draft_hash"),
                "site_intake_hash": confirmed.get("site_intake_hash") or run.get("intake_hash"),
                "design_run_id": run.get("run_id"),
                "site_intake": copy.deepcopy(site_intake),
            },
            "genesis_revision": copy.deepcopy(genesis["genesis"].to_dict()),
            "design_skill_set": design_skill_set,
            "customer_context": context.to_dict(),
            "acceptance_manifest": manifest.to_dict(),
            **collections,
            "prohibited_claims": list((site_intake.get("site") or {}).get("prohibited_claims") or []),
            "integrity": {"record_counts": counts},
        }
        bundle_data["integrity"] = {"content_hash": canonical_hash(bundle_data), "record_counts": counts}
        bundle = ProvisioningBundle.from_dict(bundle_data)
        try:
            stored = self.memory.save_provisioning_bundle(bundle)
        except (ContractError, ValueError) as exc:
            raise ProvisioningServiceError(str(exc)[:500]) from exc
        return stored.get("bundle") if isinstance(stored.get("bundle"), ProvisioningBundle) else bundle


class CustomerProvisioningService:
    """Create a destination instance, import the bundle, and verify its receipt."""

    def __init__(
        self,
        memory: Memory,
        intake_store: IntakeAdaStore,
        record: IncubationRecord,
        *,
        customer_root: str | Path,
        source_media: Any = None,
        importer: CustomerGenesisImporter | None = None,
        website_source_path: str | Path | None = None,
    ) -> None:
        self.memory = memory
        self.intake_store = intake_store
        self.record = record
        self.customer_root = Path(customer_root).expanduser().resolve()
        self.source_media = source_media
        self.importer = importer or CustomerGenesisImporter()
        self.website_source_path = Path(website_source_path).expanduser().resolve() if website_source_path else None
        if self.customer_root == Path(self.customer_root.anchor):
            raise ProvisioningServiceError("customer root is too broad")
        self.customer_root.mkdir(parents=True, exist_ok=True)

    def provision(self, body: Mapping[str, Any], *, bundle: ProvisioningBundle | None = None) -> ProvisioningReceipt:
        if not isinstance(body, Mapping):
            raise ProvisioningServiceError("provisioning request must be an object")
        request_id = _request_id(body.get("request_id"), self.record.incubation_id)
        existing = self.intake_store.get_receipt(request_id)
        if existing is not None:
            return existing
        bundle = bundle or ProvisioningBundleService(self.memory, self.record).freeze(request_id)
        customer_id = _customer_id(body.get("customer_instance_id"), request_id)
        if self.record.customer_instance_id and self.record.customer_instance_id != customer_id:
            raise ProvisioningServiceError("customer instance is already bound to another ID")
        destination = (self.customer_root / customer_id).resolve()
        if destination == self.customer_root or self.customer_root not in destination.parents:
            raise ProvisioningServiceError("customer destination is outside the configured root")
        destination.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(destination, 0o700)
        except OSError:
            pass
        data_dir = destination / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(data_dir, 0o700)
        except OSError:
            pass
        config_path = destination / "config.yaml"
        generated = generate_customer_config(
            bundle,
            customer_id=customer_id,
            customer_root=destination,
            display_name=str(body.get("display_name") or "New customer site"),
            model_env=str(body.get("model_env") or ""),
        )
        _write_config_once(config_path, generated, customer_id)
        target = Memory(data_dir / "memory.db")
        target_media = MediaService(target, LocalMediaStore(destination / "media"), generated)
        website_destination = destination / "site"
        website_source = self.website_source_path
        try:
            if website_source is not None:
                _copy_accepted_website(website_source, website_destination, bundle.accepted_candidate_sha)
            counts = self.importer.import_bundle(
                target,
                bundle,
                source_media=self.source_media,
                target_media=target_media,
            )
            verified = _verify_destination(
                data_dir / "memory.db",
                bundle,
                counts,
                website_destination if website_source is not None else None,
            )
            if verified:
                target.kv_set(
                    "provisioning_receipt",
                    {
                        "request_id": request_id,
                        "bundle_id": bundle.bundle_id,
                        "customer_instance_id": customer_id,
                        "bundle_hash": bundle.integrity["content_hash"],
                        "website_path": str(website_destination) if website_destination.is_dir() else "",
                    },
                )
        finally:
            target.close()
        receipt = ProvisioningReceipt.from_dict({
            "request_id": request_id,
            "bundle_id": bundle.bundle_id,
            "customer_instance_id": customer_id,
            "config_path": str(config_path),
            "database_path": str(data_dir / "memory.db"),
            "imported_counts": counts,
            "bundle_hash": bundle.integrity["content_hash"],
            "verified": verified,
            "created_at": utc_now(),
        })
        if not receipt.verified:
            raise ProvisioningServiceError("customer import verification failed")
        self.intake_store.save_receipt(receipt, incubation_id=self.record.incubation_id)
        return receipt


class CustomerActivationService:
    """Enable an already verified customer config as an explicit handoff."""

    def __init__(self, customer_root: str | Path) -> None:
        self.customer_root = Path(customer_root).expanduser().resolve()
        if self.customer_root == Path(self.customer_root.anchor):
            raise ProvisioningServiceError("customer root is too broad")

    def activate(self, receipt: ProvisioningReceipt) -> dict[str, Any]:
        if not isinstance(receipt, ProvisioningReceipt) or not receipt.verified:
            raise ProvisioningServiceError("a verified provisioning receipt is required")
        destination = Path(receipt.config_path).expanduser().resolve()
        expected_root = self.customer_root / receipt.customer_instance_id
        if destination != expected_root / "config.yaml" or self.customer_root not in destination.parents:
            raise ProvisioningServiceError("customer config is outside the configured root")
        database = Path(receipt.database_path).expanduser().resolve()
        if database != expected_root / "data" / "memory.db":
            raise ProvisioningServiceError("customer database identity is invalid")
        try:
            config = yaml.safe_load(destination.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ProvisioningServiceError("customer config is unreadable") from exc
        if not isinstance(config, dict) or config.get("instance_name") != receipt.customer_instance_id:
            raise ProvisioningServiceError("customer config belongs to another instance")
        activation = config.get("activation")
        if not isinstance(activation, dict):
            raise ProvisioningServiceError("customer activation settings are invalid")
        if activation.get("enabled") is True:
            return {"activated": True, "idempotent": True, "customer_instance_id": receipt.customer_instance_id}
        if activation.get("enabled") not in (False, None):
            raise ProvisioningServiceError("customer activation setting is invalid")
        config["activation"] = {**activation, "enabled": True}
        _replace_config(destination, config)
        target = Memory(database)
        try:
            target.kv_set("activation_enabled", True)
            target.record_action(
                "customer_runtime_activation_requested",
                json.dumps({"customer_instance_id": receipt.customer_instance_id, "request_id": receipt.request_id}, separators=(",", ":")),
            )
        finally:
            target.close()
        return {"activated": True, "idempotent": False, "customer_instance_id": receipt.customer_instance_id}


def generate_customer_config(
    bundle: ProvisioningBundle,
    *,
    customer_id: str,
    customer_root: Path,
    display_name: str,
    model_env: str = "",
) -> dict[str, Any]:
    genesis = bundle.genesis_revision
    relationship = genesis.get("relationship") or {}
    research = genesis.get("research_identity") or {}
    creative = genesis.get("creative_identity") or {}
    env_name = str(model_env or "").strip()
    if env_name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise ProvisioningServiceError("model_env must be an environment variable name")
    website_source = bundle.acceptance_manifest.get("website_source") or {}
    has_website = bool(str(website_source.get("source_path") or "").strip())
    provider_env = env_name or "SITE_AGENT_LLM_API_KEY"
    design_model = "deepseek/deepseek-v4-flash-vision-exp"
    design_base_url = "https://openrouter.ai/api/v1"
    site_path = str(customer_root / "site") if has_website else ""
    config = {
        "instance_name": customer_id,
        "customer_instance_id": customer_id,
        "data_dir": str(customer_root / "data"),
        "poll_seconds": 300,
        "activation": {"enabled": False},
        "persona": {
            "name": "Ada",
            "spirit": "",
            "voice": " ".join(str(item) for item in (creative.get("principles") or [])[:8]),
            "audience": ", ".join(str(item) for item in (research.get("subjects") or [])[:8]),
            "directions": [str(item) for item in (creative.get("principles") or [])[:20]],
            "taboo": [str(item) for item in (creative.get("patterns_to_avoid") or [])[:50]],
            "lures": [],
        },
        "owner_interaction": {
            "communication_preferences": [str(item) for item in (relationship.get("communication_preferences") or [])[:50]],
            "boundaries": [str(item) for item in (relationship.get("boundaries") or [])[:50]],
        },
        "schedule": {},
        "sources": {
            "subreddits": [],
            "rss_feeds": [
                {"name": str(item.get("title") or item.get("source_id") or "approved-source"), "url": str(item.get("feed_url") or item.get("url") or "")}
                for item in bundle.approved_feed_subscriptions
            ],
            "keywords": [str(item)[:500] for item in (research.get("subjects") or [])[:20]],
            "min_score": 0.0,
            "max_per_run": 25,
        },
        "ga": {"enabled": False, "property_id": "", "key_path": ""},
        "seo": {"enabled": False, "site_url": "", "key_path": ""},
        "providers": {"cicero": {"enabled": False}, "crawlseo": {"enabled": False}},
        "site": {
             "adapter": "neutral_scaffold",
             "repository": site_path,
             "branch": "main",
             "clone_path": site_path,
             "preview_branch": "",
              "writable_patterns": list(NEXT_REACT_PROFILE.writable_patterns),
             "media": {"enabled": False},
             "cloudflare": {"account_id": "", "project_name": "", "mode": "none"},
             "prohibited_claims": list(bundle.prohibited_claims),
        },
        "customer_context": {
            "schema_version": 1,
            "context_id": str(bundle.customer_context.get("context_id") or ""),
            "revision": int(bundle.customer_context.get("revision") or 0),
            "content_hash": str(bundle.customer_context.get("content_hash") or ""),
            "acceptance_manifest_id": str(bundle.acceptance_manifest.get("manifest_id") or ""),
            "acceptance_manifest_hash": str(bundle.acceptance_manifest.get("content_hash") or ""),
        },
        "design_engine": {
            "enabled": has_website,
            "build_profile": NEXT_REACT_PROFILE.name,
            "intake_schema_version": 1,
            "manifest_path": "design/ada-design-manifest.json",
            "provider": "openrouter",
            "model": design_model,
            "base_url": design_base_url,
            "api_key_env": provider_env,
            "repair_attempts": 0,
            "push_mode": "none",
            "required_viewports": [
                {"name": "desktop", "width": 1440, "height": 1000},
                {"name": "tablet", "width": 768, "height": 1024},
                {"name": "mobile", "width": 390, "height": 844},
            ],
            "libraries": {},
            "quality": {"browser": True, "accessibility": True, "visual_critic": False},
        },
        "llm": {"base_url": design_base_url, "model": design_model, "timeout_seconds": 300, "max_retries": 2, "daily_budget_usd": 2.0},
        "builder": {
            "enabled": has_website,
            "model": f"openrouter/{design_model}",
            "timeout_seconds": 1800,
            "provider_timeout_seconds": 2100,
            "provider_chunk_timeout_seconds": 180,
            "output_tokens": 32768,
            "reasoning_effort": "low",
            "validation_repair_attempts": 0,
        },
        "vision": {"enabled": False},
        "publish_mode": "ask_first",
        "display_name": str(display_name or "New customer site")[:200],
        "env": {
            "llm_api_key": provider_env,
            "vision_api_key": provider_env,
            "design_api_key": provider_env,
            "visual_review_api_key": provider_env,
        },
    }
    canonical_json(config)
    return config


def _write_config_once(path: Path, config: Mapping[str, Any], customer_id: str) -> None:
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ProvisioningServiceError("existing customer config is unreadable") from exc
        if existing.get("instance_name") != customer_id:
            raise ProvisioningServiceError("existing customer config belongs to another instance")
        return
    _replace_config(path, config)


def _replace_config(path: Path, config: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(yaml.safe_dump(dict(config), sort_keys=False), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise ProvisioningServiceError("customer config could not be created") from exc


def _copy_accepted_website(source: Path, destination: Path, expected_sha: str) -> None:
    """Materialize the exact accepted commit without copying a mutable worktree."""
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_dir() or not (source / ".git").exists():
        raise ProvisioningServiceError("accepted website source is not a git worktree")
    if destination == source or source in destination.parents:
        raise ProvisioningServiceError("accepted website destination overlaps its source")

    def git(root: Path, *arguments: str, timeout: int = 30) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *arguments],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProvisioningServiceError("accepted website commit could not be verified") from exc
        return result.stdout.strip().lower()

    if destination.exists():
        if git(destination, "rev-parse", "HEAD") != expected_sha:
            raise ProvisioningServiceError("existing customer website is not the accepted commit")
        if git(destination, "status", "--porcelain", "--untracked-files=all"):
            raise ProvisioningServiceError("existing customer website has local changes")
        if git(destination, "remote"):
            raise ProvisioningServiceError("existing customer website retains a remote")
        return
    if git(source, "rev-parse", "HEAD") != expected_sha:
        raise ProvisioningServiceError("accepted website source is not checked out at the accepted commit")

    temporary = destination.with_name(f".{destination.name}.handoff-{secrets.token_hex(8)}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git", "clone", "--no-local", "--no-hardlinks", "--no-tags",
                "--no-checkout", str(source), str(temporary),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        git(temporary, "checkout", "--detach", expected_sha, timeout=120)
        git(temporary, "remote", "remove", "origin")
        if git(temporary, "status", "--porcelain", "--untracked-files=all"):
            raise ProvisioningServiceError("cloned customer website has local changes")
        temporary.replace(destination)
    except (OSError, subprocess.SubprocessError) as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise ProvisioningServiceError("accepted website source could not be copied") from exc
    except ProvisioningServiceError:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    if git(destination, "rev-parse", "HEAD") != expected_sha:
        raise ProvisioningServiceError("copied customer website does not match the accepted commit")


def _verify_destination(
    path: Path,
    bundle: ProvisioningBundle,
    counts: Mapping[str, int],
    website_path: Path | None = None,
) -> bool:
    if not path.is_file():
        return False
    target = Memory(path)
    try:
        verified = (
            target.get_schema_version() == SCHEMA_VERSION
            and
            target.kv_get("provisioning_bundle_hash") == bundle.integrity["content_hash"]
            and target.kv_get("provisioning_accepted_candidate_sha") == bundle.accepted_candidate_sha
            and target.kv_get("provisioning_import_counts") == dict(counts)
        )
        if verified and bundle.customer_context:
            context = target.get_customer_context(str(bundle.customer_context.get("context_id") or ""), int(bundle.customer_context.get("revision") or 0))
            verified = bool(
                context
                and context.get("context_hash") == bundle.customer_context.get("content_hash")
                and isinstance(context.get("context"), CustomerContextSnapshot)
                and context["context"].computed_hash == bundle.customer_context.get("content_hash")
            )
        if verified and bundle.acceptance_manifest:
            manifest = target.get_acceptance_manifest(str(bundle.acceptance_manifest.get("manifest_id") or ""))
            verified = bool(
                manifest
                and manifest.get("manifest_hash") == bundle.acceptance_manifest.get("content_hash")
                and isinstance(manifest.get("manifest"), AcceptanceManifest)
                and manifest["manifest"].computed_hash == bundle.acceptance_manifest.get("content_hash")
            )
        if verified and bundle.acceptance_manifest:
            intake = bundle.intake_revision
            source_session_id = str(intake.get("session_id") or "")
            session_id = "imported-" + hashlib.sha256(source_session_id.encode("utf-8")).hexdigest()[:32] if source_session_id else ""
            source_revision = int(intake.get("revision") or 0)
            revision_id = intake.get("revision_id")
            revisions = target.list_design_intake_revisions(session_id, limit=500) if session_id else []
            imported_revision = next(
                (
                    item for item in revisions
                    if int(item.get("revision") or 0) == source_revision
                    and item.get("site_intake_hash") == intake.get("site_intake_hash")
                ),
                None,
            )
            verified = bool(
                imported_revision
                and canonical_hash(imported_revision.get("site_intake") or {}) == intake.get("site_intake_hash")
                and (imported_revision.get("summary") or {}).get("source_session_id") == source_session_id
                and (imported_revision.get("summary") or {}).get("source_revision_id") == revision_id
            )
            genesis = target.get_customer_genesis_revision(int(bundle.acceptance_manifest.get("genesis_revision") or 0))
            verified = bool(
                verified
                and genesis
                and genesis.get("genesis").content_hash == bundle.acceptance_manifest.get("genesis_hash")
            )
        if verified and website_path is not None:
            try:
                result = subprocess.run(
                    ["git", "-C", str(website_path), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                status = subprocess.run(
                    ["git", "-C", str(website_path), "status", "--porcelain", "--untracked-files=all"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                verified = result.stdout.strip().lower() == bundle.accepted_candidate_sha and not status.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                verified = False
        return verified
    except (ContractError, KeyError, TypeError, ValueError):
        # Corrupt imported JSON is a failed verification, not an importer crash.
        return False
    finally:
        target.close()


def _without_storage_metadata(item: Mapping[str, Any], keys: set[str]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key not in keys
    }


def _safe_design_history(runs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep review lineage while excluding paths, prompts, and provider output."""
    safe: list[dict[str, Any]] = []
    skill: dict[str, Any] = {}
    allowed = (
        "run_id", "mode", "status", "base_sha", "candidate_sha", "operation_kind",
        "parent_run_id", "source_candidate_sha", "publishable", "created_ts", "updated_ts",
        "quality_report_hash", "design_manifest_hash", "planning_hash", "context_snapshot_hash",
    )
    for run in runs:
        item = {key: copy.deepcopy(run.get(key)) for key in allowed if run.get(key) is not None}
        planning = run.get("planning_json")
        if isinstance(planning, Mapping):
            selection = planning.get("selection")
            if isinstance(selection, Mapping):
                selected = selection.get("selected")
                if isinstance(selected, Mapping) and selected.get("name"):
                    item["selected_direction"] = str(selected["name"])[:200]
        snapshot = run.get("context_snapshot")
        raw_skill = snapshot.get("design_skill_set") if isinstance(snapshot, Mapping) else None
        if isinstance(raw_skill, Mapping):
            names = raw_skill.get("names")
            content_hash = raw_skill.get("content_hash")
            if isinstance(names, list) and isinstance(content_hash, str):
                skill = {"names": [str(name)[:200] for name in names[:100]], "content_hash": content_hash}
        if item:
            safe.append(item)
    return safe, skill


def _safe_activity(item: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = str(item.get("kind") or "").strip().lower()
    if "poll" in kind or kind in {"worker_waiting", "research_waiting"}:
        return None
    return {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key != "id"
    }


def _request_id(value: Any, incubation_id: str) -> str:
    text = str(value or "").strip()
    if not text:
        text = "provision_" + hashlib.sha256(incubation_id.encode("utf-8")).hexdigest()[:32]
    if not re.fullmatch(r"provision_[0-9a-f]{32}", text):
        raise ProvisioningServiceError("request_id must be a provision_ identifier")
    return text


def _customer_id(value: Any, request_id: str) -> str:
    text = str(value or "").strip() or "customer_" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:32]
    if not re.fullmatch(r"customer_[0-9a-f]{32}", text):
        raise ProvisioningServiceError("customer_instance_id must be a customer_ identifier")
    return text


def _first_timestamp(items: Any) -> str:
    if isinstance(items, (list, tuple)):
        for item in items:
            if isinstance(item, Mapping) and item.get("ts"):
                return str(item["ts"])
    return utc_now()


def _attachments(value: Any, asset_ids: Mapping[int, int] | None = None) -> list[dict[str, int]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:20]:
        if isinstance(item, Mapping):
            try:
                source_asset_id = int(item.get("asset_id"))
                result.append({"asset_id": int((asset_ids or {}).get(source_asset_id, source_asset_id)), "position": int(item.get("position", len(result)))})
            except (TypeError, ValueError):
                continue
    return result


def _json_text(value: Any, maximum: int) -> str:
    try:
        return canonical_json(value)[:maximum]
    except (ContractError, TypeError, ValueError):
        return str(value)[:maximum]


__all__ = [
    "CustomerActivationService",
    "CustomerGenesisImporter",
    "CustomerProvisioningService",
    "ProvisioningBundleService",
    "ProvisioningServiceError",
    "generate_customer_config",
]

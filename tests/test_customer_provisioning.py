import io
import hashlib
from pathlib import Path
from dataclasses import replace

import pytest
from PIL import Image

from site_agent.application.incubations import IncubationApplicationService, IncubationRuntime
from site_agent.application.media import MediaService
from site_agent.application.incubation_research import IncubationResearchService
from site_agent.config import load, load_intake_config, validate_design_config
from site_agent.core.design_intake_contracts import DesignIntakeDraft
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.incubation_contracts import (
    CustomerAdaGenesis,
    IncubationActivity,
    IncubationInsight,
    IncubationStatus,
    ResearchFinding,
    ResearchRequest,
    ResearchSource,
)
from site_agent.application.provisioning import (
    CustomerGenesisImporter,
    ProvisioningBundleService,
    ProvisioningServiceError,
    generate_customer_config,
)
from site_agent.core.intake_ada_store import IntakeAdaStore
from site_agent.core.media_worker import MediaWorker
from site_agent.core.memory import Memory
from site_agent.hands.local_media import LocalMediaStore


def _intake():
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {"name": "Working business", "offer_summary": "A clear service", "primary_services": ["A clear service"], "location": "Local service area"},
        "audience": {"primary": "People evaluating the service"},
        "conversion": {"primary_action": "Get in touch", "not_available": True},
        "brand": {"voice": "Clear and warm"},
        "site": {"required_pages": ["index.html"]},
    })


def test_customer_config_enables_reviewable_design_runtime_without_activation(tmp_path):
    from types import SimpleNamespace

    bundle = SimpleNamespace(
        genesis_revision={"relationship": {}, "research_identity": {}, "creative_identity": {}},
        acceptance_manifest={"website_source": {"source_path": str(tmp_path / "accepted-site")}},
        customer_context={},
        approved_feed_subscriptions=[],
        prohibited_claims=[],
    )

    config = generate_customer_config(
        bundle,
        customer_id="customer-1",
        customer_root=tmp_path / "customer-1",
        display_name="Customer",
        model_env="OPENROUTER_API_KEY",
    )

    assert config["activation"]["enabled"] is False
    assert config["site"]["adapter"] == "neutral_scaffold"
    assert config["site"]["clone_path"] == str(tmp_path / "customer-1" / "site")
    assert config["design_engine"]["enabled"] is True
    assert config["design_engine"]["push_mode"] == "none"
    assert config["builder"]["enabled"] is True
    assert config["env"]["llm_api_key"] == "OPENROUTER_API_KEY"
    assert "secret" not in str(config).lower()
    validate_design_config(config)


def test_accepted_incubation_imports_once_and_returns_receipt(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    config["provisioning"]["customer_root"] = str(tmp_path / "customers")
    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    service = IncubationApplicationService(store, root=config["incubation"]["root"], config=config)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        draft = DesignIntakeDraft.from_site_intake(_intake())
        conversation_id = scoped.memory.create_conversation("intake")
        scoped.memory.create_design_intake_session("intake-" + "a" * 32, draft, conversation_id=conversation_id)
        session = scoped.memory.get_design_intake_session("intake-" + "a" * 32)
        confirmed = service.confirm_intake(record.incubation_id, {
            "session_id": session["session_id"],
            "revision": session["revision"],
            "draft_hash": session["draft_hash"],
        })
        assert confirmed["incubation"]["status"] == IncubationStatus.READY_TO_BUILD.value

        service.transition(record.incubation_id, IncubationStatus.BUILDING.value)
        service.transition(record.incubation_id, IncubationStatus.READY_FOR_FEEDBACK.value)
        service.transition(record.incubation_id, IncubationStatus.ACCEPTED.value, accepted_candidate_sha="a" * 40)
        first = service.provision(record.incubation_id, {})
        second = service.provision(record.incubation_id, {})
        assert first["receipt"]["verified"] is True
        assert second["idempotent"] is True
        assert Path(first["receipt"]["config_path"]).is_file()
        assert Path(first["receipt"]["database_path"]).is_file()
        customer_config, _ = load(first["receipt"]["config_path"], env={})
        assert customer_config["instance_name"] == first["receipt"]["customer_instance_id"]
        assert customer_config["activation"]["enabled"] is False
        activation = service.activate(record.incubation_id, {})
        assert activation["activation"]["activated"] is True
        customer_config, _ = load(first["receipt"]["config_path"], env={})
        assert customer_config["activation"]["enabled"] is True
        destination = Memory(first["receipt"]["database_path"])
        try:
            assert destination.kv_get("provisioning_receipt")["bundle_id"] == first["receipt"]["bundle_id"]
            assert destination.kv_get("provisioning_accepted_candidate_sha") == "a" * 40
            assert destination.kv_get("activation_enabled") is True
            assert destination.get_customer_genesis_revision()["accepted"] is True
        finally:
            destination.close()
        episodes = store.list_episodes()
        assert len(episodes) == 1
        assert "Working business" not in episodes[0].semantic_text
    finally:
        service.close()
        store.close()


def test_provisioning_transfers_research_and_genesis_history(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    config["provisioning"]["customer_root"] = str(tmp_path / "customers")
    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    service = IncubationApplicationService(store, root=config["incubation"]["root"], config=config)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        draft = DesignIntakeDraft.from_site_intake(_intake())
        conversation_id = scoped.memory.create_conversation("intake")
        session_id = "intake-" + "c" * 32
        scoped.memory.create_design_intake_session(session_id, draft, conversation_id=conversation_id)
        session = scoped.memory.get_design_intake_session(session_id)
        service.confirm_intake(record.incubation_id, {
            "session_id": session_id,
            "revision": session["revision"],
            "draft_hash": session["draft_hash"],
        })

        genesis = service.genesis_service(record.incubation_id).current()
        service.genesis_service(record.incubation_id).save(
            replace(genesis, revision=genesis.revision + 1, creative_identity={
                **genesis.creative_identity,
                "principles": ["Make the value obvious"],
            })
        )
        source = ResearchSource.from_dict({
            "source_id": "src_" + "d" * 32,
            "kind": "rss",
            "url": "https://example.com/feed.xml",
            "feed_url": "https://example.com/feed.xml",
            "title": "Public source",
            "discovered_by": "owner",
            "trust_state": "allowed",
            "ongoing_subscription": "approved",
        })
        scoped.memory.save_research_source(source)
        finding = ResearchFinding.from_dict({
            "finding_id": "finding_" + "e" * 32,
            "source_id": source.source_id,
            "published_at": "2026-09-03T00:00:00+00:00",
            "summary": "Visitors want a concise explanation of the service.",
            "relevance": 0.8,
            "supports": [],
            "contradicts": [],
            "confidence": 0.5,
            "content_hash": "f" * 64,
        })
        scoped.memory.save_research_finding(finding)
        scoped.memory.save_research_request(ResearchRequest.from_dict({
            "request_id": "research_" + "1" * 32,
            "dedupe_key": "2" * 64,
            "created_at": "2026-09-03T00:00:00+00:00",
            "updated_at": "2026-09-03T00:00:00+00:00",
            "status": "completed",
            "trigger": "owner_request",
            "intake_revision": 1,
            "owner_language": "en",
            "subjects": ["service"],
            "markets": [],
            "candidate_communities": [],
            "query_terms_by_language": {"en": ["service"]},
            "source_ids": [source.source_id],
            "finding_ids": [finding.finding_id],
            "insight_ids": ["insight_" + "3" * 32],
            "error": "",
            "intent": "service audience",
        }))
        scoped.memory.save_incubation_insight(IncubationInsight.from_dict({
            "insight_id": "insight_" + "3" * 32,
            "kind": "content_opportunity",
            "summary": "Lead with the service outcome.",
            "owner_language": "en",
            "source_languages": ["en"],
            "finding_ids": [finding.finding_id],
            "supports_paths": ["site.required_pages"],
            "contradicts_paths": [],
            "confidence": 0.5,
            "status": "inferred",
            "created_at": "2026-09-03T00:00:00+00:00",
        }))
        scoped.memory.append_incubation_activity(IncubationActivity.from_dict({
            "activity_id": "activity_" + "4" * 32,
            "occurred_at": "2026-09-03T00:00:00+00:00",
            "category": "research",
            "kind": "source_read",
            "state": "completed",
            "summary": "Read one approved public source.",
            "provenance": "public_source",
            "confidence": 0.5,
            "detail": {"item_count": 1},
            "research_request_id": "research_" + "1" * 32,
            "source_id": source.source_id,
            "finding_ids": [finding.finding_id],
        }))

        service.transition(record.incubation_id, IncubationStatus.BUILDING.value)
        service.transition(record.incubation_id, IncubationStatus.READY_FOR_FEEDBACK.value)
        service.transition(record.incubation_id, IncubationStatus.ACCEPTED.value, accepted_candidate_sha="c" * 40)
        result = service.provision(record.incubation_id, {})

        destination = Memory(result["receipt"]["database_path"])
        try:
            assert [item["revision"] for item in destination.list_customer_genesis_revisions()] == [1, 2, 3]
            assert destination.get_research_request("research_" + "1" * 32)["status"] == "completed"
            assert destination.list_incubation_insights()[0]["insight_id"] == "insight_" + "3" * 32
            activities = destination.list_incubation_activity(limit=20)["activities"]
            assert any(item["activity_id"] == "activity_" + "4" * 32 for item in activities)
            assert all(item["conversation_id"] is None for item in activities)
        finally:
            destination.close()
    finally:
        service.close()
        store.close()


def test_provisioning_copies_bound_media_and_remaps_message_attachments(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    config["provisioning"]["customer_root"] = str(tmp_path / "customers")
    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    service = IncubationApplicationService(store, root=config["incubation"]["root"], config=config)
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        source_media = MediaService(scoped.memory, LocalMediaStore(scoped.path.parent / "media"), {"site": {"media": {"enabled": True}}})
        service.attach_runtime(record.incubation_id, IncubationRuntime(media_service=source_media))
        image = io.BytesIO()
        Image.new("RGB", (20, 10), "blue").save(image, format="JPEG")
        uploaded = source_media.upload("blue.jpg", image.getvalue(), "image/jpeg")
        MediaWorker({"memory": scoped.memory, "media_store": source_media.store, "media_service": source_media}).process_one()
        asset_id = uploaded["asset"]["id"]
        conversation_id = scoped.memory.create_conversation("intake")
        session_id = "intake-" + "b" * 32
        scoped.memory.create_design_intake_session(session_id, DesignIntakeDraft.from_site_intake(_intake()), conversation_id=conversation_id)
        scoped.memory.replace_design_intake_assets(session_id, [{"asset_id": asset_id, "position": 0, "usage": "website"}])
        scoped.memory.add_message(conversation_id, "user", "Use this image", attachments=[{"asset_id": asset_id, "position": 0}])
        session = scoped.memory.get_design_intake_session(session_id)
        service.confirm_intake(record.incubation_id, {"session_id": session_id, "revision": session["revision"], "draft_hash": session["draft_hash"]})
        service.transition(record.incubation_id, IncubationStatus.BUILDING.value)
        service.transition(record.incubation_id, IncubationStatus.READY_FOR_FEEDBACK.value)
        service.transition(record.incubation_id, IncubationStatus.ACCEPTED.value, accepted_candidate_sha="b" * 40)

        result = service.provision(record.incubation_id, {})
        destination = Memory(result["receipt"]["database_path"])
        try:
            imported = destination.list_media_assets()
            messages = destination.get_messages(destination.list_conversations(limit=1)[0]["id"])
            assert len(imported) == 1
            assert imported[0].original_sha256 == scoped.memory.get_media_asset(asset_id).original_sha256
            assert messages[0]["attachments"][0]["asset_id"] == imported[0].asset_id
        finally:
            destination.close()
        assert (Path(result["receipt"]["database_path"]).parent.parent / "media" / imported[0].original_key).is_file()
    finally:
        service.close()
        store.close()


def test_importer_resumes_media_from_persisted_id_maps(tmp_path):
    config, _ = load_intake_config(env={})
    config["data_dir"] = str(tmp_path / "intake-data")
    config["incubation"]["root"] = str(tmp_path / "incubations")
    config["incubation"]["scaffold"] = str(tmp_path / "scaffold")
    store = IntakeAdaStore(Path(config["data_dir"]) / "intake-ada.db")
    service = IncubationApplicationService(store, root=config["incubation"]["root"], config=config)
    target = None
    try:
        record = service.create_incubation()
        scoped = service.open_store(record.incubation_id)
        source_media = MediaService(scoped.memory, LocalMediaStore(scoped.path.parent / "media"), {"site": {"media": {"enabled": True}}})
        service.attach_runtime(record.incubation_id, IncubationRuntime(media_service=source_media))
        asset_ids = []
        for color in ("blue", "green"):
            image = io.BytesIO()
            Image.new("RGB", (20, 10), color).save(image, format="JPEG")
            asset_ids.append(source_media.upload(f"{color}.jpg", image.getvalue(), "image/jpeg")["asset"]["id"])
        MediaWorker({"memory": scoped.memory, "media_store": source_media.store, "media_service": source_media}).process_one()
        MediaWorker({"memory": scoped.memory, "media_store": source_media.store, "media_service": source_media}).process_one()

        session_id = "intake-" + "f" * 32
        conversation_id = scoped.memory.create_conversation("intake")
        scoped.memory.create_design_intake_session(session_id, DesignIntakeDraft.from_site_intake(_intake()), conversation_id=conversation_id)
        scoped.memory.replace_design_intake_assets(
            session_id,
            [{"asset_id": asset_id, "position": index, "usage": "website"} for index, asset_id in enumerate(asset_ids)],
        )
        session = scoped.memory.get_design_intake_session(session_id)
        service.confirm_intake(record.incubation_id, {"session_id": session_id, "revision": session["revision"], "draft_hash": session["draft_hash"]})
        service.transition(record.incubation_id, IncubationStatus.BUILDING.value)
        service.transition(record.incubation_id, IncubationStatus.READY_FOR_FEEDBACK.value)
        accepted = service.transition(record.incubation_id, IncubationStatus.ACCEPTED.value, accepted_candidate_sha="f" * 40)
        bundle = ProvisioningBundleService(scoped.memory, accepted).freeze("provision_" + "1" * 32)

        target = Memory(tmp_path / "destination" / "memory.db")
        target_media = MediaService(target, LocalMediaStore(tmp_path / "destination" / "media"), {"site": {"media": {"enabled": True}}})

        class FlakyMedia:
            def export_asset(self, asset_id):
                if int(asset_id) == int(asset_ids[1]):
                    raise RuntimeError("simulated media interruption")
                return source_media.export_asset(asset_id)

        with pytest.raises(ProvisioningServiceError):
            CustomerGenesisImporter().import_bundle(target, bundle, source_media=FlakyMedia(), target_media=target_media)
        import_id = "import_" + hashlib.sha256(bundle.integrity["content_hash"].encode()).hexdigest()[:32]
        assert len(target.list_provisioning_id_maps(import_id, "media_asset")) == 1

        counts = CustomerGenesisImporter().import_bundle(target, bundle, source_media=source_media, target_media=target_media)
        assert counts["assets"] == 2
        assert len(target.list_media_assets()) == 2
        assert len(target.list_provisioning_id_maps(import_id, "media_asset")) == 2
    finally:
        if target is not None:
            target.close()
        service.close()
        store.close()

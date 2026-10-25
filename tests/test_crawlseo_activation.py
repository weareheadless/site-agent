import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from site_agent.application.crawlseo_activation import (
    CrawlSEOActivationError, apply_crawlseo_activation, build_crawlseo_activation,
)
from site_agent.application.growth_budget import GrowthBudgetBlocked, reserve_paid_research
from site_agent.application.crawlseo_migration import evidence_hash
from site_agent.application.crawlseo_accounting import verify_import_receipt
from site_agent.core.memory import Memory
from site_agent.hands.crawlseo_connector_credentials import (
    CONNECTOR_RUNTIME_TOKEN_ENV, CONNECTOR_TOKEN_ENV, install_connector_credential,
    install_runtime_connector_credential, load_connector_runtime_environment,
)

READ_TOKEN = "cseo_read_12345678901234567890"
RUNTIME_TOKEN = "cseo_runtime_12345678901234567890"
CAPABILITIES = {
    "schemaVersion": "1.0", "siteId": "site-1", "projectId": "project-1",
    "credentialScopes": ["connector:read", "connector:write"],
    "binding": {"siteId": "site-1", "status": "active", "executor": "helloada", "generation": 5,
                "executionSupported": True},
}


def _tenant(tmp_path):
    directory = tmp_path / "tenant-a"
    directory.mkdir()
    config = {
        "instance_name": "tenant-a", "data_dir": str(directory / "data"),
        "providers": {"crawlseo": {
            "enabled": True, "url": "https://crawlseo.example/mcp",
            "token_env": "CRAWLSEO_SERVICE_TOKEN", "connector_token_env": CONNECTOR_TOKEN_ENV,
            "connector_url": "https://crawlseo.example/api/connector/v1",
            "research_authority": "local",
        }},
        "seo": {"enabled": True, "research": {"enabled": True},
                "site_report": {"enabled": True}, "article_research": {"enabled": True}},
        "growth": {"enabled": True},
    }
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    memory = Memory(directory / "memory.db")
    memory.kv_set("crawlseo_migration:producer_freeze", {
        "active": True, "registrationsVerified": True, "pendingDrain": False,
    })
    return SimpleNamespace(tenant_id="tenant-a", config_path=str(path), config=config,
                           memory=memory, api_token="api", api_token_env="API_TOKEN",
                           runtime=SimpleNamespace(scheduler=SimpleNamespace(jobs=[])), context={})


def _inventory(memory):
    inventory = memory.crawlseo_migration_snapshot()
    for key in ("activeJobs", "executionBindings", "budgetReservations", "providerReceipts"):
        inventory[key]["truncated"] = False
    return inventory


def _plan(tenant):
    inventory = _inventory(tenant.memory)
    return {
        "tenant": "tenant-a", "siteId": "site-1", "snapshotHash": "sha256:" + "a" * 64,
        "preflightReady": True, "blockers": [
            "Tenant is not yet configured for CrawlSEO authority; this plan does not activate cutover.",
            "Legacy research settings remain enabled and need an explicit retirement disposition: seoResearchEnabled.",
        ], "inventory": inventory,
        "crawlseo": {"projectId": "project-1"},
        "canonicalRouteVerification": {"state": "current_server_verified"},
        "checks": [{"id": "inventory", "phase": "preflight", "state": "passed"}],
    }


def _body(tenant, mode="plan"):
    raw = Path(tenant.config_path).read_bytes()
    return {"mode": mode, "expectedSnapshotHash": "sha256:" + "a" * 64,
            "expectedConfigHash": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "operatorRequestId": "activation-req-0001", "reason": "Activate reviewed CrawlSEO research authority"}


def _factory(_config, _env):
    return SimpleNamespace(connector_capabilities=lambda site_id=None: CAPABILITIES, close=lambda: None)


def test_runtime_credential_is_separate_from_read_only_and_mcp(tmp_path):
    tenant = _tenant(tmp_path)
    install_connector_credential(tenant.config, CONNECTOR_TOKEN_ENV, READ_TOKEN)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    assert load_connector_runtime_environment(tenant.config) == {CONNECTOR_RUNTIME_TOKEN_ENV: RUNTIME_TOKEN}
    read_path = Path(tenant.config["data_dir"]).parent / "crawlseo-connector.env"
    assert READ_TOKEN in read_path.read_text()
    assert RUNTIME_TOKEN not in read_path.read_text()


def test_plan_is_read_only_and_never_grants_paid_work(tmp_path):
    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    before = Path(tenant.config_path).read_bytes()
    result = build_crawlseo_activation(tenant, _plan(tenant), _body(tenant),
        {"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    assert result["valid"] is True
    assert result["paidOperationsAllowed"] is False
    assert Path(tenant.config_path).read_bytes() == before


def test_activation_fails_closed_on_unreviewed_or_unknown_outcomes(tmp_path):
    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    plan = _plan(tenant)
    plan["checks"][0]["state"] = "blocked"
    with pytest.raises(CrawlSEOActivationError, match="passed or reviewed"):
        build_crawlseo_activation(tenant, plan, _body(tenant), client_factory=_factory)


def test_crawlseo_paid_dispatch_stays_held_without_policy_import(tmp_path):
    tenant = _tenant(tmp_path)
    config = yaml.safe_load(Path(tenant.config_path).read_text(encoding="utf-8"))
    config["providers"]["crawlseo"]["research_authority"] = "crawlseo"
    tenant.memory.kv_set("crawlseo_activation:paid_dispatch_hold", {"active": True})
    with pytest.raises(GrowthBudgetBlocked, match="policy import is not implemented"):
        reserve_paid_research({"memory": tenant.memory, "config": config},
            idempotency_key="activation-test", operation="seo_monthly_research")
    plan = _plan(tenant)
    plan["inventory"]["providerReceipts"]["items"] = [{"status": "mystery"}]
    plan["inventory"]["providerReceipts"]["total"] = 1
    with pytest.raises(CrawlSEOActivationError, match="unknown provider outcome"):
        build_crawlseo_activation(tenant, plan, _body(tenant), client_factory=_factory)


def test_activation_allows_preserved_terminal_execution_history_but_requires_completed_drain(tmp_path):
    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    plan = _plan(tenant)
    plan["inventory"]["executionBindings"].update({"total": 1, "items": [{"state": "publication_unreported"}]})
    assert build_crawlseo_activation(tenant, plan, _body(tenant),
        env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)["valid"] is True
    tenant.memory.kv_set("crawlseo_migration:producer_freeze", {
        "active": True, "registrationsVerified": True, "pendingDrain": True,
    })
    with pytest.raises(CrawlSEOActivationError, match="pending drain complete"):
        build_crawlseo_activation(tenant, plan, _body(tenant),
            env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)


def test_activation_blocks_settled_reservation_without_actual_cost(tmp_path):
    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    plan = _plan(tenant)
    plan["inventory"]["budgetReservations"].update({
        "total": 1, "items": [{"status": "settled", "recorded_actual_cost_micros": None}],
    })
    with pytest.raises(CrawlSEOActivationError, match="reservation outcome"):
        build_crawlseo_activation(tenant, plan, _body(tenant),
            env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)


def test_activation_accepts_persisted_terminal_import_with_full_quote_held_and_paid_dispatch_held(tmp_path):
    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    fixture = json.loads((Path(__file__).parent / "fixtures" / "crawlseo_legacy_budget_import_sanitized.json")
        .read_text(encoding="utf-8"))
    source_plan, source_receipt = fixture["plan"], fixture["receipt"]
    # Match the activation tenant's real binding while preserving the fixture's distinct legacy source.
    source_plan["siteId"] = "site-1"
    source_plan["crawlseo"]["projectId"] = "project-1"
    source_plan["crawlseo"]["binding"].update({"siteId": "site-1", "projectId": "project-1"})
    source_receipt["targetSiteId"] = "site-1"
    source_receipt["targetProjectId"] = "project-1"
    source_receipt["snapshot"]["target"].update({"siteId": "site-1", "projectId": "project-1"})

    invalid_receipt = deepcopy(source_receipt)
    invalid_receipt["snapshot"]["rows"][0]["sourceTask"]["status"] = "ATTEMPTING"
    with pytest.raises(ValueError, match="nonterminal"):
        verify_import_receipt(invalid_receipt, source_plan, "fixture-nonterminal-0001")

    verified = verify_import_receipt(source_receipt, source_plan, "fixture-terminal-0001")
    imported_receipt = {**verified, "type": "crawlseo_legacy_budget_import", "state": "verified"}
    tenant.memory.persist_crawlseo_migration_receipt(imported_receipt)
    assert len(verified["rows"]) == 7
    assert verified["heldUnknownMicros"] == "100000"
    assert verified["knownSpendMicros"] == "72720"
    assert sum(row["sourceTaskStatus"] == "FAILED" for row in verified["rows"]) == 1
    assert all(row["actualCostMicros"] is None for row in verified["rows"]
        if row["effectiveStatus"] == "UNCERTAIN")
    assert all(row["recorded_actual_cost_micros"] is None
        for row in source_plan["inventory"]["budgetReservations"]["items"])

    plan = _plan(tenant)
    plan["siteId"] = "site-1"
    plan["crawlseo"] = source_plan["crawlseo"]
    plan["legacyPolicy"] = source_plan["legacyPolicy"]
    plan["inventory"].update({
        "budgetReservations": source_plan["inventory"]["budgetReservations"],
        "articleIdeas": source_plan["inventory"]["articleIdeas"],
    })
    tenant.memory.kv_set("crawlseo_activation:paid_dispatch_hold", {"active": True})
    result = build_crawlseo_activation(tenant, plan, _body(tenant),
        env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    assert result["valid"] is True
    assert result["paidOperationsAllowed"] is False
    assert tenant.memory.kv_get("crawlseo_activation:paid_dispatch_hold")["active"] is True


def test_activation_requires_verified_freeze_and_no_legacy_scheduler_jobs(tmp_path):
    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    tenant.memory.kv_set("crawlseo_migration:producer_freeze", {"active": True, "registrationsVerified": False})
    with pytest.raises(CrawlSEOActivationError, match="frozen"):
        build_crawlseo_activation(tenant, _plan(tenant), _body(tenant), client_factory=_factory)
    tenant.memory.kv_set("crawlseo_migration:producer_freeze", {
        "active": True, "registrationsVerified": True, "pendingDrain": False,
    })
    tenant.runtime.scheduler.jobs = [("growth_daily", {})]
    with pytest.raises(CrawlSEOActivationError, match="legacy producer registrations"):
        build_crawlseo_activation(tenant, _plan(tenant), _body(tenant), client_factory=_factory)


def test_activation_configures_authority_but_preserves_freeze_and_paid_hold(tmp_path):
    tenant = _tenant(tmp_path)
    install_connector_credential(tenant.config, CONNECTOR_TOKEN_ENV, READ_TOKEN)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    plan, body = _plan(tenant), _body(tenant, "apply")

    class Registry:
        tenants = {"tenant-a": tenant}
        def reload_tenant(self, tenant_id, config_path, **kwargs):
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            memory = Memory(Path(config_path).with_name("memory.db"))
            service = SimpleNamespace(connector_capabilities=lambda _site_id: CAPABILITIES)
            replacement = SimpleNamespace(tenant_id=tenant_id, config_path=config_path, config=config,
                memory=memory, context={"crawlseo_service": service},
                runtime=SimpleNamespace(scheduler=SimpleNamespace(jobs=[])))
            memory.kv_set("crawlseo_migration:producer_freeze", {
                "active": True, "registrationsVerified": True, "pendingDrain": False,
            })
            self.tenants[tenant_id] = replacement
            # A newly started scheduler must not ingest Actions or prepare
            # candidates before the immutable activation checkpoint commits.
            from site_agent.application.growth_workflow import run_pending_growth
            from site_agent.core.research_authority import CONNECTOR_DISPATCH_HOLD_KEY
            assert memory.kv_get(CONNECTOR_DISPATCH_HOLD_KEY)["active"] is True
            with pytest.raises(RuntimeError, match="paused"):
                run_pending_growth({"config": config, "memory": memory})
            return replacement

    registry = Registry()
    result = apply_crawlseo_activation(registry, tenant, plan, body,
        env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    assert result["status"] == "authority_active"
    assert result["paidOperationsAllowed"] is False
    saved = yaml.safe_load(Path(tenant.config_path).read_text(encoding="utf-8"))
    assert saved["providers"]["crawlseo"]["research_authority"] == "crawlseo"
    assert saved["providers"]["crawlseo"]["token_env"] == "CRAWLSEO_SERVICE_TOKEN"
    assert saved["providers"]["crawlseo"]["connector_token_env"] == CONNECTOR_RUNTIME_TOKEN_ENV
    assert saved["seo"]["research"]["enabled"] is False
    assert saved["seo"]["site_report"]["enabled"] is False
    assert saved["seo"]["article_research"]["enabled"] is False
    assert registry.tenants["tenant-a"].memory.crawlseo_producer_freeze_status()["active"] is True
    assert registry.tenants["tenant-a"].memory.kv_get("crawlseo_activation:paid_dispatch_hold")["active"] is True
    dispatch = registry.tenants["tenant-a"].memory.kv_get("crawlseo_activation:connector_dispatch_hold")
    assert dispatch["active"] is False
    assert dispatch["verificationReceiptId"] == result["receipt"]["receiptId"]
    assert {r["state"] for r in registry.tenants["tenant-a"].memory.crawlseo_migration_receipts()
            if r.get("type") == "crawlseo_activation"} >= {"begin", "config_saved", "runtime_verified"}
    replay = apply_crawlseo_activation(registry, registry.tenants["tenant-a"], plan,
        body, env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    assert replay["idempotent"] is True
    registry.tenants["tenant-a"].context["crawlseo_service"] = SimpleNamespace(
        connector_capabilities=lambda _site_id: {**CAPABILITIES, "binding": {
            **CAPABILITIES["binding"], "generation": 6,
        }})
    with pytest.raises(CrawlSEOActivationError, match="differs from the activation checkpoint"):
        apply_crawlseo_activation(registry, registry.tenants["tenant-a"], plan,
            body, env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    registry.tenants["tenant-a"].context["crawlseo_service"] = SimpleNamespace(
        connector_capabilities=lambda _site_id: CAPABILITIES)
    registry.tenants["tenant-a"].memory.kv_set("crawlseo_migration:producer_freeze", {
        "active": False, "registrationsVerified": True, "pendingDrain": False,
    })
    with pytest.raises(CrawlSEOActivationError, match="freeze"):
        apply_crawlseo_activation(registry, registry.tenants["tenant-a"], plan,
            body, env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)


def test_activation_recovers_config_cas_before_saved_receipt(tmp_path, monkeypatch):
    import site_agent.application.crawlseo_activation as activation

    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    plan, body = _plan(tenant), _body(tenant, "apply")

    class Registry:
        tenants = {"tenant-a": tenant}
        def reload_tenant(self, tenant_id, config_path, **kwargs):
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            memory = Memory(Path(config_path).with_name("memory.db"))
            memory.kv_set("crawlseo_migration:producer_freeze", {
                "active": True, "registrationsVerified": True, "pendingDrain": False,
            })
            replacement = SimpleNamespace(tenant_id=tenant_id, config_path=config_path, config=config,
                memory=memory, context={"crawlseo_service": SimpleNamespace(
                    connector_capabilities=lambda _site_id: CAPABILITIES)},
                runtime=SimpleNamespace(scheduler=SimpleNamespace(jobs=[])))
            self.tenants[tenant_id] = replacement
            return replacement

    registry = Registry()
    persist = activation._persist
    def fail_saved(memory, request_id, phase, values, inventory_hash):
        if phase == "config_saved":
            raise RuntimeError("simulated process interruption after config CAS")
        return persist(memory, request_id, phase, values, inventory_hash)
    monkeypatch.setattr(activation, "_persist", fail_saved)
    with pytest.raises(CrawlSEOActivationError, match="config could not be saved"):
        apply_crawlseo_activation(registry, tenant, plan, body,
            env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    saved = yaml.safe_load(Path(tenant.config_path).read_text(encoding="utf-8"))
    assert saved["providers"]["crawlseo"]["research_authority"] == "crawlseo"
    assert {r["state"] for r in tenant.memory.crawlseo_migration_receipts()
            if r.get("type") == "crawlseo_activation"} == {"begin"}
    monkeypatch.setattr(activation, "_persist", persist)
    result = apply_crawlseo_activation(registry, tenant, plan, body,
        env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    assert result["status"] == "authority_active"
    assert {r["state"] for r in registry.tenants["tenant-a"].memory.crawlseo_migration_receipts()
            if r.get("type") == "crawlseo_activation"} >= {"begin", "config_saved", "runtime_verified"}


def test_saved_activation_checkpoint_retries_runtime_verification(tmp_path):
    tenant = _tenant(tmp_path)
    install_runtime_connector_credential(tenant.config, RUNTIME_TOKEN)
    plan, body = _plan(tenant), _body(tenant, "apply")

    class Registry:
        tenants = {"tenant-a": tenant}
        fail = True
        def reload_tenant(self, tenant_id, config_path, **kwargs):
            if self.fail:
                raise RuntimeError("reload temporarily failed")
            config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            memory = Memory(Path(config_path).with_name("memory.db"))
            memory.kv_set("crawlseo_migration:producer_freeze", {
                "active": True, "registrationsVerified": True, "pendingDrain": False,
            })
            service = SimpleNamespace(connector_capabilities=lambda _site_id: CAPABILITIES)
            replacement = SimpleNamespace(tenant_id=tenant_id, config_path=config_path, config=config,
                memory=memory, context={"crawlseo_service": service},
                runtime=SimpleNamespace(scheduler=SimpleNamespace(jobs=[])))
            self.tenants[tenant_id] = replacement
            return replacement

    registry = Registry()
    first = apply_crawlseo_activation(registry, tenant, plan, body,
        env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    assert first["status"] == "config_saved_runtime_unverified"
    assert tenant.memory.crawlseo_producer_freeze_status()["active"] is True
    registry.fail = False
    recovered = apply_crawlseo_activation(registry, tenant, plan, body,
        env={"CRAWLSEO_SERVICE_TOKEN": "legacy"}, client_factory=_factory)
    assert recovered["status"] == "authority_active"
    assert recovered["idempotent"] is True

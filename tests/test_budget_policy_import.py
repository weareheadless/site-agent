from __future__ import annotations

from site_agent.application.crawlseo_migration import current_budget_policy_import


class MemoryStub:
    def __init__(self, receipts):
        self.receipts = receipts
        self.current = {r["type"]: r["receiptId"] for r in receipts}

    def crawlseo_migration_current_receipts(self):
        return self.current

    def crawlseo_migration_receipts(self):
        return self.receipts


LOCAL = {"monthlyResearchCapMicros": 500000, "effectiveMonthlyAllowanceMicros": "500000", "timezone": "UTC"}
REMOTE = {"allowanceMicros": "500000", "maxOperationMicros": "100000", "currency": "USD",
          "timeZone": "UTC", "policyRevision": 2, "siteId": "site-1", "projectId": "project-1"}
PLAN = {"legacyPolicy": LOCAL, "crawlseo": {"budget": REMOTE}}


def receipt(**overrides):
    value = {
        "type": "budget_policy_import",
        "receiptId": "sha256:abc",
        "localPolicy": LOCAL,
        "remoteAfter": REMOTE,
    }
    value.update(overrides)
    return value


def test_matching_import_receipt_is_current() -> None:
    memory = MemoryStub([receipt()])
    assert current_budget_policy_import(memory, PLAN) is not None


def test_stale_remote_budget_invalidates_the_receipt() -> None:
    memory = MemoryStub([receipt(remoteAfter={**REMOTE, "policyRevision": 1})])
    assert current_budget_policy_import(memory, PLAN) is None


def test_changed_local_policy_invalidates_the_receipt() -> None:
    memory = MemoryStub([receipt()])
    plan = {"legacyPolicy": {**LOCAL, "effectiveMonthlyAllowanceMicros": "700000"}, "crawlseo": {"budget": REMOTE}}
    assert current_budget_policy_import(memory, plan) is None


def test_missing_current_pointer_returns_none() -> None:
    memory = MemoryStub([])
    assert current_budget_policy_import(memory, PLAN) is None

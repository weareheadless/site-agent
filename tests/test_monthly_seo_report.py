import datetime

from site_agent.brain import monthly_seo_report
from site_agent.core.memory import Memory


class EvidenceService:
    def __init__(self):
        self.calls = []

    def prepare_monthly_site_evidence(self, period, idempotency_key, max_crawl_pages):
        self.calls.append(("prepare", period, idempotency_key, max_crawl_pages))
        return {
            "schema_version": 1,
            "period": period,
            "status": "ready",
            "gsc": {"status": "ready", "top_queries": [], "top_pages": []},
            "ga4": {"status": "ready", "totals": {}, "top_pages": [], "sources": []},
            "crawl": {"status": "ready", "issue_count": 0, "issues": []},
            "history": {"gsc_months": [], "ga4_months": [], "history_state": "insufficient_history"},
            "freshness": {},
        }

    def monthly_site_evidence(self, period):
        self.calls.append(("read", period))
        raise AssertionError("a ready preparation must not be read again")


class ReportLlm:
    def __init__(self):
        self.calls = 0

    def chat(self, *_args, **_kwargs):
        self.calls += 1
        return "# Website SEO report: 2026-07\n\nTraffic was steady.\n\n## Prioritized next steps\n1. Keep monitoring."


def _config():
    return {
        "seo": {
            "enabled": True,
            "site_report": {"enabled": True, "timezone": "America/Cancun", "max_crawl_pages": 250},
        }
    }


def test_previous_period_uses_configured_timezone():
    now = datetime.datetime(2026, 3, 1, 6, 30, tzinfo=datetime.timezone.utc)
    assert monthly_seo_report.previous_period(_config(), now) == "2026-02"


def test_report_prepares_first_party_evidence_once_and_persists_artifact(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    service = EvidenceService()
    llm = ReportLlm()
    context = {"config": _config(), "memory": memory, "crawlseo_service": service, "llm": llm, "persona_prompt": "Be clear."}
    period = monthly_seo_report.previous_period(_config())
    try:
        monthly_seo_report.run(context)
        report = memory.get_seo_site_report_for_period(period)
        assert report is not None
        assert report["status"] == "completed"
        assert report["artifact_id"] is not None
        assert memory.get_artifact(report["artifact_id"]).preview_data["body"].startswith("# Website SEO")
        assert service.calls == [("prepare", period, f"site-report:{period}:v1", 250)]
        assert llm.calls == 1

        monthly_seo_report.run(context)
        assert service.calls == [("prepare", period, f"site-report:{period}:v1", 250)]
        assert llm.calls == 1
    finally:
        memory.close()

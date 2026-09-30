from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from site_agent.application.designs import DesignService
from site_agent.application.workspace import Tenant, TenantRegistry
from site_agent.core.design_contracts import SiteIntake
from site_agent.core.memory import Memory
from site_agent.hands.site_build import PELICAN_BASELINE_PROFILE, SiteOutputArtifactStore
from site_agent.web.workspace import register_workspace_routes


def _preview_tenant(tmp_path):
    memory = Memory(tmp_path / "memory.db")
    site = tmp_path / "site"
    site.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    (output / "index.html").write_text(
        "<html><head><title>Candidate</title></head>"
        "<body><a href=\"/about.html\">About</a></body></html>",
        encoding="utf-8",
    )
    store = SiteOutputArtifactStore(tmp_path / "artifacts")
    service = DesignService(
        memory,
        config={"site": {"clone_path": str(site)}, "data_dir": str(tmp_path / "data")},
        output_artifact_store=store,
    )
    run = service.create_run(
        SiteIntake.from_dict({
            "schema_version": 1,
            "business": {
                "name": "Preview Studio",
                "offer_summary": "A candidate site.",
                "primary_services": ["Website design"],
            },
            "audience": {"primary": "Owners"},
            "conversion": {"primary_action": "Contact", "not_available": True},
            "brand": {"voice": "Clear"},
            "site": {"required_pages": ["index.html"]},
        }),
        run_id="preview-run",
        base_sha="a" * 40,
        mode="production_candidate",
        candidate_ref="refs/ada-design/preview-run",
        publishable=True,
    )
    candidate_sha = "b" * 40
    published = store.publish(output, profile=PELICAN_BASELINE_PROFILE, candidate_sha=candidate_sha)
    memory.update_design_run(
        run["run_id"],
        candidate_sha=candidate_sha,
        candidate_ref=run["candidate_ref"],
        output_artifact_id=published["artifact_id"],
        output_tree_hash=published["tree_hash"],
        artifact_required=True,
        quality_report_json={"state": "passed", "gates": {"output": "passed"}},
    )
    for status in ("assessing_intake", "planning", "building", "candidate_ready", "validating", "ready_for_review"):
        memory.transition_design_run(run["run_id"], status)

    class Runtime:
        def close(self):
            pass

    tenant = Tenant(
        tenant_id="preview-site",
        config={},
        memory=memory,
        runtime=Runtime(),
        context={"design_service": service},
        api_token="tenant-secret",
    )
    return memory, TenantRegistry({tenant.tenant_id: tenant})


def test_workspace_preview_issues_scoped_link_and_serves_retained_artifact(tmp_path):
    memory, registry = _preview_tenant(tmp_path)
    app = FastAPI()
    register_workspace_routes(
        app,
        config={},
        env={},
        service=None,
        registry=registry,
        prefix="/v1/workspace",
    )
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer tenant-secret"}
            token_response = client.get(
                "/v1/workspace/design/runs/preview-run/preview-token",
                headers=headers,
            )
            assert token_response.status_code == 200
            token_data = token_response.json()
            assert token_data["candidate_sha"] == "b" * 40
            assert token_data["preview_url"].startswith("http://testserver/v1/workspace/")

            preview_url = urlsplit(token_data["preview_url"])
            page = client.get(preview_url.path + "?" + preview_url.query)
            assert page.status_code == 200
            assert b"Candidate" in page.content
            assert b'href="/about.html"' not in page.content
            assert b'href="./about.html?' in page.content
            assert page.headers["x-preview-candidate-sha"] == "b" * 40

            pages = client.get(
                "/v1/workspace/design/runs/preview-run/pages",
                headers=headers,
            )
            assert pages.status_code == 200
            assert pages.json()["pages"] == ["index.html"]

            denied = client.get("/v1/workspace/design/runs/preview-run/preview/index.html")
            assert denied.status_code == 401
    finally:
        registry.close()

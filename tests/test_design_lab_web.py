import json

from fastapi.testclient import TestClient

from site_agent.web.design_lab import create_app


def test_design_lab_comparison_server_is_read_only_and_mounts_artifacts(tmp_path):
    run_id = "design-lab-test"
    reports = tmp_path / "reports" / run_id
    reports.mkdir(parents=True)
    for variant in ("baseline", "candidate"):
        artifact = tmp_path / "artifacts" / run_id / variant
        artifact.mkdir(parents=True)
        (artifact / "_next").mkdir()
        (artifact / "images").mkdir()
        (artifact / "_next" / "app.css").write_text("body { color: red; }")
        (artifact / "images" / "hero.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        (artifact / "index.html").write_text(
            f'<link rel="stylesheet" href="/_next/app.css"><img src="/images/hero.svg"><a href="/articles.html">{variant}</a><a href="/">Home</a><script src="/_next/client.js"></script><script src="/_next/renderer.js"></script>'
        )
    result = {
        "run_id": run_id,
        "baseline_sha": "a" * 40,
        "candidate_sha": "b" * 40,
        "quality": {"state": "passed"},
    }
    comparison = {
        "run_id": run_id,
        "pages": [{
            "path": "index.html",
            "baseline": f"/artifacts/{run_id}/baseline/index.html",
            "candidate": f"/artifacts/{run_id}/candidate/index.html",
        }],
        "quality": {"state": "passed"},
    }
    (reports / "run.json").write_text(json.dumps(result))
    (reports / "comparison.json").write_text(json.dumps(comparison))

    client = TestClient(create_app(tmp_path, run_id))
    assert client.get("/health").json() == {"status": "ok", "mode": "read_only"}
    assert "Approve" not in client.get(f"/?run={run_id}").text
    response = client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["pages"][0]["path"] == "index.html"
    artifact_response = client.get(f"/artifacts/{run_id}/candidate/index.html")
    assert artifact_response.status_code == 200
    assert f"/artifacts/{run_id}/candidate/_next/app.css" in artifact_response.text
    assert f"/artifacts/{run_id}/candidate/images/hero.svg" in artifact_response.text
    assert f"/artifacts/{run_id}/candidate/articles.html" in artifact_response.text
    assert f"/artifacts/{run_id}/candidate/index.html" in artifact_response.text
    assert f"/artifacts/{run_id}/candidate/_next/client.js" in artifact_response.text
    assert f"/artifacts/{run_id}/candidate/_next/renderer.js" in artifact_response.text
    assert client.get(f"/artifacts/{run_id}/candidate/_next/app.css").status_code == 200
    assert client.get(f"/artifacts/{run_id}/candidate/images/hero.svg").status_code == 200
    assert client.get(f"/artifacts/{run_id}/candidate/%2e%2e/baseline/index.html").status_code in {400, 404}

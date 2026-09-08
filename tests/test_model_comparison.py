import json

import pytest
from fastapi.testclient import TestClient

from site_agent.application.model_comparison import ModelComparisonError, load_model_comparison
from site_agent.web.design_lab import create_model_comparison_app


def _matrix(tmp_path):
    models = []
    for model_id, label, model in (
        ("gemini", "Gemini", "google/gemini-2.5-pro"),
        ("gpt-5-6-luna", "GPT-5.6 Luna", "openai/gpt-5.6-luna"),
        ("deepseek", "DeepSeek V4 0731", "deepseek/deepseek-v4-flash-0731"),
    ):
        workspace = tmp_path / model_id
        run_id = f"{model_id}-run"
        report = workspace / "reports" / run_id
        artifact = workspace / "artifacts" / run_id / "candidate"
        report.mkdir(parents=True)
        artifact.mkdir(parents=True)
        (artifact / "index.html").write_text(
            f'<link rel="stylesheet" href="/styles.css"><h1>{label}</h1><a href="/articles.html">Journal</a>'
        )
        (report / "run.json").write_text(json.dumps({
            "schema_version": 1,
            "ok": True,
            "run_id": run_id,
            "candidate_sha": model_id * 40,
            "baseline_sha": "a" * 40,
            "quality": {"state": "passed"},
            "comparison": {"pages": [{"path": "index.html"}]},
        }))
        models.append({
            "id": model_id,
            "label": label,
            "model": model,
            "workspace": str(workspace),
            "run_id": run_id,
        })
    manifest = tmp_path / "model-comparison.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "comparison_id": "oceanicvibes-test",
        "subject": "OceanicVibes",
        "models": models,
    }))
    return manifest


def test_model_comparison_loads_three_retained_candidates_and_restricts_artifacts(tmp_path):
    manifest = _matrix(tmp_path)
    comparison = load_model_comparison(manifest)

    result = comparison.to_dict()
    assert [model["id"] for model in result["models"]] == ["gemini", "gpt-5-6-luna", "deepseek"]
    assert result["pages"] == ["index.html"]
    assert result["models"][0]["candidates"]["index.html"].startswith("/model-artifacts/gemini/")
    assert comparison.artifact_path("gemini", "gemini-run", "candidate", "index.html").is_file()

    with pytest.raises(ModelComparisonError):
        comparison.artifact_path("gemini", "deepseek-run", "candidate", "index.html")


def test_model_comparison_server_is_read_only_and_rewrites_candidate_assets(tmp_path):
    manifest = _matrix(tmp_path)
    client = TestClient(create_model_comparison_app(manifest))

    assert client.get("/health").json() == {"status": "ok", "mode": "read_only"}
    assert "Approve" not in client.get("/").text
    response = client.get("/api/model-comparison")
    assert response.status_code == 200
    assert len(response.json()["models"]) == 3
    artifact = client.get("/model-artifacts/gemini/gemini-run/candidate/index.html")
    assert artifact.status_code == 200
    assert "/model-artifacts/gemini/gemini-run/candidate/styles.css" in artifact.text
    assert client.get("/model-artifacts/gemini/gemini-run/candidate/%2e%2e/run.json").status_code in {400, 404}


def test_model_comparison_rejects_workspaces_outside_manifest_root(tmp_path):
    manifest = tmp_path / "model-comparison.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "models": [{"id": "escape", "workspace": str(tmp_path.parent), "run_id": "run"}],
    }))

    with pytest.raises(ModelComparisonError, match="under the manifest directory"):
        load_model_comparison(manifest)

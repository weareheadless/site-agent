from copy import deepcopy
from types import SimpleNamespace

import pytest

from site_agent.application.designs import DesignService, DesignServiceError


def lineage():
    parent = {"run_id": "parent", "base_sha": "b" * 40, "candidate_sha": "a" * 40,
              "parent_run_id": "", "mode": "production_candidate", "publishable": True}
    child = {"run_id": "child", "base_sha": "a" * 40, "candidate_sha": "c" * 40,
             "source_candidate_sha": "a" * 40, "parent_run_id": "parent",
             "operation_kind": "visual_refinement", "mode": "production_candidate", "publishable": True,
             "status": "ready_for_review", "quality_report_json": {"state": "passed"}}
    return {"parent": parent, "child": child}


def test_approval_resolves_production_base_without_rewriting_generation_base():
    runs = lineage()
    before = deepcopy(runs)
    service = DesignService(SimpleNamespace(get_design_run=runs.get))
    assert service.publication_base_sha(runs["child"]) == "b" * 40
    assert service.publication_base_sha(runs["parent"]) == "b" * 40
    assert runs == before


@pytest.mark.parametrize("defect", ["missing", "source", "base", "cycle", "mode", "unpublishable", "invalid-root"])
def test_publication_base_fails_closed_for_invalid_parent_chain(defect):
    runs = lineage()
    if defect == "missing":
        del runs["parent"]
    elif defect == "source":
        runs["child"]["source_candidate_sha"] = "d" * 40
    elif defect == "base":
        runs["child"]["base_sha"] = "d" * 40
    elif defect == "cycle":
        runs["parent"].update(parent_run_id="child", base_sha="c" * 40, source_candidate_sha="c" * 40)
    elif defect == "mode":
        runs["parent"]["mode"] = "experiment"
    elif defect == "unpublishable":
        runs["parent"]["publishable"] = False
    else:
        runs["parent"]["base_sha"] = "not-a-sha"
    service = DesignService(SimpleNamespace(get_design_run=runs.get))
    with pytest.raises(DesignServiceError):
        service.publication_base_sha(runs["child"])


def test_design_approval_passes_explicit_publication_base_to_existing_merger():
    runs = lineage()
    draft = {"id": 6, "kind": "design", "status": "pending", "meta": {
        "run_id": "child", "candidate_sha": "c" * 40, "base_sha": "a" * 40}}
    memory = SimpleNamespace(get_design_run=runs.get, list_drafts=lambda **_: [draft],
                             update_draft_status=lambda *_: None, add_design_run_event=lambda *_: None)
    service = DesignService(memory)
    service.get_run = lambda run_id: runs[run_id]
    observed = []

    def merge(run):
        observed.append(run)
        assert run["publication_base_sha"] == "b" * 40
        return {"merged": True, "candidate_sha": run["candidate_sha"]}

    service.approve_review_draft(6, merge)
    assert observed[0]["base_sha"] == "a" * 40
    assert "publication_base_sha" not in runs["child"]


def test_a_failed_publication_can_retry_the_same_exact_approval():
    runs = lineage()
    draft = {"id": 6, "kind": "design", "status": "publish_failed", "meta": {
        "run_id": "child", "candidate_sha": "c" * 40, "base_sha": "a" * 40}}
    memory = SimpleNamespace(get_design_run=runs.get, list_drafts=lambda **_: [draft],
                             update_draft_status=lambda *_: None, add_design_run_event=lambda *_: None)
    service = DesignService(memory)
    service.get_run = lambda run_id: runs[run_id]
    merged = []
    result = service.approve_review_draft(6, lambda run: merged.append(run["candidate_sha"]) or {
        "merged": True, "candidate_sha": run["candidate_sha"]})
    assert merged == ["c" * 40]
    assert result["published"]["merged"] is True


def test_an_already_merged_retry_still_fails_closed():
    runs = lineage()
    draft = {"id": 6, "kind": "design", "status": "publish_failed", "meta": {
        "run_id": "child", "candidate_sha": "c" * 40, "base_sha": "a" * 40}}
    memory = SimpleNamespace(get_design_run=runs.get, list_drafts=lambda **_: [draft],
                             update_draft_status=lambda *_: None, add_design_run_event=lambda *_: None)
    service = DesignService(memory)
    service.get_run = lambda run_id: runs[run_id]
    with pytest.raises(DesignServiceError, match="production branch advanced"):
        service.approve_review_draft(6, lambda run: {
            "merged": False, "reason": "production branch advanced since this candidate was built"})

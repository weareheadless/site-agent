import json
import os
import subprocess
from pathlib import Path

from site_agent.application.design_lab import DesignLabService, path_sentinel
from site_agent.core.design_contracts import DesignCandidateReceipt, DesignManifest, SiteIntake, canonical_hash, canonical_json
from site_agent.hands.site_build import SiteBuildResult


def _intake():
    return SiteIntake.from_dict({
        "schema_version": 1,
        "business": {
            "name": "Test Current",
            "offer_summary": "A considered service",
            "primary_services": ["A clear first step"],
            "location": "The stated place",
            "verified_trust_evidence": [],
        },
        "audience": {"primary": "People making a careful decision"},
        "conversion": {"primary_action": "Start a conversation", "not_available": True},
        "brand": {"voice": "Clear and calm", "visual_preferences": []},
        "site": {"required_pages": ["index.html", "articles.html"], "navigation_intent": ["Philosophy", "Training", "Contact", "Journal"]},
        "constraints": {},
        "assets": [],
        "unknowns": ["The destination is not supplied."],
    })


def _git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


def _remote(tmp_path):
    bare = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    (seed / "build.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nrm -rf output\nmkdir -p output\ncat > output/index.html <<'EOF'\n<!doctype html><html lang=\"en\"><head><title>Baseline</title><meta name=\"description\" content=\"Baseline\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head><body><header>Header</header><main><h1>Baseline</h1><a href=\"/articles.html\">Journal</a></main><footer>Footer</footer></body></html>\nEOF\ncp output/index.html output/articles.html\n"
    )
    (seed / "build.sh").chmod(0o755)
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "baseline")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-q", "origin", "main")
    return bare


class _NativeBuilder:
    """Small source-authoring double; no planner or compiler is involved."""

    def build_design(self, request, target, progress=None):
        root = Path(target.clone_path)
        (root / "src/pages").mkdir(parents=True, exist_ok=True)
        (root / "design").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(json.dumps({
            "name": "native-candidate",
            "private": True,
            "type": "module",
            "scripts": {"check": "astro check", "build": "astro build"},
            "dependencies": {
                "@astrojs/check": "0.9.10",
                "@astrojs/react": "4.4.2",
                "@gsap/react": "2.1.2",
                "@types/node": "22.20.1",
                "@types/react": "19.2.18",
                "@types/react-dom": "19.2.5",
                "astro": "5.18.2",
                "gsap": "3.12.5",
                "react": "19.2.8",
                "react-dom": "19.2.8",
                "typescript": "5.9.3",
            },
        }, sort_keys=True), encoding="utf-8")
        (root / "astro.config.mjs").write_text("export default {};\n", encoding="utf-8")
        (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        locked = {
            "@astrojs/check": "0.9.10",
            "@astrojs/react": "4.4.2",
            "@gsap/react": "2.1.2",
            "@types/node": "22.20.1",
            "@types/react": "19.2.18",
            "@types/react-dom": "19.2.5",
            "astro": "5.18.2",
            "gsap": "3.12.5",
            "react": "19.2.8",
            "react-dom": "19.2.8",
            "typescript": "5.9.3",
        }
        (root / "package-lock.json").write_text(
            json.dumps({
                "name": "native-candidate",
                "version": "0.0.0",
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "native-candidate", "dependencies": locked},
                    **{f"node_modules/{name}": {"version": version} for name, version in locked.items()},
                },
            }),
            encoding="utf-8",
        )
        (root / "src/pages/index.astro").write_text(
            "<html lang=\"en\"><body><h1>A considered service</h1><p>A clear first step.</p></body></html>\n",
            encoding="utf-8",
        )
        manifest = DesignManifest.from_dict({
            "schema_version": 1,
            "source_homepage_path": "src/pages/index.astro",
            "design_direction_id": "native-test",
            "intake_hash": request.site_intake_hash,
            "tokens": {},
            "shared_regions": [],
        })
        manifest_path = root / "design/ada-design-manifest.json"
        manifest_path.write_text(canonical_json(manifest.to_dict()) + "\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=ada@site-agent.local", "-c", "user.name=Ada", "commit", "-qm", "native candidate"],
            check=True,
            capture_output=True,
        )
        candidate_sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(["git", "-C", str(root), "update-ref", target.candidate_ref, candidate_sha], check=True, capture_output=True)
        return DesignCandidateReceipt.from_dict({
            "run_id": request.run_id,
            "operation_kind": target.operation_kind,
            "base_sha": target.base_sha,
            "candidate_sha": candidate_sha,
            "candidate_ref": target.candidate_ref,
            "diff_summary": "native source authored",
            "changed_paths": ["package.json", "package-lock.json", "astro.config.mjs", "tsconfig.json", "src/pages/index.astro", "design/ada-design-manifest.json"],
            "manifest_path": "design/ada-design-manifest.json",
            "manifest_hash": canonical_hash(manifest.to_dict()),
            "opencode_session_id": "native-test-session",
            "transcript_path": "design-runs/native-test/opencode.jsonl",
            "provider": "test",
            "model": "native-test",
            "publishable": False,
            "design_manifest": manifest.to_dict(),
        })


def test_design_lab_retains_artifacts_without_live_or_remote_mutation(tmp_path, monkeypatch):
    remote = _remote(tmp_path)
    live = tmp_path / "live-data"
    live.mkdir()
    (live / "state.db").write_text("unchanged")
    before_live = path_sentinel(live)
    before_remote = _git(remote, "show-ref").stdout

    def fake_build(root, profile, **kwargs):
        output = root / profile.output_dir
        output.mkdir(parents=True, exist_ok=True)
        (output / "index.html").write_text(
            '<!doctype html><html lang="en"><head><title>Candidate</title><meta name="description" content="Candidate"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><header>Header</header><main><h1>Candidate</h1><p>A considered service. A clear first step.</p><a href="/articles.html">Journal</a></main><footer>Footer</footer></body></html>'
        )
        (output / "articles.html").write_text(
            '<!doctype html><html lang="en"><head><title>Articles</title><meta name="description" content="Articles"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><header>Header</header><main><h1>Articles</h1><p>A considered service. A clear first step.</p></main><footer>Footer</footer></body></html>'
        )
        return SiteBuildResult(profile.name, True, profile.output_dir, ({"command": list(profile.build_command), "status": "passed"},), ("index.html", "articles.html"))

    monkeypatch.setattr("site_agent.application.design_lab.build_site", fake_build)
    monkeypatch.setattr("site_agent.application.designs.build_site", fake_build)
    config = {
        "site": {"repository": str(remote), "branch": "main"},
        "data_dir": str(live),
        "env": {"llm_api_key": "SITE_AGENT_LLM_API_KEY"},
        "design_engine": {"repair_attempts": 0},
    }
    result = DesignLabService(
        config,
        tmp_path / "lab",
        env={"PATH": os.environ["PATH"], "SITE_AGENT_LLM_API_KEY": "model-secret", "GITHUB_TOKEN": "must-not-pass"},
        builder=_NativeBuilder(),
    ).generate(_intake(), browser=False)

    assert result["ok"] is True
    assert result["baseline_sha"] == _git(tmp_path / "lab" / "source.git-or-clone", "rev-parse", "refs/remotes/origin/main").stdout.strip()
    assert result["candidate_ref"] == f"refs/ada-design-lab/{result['run_id']}"
    assert result["remote_refs_unchanged"] is True
    assert result["live_paths_unchanged"] is True
    assert path_sentinel(live) == before_live
    assert _git(remote, "show-ref").stdout == before_remote
    assert (tmp_path / "lab" / "artifacts" / result["run_id"] / "baseline" / "index.html").is_file()
    assert (tmp_path / "lab" / "artifacts" / result["run_id"] / "candidate" / "index.html").is_file()
    retained = json.loads((tmp_path / "lab" / "reports" / result["run_id"] / "run.json").read_text())
    assert retained["candidate_sha"] == result["candidate_sha"]


def test_design_lab_rejects_workspace_overlapping_live_data(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    service = DesignLabService({"data_dir": str(live), "site": {"repository": "owner/repo"}}, live / "lab")
    try:
        service.generate(_intake(), browser=False)
    except Exception as exc:
        assert "overlaps a live path" in str(exc)
    else:
        raise AssertionError("overlapping design-lab workspace was accepted")


def test_design_lab_has_no_planner_or_compiler_injection_surface():
    assert "planner" not in DesignLabService.__init__.__code__.co_varnames
    assert "compiler" not in DesignLabService.__init__.__code__.co_varnames

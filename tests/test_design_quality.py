import hashlib
import json
import subprocess
import pytest

from tests.test_design_contracts import _experience_plan
from site_agent.core.design_contracts import DesignManifest, ExperiencePlanBundle
from site_agent.hands.design_quality import (
    QualityPolicy,
    _compact_browser_result,
    _font_findings,
    _native_source_findings,
    _repository_findings,
    run_quality_gates as _run_quality_gates,
)


def run_quality_gates(*args, **kwargs):
    # These tests exercise downstream gates against deliberately prebuilt
    # fixture output. Production callers must provide canonical host-build evidence.
    kwargs.setdefault("build_evidence", {
        "status": "passed",
        "profile": "next_react",
        "source": "prebuilt_test_fixture",
    })
    return _run_quality_gates(*args, **kwargs)


def test_browser_evidence_compaction_drops_repeated_dom_fingerprints():
    huge = "data:image/svg+xml;base64," + ("A" * 200_000)
    condition = {
        "condition_id": "scene-1-visible",
        "scene_id": "scene-1",
        "visible": True,
        "observed_transition": True,
        "rendered_fingerprint": {"text": huge, "descendants": [{"backgroundImage": huge}]},
    }
    raw = {
        "routes": [{
            "journey_conditions_before": [condition],
            "journey_conditions_after": [condition],
            "motion_preferences": {
                "no-preference": {
                    "scroll_states": [{
                        "position": 0,
                        "journey_conditions": [condition],
                        "observable": {
                            "critical_content_visible": True,
                            "nodes": [{"visible": True, "fingerprint": {"backgroundImage": huge}}],
                        },
                    }],
                },
            },
        }],
    }

    compact = _compact_browser_result(raw)
    encoded = json.dumps(compact)

    assert len(encoded.encode("utf-8")) < 10_000
    state = compact["routes"][0]["motion_preferences"]["no-preference"]["scroll_states"][0]
    assert state["journey_conditions"][0]["condition_id"] == "scene-1-visible"
    assert state["journey_conditions"][0]["observed_transition"] is True
    assert state["observable_summary"]["critical_content_visible"] is True


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "package.json").write_text('{"scripts":{"build":"next build"}}\n')
    (repo / "next.config.mjs").write_text("export default { output: 'export' };\n")
    (repo / "src" / "app").mkdir(parents=True)
    (repo / "src" / "app" / "page.tsx").write_text("export default function Page() { return null; }\n")
    (repo / "payload.config.ts").write_text("export {};\n")
    (repo / "index.html").write_text("baseline")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, sha


def _policy(**overrides):
    values = {
        "output_dir": "out",
        "allowed_patterns": ("index.html", "out/**"),
        "required_pages": ("index.html",),
    }
    values.update(overrides)
    return QualityPolicy(**values)


def test_missing_output_page_blocks_quality(tmp_path):
    repo, sha = _repo(tmp_path)

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-1",
        policy=_policy(),
    )

    assert report.state == "failed"
    assert any(finding["code"] == "missing_output" for finding in report.to_dict()["findings"])


def test_experience_plan_gates_use_browser_composition_and_temporal_evidence(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><style>main{display:block}</style></head>'
        '<body><main><img data-ada-asset-id="asset-logo" '
        'data-ada-asset-sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" '
        'data-ada-composition-role="logo" data-ada-focal-coverage="0.9" src="/logo.svg" alt="Logo">'
        '<nav data-ada-composition-role="navigation">Navigation</nav>'
         '<div data-ada-signature-behavior="measured-arrival">'
         '<section data-ada-journey-scene="arrival" data-ada-journey-condition="journey-arrival-visible" '
         'data-ada-journey-trigger="pointer-enter">'
         '<h1>Home</h1><p>Useful public copy stays visible at rest.</p></section>'
         '<section data-ada-journey-scene="commitment" data-ada-journey-condition="journey-commitment-readable" '
         'data-ada-journey-trigger="keyboard-focus">Commitment</section></main></body></html>'
    )
    plan = _experience_plan()
    experience_plan_hash = ExperiencePlanBundle.from_dict(plan).content_hash

    class Browser:
        def inspect(self, _output, _viewport):
            temporal = {
                "schema_version": 1,
                "candidate_sha": sha,
                "experience_plan_hash": experience_plan_hash,
                "route": "/index.html",
                "viewport": {"name": "desktop", "width": 1440, "height": 1000},
                "reduced_motion": False,
                "interaction_script_id": "bounded-controls-v1",
                "frames": [
                    {"phase": "before", "path": "candidate/desktop/before.png"},
                    {"phase": "intermediate", "path": "candidate/desktop/intermediate.png"},
                    {"phase": "after", "path": "candidate/desktop/after.png"},
                ],
                "layout_shifts": [{"value": 0.02}],
                "console_errors": [],
                "network_errors": [],
                "animation_observations": [{"id": "measured-arrival", "state": "observed"}],
                "keyboard_path_observations": ["logo", "navigation"],
                "resting_state_observations": {"critical_content_visible": True},
            }
            return {
                "status": "passed",
                "motion_preferences": {
                    "no-preference": {"journey_conditions": [
                            {"condition_id": "journey-arrival-visible", "scene_id": "arrival", "visible": True, "state": "completed", "completion": "arrival is visible"},
                            {"condition_id": "journey-commitment-readable", "scene_id": "commitment", "visible": True, "state": "active", "completion": "commitment is readable"},
                    ]},
                    "reduce": {"journey_conditions": [
                            {"condition_id": "journey-arrival-visible", "scene_id": "arrival", "visible": True, "state": "completed", "completion": "arrival is visible"},
                            {"condition_id": "journey-commitment-readable", "scene_id": "commitment", "visible": True, "state": "active", "completion": "commitment is readable"},
                    ]},
                },
                "routes": [{
                    "route": "index.html",
                    "journey_conditions_before": [
                        # A page-level condition can belong to a scene in the
                        # plan without identifying that scene in the rendered
                        # marker. It must not become a false leading scene in
                        # the ordered path.
                        {"condition_id": "journey-commitment-readable", "scene_id": "", "visible": True, "state": "rendered", "completion": ""},
                            {"condition_id": "journey-arrival-visible", "scene_id": "arrival", "visible": True, "state": "completed", "completion": "arrival is visible"},
                            {"condition_id": "journey-commitment-readable", "scene_id": "commitment", "visible": True, "state": "active", "completion": "commitment is readable"},
                    ],
                    "journey_conditions_after": [
                            {"condition_id": "journey-arrival-visible", "scene_id": "arrival", "visible": True, "state": "rendered", "completion": "", "observed_transition": True},
                            {"condition_id": "journey-commitment-readable", "scene_id": "commitment", "visible": True, "state": "rendered", "completion": "", "observed_transition": True},
                    ],
                    "composition_elements": [
                        {
                            "role": "logo",
                            "asset_id": "asset-logo",
                            "asset_sha256": "a" * 64,
                            "src": "/logo.svg",
                            "focal_coverage": 0.9,
                            "box": {"x": 20, "y": 20, "width": 180, "height": 40},
                        },
                        {"role": "navigation", "box": {"x": 320, "y": 20, "width": 400, "height": 40}},
                    ],
                 "temporal_evidence": [{
                     **temporal,
                     # These route-level observations are intentionally not
                     # part of the strict temporal evidence contract.
                     "journey_conditions_before": [],
                     "journey_conditions_after": [],
                 }],
                }],
                "external_requests": [],
            }

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-experience-plan",
        policy=_policy(browser_required=True, viewports=({"name": "desktop", "width": 1440, "height": 1000},)),
        browser=Browser(),
        experience_plan=plan,
    )

    data = report.to_dict()
    assert report.state == "passed", data
    assert data["gates"]["composition"] == "passed"
    assert data["gates"]["temporal"] == "passed"
    assert data["evidence"]["experience_journey"]["ordered_scene_paths"] == [{
        "route": "index.html",
        "viewport": "desktop",
        "scene_ids": ["arrival", "commitment"],
    }]

    class MissingSceneTransitionBrowser(Browser):
        def inspect(self, output_dir, viewport):
            result = super().inspect(output_dir, viewport)
            result["routes"][0]["journey_conditions_after"][1]["observed_transition"] = False
            return result

    missing_transition = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-experience-plan-missing-scene-transition",
        policy=_policy(browser_required=True, viewports=({"name": "desktop", "width": 1440, "height": 1000},)),
        browser=MissingSceneTransitionBrowser(),
        experience_plan=plan,
    )
    missing_data = missing_transition.to_dict()
    assert missing_transition.state == "failed", missing_data
    assert any(
        finding["code"] == "journey_scene_transition_missing"
        for finding in missing_data["findings"]
    )


def test_font_gate_requires_local_approved_woff2_and_face_declaration(tmp_path):
    repo, base_sha = _repo(tmp_path)
    data = b"wOF2-owner-font-bytes"
    digest = hashlib.sha256(data).hexdigest()
    (repo / "public" / "fonts").mkdir(parents=True)
    (repo / "public" / "fonts" / "owner.woff2").write_bytes(data)
    (repo / "src").mkdir(exist_ok=True)
    css = repo / "src" / "app" / "(frontend)" / "site.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    css.write_text(
        "@font-face { font-family: 'Owner Sans'; src: url('/fonts/owner.woff2') format('woff2'); }\n"
        "body { font-family: 'Owner Sans', sans-serif; }\n"
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "font candidate"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    evidence, findings = _font_findings(
        repo,
        base_sha,
        candidate_sha,
        _policy(
            required_font_families=("Owner Sans",),
            approved_font_files=({"path": "public/fonts/owner.woff2", "sha256": digest},),
        ),
    )

    assert findings == []
    assert evidence["status"] == "passed"
    assert evidence["font_hashes"]["public/fonts/owner.woff2"] == digest


def test_font_gate_allows_removed_font_assets(tmp_path):
    repo, initial_sha = _repo(tmp_path)
    font = repo / "public" / "fonts" / "removed.woff2"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"wOF2-font-to-remove")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "font baseline"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    font.unlink()
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "remove font"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    evidence, findings = _font_findings(repo, base_sha, candidate_sha, _policy())

    assert findings == []
    assert evidence["status"] == "passed"
    assert evidence["changed_font_files"] == ["public/fonts/removed.woff2"]
    assert evidence["removed_font_files"] == ["public/fonts/removed.woff2"]


def test_quality_policy_rejects_site_supplied_build_commands():
    with pytest.raises(ValueError, match="canonical host toolchain"):
        QualityPolicy.from_config({
            "design_engine": {
                "build_profile": "next_react",
                "quality": {"build_command": ["npm", "run", "build"]},
            },
        })


def test_quality_requires_canonical_build_evidence(tmp_path):
    repo, sha = _repo(tmp_path)
    report = _run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-no-build-evidence",
        policy=_policy(),
    )
    assert report.state == "failed"
    assert any(item["code"] == "build_evidence_missing" for item in report.to_dict()["findings"])


def test_required_content_blocks_quality_when_brief_items_are_missing(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1><p>Freediving instruction for curious people.</p></body></html>'
    )

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-content",
        policy=_policy(required_content=("AIDA 3 training in Bacalar", "Depth training in Bacalar")),
    )

    findings = report.to_dict()["findings"]
    assert report.state == "failed"
    assert {finding["requirement"] for finding in findings if finding["code"] == "missing_required_content"} == {
        "aida 3 training in bacalar",
        "depth training in bacalar",
    }
    assert report.to_dict()["evidence"]["content"]["status"] == "failed"


def test_required_content_ignores_hidden_text_and_normalizes_visible_markup(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1><p><strong>AIDA 3</strong> training in Bacalar.</p>'
        '<span aria-hidden="true">Depth training in Bacalar</span></body></html>'
    )

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-content-visible",
        policy=_policy(required_content=("AIDA 3 training in Bacalar", "Depth training in Bacalar")),
    )

    assert report.state == "failed"
    assert report.to_dict()["evidence"]["content"]["missing"] == ["depth training in bacalar"]


def test_unavailable_contact_destination_blocks_contact_links(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1><a href="mailto:invented@example.com">Start a conversation</a></body></html>'
    )

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-unavailable-contact",
        policy=_policy(contact_destination_unavailable=True),
    )

    findings = report.to_dict()["findings"]
    assert report.state == "failed"
    assert any(finding["code"] == "unsupported_contact_destination" for finding in findings)
    assert report.to_dict()["evidence"]["conversion"]["status"] == "failed"


def test_unavailable_contact_destination_blocks_social_and_booking_links(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1><a href="https://wa.me/15551234567">Message us</a>'
        '<a href="https://www.instagram.com/oceanicvibes/">Instagram</a></body></html>'
    )

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-unavailable-social-contact",
        policy=_policy(contact_destination_unavailable=True),
    )

    links = report.to_dict()["evidence"]["conversion"]["links"]
    assert {link["href"] for link in links} == {
        "https://wa.me/15551234567",
        "https://www.instagram.com/oceanicvibes/",
    }
    assert report.state == "failed"


def test_designed_quality_requires_author_styling_on_every_output_page(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1></body></html>'
    )

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-styling",
        policy=_policy(browser_required=True),
    )

    assert any(finding["code"] == "unstyled_page" for finding in report.to_dict()["findings"])


def test_leaked_source_and_secret_block_quality(tmp_path):
    repo, base_sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1></body></html>'
    )
    (output / "themes").mkdir()
    (output / "themes" / "leaked.jinja").write_text("secret")
    (repo / "secrets.txt").write_text("OPENAI_API_KEY=sk-abc123")

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=base_sha,
        run_id="run-2",
        policy=_policy(allowed_patterns=("index.html", "out/**", "themes/**", "secrets.txt")),
    )

    codes = {finding["code"] for finding in report.to_dict()["findings"]}
    assert report.state == "failed"
    assert {"source_leak", "secret"} <= codes


def test_unavailable_browser_is_incomplete_not_passed(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><style>body { color: black; }</style></head>'
        '<body><h1>Home</h1></body></html>'
    )

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-3",
        policy=_policy(browser_required=True),
    )

    assert report.state == "incomplete"
    assert any(finding["code"] == "browser_unavailable" for finding in report.to_dict()["findings"])


def test_root_relative_links_resolve_from_output_root(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    (output / "articles").mkdir(parents=True)
    page = lambda title, links: (
        '<html lang="en"><head><title>' + title + '</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>' + title + '</h1>' + links + '</body></html>'
    )
    (output / "index.html").write_text(page("Home", '<a href="/articles.html">Journal</a>'))
    (output / "articles.html").write_text(page("Journal", '<a href="/">Home</a>'))
    (output / "articles" / "story.html").write_text(
        page("Story", '<a href="/">Home</a><a href="/articles.html">Journal</a>')
    )

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-root-relative-links",
        policy=_policy(),
    )

    findings = report.to_dict()["findings"]
    assert not any(finding["code"] == "broken_link" for finding in findings)
    assert report.to_dict()["evidence"]["output"]["status"] == "passed"


def test_output_warnings_do_not_block_retained_artifact(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1><p>This form is a placeholder.</p></body></html>'
    )
    published = []

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-output-warning",
        policy=_policy(),
        output_artifact_publisher=lambda output_dir: published.append(output_dir) or {
            "artifact_id": "site-output-test",
            "tree_hash": "a" * 64,
        },
    )

    data = report.to_dict()
    assert data["evidence"]["output"]["status"] == "passed"
    assert data["evidence"]["output_artifact"]["status"] == "passed"
    assert published == [output]
    assert any(finding["code"] == "placeholder_text" for finding in data["findings"])


def test_quality_reads_candidate_commit_not_persistent_clone_worktree(tmp_path):
    repo, base_sha = _repo(tmp_path)
    (repo / "index.html").write_text("candidate source")
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Candidate</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Candidate</h1></body></html>'
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (output / "index.html").write_text("invalid persistent worktree content")

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        run_id="run-4",
        policy=_policy(),
    )

    assert report.state == "passed"


def test_quality_candidate_worktree_is_created_next_to_repository(tmp_path):
    repo, base_sha = _repo(tmp_path)
    (repo / "index.html").write_text("candidate source")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "candidate"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    workspaces = []

    def build_runner(workspace):
        workspaces.append(workspace)
        output = workspace / "out"
        output.mkdir()
        (output / "index.html").write_text(
            '<html lang="en"><head><title>Candidate</title>'
            '<meta name="description" content="A real page">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
            '<body><h1>Candidate</h1></body></html>'
        )
        return {"ok": True, "status": "passed"}

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=candidate_sha,
        run_id="run-quality-worktree-volume",
        policy=_policy(),
        build_runner=build_runner,
    )

    assert report.state == "passed"
    assert len(workspaces) == 1
    assert workspaces[0].parent == repo.parent


def test_manifest_gate_checks_declared_source_files_and_intake(tmp_path):
    repo, base_sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1></body></html>'
    )
    manifest = DesignManifest.from_dict({
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "design_direction_id": "quiet-tide",
        "intake_hash": "a" * 64,
        "tokens": {"accent": "#087f99"},
        "shared_regions": ["header", "footer"],
        "source_files": {"homepage": "index.html"},
    })
    (repo / "design").mkdir()
    (repo / "design" / "ada-design-manifest.json").write_text(json.dumps(manifest.to_dict()))

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=base_sha,
        run_id="run-manifest",
        policy=_policy(
            allowed_patterns=("index.html", "out/**", "design/**"),
            required_pages=("index.html",),
            manifest_path="design/ada-design-manifest.json",
            expected_intake_hash="a" * 64,
        ),
    )

    assert report.state == "passed"
    assert report.to_dict()["evidence"]["manifest"]["source_files_checked"] == ["index.html"]


def test_manifest_gate_ignores_descriptions_in_source_file_metadata(tmp_path):
    repo, base_sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1></body></html>'
    )
    manifest = DesignManifest.from_dict({
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "design_direction_id": "tideline-editorial",
        "intake_hash": "a" * 64,
        "tokens": {"accent": "#087f99"},
        "shared_regions": ["header", "footer"],
        "source_files": {
            "homepage": {"path": "index.html", "description": "homepage markup"},
            "design_system": {"path": "styles.css", "description": "Tokens, layout, responsive and reduced-motion behavior"},
            "motion_system": {"path": "app.js", "description": "GSAP entrance, reveals and depth choreography"},
        },
    })
    (repo / "design").mkdir()
    (repo / "design" / "ada-design-manifest.json").write_text(json.dumps(manifest.to_dict()))
    (repo / "styles.css").write_text("body { color: black; }")
    (repo / "app.js").write_text("console.log('ok');")

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=base_sha,
        run_id="run-manifest-descriptions",
        policy=_policy(
            allowed_patterns=("index.html", "styles.css", "app.js", "out/**", "design/**"),
            required_pages=("index.html",),
            manifest_path="design/ada-design-manifest.json",
            expected_intake_hash="a" * 64,
        ),
    )

    assert report.state == "passed"
    assert report.to_dict()["evidence"]["manifest"]["source_files_checked"] == ["app.js", "index.html", "styles.css"]


def test_host_runtime_files_are_staged_into_build_output(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1></body></html>'
    )
    (repo / "vendor" / "gsap").mkdir(parents=True)
    (repo / "vendor" / "gsap" / "gsap.min.js").write_text("verified runtime")
    manifest = DesignManifest.from_dict({
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "design_direction_id": "host-runtime",
        "intake_hash": "a" * 64,
        "tokens": {},
        "shared_regions": [],
        "source_files": {"changed": ["index.html"]},
    }).to_dict()
    manifest["host_generated"] = True
    manifest["host_metadata"] = {"provisioned_runtime_paths": ["vendor/gsap/gsap.min.js"]}
    (repo / "design").mkdir()
    (repo / "design" / "ada-design-manifest.json").write_text(json.dumps(manifest))

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-host-runtime",
        policy=_policy(
            allowed_patterns=("index.html", "out/**", "vendor/**", "design/**"),
            manifest_path="design/ada-design-manifest.json",
            expected_intake_hash="a" * 64,
        ),
    )

    assert report.state == "passed"
    assert (output / "vendor" / "gsap" / "gsap.min.js").read_text() == "verified runtime"
    assert report.to_dict()["evidence"]["runtime"]["paths"] == ["vendor/gsap/gsap.min.js"]


def test_host_runtime_paths_from_host_manifest_are_exempt_from_source_allowlist(tmp_path):
    repo, base_sha = _repo(tmp_path)
    (repo / "index.html").write_text("candidate")
    runtime = repo / "vendor" / "gsap" / "gsap.min.js"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("host-provisioned runtime")
    manifest = DesignManifest.from_dict({
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "intake_hash": "a" * 64,
        "source_files": {"changed": ["index.html"]},
    }).to_dict()
    manifest["host_generated"] = True
    manifest["host_metadata"] = {"provisioned_runtime_paths": ["vendor/gsap/gsap.min.js"]}
    (repo / "design").mkdir()
    (repo / "design" / "ada-design-manifest.json").write_text(json.dumps(manifest))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "host runtime candidate"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    findings = _repository_findings(
        repo,
        base_sha,
        candidate_sha,
        _policy(
            allowed_patterns=("index.html", "design/**"),
            manifest_path="design/ada-design-manifest.json",
        ),
    )

    assert not any(
        finding["code"] == "path_policy" and finding.get("path") == "vendor/gsap/gsap.min.js"
        for finding in findings
    )


def test_native_source_gate_does_not_scan_host_provisioned_runtime_files(tmp_path):
    repo, base_sha = _repo(tmp_path)
    tenant_source = repo / "src" / "components" / "site" / "presentation" / "App.tsx"
    tenant_source.parent.mkdir(parents=True)
    tenant_source.write_text("export function App() { return <main />; }")
    (repo / "src" / "app.js").write_text("document.body.dataset.ready = 'true';")
    runtime = repo / "public" / "vendor" / "gsap" / "gsap.min.js"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("gsap.registerPlugin(Draggable);")
    manifest = {
        "schema_version": 1,
        "source_homepage_path": "index.html",
        "source_files": {"homepage": "index.html", "app": "src/app.js"},
        "host_generated": True,
        "host_metadata": {"provisioned_runtime_paths": ["public/vendor/gsap/gsap.min.js"]},
    }
    (repo / "design").mkdir()
    (repo / "design" / "ada-design-manifest.json").write_text(json.dumps(manifest))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "host runtime candidate"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    evidence, findings = _native_source_findings(
        repo,
        base_sha,
        candidate_sha,
        _policy(
            native_source_required=True,
            manifest_path="design/ada-design-manifest.json",
            allowed_patterns=("index.html", "src/**", "design/**", "public/**"),
        ),
    )

    assert findings == []
    assert evidence["source_files"] == ["src/components/site/presentation/App.tsx"]
    assert evidence["host_provisioned_files"] == ["public/vendor/gsap/gsap.min.js"]


def test_native_source_gate_ignores_urls_inside_inline_data_css(tmp_path):
    repo, base_sha = _repo(tmp_path)
    css = repo / "src" / "app" / "(frontend)" / "site.css"
    css.parent.mkdir(parents=True)
    css.write_text(
        "body { background-image: url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3C/svg%3E\"); }\n"
    )
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "inline texture"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    evidence, findings = _native_source_findings(
        repo,
        base_sha,
        candidate_sha,
        _policy(
            native_source_required=True,
            allowed_patterns=("src/**",),
        ),
    )

    assert findings == []
    assert evidence["external_resources"] == []


def test_repair_native_source_gate_scans_retained_candidate_tree(tmp_path):
    repo, _ = _repo(tmp_path)
    presentation = repo / "src" / "components" / "site" / "presentation"
    presentation.mkdir(parents=True)
    (presentation / "LightDescent.tsx").write_text(
        'import { useGSAP } from "@gsap/react";\n'
        'import gsap from "gsap";\n'
        'export default function LightDescent() {\n'
        '  useGSAP(() => {\n'
        '    const timeline = gsap.timeline();\n'
        '    window.matchMedia("(prefers-reduced-motion: no-preference)");\n'
        '    return () => timeline.kill();\n'
        '  });\n'
        '  return <div />;\n'
        '}\n'
    )
    css = repo / "src" / "app" / "(frontend)" / "site.css"
    css.parent.mkdir(parents=True)
    css.write_text(
        '@media (prefers-reduced-motion: reduce) { * { transition: none; } }\n'
    )
    (repo / "package.json").write_text(json.dumps({
        "dependencies": {"@gsap/react": "2.1.2", "gsap": "3.12.5"},
    }))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "native parent"], check=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    css.write_text(
        '@media (prefers-reduced-motion: reduce) { * { transition: none; } }\n'
        '.hero { color: white; }\n'
    )
    subprocess.run(["git", "-C", str(repo), "add", "src/app/(frontend)/site.css"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "repair composition"], check=True)
    candidate_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    evidence, findings = _native_source_findings(
        repo,
        base_sha,
        candidate_sha,
        _policy(
            native_source_required=True,
            react_source_required=True,
            gsap_required=True,
            operation_kind="technical_repair",
            approved_capabilities=(
                {"package": "@gsap/react", "version": "2.1.2"},
                {"package": "gsap", "version": "3.12.5"},
            ),
            allowed_patterns=("index.html", "src/**", "out/**"),
        ),
    )

    assert findings == []
    expected = "src/components/site/presentation/LightDescent.tsx"
    assert expected in evidence["source_files"]
    assert evidence["react_source_files"] == [expected]
    assert evidence["gsap_usage_files"] == [expected]


def test_unapproved_dependency_change_is_blocked(tmp_path):
    repo, base_sha = _repo(tmp_path)
    (repo / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "1.3.0"}}))

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=base_sha,
        run_id="run-dependency-blocked",
        policy=_policy(
            allowed_patterns=("index.html", "out/**", "package.json"),
            approved_capabilities=({"package": "gsap", "version": "3.12.5"},),
        ),
    )

    assert report.state == "failed"
    assert any(finding["code"] == "dependency_not_approved" for finding in report.to_dict()["findings"])


def test_approved_exact_dependency_and_lockfile_pass(tmp_path):
    repo, base_sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1></body></html>'
    )
    (repo / "package.json").write_text(json.dumps({"dependencies": {"gsap": "3.12.5"}}))
    (repo / "package-lock.json").write_text(json.dumps({
        "name": "design",
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"gsap": "3.12.5"}},
            "node_modules/gsap": {"version": "3.12.5"},
        },
    }))

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=base_sha,
        run_id="run-dependency-approved",
        policy=_policy(
            allowed_patterns=("index.html", "out/**", "package.json", "package-lock.json"),
            approved_capabilities=({"package": "gsap", "version": "3.12.5"},),
            allowed_hard_denied_paths=("package.json",),
        ),
    )

    assert report.state == "passed"


def test_dependency_version_must_match_approved_pin(tmp_path):
    repo, base_sha = _repo(tmp_path)
    (repo / "package.json").write_text(json.dumps({"dependencies": {"gsap": "^3.12.5"}}))
    (repo / "package-lock.json").write_text(json.dumps({
        "lockfileVersion": 3,
        "packages": {"node_modules/gsap": {"version": "3.12.5"}},
    }))

    report = run_quality_gates(
        repo,
        base_sha=base_sha,
        candidate_sha=base_sha,
        run_id="run-dependency-unpinned",
        policy=_policy(
            allowed_patterns=("index.html", "out/**", "package.json", "package-lock.json"),
            approved_capabilities=({"package": "gsap", "version": "3.12.5"},),
            allowed_hard_denied_paths=("package.json",),
        ),
    )

    assert report.state == "failed"
    assert any(finding["code"] == "dependency_not_pinned" for finding in report.to_dict()["findings"])


def test_browser_evidence_blocks_contrast_and_unreduced_motion(tmp_path):
    repo, sha = _repo(tmp_path)
    output = repo / "out"
    output.mkdir()
    (output / "index.html").write_text(
        '<html lang="en"><head><title>Home</title>'
        '<meta name="description" content="A real page">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body><h1>Home</h1></body></html>'
    )

    class Browser:
        def inspect(self, _output, viewport):
            return {
                "routes": [{
                    "route": "index.html",
                    "keyboard": {"focusable_count": 0, "focus_visible": True},
                    "motion_preferences": {
                        "no-preference": {"motion_observed": True, "observable_delta": {"observed": True}},
                        "reduce": {"motion_observed": True, "observable_delta": {"observed": True}},
                    },
                }],
                "hidden_resting_text": [{
                    "route": "index.html",
                    "details": [{"tag": "h1", "text": "Hidden headline"}],
                }],
                "contrast_failures": [{"text": "Home", "ratio": 2.1}],
                "font_load_failures": [{"family": "Brand Sans", "loaded": False}],
                "low_resolution_images": [{"src": "hero.jpg", "natural_width": 100, "rendered_width": 400}],
                "text_wrap_failures": [{"route": "index.html", "text": "One word per line."}],
            }

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-browser-evidence",
        policy=_policy(browser_required=True),
        browser=Browser(),
    )

    findings = report.to_dict()["findings"]
    codes = {finding["code"] for finding in findings}
    assert report.state == "failed"
    assert {"contrast_failure", "reduced_motion_unsettled", "font_load_failure", "low_resolution_image", "text_wrap_failure", "resting_text_hidden"} <= codes


def test_server_rendered_build_skips_static_output_gates_without_failing(tmp_path):
    """A Next/Payload candidate has no `out/` tree, and that is not a failure.

    The static-output, content, conversion and browser gates inspect a static
    export. For a server-rendered build they are not applicable; marking them
    failed discarded a candidate whose build had already passed.
    """
    repo, sha = _repo(tmp_path)

    report = run_quality_gates(
        repo,
        base_sha=sha,
        candidate_sha=sha,
        run_id="run-server-rendered",
        policy=_policy(static_output_required=False),
    )

    data = report.to_dict()
    assert data["state"] == "passed"
    assert not any(finding["code"] == "missing_output" for finding in data["findings"])
    evidence = data["evidence"]
    assert evidence["output"]["status"] == "skipped"
    assert evidence["output"]["reason"] == "server_rendered_build_has_no_static_output"
    assert evidence["content"]["status"] == "skipped"
    assert evidence["browser"]["status"] == "skipped"
    # Browser-derived experience gates are deferred to the deployed site, not
    # reported as passing evidence.
    assert data["gates"]["experience_journey"] == "skipped"
    assert data["gates"]["composition"] == "skipped"
    assert data["gates"]["temporal"] == "skipped"
    assert evidence["build"]["status"] == "passed"

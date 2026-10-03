import json
from pathlib import Path

import site_agent.hands.site_build as site_build
from site_agent.hands.site_build import (
    NEXT_REACT_PROFILE,
    NEXT_REACT_TOOLCHAIN_DEPENDENCIES,
    build_site,
    prepare_native_workspace,
)
from site_agent.frontend_ownership import is_frontend_owned_path
from site_agent.site_scaffold import initialize_toolchain_workspace


def test_next_react_build_profile_is_explicit_and_safe():
    assert NEXT_REACT_PROFILE.name == "next_react"
    assert NEXT_REACT_PROFILE.output_dir == "out"
    assert "npm" in " ".join(NEXT_REACT_PROFILE.build_command)


def test_shared_frontend_ownership_allows_presentation_and_rejects_platform_paths():
    assert is_frontend_owned_path("src/components/site/Hero.tsx")
    assert is_frontend_owned_path("src/app/(frontend)/site.css")
    for path in (
        "src/collections/Pages.ts", "src/app/api/helloada/route.ts", "src/components/admin/Nav.tsx",
        "src/lib/content.ts", "payload.config.ts", "package.json", "public/brand/helloada.svg",
        "src/components/site/../../collections/Pages.ts", "/src/components/site/Hero.tsx",
    ):
        assert not is_frontend_owned_path(path), path


def test_next_react_lint_excludes_generated_and_host_trees():
    lint_command = NEXT_REACT_PROFILE.check_commands[1]
    ignored = {
        lint_command[index + 1]
        for index, value in enumerate(lint_command[:-1])
        if value == "--ignore-pattern"
    }

    assert ignored == set(site_build.NEXT_REACT_LINT_IGNORE_PATTERNS)
    assert lint_command[:5] == ("npm", "exec", "--", "eslint", "src")


def test_prepare_native_workspace_bootstraps_only_technical_next_files(tmp_path):
    workspace = tmp_path / "site"
    workspace.mkdir()

    created = prepare_native_workspace(workspace, NEXT_REACT_PROFILE)

    assert set(created) == {
        ".gitignore", "eslint.config.mjs", "next-env.d.ts", "next.config.mjs", "package.json",
        "payload.config.ts", "src/app/layout.tsx", "src/app/page.tsx", "tsconfig.json",
    }
    package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    declared = {**package["dependencies"], **package["devDependencies"]}
    assert declared == {
        item["package"]: item["version"] for item in NEXT_REACT_TOOLCHAIN_DEPENDENCIES
    }
    assert (workspace / "src" / "app" / "page.tsx").is_file()
    eslint_config = (workspace / "eslint.config.mjs").read_text(encoding="utf-8")
    assert "'.open-next/**'" in eslint_config
    assert "'dist/**'" in eslint_config
    assert prepare_native_workspace(workspace, NEXT_REACT_PROFILE) == ()


def test_build_site_runs_profile_commands_in_workspace(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(site_build, "_is_noexec_mount", lambda _path: False)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        (Path(kwargs["cwd"]) / "out").mkdir(exist_ok=True)
        (Path(kwargs["cwd"]) / "tsconfig.tsbuildinfo").write_text("generated", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("site_agent.hands.site_build.subprocess.run", fake_run)

    workspace = initialize_toolchain_workspace(tmp_path / "site", "Native Site")
    package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    declared = {
        **package["dependencies"],
        **package["devDependencies"],
    }
    (workspace / "package-lock.json").write_text(json.dumps({
        "name": package["name"],
        "version": "0.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"name": package["name"], "version": "0.0.0"},
            **{f"node_modules/{name}": {"version": version} for name, version in declared.items()},
        },
    }), encoding="utf-8")

    result = build_site(workspace, NEXT_REACT_PROFILE, npm_cache=tmp_path / "cache")

    assert result.ok is True
    assert [call[0] for call in calls] == [
        list(NEXT_REACT_PROFILE.install_command),
        *[list(command) for command in NEXT_REACT_PROFILE.check_commands],
        list(NEXT_REACT_PROFILE.build_command),
    ]
    assert calls[0][1]["env"]["npm_config_cache"] == str(tmp_path / "cache")
    assert not (workspace / "tsconfig.tsbuildinfo").exists()


def test_build_site_restores_preexisting_next_build_transient(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "_is_noexec_mount", lambda _path: False)

    def fake_run(_command, **kwargs):
        workspace = Path(kwargs["cwd"])
        (workspace / "out").mkdir(exist_ok=True)
        (workspace / "tsconfig.tsbuildinfo").write_text("generated", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("site_agent.hands.site_build.subprocess.run", fake_run)
    workspace = initialize_toolchain_workspace(tmp_path / "site", "Native Site")
    package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    declared = {**package["dependencies"], **package["devDependencies"]}
    (workspace / "package-lock.json").write_text(json.dumps({
        "name": package["name"],
        "version": "0.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"name": package["name"], "version": "0.0.0"},
            **{f"node_modules/{name}": {"version": version} for name, version in declared.items()},
        },
    }), encoding="utf-8")
    transient = workspace / "tsconfig.tsbuildinfo"
    transient.write_text("original", encoding="utf-8")

    result = build_site(workspace, NEXT_REACT_PROFILE)

    assert result.ok is True
    assert transient.read_text(encoding="utf-8") == "original"


def test_build_site_stages_noexec_workspace_on_an_executable_mount(tmp_path, monkeypatch):
    workspace = initialize_toolchain_workspace(tmp_path / "site", "Native Site")
    package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    declared = {**package["dependencies"], **package["devDependencies"]}
    (workspace / "package-lock.json").write_text(json.dumps({
        "name": package["name"],
        "version": "0.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"name": package["name"], "version": "0.0.0"},
            **{f"node_modules/{name}": {"version": version} for name, version in declared.items()},
        },
    }), encoding="utf-8")
    calls = []

    monkeypatch.setattr(
        site_build,
        "_is_noexec_mount",
        lambda path: Path(path).resolve() == workspace.resolve(),
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output = Path(kwargs["cwd"]) / "out"
        output.mkdir(exist_ok=True)
        (output / "index.html").write_text("candidate", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(site_build.subprocess, "run", fake_run)

    result = build_site(workspace, NEXT_REACT_PROFILE, npm_cache=tmp_path / "cache")

    assert result.ok is True
    assert (workspace / "out" / "index.html").read_text(encoding="utf-8") == "candidate"
    assert all(Path(kwargs["cwd"]) != workspace for _, kwargs in calls)

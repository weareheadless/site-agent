import json
from pathlib import Path

from site_agent.hands.site_build import (
    ASTRO_REACT_PROFILE,
    ASTRO_REACT_TOOLCHAIN_DEPENDENCIES,
    build_site,
    prepare_native_workspace,
)
from site_agent.site_scaffold import initialize_toolchain_workspace


def test_astro_react_build_profile_is_explicit_and_safe():
    assert ASTRO_REACT_PROFILE.name == "astro_react"
    assert ASTRO_REACT_PROFILE.output_dir == "dist"
    assert "npm" in " ".join(ASTRO_REACT_PROFILE.build_command)


def test_prepare_native_workspace_bootstraps_only_technical_astro_files(tmp_path):
    workspace = tmp_path / "site"
    workspace.mkdir()

    created = prepare_native_workspace(workspace, ASTRO_REACT_PROFILE)

    assert set(created) == {".gitignore", "astro.config.mjs", "package.json", "tsconfig.json"}
    package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    declared = {**package["dependencies"], **package["devDependencies"]}
    assert declared == {
        item["package"]: item["version"] for item in ASTRO_REACT_TOOLCHAIN_DEPENDENCIES
    }
    assert not (workspace / "src").exists()
    assert prepare_native_workspace(workspace, ASTRO_REACT_PROFILE) == ()


def test_build_site_runs_profile_commands_in_workspace(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        (Path(kwargs["cwd"]) / "dist").mkdir(exist_ok=True)

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

    result = build_site(workspace, ASTRO_REACT_PROFILE, npm_cache=tmp_path / "cache")

    assert result.ok is True
    assert [call[0] for call in calls] == [list(ASTRO_REACT_PROFILE.install_command), list(ASTRO_REACT_PROFILE.check_command), list(ASTRO_REACT_PROFILE.build_command)]
    assert calls[0][1]["env"]["npm_config_cache"] == str(tmp_path / "cache")

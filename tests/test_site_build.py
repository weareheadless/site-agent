import json
from pathlib import Path

import pytest

import site_agent.hands.site_build as site_build
from site_agent.hands.site_build import (
    NEXT_REACT_PROFILE,
    next_react_toolchain_dependencies,
    SiteBuildError,
    build_site,
    get_build_profile,
    prepare_native_workspace,
)
from site_agent.frontend_ownership import is_frontend_owned_path
from site_agent.site_scaffold import initialize_toolchain_workspace


def _lockfile_package_entries(declared):
    entries = {}
    for name, value in declared.items():
        artifact = site_build._SHARED_ARTIFACT_PATTERNS[name].fullmatch(value) if name in site_build._SHARED_ARTIFACT_PATTERNS else None
        entries[f"node_modules/{name}"] = (
            {"version": artifact.group("v"), "resolved": value}
            if artifact else {"version": value}
        )
    return entries


def test_next_react_build_profile_is_explicit_and_safe():
    assert NEXT_REACT_PROFILE.name == "next_react"
    assert NEXT_REACT_PROFILE.output_dir == "out"
    assert "npm" in " ".join(NEXT_REACT_PROFILE.build_command)


def test_next_react_is_the_only_supported_build_profile():
    assert set(site_build.PROFILES) == {"next_react"}
    with pytest.raises(SiteBuildError, match="unknown site build profile"):
        get_build_profile("unsupported")


def test_shared_frontend_ownership_allows_presentation_and_rejects_platform_paths():
    assert is_frontend_owned_path("src/components/site/presentation/Hero.tsx")
    assert is_frontend_owned_path("src/app/(frontend)/site.css")
    for path in (
        "src/collections/Pages.ts", "src/app/api/helloada/route.ts", "src/components/admin/Nav.tsx",
        "src/lib/content.ts", "payload.config.ts", "package.json", "public/brand/helloada.svg",
        "src/components/site/presentation/../../collections/Pages.ts", "/src/components/site/presentation/Hero.tsx",
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


def test_next_manifest_accepts_immutable_shared_package_release_artifacts(tmp_path):
    template = json.loads((Path(site_build.__file__).resolve().parents[1] / "templates/next-payload/package.json").read_text())
    shared_names = ("@weareheadless/helloada-payload-admin", "@weareheadless/helloada-payload-core")
    package = {"dependencies": {name: template["dependencies"][name] for name in shared_names}}
    (tmp_path / "package.json").write_text(json.dumps(package))
    assert set(site_build._validate_next_manifest(tmp_path)) == set(shared_names)
    for name in shared_names:
        package["dependencies"][name] = (
            "https://github.com/weareheadless/site-agent/releases/download/"
            "payload-admin-v0.10.38/weareheadless-helloada-payload-admin-0.10.38.tgz"
            if name.endswith("admin") else
            "https://github.com/weareheadless/site-agent/releases/download/"
            "helloada-payload-core-v0.10.38/weareheadless-helloada-payload-core-0.10.38.tgz"
        )
        (tmp_path / "package.json").write_text(json.dumps(package))
        assert set(site_build._validate_next_manifest(tmp_path)) == set(shared_names)
        for invalid in (
            "https://example.invalid/releases/download/payload-admin-v0.10.38/pkg-0.10.38.tgz",
            "https://github.com/other/repo/releases/download/payload-admin-v0.10.38/pkg-0.10.38.tgz",
            "https://github.com/weareheadless/site-agent/releases/download/payload-admin-v0.10.38/pkg-0.10.39.tgz",
            "0.10.38",
        ):
            package["dependencies"][name] = invalid
            (tmp_path / "package.json").write_text(json.dumps(package))
            with pytest.raises(SiteBuildError, match=f"native dependency must use the approved exact version: {name}"):
                site_build._validate_next_manifest(tmp_path)
        package["dependencies"][name] = template["dependencies"][name]


def test_next_manifest_still_rejects_unknown_and_non_exact_third_party_dependencies(tmp_path):
    for package in ({"dependencies": {"unknown-package": "1.0.0"}}, {"dependencies": {"next": "^16.3.4"}}):
        (tmp_path / "package.json").write_text(json.dumps(package))
        with pytest.raises(SiteBuildError):
            site_build._validate_next_manifest(tmp_path)


def test_next_manifest_lockfile_validates_shared_artifact_url_and_version(tmp_path):
    dependencies = {
        "@weareheadless/helloada-payload-admin": "https://github.com/weareheadless/site-agent/releases/download/payload-admin-v0.10.38/weareheadless-helloada-payload-admin-0.10.38.tgz",
        "@weareheadless/helloada-payload-core": "https://github.com/weareheadless/site-agent/releases/download/helloada-payload-core-v0.10.38/weareheadless-helloada-payload-core-0.10.38.tgz",
    }
    approved = {item["package"]: item["version"] for item in next_react_toolchain_dependencies()}
    dependencies.update({name: version for name, version in approved.items() if name not in dependencies})

    def write_lock(shared_overrides=None, omit=None):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": dependencies}))
        packages = {}
        for name, value in dependencies.items():
            if name == omit:
                continue
            is_shared = name in {
                "@weareheadless/helloada-payload-admin",
                "@weareheadless/helloada-payload-core",
            }
            entry = {"version": "0.10.38" if is_shared else value}
            if is_shared:
                entry["resolved"] = value
            entry.update((shared_overrides or {}).get(name, {}))
            packages[f"node_modules/{name}"] = entry
        (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": packages}))

    write_lock()
    site_build._validate_next_manifest(tmp_path, require_lockfile=True)

    admin = "@weareheadless/helloada-payload-admin"
    write_lock({admin: {"resolved": dependencies["@weareheadless/helloada-payload-core"]}})
    with pytest.raises(SiteBuildError, match=f"lockfile does not pin {admin}@"):
        site_build._validate_next_manifest(tmp_path, require_lockfile=True)

    write_lock({admin: {"version": "0.10.39"}})
    with pytest.raises(SiteBuildError, match=f"lockfile does not pin {admin}@"):
        site_build._validate_next_manifest(tmp_path, require_lockfile=True)

    third_party = "cli-color"
    dependencies[third_party] = "2.0.4"
    write_lock({third_party: {"version": "0.0.0"}})
    with pytest.raises(SiteBuildError, match=f"lockfile does not pin {third_party}@"):
        site_build._validate_next_manifest(tmp_path, require_lockfile=True)

    write_lock(omit=admin)
    with pytest.raises(SiteBuildError, match=f"lockfile does not pin {admin}@"):
        site_build._validate_next_manifest(tmp_path, require_lockfile=True)


def test_shared_artifact_patterns_are_package_specific_and_pin_versions():
    admin = "https://github.com/weareheadless/site-agent/releases/download/payload-admin-v0.10.38/weareheadless-helloada-payload-admin-0.10.38.tgz"
    core = "https://github.com/weareheadless/site-agent/releases/download/helloada-payload-core-v0.5.9/weareheadless-helloada-payload-core-0.5.9.tgz"
    admin_pattern = site_build._SHARED_ARTIFACT_PATTERNS["@weareheadless/helloada-payload-admin"]
    core_pattern = site_build._SHARED_ARTIFACT_PATTERNS["@weareheadless/helloada-payload-core"]

    assert admin_pattern.fullmatch(admin)
    assert core_pattern.fullmatch(core)
    assert not admin_pattern.fullmatch(core)
    assert not core_pattern.fullmatch(admin)
    assert not core_pattern.fullmatch(core.replace("github.com", "example.com"))
    assert not core_pattern.fullmatch(core.replace("core-0.5.9.tgz", "core-0.5.10.tgz"))
    assert not core_pattern.fullmatch("0.5.9")

def test_next_manifest_unknown_package_fails_as_not_host_approved(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"unknown-package": "1.0.0"}}))
    with pytest.raises(SiteBuildError, match="not host-approved: unknown-package"):
        site_build._validate_next_manifest(tmp_path)


def test_next_manifest_rejects_third_party_version_different_from_template(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"cli-color": "2.0.3"}}))
    with pytest.raises(SiteBuildError, match="approved exact version: cli-color@2.0.4"):
        site_build._validate_next_manifest(tmp_path)


def test_next_manifest_uses_every_exact_template_dependency(tmp_path, monkeypatch):
    template_path = Path(site_build.__file__).resolve().parents[1] / "templates/next-payload/package.json"
    template = json.loads(template_path.read_text())
    dependencies = {**template["dependencies"], **template["devDependencies"]}
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": dependencies}))
    assert set(site_build._validate_next_manifest(tmp_path)) == set(dependencies)

    isolated_template = tmp_path / "site_agent/templates/next-payload"
    isolated_template.mkdir(parents=True)
    template_path = isolated_template / "package.json"
    template["dependencies"]["unlisted-template-package"] = "1.2.3"
    template_path.write_text(json.dumps(template))
    monkeypatch.setattr(site_build, "__file__", str(tmp_path / "site_agent/hands/site_build.py"))
    dependency = {"dependencies": {**dependencies, "unlisted-template-package": "1.2.3"}}
    (tmp_path / "package.json").write_text(json.dumps(dependency))
    assert "unlisted-template-package" in site_build._validate_next_manifest(tmp_path)


def test_next_template_dependency_source_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(site_build, "__file__", str(tmp_path / "site_build.py"))
    with pytest.raises(SiteBuildError, match="canonical Next/React template package.json is invalid"):
        site_build.next_react_toolchain_dependencies()


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
        item["package"]: item["version"] for item in next_react_toolchain_dependencies()
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
            **_lockfile_package_entries(declared),
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
            **_lockfile_package_entries(declared),
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
            **_lockfile_package_entries(declared),
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


def test_next_profile_does_not_require_a_static_export_tree():
    """A server-rendered Next/Payload build never writes `out`.

    Requiring it reported every good build as `missing build output: out`,
    which is how a real candidate died after thirty minutes of authoring.
    """
    assert NEXT_REACT_PROFILE.output_required is False
    assert NEXT_REACT_PROFILE.output_dir == "out"

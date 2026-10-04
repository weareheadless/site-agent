#!/usr/bin/env python3
"""Build and atomically promote one exact site-agent API source release."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"[0-9a-f]{40}")
RELEASE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
SERVICE = "site-agent-api.service"
RESTART_SOCKET = "/run/helloada-api-restart.sock"
HEALTH_URL = "http://127.0.0.1:3014/healthz"


def validate_api_queue(queue: Any) -> dict[str, str] | None:
    if (not isinstance(queue, dict) or set(queue) != {"schema", "release"}
            or isinstance(queue.get("schema"), bool) or queue.get("schema") != 1):
        raise ValueError("invalid API release queue schema")
    request = queue["release"]
    if request is None:
        return None
    if not isinstance(request, dict) or set(request) != {"id", "sha"}:
        raise ValueError("API release must contain only an ID and full source SHA")
    if not isinstance(request["id"], str) or not RELEASE_ID_RE.fullmatch(request["id"]):
        raise ValueError("unsafe API release ID")
    if not isinstance(request["sha"], str) or not SHA_RE.fullmatch(request["sha"]):
        raise ValueError("API release requires a full immutable source SHA")
    return request


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
         capture: bool = True, log_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, check=False,
                                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.PIPE if capture else subprocess.DEVNULL)
    except OSError as exc:
        raise RuntimeError(f"could not execute {Path(command[0]).name}") from exc
    if log_path is not None:
        secrets_to_redact = sorted(
            (value for key, value in (env or {}).items()
             if value and re.search(r"TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE.?KEY", key, re.I)),
            key=len, reverse=True,
        )
        output = f"[{Path(command[0]).name}: exit {result.returncode}]\n{result.stdout or ''}\n{result.stderr or ''}\n"
        for secret in secrets_to_redact:
            output = output.replace(secret, "[REDACTED]")
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(output)
        os.chmod(log_path, 0o600)
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed with exit code {result.returncode}")
    return result


def _verify_wheel_runtime_dependencies(python: str, wheel: Path, *, cwd: Path,
                                       env: dict[str, str], log_path: Path) -> None:
    """Check the built wheel against the service interpreter without pip CLI feature drift."""
    code = "\n".join((
        "import importlib.metadata as metadata",
        "import json, sys, zipfile",
        "from email.parser import BytesParser",
        "from pip._vendor.packaging.requirements import Requirement",
        "from pip._vendor.packaging.markers import default_environment",
        "with zipfile.ZipFile(sys.argv[1]) as archive:",
        "    names = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]",
        "    if len(names) != 1:",
        "        raise RuntimeError('wheel must contain exactly one distribution metadata file')",
        "    distribution = BytesParser().parsebytes(archive.read(names[0]))",
        "missing = []",
        "marker_environment = default_environment()",
        "marker_environment['extra'] = ''",
        "for raw in distribution.get_all('Requires-Dist', []):",
        "    requirement = Requirement(raw)",
        "    if requirement.marker and not requirement.marker.evaluate(marker_environment):",
        "        continue",
        "    try:",
        "        installed = metadata.version(requirement.name)",
        "    except metadata.PackageNotFoundError:",
        "        missing.append(requirement.name)",
        "    else:",
        "        if requirement.specifier and not requirement.specifier.contains(installed, prereleases=True):",
        "            missing.append(f'{requirement.name}{requirement.specifier} (installed {installed})')",
        "print(json.dumps(sorted(set(missing))))",
    ))
    result = _run([python, "-c", code, str(wheel)], cwd=cwd, env=env, log_path=log_path)
    try:
        missing = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("API dependency audit returned invalid output") from exc
    if not isinstance(missing, list) or any(not isinstance(item, str) for item in missing):
        raise RuntimeError("API dependency audit returned invalid output")
    if missing:
        raise RuntimeError(
            "API release requires runtime dependencies not present in the service environment: "
            + ", ".join(missing)
        )


def _set_current(current: Path, destination: Path) -> None:
    if current.exists() and not current.is_symlink():
        raise RuntimeError("API current release path is not a managed symlink")
    temporary = current.with_name(f".{current.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(destination)
    os.replace(temporary, current)


def _health_check(url: str, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.loads(response.read(4096))
            if response.status == 200 and payload == {"ok": True}:
                return
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise RuntimeError("API /healthz did not pass after restart")


def _restart_api(socket_path: str = RESTART_SOCKET) -> None:
    """Request the one host-authorized action through its fixed-function broker."""
    response = bytearray()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(150)
            connection.connect(socket_path)
            connection.sendall(b"restart\\n")
            connection.shutdown(socket.SHUT_WR)
            while True:
                chunk = connection.recv(64)
                if not chunk:
                    break
                response.extend(chunk)
                if len(response) > 64:
                    raise RuntimeError("API restart broker returned an invalid response")
    except OSError as exc:
        raise RuntimeError("API restart broker request failed") from exc
    if response != b"restarted\\n":
        raise RuntimeError("API restart broker rejected the fixed API restart request")


def _installed_package_identity(python: str) -> dict[str, str]:
    code = (
        "import importlib.metadata as m, importlib.util, json, pathlib; "
        "spec=importlib.util.find_spec('site_agent'); "
        "dist=m.distribution('site-agent'); "
        "print(json.dumps({'module':str(pathlib.Path(spec.origin).resolve()),"
        "'distInfo':str(pathlib.Path(dist._path).resolve()),'version':dist.version}))"
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = _run([python, "-c", code], cwd=Path("/"), env=env)
    identity = json.loads(result.stdout)
    module = Path(identity["module"])
    dist_info = Path(identity["distInfo"])
    if "site-packages" not in module.parts or module.parent.name != "site_agent":
        raise RuntimeError("installed API package is not in the managed virtualenv site-packages")
    if module.parent.parent != dist_info.parent or not dist_info.name.endswith(".dist-info"):
        raise RuntimeError("installed API distribution metadata is not colocated with its package")
    return {"packageDir": str(module.parent), "distInfoDir": str(dist_info), "version": identity["version"]}


def _baseline_release(python: str, releases: Path, release_root: Path) -> Path:
    identity = _installed_package_identity(python)
    digest = hashlib.sha256()
    for path in sorted((Path(identity["packageDir"]), Path(identity["distInfoDir"]))):
        for item in sorted(path.rglob("*")):
            if item.is_file():
                digest.update(item.relative_to(path.parent).as_posix().encode())
                digest.update(item.read_bytes())
    release_id = f"baseline-{identity['version']}-{digest.hexdigest()[:12]}"
    destination = releases / release_id
    if not destination.exists():
        package_root = destination / "site-packages"
        package_root.mkdir(parents=True, mode=0o700)
        shutil.copytree(identity["packageDir"], package_root / "site_agent")
        shutil.copytree(identity["distInfoDir"], package_root / Path(identity["distInfoDir"]).name)
        os.chmod(destination, 0o700)
    return destination


def _record(receipt_path: Path, receipt: dict[str, Any], stage: str,
            status: str = "running", **values: Any) -> None:
    receipt.update(values)
    receipt.update({"stage": stage, "status": status,
                    "updatedAt": datetime.now(timezone.utc).isoformat()})
    _atomic_json(receipt_path, receipt)


def _recover_interrupted(receipt_path: Path, receipt: dict[str, Any], current: Path,
                         releases: Path, health_url: str) -> bool:
    previous = receipt.get("previousRelease")
    if receipt.get("stage") not in ("switching", "activated") or not previous:
        return False
    previous_path = (releases / previous).resolve()
    if previous_path.parent != releases.resolve() or not previous_path.is_dir():
        raise RuntimeError("interrupted API release has no valid rollback slot")
    _set_current(current, previous_path)
    _restart_api()
    _health_check(health_url)
    _record(receipt_path, receipt, "recovered", "interrupted",
            recovery="restored previous immutable API slot")
    return True


def deploy(source_dir: Path, source_sha: str, release_id: str, root: Path,
           python: str, health_url: str) -> dict[str, Any]:
    if not SHA_RE.fullmatch(source_sha) or not RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError("API deployment requires a safe release ID and full source SHA")
    source_dir = source_dir.resolve()
    marker = source_dir / ".site-agent-source-sha"
    if not source_dir.is_dir() or not marker.is_file() or marker.read_text().strip() != source_sha:
        raise ValueError("API source snapshot does not match the requested SHA")
    if not (source_dir / "pyproject.toml").is_file() or not (source_dir / "src/site_agent/__init__.py").is_file():
        raise ValueError("API source snapshot is incomplete")

    api_root = root / "api"
    releases = api_root / "releases"
    current = api_root / "current"
    release_dir = releases / release_id
    receipt_path = root / "runs" / "api" / release_id / "receipt.json"
    releases.mkdir(parents=True, exist_ok=True, mode=0o700)
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("sourceSha") != source_sha:
            raise ValueError("API release ID was reused for a different source SHA")
        if receipt.get("status") in ("deployed", "verified"):
            return receipt
        if receipt.get("status") in ("running", "interrupted"):
            if _recover_interrupted(receipt_path, receipt, current, releases, health_url):
                raise RuntimeError("interrupted API activation was rolled back; use a new release ID")
        raise RuntimeError("API release ID already has a terminal receipt; use a new release ID")
    if release_dir.exists():
        raise RuntimeError("API release directory exists without its immutable receipt")

    prior_path: Path | None = None
    if current.is_symlink():
        prior_path = current.resolve(strict=True)
        if prior_path.parent != releases.resolve():
            raise RuntimeError("API current symlink points outside the release store")
    elif current.exists():
        raise RuntimeError("API current release path is not a managed symlink")

    receipt: dict[str, Any] = {
        "schema": 1, "releaseId": release_id, "sourceSha": source_sha,
        "pipelineSha": os.environ.get("HELLOADA_PIPELINE_SHA", ""),
        "startedAt": datetime.now(timezone.utc).isoformat(),
    }
    _record(receipt_path, receipt, "preflight")
    log_path = receipt_path.parent / "deployment.log"
    staging = releases / f".{release_id}.staging-{os.getpid()}"
    try:
        if staging.exists():
            raise RuntimeError("API staging directory already exists")
        staging.mkdir(mode=0o700)
        test_env = {**os.environ, "PYTHONPATH": str(source_dir / "src")}
        _run([python, "-m", "pytest", "-q"], cwd=source_dir, env=test_env, log_path=log_path)
        _record(receipt_path, receipt, "tests-passed")

        wheel_dir = staging / "wheel"
        wheel_dir.mkdir(mode=0o700)
        clean_env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        _run([python, "-m", "pip", "wheel", "--no-deps",
              "--wheel-dir", str(wheel_dir), str(source_dir)], cwd=source_dir, env=clean_env,
             log_path=log_path)
        wheels = list(wheel_dir.glob("site_agent-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("API build did not produce exactly one site-agent wheel")
        wheel = wheels[0]
        wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()

        _verify_wheel_runtime_dependencies(python, wheel, cwd=source_dir, env=clean_env,
                                           log_path=log_path)

        site_packages = staging / "site-packages"
        _run([python, "-m", "pip", "install", "--no-deps", "--no-index", "--target",
              str(site_packages), str(wheel)], cwd=source_dir, env=clean_env, log_path=log_path)
        smoke_env = {**clean_env, "PYTHONPATH": str(site_packages)}
        smoke = _run([python, "-c",
                      "import importlib.metadata as m, importlib.util, json, pathlib; "
                      "p=pathlib.Path(importlib.util.find_spec('site_agent').origin).resolve(); "
                      "print(json.dumps({'path':str(p),'version':m.version('site-agent')}))"],
                     cwd=Path("/"), env=smoke_env)
        smoke_result = json.loads(smoke.stdout)
        if not Path(smoke_result["path"]).is_relative_to(site_packages.resolve()):
            raise RuntimeError("API wheel smoke test imported outside the candidate release")

        _record(receipt_path, receipt, "wheel-verified", wheel=wheel.name,
                wheelSha256=wheel_hash, packageVersion=smoke_result["version"])
        (staging / "source-sha").write_text(source_sha + "\n", encoding="ascii")
        staging.rename(release_dir)

        if prior_path is None:
            prior_path = _baseline_release(python, releases, release_dir)
            _set_current(current, prior_path)
        receipt["previousRelease"] = prior_path.name

        unit_source = source_dir / "deploy/site-agent-api.service"
        if not unit_source.is_file():
            raise RuntimeError("API service unit is missing from the exact source release")
        installed_unit = Path("/etc/systemd/system/site-agent-api.service")
        _run(["systemd-analyze", "verify", str(unit_source)])
        if not installed_unit.is_file() or installed_unit.read_bytes() != unit_source.read_bytes():
            raise RuntimeError("API service unit differs from the bootstrapped host contract")

        receipt["previousRelease"] = prior_path.name
        _record(receipt_path, receipt, "switching")
        _set_current(current, release_dir)
        _record(receipt_path, receipt, "activated")
        _restart_api()
        _health_check(health_url)
        _record(receipt_path, receipt, "health-passed", "deployed",
                finishedAt=datetime.now(timezone.utc).isoformat())
        return receipt
    except Exception as exc:
        current_target = current.resolve() if current.is_symlink() else None
        activated = current_target == release_dir.resolve()
        if activated and prior_path and prior_path.is_dir():
            try:
                _set_current(current, prior_path)
                _restart_api()
                _health_check(health_url)
                _record(receipt_path, receipt, "rolled-back", "rolled-back",
                        failure=type(exc).__name__, failureMessage=str(exc),
                        finishedAt=datetime.now(timezone.utc).isoformat())
            except Exception as rollback_error:
                _record(receipt_path, receipt, "rollback-failed", "failed",
                        failure=type(exc).__name__, failureMessage=str(exc),
                        rollbackFailure=type(rollback_error).__name__,
                        finishedAt=datetime.now(timezone.utc).isoformat())
        else:
            _record(receipt_path, receipt, receipt.get("stage", "failed"), "failed",
                    failure=type(exc).__name__, failureMessage=str(exc),
                    finishedAt=datetime.now(timezone.utc).isoformat())
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--root", type=Path, default=Path("/SOCIAL/payload-releases"))
    parser.add_argument("--python", default="/SOCIAL/site-agent/.venv/bin/python")
    parser.add_argument("--health-url", default=HEALTH_URL)
    args = parser.parse_args()
    try:
        result = deploy(args.source_dir, args.source_sha, args.release_id, args.root,
                        args.python, args.health_url)
    except Exception as exc:  # noqa: BLE001 - receipts preserve a sanitized failure class
        print(json.dumps({"status": "failed", "failure": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps({key: result.get(key) for key in
                      ("status", "releaseId", "sourceSha", "packageVersion", "wheelSha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

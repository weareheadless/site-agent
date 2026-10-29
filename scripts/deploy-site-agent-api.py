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


def _load_required_extras(source_dir: Path) -> list[str]:
    try:
        manifest = json.loads((source_dir / "deploy/api-runtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("API runtime extras manifest is missing or invalid") from exc
    allowed = {"crawlseo", "design-lab", "ga"}
    if (not isinstance(manifest, dict) or set(manifest) != {"schema", "requiredExtras"}
            or type(manifest["schema"]) is not int or manifest["schema"] != 1
            or not isinstance(manifest["requiredExtras"], list)
            or not manifest["requiredExtras"]
            or any(not isinstance(extra, str) or extra not in allowed for extra in manifest["requiredExtras"])
            or len(set(manifest["requiredExtras"])) != len(manifest["requiredExtras"])
            or set(manifest["requiredExtras"]) != allowed):
        raise RuntimeError("API runtime extras manifest has invalid or unknown declarations")
    return manifest["requiredExtras"]


def _verify_wheel_runtime_dependencies(python: str, wheel: Path, *, cwd: Path,
                                       required_extras: list[str],
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
        "environments = [('default', default_environment())]",
        "for extra in json.loads(sys.argv[2]):",
        "    marker_environment = default_environment()",
        "    marker_environment['extra'] = extra",
        "    environments.append((extra, marker_environment))",
        "for raw in distribution.get_all('Requires-Dist', []):",
        "    requirement = Requirement(raw)",
        "    for extra, marker_environment in environments:",
        "        if requirement.marker and not requirement.marker.evaluate(marker_environment):",
        "            continue",
        "        try:",
        "            installed = metadata.version(requirement.name)",
        "        except metadata.PackageNotFoundError:",
        "            missing.append({'extra': extra, 'package': requirement.name})",
        "        else:",
        "            if requirement.specifier and not requirement.specifier.contains(installed, prereleases=True):",
        "                missing.append({'extra': extra, 'package': requirement.name, 'installed': installed, 'required': str(requirement.specifier)})",
        "print(json.dumps(sorted({json.dumps(item, sort_keys=True) for item in missing})))",
    ))
    result = _run([python, "-c", code, str(wheel), json.dumps(required_extras)], cwd=cwd, env=env, log_path=log_path)
    try:
        missing = [json.loads(item) for item in json.loads(result.stdout)]
    except json.JSONDecodeError as exc:
        raise RuntimeError("API dependency audit returned invalid output") from exc
    if not isinstance(missing, list) or any(not isinstance(item, dict) for item in missing):
        raise RuntimeError("API dependency audit returned invalid output")
    if missing:
        raise RuntimeError(
            "API release requires runtime dependencies not present in the service environment: "
            + ", ".join(f"{item['extra']}: {item['package']}" for item in missing)
        )


def _verify_payload_template_bundle(site_packages: Path) -> None:
    """Require the installed wheel to contain the canonical bootstrap scaffold."""
    template = site_packages / "site_agent" / "templates" / "next-payload"
    required = (".gitignore", "template-manifest.json", "helloada-content-contract.json", "wrangler.jsonc")
    missing = [name for name in required if not (template / name).is_file()]
    if missing:
        raise RuntimeError("API wheel is missing canonical Payload template files: " + ", ".join(missing))
    rules = set((template / ".gitignore").read_text(encoding="utf-8").splitlines())
    if not {"node_modules/", "*.tsbuildinfo"}.issubset(rules):
        raise RuntimeError("API wheel Payload ignore rules do not exclude generated Node/TypeScript files")


def _set_current(current: Path, destination: Path) -> None:
    if current.exists() and not current.is_symlink():
        raise RuntimeError("API current release path is not a managed symlink")
    temporary = current.with_name(f".{current.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(destination)
    os.replace(temporary, current)


def _health_check(url: str, attempts: int = 180) -> int:
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.loads(response.read(4096))
            if response.status == 200 and payload == {"ok": True}:
                return attempt
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise RuntimeError("API /healthz did not pass after restart")


def _capture_failed_unit_log(path: Path) -> str | None:
    """Best-effort, bounded journal capture; diagnostics must never block rollback."""
    try:
        result = subprocess.run(["journalctl", "-u", SERVICE, "-n", "200", "--no-pager"],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                check=False, timeout=10)
        output = "\n".join(result.stdout.splitlines()[-200:])
        output = output.encode("utf-8")[-32768:].decode("utf-8", errors="replace")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(output + ("\n" if output else ""), encoding="utf-8")
        os.chmod(path, 0o600)
        return str(path)
    except Exception:
        return None


def _runtime_config_preflight(source_dir: Path, python: str, log_path: Path) -> None:
    manifest_path = source_dir / "deploy/payload-customers.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        config_path = str(manifest["connectionGate"]["config"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("API release manifest has no runtime config preflight target") from exc
    validator = source_dir / "scripts/sync-provisioned-tenant-configs.py"
    if not Path(config_path).is_absolute() or not validator.is_file():
        raise RuntimeError("API release is missing its runtime config preflight contract")
    env = {**os.environ, "PYTHONPATH": str(source_dir / "src")}
    _run([python, str(validator), "--config", config_path, "--manifest", str(manifest_path), "--validate"],
         cwd=source_dir, env=env, log_path=log_path)


def _restart_api(socket_path: str = RESTART_SOCKET) -> None:
    """Request the one host-authorized action through its fixed-function broker."""
    response = bytearray()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(150)
            connection.connect(socket_path)
            connection.sendall(b"restart\n")
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
    if response != b"restarted\n":
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
    try:
        _restart_api()
        _health_check(health_url)
    except Exception as exc:
        _record(receipt_path, receipt, "recovery-rollback-failed", "failed",
                rollbackRelease=previous_path.name, rollbackHealth=False,
                rollbackFailure=type(exc).__name__)
        raise RuntimeError("interrupted API release restored the previous slot but its health check failed") from exc
    _record(receipt_path, receipt, "recovered", "interrupted",
            recovery="restored previous immutable API slot", rollbackRelease=previous_path.name,
            rollbackHealth=True)
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
        _runtime_config_preflight(source_dir, python, log_path)
        _record(receipt_path, receipt, "runtime-config-passed")
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

        required_extras = _load_required_extras(source_dir)
        _verify_wheel_runtime_dependencies(python, wheel, cwd=source_dir,
                                           required_extras=required_extras, env=clean_env,
                                           log_path=log_path)

        site_packages = staging / "site-packages"
        _run([python, "-m", "pip", "install", "--no-deps", "--no-index", "--target",
              str(site_packages), str(wheel)], cwd=source_dir, env=clean_env, log_path=log_path)
        _verify_payload_template_bundle(site_packages)
        smoke_env = {**clean_env, "PYTHONPATH": str(site_packages)}
        smoke_code = "\n".join((
            "import importlib.metadata as m, importlib.util, json, pathlib",
            "from site_agent.hands.crawlseo import _load_mcp_sdk",
            "_load_mcp_sdk()",
            "from playwright.sync_api import sync_playwright",
            "assert callable(sync_playwright)",
            "from google.auth.transport.requests import Request",
            "from google.oauth2 import service_account",
            "assert callable(Request) and hasattr(service_account, 'Credentials')",
            "p=pathlib.Path(importlib.util.find_spec('site_agent').origin).resolve()",
            "print(json.dumps({'path':str(p),'version':m.version('site-agent')}))",
        ))
        smoke = _run([python, "-c", smoke_code],
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
        health_started = time.monotonic()
        try:
            health_attempts = _health_check(health_url)
        except Exception:
            failed_log = _capture_failed_unit_log(receipt_path.parent / "failed-unit.log")
            receipt["healthCheck"] = {"attempts": 180, "secondsWaited": round(time.monotonic() - health_started, 1)}
            if failed_log:
                receipt["failedUnitLogPath"] = failed_log
            raise
        receipt["healthCheck"] = {"attempts": health_attempts, "secondsWaited": round(time.monotonic() - health_started, 1)}
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
                        rollbackRelease=prior_path.name, rollbackHealth=True,
                        finishedAt=datetime.now(timezone.utc).isoformat())
            except Exception as rollback_error:
                _record(receipt_path, receipt, "rollback-failed", "failed",
                        failure=type(exc).__name__, failureMessage=str(exc),
                        rollbackFailure=type(rollback_error).__name__,
                        rollbackRelease=prior_path.name, rollbackHealth=False,
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

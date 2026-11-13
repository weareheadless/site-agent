#!/usr/bin/env python3
"""Install the canonical presentation check in every tenant repository.

The check is one file plus one workflow, shipped from the site template, and
every tenant repository gets exactly those bytes. This tool is how an existing
repository receives them and how a fix reaches the whole fleet: it plans the
work per tenant and per branch, and only ``--apply`` writes commits.

Why the branches matter: a static presentation's candidate lives on the preview
branch and is only merged to main once approved, so the drift has to fail on
``preview`` too. Installing the workflow on main alone would repeat the exact
failure the check exists to prevent.

Dry-run by default. Pass ``--apply`` to commit; the plan is idempotent, so a
second run reports every file as unchanged.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from site_agent.application.tenant_registration import load_provisioned_tenants, provisioned_root
from site_agent.credentials import credential_environment, github_api_token

API = "https://api.github.com"
TEMPLATE = ROOT / "src/site_agent/templates/next-payload"

# The one canonical check, identical in every tenant repository.
CANONICAL = {
    "scripts/check-presentation.mjs": TEMPLATE / "scripts/check-presentation.mjs",
    ".github/workflows/presentation-check.yml": TEMPLATE / ".github/workflows/presentation-check.yml",
}

# The release build rehearsal: the shared-runtime overlay, contract generation,
# dependency verification and OpenNext build, with no deploy credential.
RELEASE_WORKFLOW = ".github/workflows/release-build.yml"
RELEASE_SOURCE = TEMPLATE / RELEASE_WORKFLOW
DEPLOY_WORKFLOW = ".github/workflows/release-deploy.yml"
DEPLOY_SOURCE = TEMPLATE / DEPLOY_WORKFLOW
# Non-secret identity the rehearsal needs; derived from the release registry.
RELEASE_MANIFEST = ".github/helloada-release.json"

# A tenant-specific check that the canonical one supersedes. Only files this
# platform introduced are retired; a tenant's own scripts are never touched.
SUPERSEDED = (
    "scripts/check-static-manifest.mjs",
    ".github/workflows/site-check.yml",
)

MESSAGES = {
    "created": "Add the canonical presentation check",
    "updated": "Update the presentation check to the canonical version",
    "removed": "Retire the tenant-specific presentation check",
    "release-created": "Rehearse the release build on every candidate",
    "release-updated": "Update the release build rehearsal",
    "deploy-created": "Deploy this repository without a stored credential",
    "deploy-updated": "Update the credential-free deploy workflow",
    "manifest-created": "Pin this repository to its release identity",
    "manifest-updated": "Refresh the release identity",
}


class GitHubError(RuntimeError):
    """The GitHub API refused or failed a request."""


def _request(
    method: str,
    path: str,
    token: str,
    payload: Mapping[str, Any] | None = None,
    *,
    allow_missing: bool = False,
) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "site-agent",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
            return response.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        if allow_missing and exc.code == 404:
            return 404, {}
        detail = exc.read().decode(errors="replace")[:300]
        raise GitHubError(f"github {method} {path} -> {exc.code}: {detail}") from exc


def _remote_file(token: str, repository: str, branch: str, path: str) -> tuple[bytes, str] | None:
    """Return the committed bytes and blob sha, or None when the path is absent."""
    quoted = urllib.parse.quote(path)
    status, body = _request(
        "GET", f"/repos/{repository}/contents/{quoted}?ref={urllib.parse.quote(branch)}",
        token, allow_missing=True,
    )
    if status == 404:
        return None
    if body.get("type") != "file":
        raise GitHubError(f"{repository}:{path} is not a file")
    try:
        return base64.b64decode(body.get("content") or ""), str(body.get("sha") or "")
    except (ValueError, TypeError) as exc:
        raise GitHubError(f"{repository}:{path} returned an unreadable blob") from exc


def _write(
    token: str, repository: str, branch: str, path: str, content: bytes, sha: str | None,
    *, message: str = "",
) -> None:
    payload: dict[str, Any] = {
        "message": message or MESSAGES["updated" if sha else "created"],
        "content": base64.b64encode(content).decode(),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    _request("PUT", f"/repos/{repository}/contents/{urllib.parse.quote(path)}", token, payload)


def _remove(token: str, repository: str, branch: str, path: str, sha: str) -> None:
    _request(
        "DELETE", f"/repos/{repository}/contents/{urllib.parse.quote(path)}", token,
        {"message": MESSAGES["removed"], "sha": sha, "branch": branch},
    )


def _branches(token: str, repository: str, declared: list[str]) -> list[str]:
    """The declared branches that exist, main first."""
    status, body = _request("GET", f"/repos/{repository}/branches?per_page=100", token, allow_missing=True)
    if status == 404:
        raise GitHubError(f"repository {repository} is not reachable")
    existing = {str(item.get("name")) for item in body if isinstance(item, Mapping)}
    ordered = [name for name in declared if name in existing]
    return ordered or ["main"]


def _release_identity(customer: Mapping[str, Any], tenant: str, manifest: Mapping[str, Any],
                      handoff_public_key: str, control_sha: str) -> bytes:
    """The non-secret release identity a repository needs to rehearse its build.

    Contract, schema, Worker and resource names are identity, not credentials;
    they also live in the repository's committed Wrangler configuration. The
    rehearsal validates the generated contract against them, so a stale copy
    fails loudly instead of deploying something else.
    """
    document = {
        "schema": 1,
        "tenant": tenant,
        "nodeVersion": str(manifest.get("nodeVersion") or ""),
        "npmVersion": str(manifest.get("npmVersion") or ""),
        "handoffPublicKey": handoff_public_key,
        "controlSha": control_sha,
        "customer": dict(customer),
    }
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def _tenant_rows(host_config: Mapping[str, Any], env: Mapping[str, str] | None) -> list[dict[str, Any]]:
    root = provisioned_root(host_config)
    declared, _ = load_provisioned_tenants(host_config, env)
    rows: list[dict[str, Any]] = []
    for tenant in sorted(declared):
        config_path = Path(str((declared[tenant] or {}).get("config_path") or ""))
        if not config_path.is_file():
            rows.append({"tenant": tenant, "status": "skipped", "reason": "no tenant config"})
            continue
        try:
            document = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            rows.append({"tenant": tenant, "status": "skipped", "reason": f"unreadable config: {exc}"})
            continue
        site = document.get("site") if isinstance(document.get("site"), Mapping) else {}
        repository = str(site.get("repository") or "").strip().strip("/")
        if not repository:
            rows.append({"tenant": tenant, "status": "skipped", "reason": "no GitHub repository"})
            continue
        branch = str(site.get("branch") or "main").strip() or "main"
        preview = str(site.get("preview_branch") or "preview").strip() or "preview"
        rows.append({
            "tenant": tenant,
            "status": "planned",
            "repository": repository,
            "branches": list(dict.fromkeys([branch, preview])),
        })
    return rows


def plan(host_config: Mapping[str, Any], env: Mapping[str, str] | None, tenants: list[str], apply: bool) -> dict[str, Any]:
    credentials = credential_environment(host_config, env)
    token = github_api_token(host_config, credentials)
    if not token:
        raise GitHubError("no GitHub API token is configured for this host")
    for path, source in CANONICAL.items():
        if not source.is_file():
            raise GitHubError(f"canonical file is missing from the template: {path}")

    release_manifest = json.loads((ROOT / "deploy/payload-customers.json").read_text(encoding="utf-8"))
    customers = release_manifest.get("customers") if isinstance(release_manifest.get("customers"), Mapping) else {}
    handoff_public_key = ""
    gate = release_manifest.get("connectionGate") if isinstance(release_manifest.get("connectionGate"), Mapping) else {}
    gate_env = str(gate.get("envFile") or "").strip()
    if gate_env:
        from site_agent.config import load_env_file
        handoff_public_key = str(load_env_file(gate_env, {}).get("HELLOADA_HANDOFF_PUBLIC_KEY") or "")
    for canonical_source, canonical_name in (
        (RELEASE_SOURCE, RELEASE_WORKFLOW), (DEPLOY_SOURCE, DEPLOY_WORKFLOW),
    ):
        if not canonical_source.is_file():
            raise GitHubError(f"canonical file is missing from the template: {canonical_name}")
    control_sha = str(
        __import__("subprocess").check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True,
        ).strip()
    )

    rows = _tenant_rows(host_config, credentials)
    if tenants:
        known = {row["tenant"] for row in rows}
        missing = sorted(set(tenants) - known)
        if missing:
            raise GitHubError(f"not a provisioned tenant: {', '.join(missing)}")
        rows = [row for row in rows if row["tenant"] in set(tenants)]

    result: list[dict[str, Any]] = []
    for row in rows:
        if row["status"] != "planned":
            result.append(row)
            continue
        repository = row["repository"]
        try:
            branches = _branches(token, repository, row["branches"])
            changes: list[dict[str, str]] = []
            customer = customers.get(row["tenant"])
            # The identity file lands before the workflow that reads it, so the
            # run the workflow commit triggers already has its inputs.
            desired: list[tuple[str, bytes, str]] = [
                (path, source.read_bytes(), "") for path, source in CANONICAL.items()
            ]
            if isinstance(customer, Mapping):
                desired.append((
                    RELEASE_MANIFEST,
                    _release_identity(customer, str(row["tenant"]), release_manifest, handoff_public_key, control_sha),
                    MESSAGES["manifest-updated"],
                ))
                desired.append((RELEASE_WORKFLOW, RELEASE_SOURCE.read_bytes(), MESSAGES["release-updated"]))
                desired.append((DEPLOY_WORKFLOW, DEPLOY_SOURCE.read_bytes(), MESSAGES["deploy-updated"]))
            for branch in branches:
                for path, content, message in desired:
                    current = _remote_file(token, repository, branch, path)
                    if current is not None and current[0] == content:
                        changes.append({"branch": branch, "path": path, "action": "unchanged"})
                        continue
                    action = "created" if current is None else "updated"
                    if apply:
                        _write(token, repository, branch, path, content, current[1] if current else None,
                               message=message)
                    changes.append({"branch": branch, "path": path, "action": action})
                for path in SUPERSEDED:
                    current = _remote_file(token, repository, branch, path)
                    if current is None:
                        continue
                    if apply:
                        _remove(token, repository, branch, path, current[1])
                    changes.append({"branch": branch, "path": path, "action": "removed"})
        except GitHubError as exc:
            # One unreachable or protected repository must not stop the fleet.
            result.append({
                "tenant": row["tenant"],
                "status": "failed",
                "repository": repository,
                "reason": str(exc)[:500],
            })
            continue
        result.append({
            "tenant": row["tenant"],
            "status": "applied" if apply else "planned",
            "repository": repository,
            "changes": changes,
        })
    return {
        "mode": "apply" if apply else "dry-run",
        "canonical": sorted(CANONICAL),
        "tenants": result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="shared Site-Agent API host config")
    parser.add_argument("--tenant", action="append", default=[], help="provisioned tenant to sync; repeatable, default all")
    parser.add_argument("--apply", action="store_true", help="commit the plan; default is a dry run")
    args = parser.parse_args(argv)
    try:
        document = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
        if not isinstance(document, Mapping):
            raise GitHubError("host config must be an object")
        if len(set(args.tenant)) != len(args.tenant):
            raise GitHubError("--tenant values must be unique")
        outcome = plan(document, os.environ, args.tenant, args.apply)
    except (OSError, UnicodeError, yaml.YAMLError, GitHubError) as exc:
        print(f"tenant repository sync failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(outcome, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Verify a GitHub Actions OIDC token for one repository, branch and workflow.

A tenant repository must be able to deploy without holding a Cloudflare
credential and without anyone creating a token per site. GitHub's OIDC token is
the proof: it is minted per job, names the repository, the ref and the exact
workflow file that asked for it, and cannot be replayed from another repository.

Two checks make that proof enough. The token must name the tenant's own
repository on its site branch, and the workflow file at the token's exact
commit must still be the platform's canonical deploy contract — so a modified
workflow cannot borrow the site's identity.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse
from typing import Any, Mapping
import urllib.error
import urllib.request

import jwt

ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = f"{ISSUER}/.well-known/jwks"
DEPLOY_WORKFLOW = ".github/workflows/release-deploy.yml"
_ALLOWED_EVENTS = frozenset({"push", "workflow_dispatch"})
_KEY_TTL_SECONDS = 300
_keys: tuple[float, dict[str, Mapping[str, Any]]] | None = None


class GitHubOIDCError(ValueError):
    """A release credential request did not prove enough."""


def _signing_keys() -> dict[str, Mapping[str, Any]]:
    global _keys
    now = time.time()
    if _keys is not None and _keys[0] > now:
        return dict(_keys[1])
    try:
        with urllib.request.urlopen(JWKS_URL, timeout=10) as response:
            document = json.load(response)
    except (OSError, ValueError) as exc:
        raise GitHubOIDCError("GitHub OIDC signing keys are unavailable") from exc
    keys = {
        str(item.get("kid")): item
        for item in (document.get("keys") or [])
        if isinstance(item, Mapping) and item.get("kid") and item.get("kty") == "RSA"
    }
    if not keys:
        raise GitHubOIDCError("GitHub OIDC signing keys are unavailable")
    _keys = (now + _KEY_TTL_SECONDS, keys)
    return keys


def verify(
    token: str,
    *,
    audience: str,
    repository: str,
    branch: str,
    workflow: str = DEPLOY_WORKFLOW,
) -> dict[str, Any]:
    """Return the verified claims, or raise with the exact reason it failed."""
    raw = str(token or "").strip()
    if not raw:
        raise GitHubOIDCError("a GitHub OIDC token is required")
    try:
        header = jwt.get_unverified_header(raw)
    except jwt.PyJWTError as exc:
        raise GitHubOIDCError("the GitHub OIDC token is unreadable") from exc
    key = _signing_keys().get(str(header.get("kid") or ""))
    if key is None:
        raise GitHubOIDCError("the GitHub OIDC token is not signed by GitHub")
    try:
        claims = jwt.decode(
            raw,
            key=jwt.PyJWK(key).key,
            algorithms=["RS256"],
            audience=audience,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise GitHubOIDCError("the GitHub OIDC token is not valid for this deploy") from exc
    named_repository = str(claims.get("repository") or "").strip().lower()
    if named_repository != str(repository or "").strip().lower():
        raise GitHubOIDCError("the GitHub OIDC token names a different repository")
    if str(claims.get("ref") or "") != f"refs/heads/{branch}":
        raise GitHubOIDCError("the GitHub OIDC token names a different branch")
    if str(claims.get("event_name") or "") not in _ALLOWED_EVENTS:
        raise GitHubOIDCError("only a push or an explicit deploy may fetch release credentials")
    workflow_ref = str(claims.get("job_workflow_ref") or "")
    expected_ref = f"{named_repository}/{workflow}@refs/heads/{branch}"
    if workflow_ref.strip().lower() != expected_ref:
        raise GitHubOIDCError("the GitHub OIDC token was not minted for the canonical deploy workflow")
    if not re.fullmatch(r"[0-9a-f]{40}", str(claims.get("sha") or "")):
        raise GitHubOIDCError("the GitHub OIDC token carries no exact commit")
    return dict(claims)


_verified_workflows: dict[tuple[str, str, str], bool] = {}


def repo_file(repository: str, ref: str, path: str, token: str) -> bytes:
    """Read one committed file at an exact ref through the GitHub API."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/contents/{urllib.parse.quote(path)}?ref={ref}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "site-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            document = json.load(response)
        if not isinstance(document, Mapping) or document.get("type") != "file":
            raise GitHubOIDCError(f"{path} is not a committed file at {ref[:8]}")
        return base64.b64decode(str(document.get("content") or ""))
    except GitHubOIDCError:
        raise
    except (OSError, ValueError, TypeError, urllib.error.HTTPError) as exc:
        raise GitHubOIDCError(f"{path} could not be read at {ref[:8]}") from exc


def verify_canonical_workflow(
    repository: str,
    sha: str,
    token: str,
    *,
    control_sha: str,
    platform_repository: str = "weareheadless/site-agent",
    workflow: str = DEPLOY_WORKFLOW,
    platform_path: str | None = None,
) -> None:
    """Refuse a credential request from a workflow that is not the canonical one.

    The OIDC token says which workflow asked, not what that file contains. Ada
    can commit; a commit can rewrite a workflow. The file at the exact commit is
    compared with the platform's own bytes at the control revision the
    repository pins — so a modified workflow cannot borrow the site's identity,
    and a pin that does not exist in the platform cannot vouch for anything.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", str(control_sha or "")):
        raise GitHubOIDCError("the repository does not pin an exact control revision")
    key = (str(repository).lower(), str(sha), str(control_sha))
    if _verified_workflows.get(key):
        return
    requested = repo_file(repository, sha, workflow, token)
    canonical = repo_file(
        platform_repository, control_sha,
        platform_path or f"src/site_agent/templates/next-payload/{workflow}", token,
    )
    if requested != canonical:
        raise GitHubOIDCError("the deploy workflow differs from the canonical contract")
    if len(_verified_workflows) > 512:
        _verified_workflows.clear()
    _verified_workflows[key] = True

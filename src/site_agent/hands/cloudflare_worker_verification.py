"""Read-only Cloudflare Worker deployment/version verification authority."""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable


def cloudflare_deployment(customer: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    url = ("https://api.cloudflare.com/client/v4/accounts/" + env["CLOUDFLARE_ACCOUNT_ID"]
           + "/workers/scripts/" + customer["worker"] + "/deployments")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {}
        raise RuntimeError(f"Cloudflare deployment inspection failed with HTTP {error.code}") from error
    if body.get("success") is not True:
        raise RuntimeError("Cloudflare deployment inspection failed")
    deployments = body["result"]["deployments"]
    if not deployments:
        return {}
    return max(deployments, key=lambda item: item["created_on"])


def worker_version_identity(version: Any) -> dict[str, str]:
    resources = version.get("resources") if isinstance(version, dict) else None
    script = resources.get("script") if isinstance(resources, dict) else None
    bindings = resources.get("bindings") if isinstance(resources, dict) else None
    etag = script.get("etag") if isinstance(script, dict) else None
    if not isinstance(etag, str) or not etag or not isinstance(bindings, list):
        raise RuntimeError("Cloudflare Worker version has incomplete code or binding identity")
    normalized_bindings = []
    names = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise RuntimeError("Cloudflare Worker version has an invalid binding")
        name, binding_type = binding.get("name"), binding.get("type")
        if not isinstance(name, str) or not name or not isinstance(binding_type, str) or not binding_type:
            raise RuntimeError("Cloudflare Worker version has an incomplete binding identity")
        if name in names:
            raise RuntimeError("Cloudflare Worker version has duplicate binding names")
        names.add(name)
        normalized_bindings.append({key: binding[key] for key in ("name", "type", "algorithm", "format") if key in binding}
                                   if binding_type in {"secret_text", "secret_key"} else binding)
    normalized_bindings.sort(key=lambda item: item["name"])
    identity = hashlib.sha256(json.dumps(normalized_bindings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"script_etag": etag, "binding_identity": identity}


def cloudflare_worker_version_identity(customer: dict[str, Any], version_id: str, env: dict[str, str]) -> dict[str, str]:
    url = ("https://api.cloudflare.com/client/v4/accounts/" + urllib.parse.quote(env["CLOUDFLARE_ACCOUNT_ID"], safe="")
           + "/workers/scripts/" + urllib.parse.quote(customer["worker"], safe="") + "/versions/"
           + urllib.parse.quote(version_id, safe=""))
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + env["CLOUDFLARE_API_TOKEN"]})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Cloudflare Worker version inspection failed with HTTP {error.code}") from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("Cloudflare Worker version inspection returned no valid response") from error
    if payload.get("success") is not True:
        raise RuntimeError("Cloudflare Worker version inspection failed")
    version = payload.get("result")
    if not isinstance(version, dict) or version.get("id") != version_id:
        raise RuntimeError("Cloudflare Worker version identity does not match the requested version")
    return worker_version_identity(version)


def require_active_worker_snapshot(customer, deploy_env, deployment_id, version_id, *, inspect_deployment=None):
    inspect_deployment = inspect_deployment or cloudflare_deployment
    current = inspect_deployment(customer, deploy_env)
    versions = current.get("versions")
    if (current.get("id") != deployment_id or not isinstance(versions, list) or len(versions) != 1
            or versions[0].get("version_id") != version_id or versions[0].get("percentage") != 100):
        raise RuntimeError("the active Worker version changed during readiness verification")


def resolve_verified_active_worker(customer, deploy_env, uploaded_version, *, inspect_deployment=None,
                                   inspect_version=None, require_snapshot=None, sleep=None):
    inspect_deployment = inspect_deployment or cloudflare_deployment
    inspect_version = inspect_version or cloudflare_worker_version_identity
    require_snapshot = require_snapshot or require_active_worker_snapshot
    sleep = sleep or time.sleep
    changed_message = "the active Worker version changed during readiness verification"
    for attempt in range(8):
        deployment = inspect_deployment(customer, deploy_env)
        versions = deployment.get("versions")
        if not isinstance(versions, list) or len(versions) != 1 or versions[0].get("percentage") != 100:
            raise RuntimeError("Cloudflare production deployment does not have exactly one 100%-traffic Worker version")
        active_version, deployment_id = versions[0].get("version_id"), deployment.get("id")
        if not isinstance(active_version, str) or not active_version or not isinstance(deployment_id, str) or not deployment_id:
            raise RuntimeError("Cloudflare production deployment has no active Worker identity")
        if active_version != uploaded_version:
            annotations = deployment.get("annotations")
            if not isinstance(annotations, dict) or annotations.get("workers/triggered_by") != "secret":
                raise RuntimeError("the active Worker differs from the release outside a secret-only update")
        uploaded_identity = inspect_version(customer, uploaded_version, deploy_env)
        active_identity = uploaded_identity if active_version == uploaded_version else inspect_version(customer, active_version, deploy_env)
        if uploaded_identity != active_identity:
            raise RuntimeError("the active Worker code or non-secret bindings differ from the exact release")
        try:
            require_snapshot(customer, deploy_env, deployment_id, active_version)
        except RuntimeError as error:
            if str(error) != changed_message or attempt == 7:
                raise
            sleep(0.25)
            continue
        return deployment, active_version, uploaded_identity, active_identity
    raise RuntimeError("Cloudflare production deployment kept changing during readiness verification")

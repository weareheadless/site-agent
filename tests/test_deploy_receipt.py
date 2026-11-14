import json
from pathlib import Path

import pytest

from site_agent.application.deploy_receipt import DeployReceiptError, record_runner_receipt

TENANT = "site-ff8e9af06f56201f"
SHA = "1" * 40
FINGERPRINT = "a" * 64


def _receipt(**overrides):
    value = {
        "schema": 2,
        "tenant": TENANT,
        "releaseId": "ci-43538212078-1",
        "sourceSha": SHA,
        "status": "deployed",
        "stage": "awaiting-browser-verification",
        "sharedRuntimeFingerprint": FINGERPRINT,
        "health": {"ok": True, "releaseSha": SHA},
        "currentVerification": {
            "releaseId": "ci-43538212078-1",
            "sourceSha": SHA,
            "uploadedVersion": "v",
            "workerVersion": "v",
            "deploymentId": "d",
            "trafficPercentage": 100,
            "uploadedScriptEtag": "b" * 64,
            "activeScriptEtag": "b" * 64,
            "uploadedBindingIdentity": "c" * 64,
            "activeBindingIdentity": "c" * 64,
            "mode": "exact",
            "verifiedAt": "2026-11-14T00:00:00Z",
        },
    }
    value.update(overrides)
    return value


def _record(root, receipt, **overrides):
    arguments = {"source_sha": SHA, "runtime_fingerprint": FINGERPRINT, **overrides}
    return record_runner_receipt(root, TENANT, receipt, **arguments)


def test_runner_receipt_is_kept_where_activation_reads_it(tmp_path):
    stored = _record(tmp_path, _receipt())
    assert stored["releaseId"] == "ci-43538212078-1"
    path = tmp_path / "runs" / TENANT / "ci-43538212078-1" / "receipt.json"
    assert json.loads(path.read_text(encoding="utf-8"))["sourceSha"] == SHA
    assert path.stat().st_mode & 0o777 == 0o600
    # The same run may report twice without becoming a different release.
    assert _record(tmp_path, _receipt())["releaseId"] == "ci-43538212078-1"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sourceSha": "2" * 40},
        {"tenant": "another-site"},
        {"releaseId": "rel-20261113203000-shared-retry-route"},
        {"status": "running"},
        {"stage": "build"},
        {"sharedRuntimeFingerprint": "d" * 64},
        {"health": {"ok": True, "releaseSha": "3" * 40}},
        {"currentVerification": None},
    ],
)
def test_runner_receipt_must_prove_what_it_claims(tmp_path, overrides):
    with pytest.raises(DeployReceiptError):
        _record(tmp_path, _receipt(**overrides))


def test_runner_receipt_never_overwrites_a_different_release(tmp_path):
    _record(tmp_path, _receipt())
    path = tmp_path / "runs" / TENANT / "ci-43538212078-1" / "receipt.json"
    path.write_text(json.dumps({**_receipt(), "sourceSha": "4" * 40}), encoding="utf-8")
    with pytest.raises(DeployReceiptError, match="different release"):
        _record(tmp_path, _receipt())

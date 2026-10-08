from __future__ import annotations

import pytest

from site_agent.application import worker_origin
from site_agent.application.worker_origin import WorkerOriginError


def _config():
    return {
        "site": {"source_deployment": {"worker_name": "oceanicvibes"}},
        "credentials": {
            "cloudflare": {
                "api_token_env": "CF_TOKEN",
                "account_id_env": "CF_ACCOUNT",
            },
        },
    }


def test_worker_preview_origin_uses_the_cloudflare_account_subdomain(monkeypatch):
    account_id = "a" * 32

    def workers_dev_url(client, worker_name):
        assert client.account_id == account_id
        assert client.api_token == "test-token"
        assert worker_name == "oceanicvibes"
        return "https://oceanicvibes.weareheadless.workers.dev"

    monkeypatch.setattr(worker_origin.CloudflareResourceProvisioner, "workers_dev_url", workers_dev_url)

    actual = worker_origin.canonical_worker_preview_url(
        _config(),
        {"CF_TOKEN": "test-token", "CF_ACCOUNT": account_id},
    )

    assert actual == "https://oceanicvibes.weareheadless.workers.dev"


def test_worker_preview_origin_fails_closed_without_registered_account_credentials(monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("Cloudflare must not be queried without account credentials")

    monkeypatch.setattr(worker_origin.CloudflareResourceProvisioner, "workers_dev_url", unexpected_call)

    with pytest.raises(WorkerOriginError, match="account credentials"):
        worker_origin.canonical_worker_preview_url(_config(), {"CF_TOKEN": "test-token"})


def test_worker_preview_origin_rejects_a_bare_workers_dev_host(monkeypatch):
    monkeypatch.setattr(
        worker_origin.CloudflareResourceProvisioner,
        "workers_dev_url",
        lambda _client, _worker: "https://oceanicvibes.workers.dev",
    )

    with pytest.raises(WorkerOriginError, match="invalid account-qualified"):
        worker_origin.canonical_worker_preview_url(
            _config(),
            {"CF_TOKEN": "test-token", "CF_ACCOUNT": "a" * 32},
        )

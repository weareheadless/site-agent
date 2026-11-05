# UI-047: read-only Worker verification extraction

`site_agent.hands.cloudflare_worker_verification` contains the existing Cloudflare
deployment/version inspection and active-version identity policy. It accepts an
exact uploaded version, or a Cloudflare secret-triggered replacement only when
script ETag and non-secret binding identity match. It requires a single version
at 100% traffic and retries only the existing active-snapshot drift condition,
with eight bounded observations and the existing delay.

The release script keeps its public function signatures as delegates and passes
its existing monkeypatchable Cloudflare, version, snapshot, and sleep seams into
the package resolver. Receipt recording, activation, and live verification stay
script-owned. The package has no activation, receipt, or filesystem mutation
path; fixtures test logic only and are not live deployment acceptance.

Run the package proof with `PYTHONPATH=src python -m pytest -q
tests/test_cloudflare_worker_verification.py` and the release suite with
`PYTHONPATH=src python -m pytest -q tests/test_payload_release.py`.

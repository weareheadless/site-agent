# UI-047 runtime activation provenance

After the existing normal or verify-only activation guards validate the
canonical release receipt and live Worker health contract, Site-Agent may
capture a typed, secret-free `site.payload.runtime_activation` binding. It is
stored beside the Payload contract, never inside that contract or in
`tenants.json`. The binding identifies the tenant, release, customer source,
control `pipelineSha`, shared-runtime fingerprint and uploaded Worker version.

This is **activation provenance, not runtime-parity verification**. It records
which canonical receipt was activated; it does not rehash control source bytes
or prove Cloudflare still serves that Worker. Any future parity/review resolver
must independently rehash the immutable control source, check current
deployment freshness, and freeze the binding before candidate review. It must
not fall back to current main. Those checks are deliberately outside this
capture-only change.

Historical receipts with both `pipelineSha` and
`sharedRuntimeFingerprint` absent or null continue to activate without a
binding. Partial or malformed provenance fails before config writes or runtime
mount. Activating an unbound release explicitly removes any prior binding;
ordinary remounts and owner-ready state changes preserve it.

The composed regression in `tests/test_bootstrap.py` uses a disposable local
tenant registry and a canonical normal-release receipt to exercise
`activate_runtime_after_health` through the real registration sync and registry
reload. It checks that the same exact receipt binding reaches persisted YAML
and the mounted registry while existing locale/media contract metadata remains
intact. This is a focused activation-path fixture, not full acceptance of the
remaining verify-only, restart, stale-release, malformed-input, or legacy
binding cases.

Journey status for this work: no Ada-created candidate, no observed defining
behavior, no real owner review, and no bypass workaround. The journey is not
ready. Capture remains a prerequisite only; no live reads/writes, model calls,
paid flow, release, provisioning, resolver, or Design transport are involved.

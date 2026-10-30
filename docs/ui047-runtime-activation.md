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

The composed regressions in `tests/test_bootstrap.py` use a disposable local
tenant registry and canonical receipts to exercise
`activate_runtime_after_health` through real registration sync and registry
reload. Normal and verify-only activation remain covered; the verify-only case
restarts the local registry and exercises the owner-ready update. Additional
cases change only receipt provenance while keeping schema/website identity
fixed, prove a stale mounted binding causes a real reload, reject incomplete or
malformed provenance before config/index writes or reload, and clear a previous
binding for a historical receipt with both provenance fields absent. A
separately labelled fault-injection guard makes reload a no-op only to prove
that post-reload validation raises instead of reporting success. The composed
cases check strict contract metadata including media and locale values. No
external services are contacted; this is local composition evidence, not live
runtime parity evidence.

Journey status for this work: confirmed intake remains a prerequisite only;
there is no Ada-created accepted candidate, no observed defining behavior, no
actual owner Design acceptance, and no bypass workaround. The journey is not
ready. No provider, paid flow, release, provisioning, customer mutation,
resolver, or Design transport is involved.

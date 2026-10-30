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

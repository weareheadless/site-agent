# UI-047 registered runtime resolution

`RuntimeResolutionService` is a read-only authority check for one already
registered and mounted tenant. It reads `runtime_activation` from that
tenant's Payload config, selects only the matching canonical release receipt,
checks its successful status, identity, health contract and uploaded-version
deployment evidence, then invokes the shared Cloudflare active-Worker verifier
with the registered Worker and centrally resolved credentials.

The immutable result contains the activation and only deployment/version and
normalized code/non-secret-binding identities. It is evidence, not frozen build
inputs or a candidate. It performs no receipt, configuration, activation or
Cloudflare writes and has no fallback to another release or moving `main`.
The canonical verifier's exact-version and secret-only replacement rules are
preserved. Receipt and registered identities are reread after verification;
the active deployment snapshot is required again before return.

This evidence is point-in-time and does not provide perpetual freshness. A
future retained-candidate acceptance must revalidate the registration, exact
receipt and active Worker before using the candidate. Control materialization,
nonsecret config freeze, content snapshots, artifacts, visual/behavioral review
and owner Design acceptance are later boundaries. This work does not establish
UI-047 or UI-056 as Verified.

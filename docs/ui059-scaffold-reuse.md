# UI-059: canonical neutral scaffold admission

`initialize_neutral_repository` now validates a newly copied managed Payload
template before creating its baseline commit. Reuse applies the same validation
before returning the baseline SHA. The accepted `templateSchema` comes from the
checked-in canonical `next-payload/template-manifest.json`; the package pin,
content contract, schema identity, canonical Payload config and managed guide
checks remain strict. No compatibility range or schema migration is introduced.

Focused tests create a real canonical template, verify unchanged reuse from a
fresh intake service/memory context, and reject altered schema/package pins,
dirty scaffolds and remote-backed scaffolds. The planner test seam creates the
typed planning request and enqueues it; it does **not** call Ada or prove a site
build, validation, owner-facing experience, deployment, or browser acceptance.
Those gates remain unproven and manager-owned. The fix addresses admission only;
it does not resolve the separate dynamic-build/static-output boundary.

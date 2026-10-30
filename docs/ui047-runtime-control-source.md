# UI-047 exact runtime control source

`materialize_runtime_control` is an internal helper for a previously validated
`RuntimeActivation` and an operator-owned local Site-Agent Git repository. It
does not choose a receipt, deployment, tenant identity, or control revision.
The repository's `origin` must be the canonical Site-Agent GitHub SSH/HTTPS
URL. The helper reads only local Git objects and archives the binding's full
commit SHA; it never fetches, selects a branch, changes the mirror index, or
executes archived code.

Archive entries are screened before writing into a private temporary directory
under the caller's explicit existing scratch parent. The reviewed shared-runtime
fingerprint is calculated from those exact files and must match the activation
before a typed proof is yielded. The proof includes both the full control SHA
and isolated source root. The directory is removed when the context exits,
including exceptions. This is a short-lived source snapshot, not a freshness,
parity, owner-approval, or current-deployment assertion. Canonical receipt
selection, deployment verification, frozen tenant configuration, drift checks,
dynamic Worker/assets transport, and owner Design review remain future work.

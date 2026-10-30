# UI047 runtime control source boundary

`materialize_runtime_control` accepts an already-validated `RuntimeActivation`
and an operator-owned local Site-Agent Git mirror. It confirms the official
origin and resolves only the exact full control commit recorded in the binding.
It does not select a receipt, fetch from a remote, follow a branch, or execute
historical source.

The helper reads the commit tree with `git ls-tree` and each regular blob with
`git cat-file`. Git archive attributes therefore cannot omit or rewrite bytes.
Only regular non-executable/executable blobs are accepted; symlinks, gitlinks,
other modes and unsafe paths fail closed. The executable bit is retained. The
whole tree is written into a private, per-context temporary directory beneath
the caller's existing scratch parent. The reviewed shared-runtime fingerprint
is checked before yielding the typed proof, which also retains the exact control
SHA. The mirror, its index and tenant candidate sources are not modified.

The snapshot is removed on normal exit, validation failure, and caller
exceptions. Caller exceptions propagate unchanged. Independent invocations do
not share snapshot state. This is only exact local source materialization; it
does not establish deployment freshness/parity, resolve canonical receipts,
freeze tenant configuration, detect candidate drift, transport dynamic Worker
assets, or establish owner Design acceptance.

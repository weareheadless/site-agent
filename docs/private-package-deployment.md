# Private shared packages in the VPS pipeline

The shared GitHub API credential is stored in `/SOCIAL/configs/github.env`,
referenced by `/SOCIAL/configs/host-credentials.yaml`. It is not tenant-owned.
Only the operator and trusted deployment adapter may read it. Never include it
in source, subprocess arguments, logs, Worker variables, or tenant builds.

Each deployment fetches both exact shared-package release assets using GitHub's
authenticated release API. It requires an exact release URL, compares the
download to committed SHA-512 lockfile integrity and GitHub's SHA-256 digest,
then seeds npm's content-addressed cache. Cross-host redirects strip the token.
The clean `npm ci --prefer-offline` still installs the committed lockfile;
there is no alternate artifact, local-source replacement, or silent recovery.
Missing credentials, assets, or integrity matches stop the deployment.
Deployment subprocesses and release-asset staging use the release's own
disk-backed `temporary` directory, not the host's shared memory-backed `/tmp`.

Keep new-site scaffold pins, registry pins, tenant manifests and lockfiles in
sync. A published package is not a deployed tenant. Use the unique-ID/full-SHA
VPS queue and verify authenticated browser behavior afterward.

# HelloAda VPS deployment pipeline

## Release command

1. Review, test and push the customer source to its official GitHub `main`.
2. In `site-agent`, update `deploy/desired-releases.json` with the registered
   tenant, full customer commit SHA and a new release ID:

   ```json
   {
     "schema": 1,
     "releases": {
       "oceanicvibes": { "id": "20261003-release-1", "sha": "<full 40-character SHA>" }
     }
   }
   ```

3. Run `python -m pytest -q tests/test_payload_release.py`, then commit and push
   the queue to official `site-agent/main`.
4. The VPS discovers the request within one minute. Check it with:

   ```bash
   ssh codex-vps 'systemctl status helloada-release.service --no-pager'
   ssh codex-vps 'journalctl -u helloada-release.service -n 80 --no-pager'
   ```

5. Read `/SOCIAL/payload-releases/runs/<tenant>/<release-id>/receipt.json`.
   `deployed` means upload, exact live SHA and authenticated Ada/Payload checks
   passed. It still requires a fresh signed-in browser check. Record that check
   in `browser-verification.json` beside the receipt before reporting completion.

Keep the latest request for each tenant in the queue. Existing terminal receipts
make it idempotent: unchanged requests do no work. Failed or interrupted requests
are recorded and never rebuilt by every poll. Fix the cause, then commit a new
release ID. A release ID cannot be reused for a different source SHA.

To cancel an obsolete build, stop `helloada-release.timer` and then
`helloada-release.service`. The service stops its complete process group. Commit
the corrected source and a new release ID, then start the timer again. The next
poll records unfinished receipts as `interrupted`, including requests superseded
in the queue. Never edit the canceled source directory or resume its upload.

## What executes

`helloada-release.timer` starts a systemd service every minute after the previous
run finishes. The service fetches official `site-agent/main` via the existing
host GitHub SSH identity and snapshots the control commit. It runs that snapshot's
tests, manifest and pipeline, so later Git changes cannot alter an in-flight run.
It persists across SSH/chat disconnects and machine restarts. A systemd timeout
kills the complete process group; the next poll records an interrupted attempt.

Each customer gets a fresh Git clone. The pipeline checks its source SHA is on
official `main`, uses Node 22 and `npm ci`, typechecks and builds OpenNext with
local bindings. Production credentials are supplied only to Cloudflare calls,
never to dependency installation or builds. The artifact is inspected, hashed
and archived before upload. The pipeline checks production did not change during
the build, uploads an immutable version and promotes that exact version to 100% traffic,
checks the live SHA and tenant, then performs the authenticated connection gate.

Application releases use OpenNext `upload` and Wrangler `versions deploy`.
Domain routes, DNS and cron triggers are provisioned separately and are never
rewritten by an application release. This keeps the existing deployment token's
Worker permissions sufficient. See [Cloudflare's deployment permissions](https://developers.cloudflare.com/workers/authorization/workers/)
and [OpenNext's upload command](https://opennext.js.org/cloudflare/cli).

Artifacts, source, receipts and previous Cloudflare versions are retained under
`/SOCIAL/payload-releases`. Customer content and databases are untouched. Schema
migrations require a separate reviewed migration release; this command does not
guess or apply them. Rollback uses the previous receipt's Cloudflare version with
`wrangler versions deploy <version>@100% --name <worker> --yes` through the
declared credential profile, followed by live checks. It never rolls back data.

## Install/update the service

From a reviewed, clean `/SOCIAL/site-agent` checkout on the VPS:

```bash
sudo install -m 0644 deploy/helloada-release.service /etc/systemd/system/helloada-release.service
sudo install -m 0644 deploy/helloada-release.timer /etc/systemd/system/helloada-release.timer
sudo systemctl daemon-reload
sudo systemctl enable --now helloada-release.timer
```

The service uses `/SOCIAL/site-agent/.venv/bin/python`. The host profile at
`/SOCIAL/configs/host-credentials.yaml` supplies GitHub SSH wiring and the
Cloudflare credential file. No GitHub PAT, runner registration, webhook secret or
inbound deployment endpoint is needed. GitHub's hosted CI validates the release
contract; the VPS performs the same validation before execution.

## Rules for coding agents

- Use this queue for every customer Worker release. Do not run direct
  `npm run deploy`, `deploy:app`, or Wrangler uploads from an arbitrary checkout.
- Register future tenants in `deploy/payload-customers.json` first. The customer
  must use `/api/helloada/*`, the shared Payload package, and the health route
  from the default template.
- Read the receipt and failed stage before changing source. Never use an old
  build, a different credential file, a fallback route or an automatic rollback
  to turn a failed gate into a success.
- A shared admin package release requires version-pin updates and queue entries
  for every selected consumer. Publishing a package alone cannot redeploy them.
- Source, artifact, deployment and authenticated browser verification are
  separately recorded. Report only what those records prove.

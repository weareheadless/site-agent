# HelloAda managed website

This repository is generated and managed by HelloAda. Content is edited in
Payload, design changes are owner-approved, and the live Worker is deployed
from the GitHub `main` revision recorded by the control plane.

The bootstrap service binds `src/helloada.config.ts` to one non-secret tenant
identity before the first customer commit. The Payload admin is provided by
the exact `@weareheadless/helloada-payload-admin` release in `package.json`;
do not copy the package into a customer repository or replace it with the
retired FastAPI admin.

`npm run verify:payload` is a release gate. It exercises published, draft, and
version reads for every editable collection plus both shared globals and media.
It must pass against the tenant's remote D1 database before the Worker is
deployed; a failed query is a schema/runtime error, never an empty-content
fallback.

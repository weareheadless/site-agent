# HelloAda managed website

This repository is generated and managed by HelloAda. Content is edited in
Payload, design changes are owner-approved, and the live Worker is deployed
from the GitHub `main` revision recorded by the control plane.

The bootstrap service binds `src/helloada.config.ts` to one non-secret tenant
identity before the first customer commit. The Payload admin is provided by
the exact `@weareheadless/helloada-payload-admin` release in `package.json`;
do not copy the package into a customer repository or replace it with the
retired FastAPI admin.

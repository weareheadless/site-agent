# Payload client context repair

Authenticated browser verification of both tenants exposed a client error:
`Cannot destructure property 'config' ... as it is undefined`.

The shared navigation imported `useConfig` from
`@payloadcms/ui/providers/Config`. Payload 3.88's public client export is a
bundled entry point that contains its own configuration context. Mixing that
entry point with the standalone provider module produces different React
context identities. A provider from one cannot satisfy a consumer of the other.

The shared navigation must import `useConfig` from `@payloadcms/ui`, the same
public client entry point as Payload's admin components. Do not mask this with
optional chaining, a default configuration, a duplicate provider, or static
collection lists. A source regression test asserts the intended import.

Release the shared package immutably, update the canonical scaffold and every
registered consumer pin, and deploy through the VPS queue. HTTP 200 and backend
connection checks do not establish admin readiness: verify the signed-in
workspace, content collections, Growth, gallery and history in a browser.

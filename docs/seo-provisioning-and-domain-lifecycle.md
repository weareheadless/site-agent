# Tenant SEO provisioning and domain lifecycle

This is the generic contract for every public website. It contains no
customer-specific domain or hosting rules.

## Provisioning contract

When a tenant receives its first public origin, `site-agent` must converge the
tenant to:

1. one GA4 property and web stream;
2. one verified Search Console URL-prefix property for the current origin;
3. one CrawlSEO project linked to the GA4 property and current GSC property.

The tenant's public origin is stored in `site.public_url` and `seo.site_url`.
The same value is normalized to an HTTPS/http root URL before it is sent to a
provider. Provisioning is idempotent and may be retried during startup or
scheduler recovery.

The system is not ready until the live public HTML contains the issued GSC
verification tag and Google confirms ownership. CrawlSEO work is held until
that point. A pending provider receipt is not presented as a successful
connection.

## Domain change contract

The authenticated control-plane operation is:

```text
POST /v1/control-plane/websites/{tenant_id}/site-origin
{ "public_url": "https://customer.example/" }
```

This operation:

- updates the tenant configuration;
- makes the new origin current for canonical URLs and provider calls;
- preserves the previous origin in durable provisioning history;
- keeps the stable tenant ID and GA4 property;
- re-runs GSC verification for the new origin;
- rebinds CrawlSEO to the new domain after verification;
- reloads the isolated tenant runtime from the persisted configuration.

The deployment target is resolved from the tenant's platform deployment
configuration. A custom domain never changes the Worker name, tenant identity,
or another tenant's context. Cloudflare DNS is used only when the tenant's
configured verification/deployment path requires it.

## Runtime requirements

Customer Workers receive `GOOGLE_SITE_VERIFICATION` and `GA_MEASUREMENT_ID`
as encrypted bindings. The canonical Payload/Next template reads those values
at request time through the Cloudflare runtime context. They are not public
`vars`, build-time constants, or browser configuration.

## Isolation requirements

All provisioning state, provider credentials, memory, configuration, and API
responses are keyed by the stable tenant ID. No tenant name, production domain,
or customer fixture may appear in shared provisioning logic, prompts, or
default context. A customer-specific value may exist only in that tenant's
configuration and durable state.

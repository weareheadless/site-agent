# Registered mail management and mail alerts

This is the canonical contract for who owns a tenant's mail, and for the
alerts that tell the owner about it. It extends
`docs/mailflare-single-worker-contract.md`; where the two disagree, this
contract wins.

## Why the platform does not read the answer from DNS

An apex without MX records looks like a domain nobody has mail for. It is also
what a deleted record looks like, and what a provider migration looks like
while the owner is moving their mail. The three need different answers, and
DNS cannot tell them apart.

So the platform never infers ownership from the records. The registered
settings are the only authority:

```yaml
messages:
  email:
    enabled: true
    domain: helloada.app
    local_part: inmersion-freediving-bb2a4e404a7fcea4
    domain_source: helloada_platform
    management:
      mode: external          # managed | external
      provider: GoDaddy       # label of the provider that owns the mail
    alerts:
      enabled: true
      recipient: owner@example.com
      subject: ""             # empty uses the default template
      body: ""                # empty uses the default template
      inbound: true           # warn when mail arrives in the HelloAda inbox
      external: true          # warn that the domain mail is handled elsewhere
    provisioning:
      auto: false
```

`mode: external` means the tenant's domain mail is managed outside HelloAda.
For that tenant the platform never writes mail DNS, an Email Routing rule, a
mailbox, a sender key or a routing status - whatever the records look like at
the time, and whether the tenant's site origin changes.

`mode: managed` is the default. The platform provisions the tenant's mailbox
on its registered email domain, exactly as before.

## The settings surface

The tenant settings are the registered tenant configuration, and they are
readable and writable through the owner's authenticated bridge:

- `GET /api/workspace/settings/email` - the registered settings and the
  effective mailbox.
- `PUT /api/workspace/settings/email` - change who owns the mail and how the
  owner is warned. Requires the authenticated owner actor.
- `GET /v1/control-plane/websites/{website_id}/settings/email`
- `PUT /v1/control-plane/websites/{website_id}/settings/email`

A request merges over the registered settings, so changing the mode never
clears the alert configuration:

```json
{
  "mode": "external",
  "provider": "GoDaddy",
  "alerts": {"enabled": true, "recipient": "owner@example.com"}
}
```

`alerts.recipient` is required while an alert is enabled. An alert with no
registered recipient is disabled, and no notice is promised.

## The two alerts

Both are sent with the tenant's own restricted Resend key, from the tenant's
own mailbox address. The platform's management key never sends tenant mail.

- **inbound** - mail arrived in the tenant's HelloAda inbox. The owner is told
  that they have mail and where to read it.
- **external** - the tenant's domain mail is handled somewhere else. The owner
  is told that HelloAda is not managing it, so nobody waits for mail that
  HelloAda never receives. The notice is sent when the owner registers the
  external mode.

The subject and body are configurable. The supported placeholders are
`{site}`, `{mailbox}`, `{domain}`, `{provider}` and `{subject}`.

The defaults:

- inbound: "You have mail waiting for {site}. Check HelloAda to read it in
  your inbox: {mailbox}."
- external: "Mail addressed to {domain} is handled by {provider}, not by
  HelloAda. Enquiries from your website still arrive in your HelloAda inbox:
  {mailbox}."

## Who reports the mail

The tenant Worker owns the mailbox, and the platform owns the owner's alert
settings. The Worker reports an arrival and the platform decides whether
anybody is warned and how:

- `POST /api/workspace/mail/notification` with the tenant's service token and
  `{messageId, subject, from, kind}`.

The report is a notice, never a delivery step. A failed report does not block
mail: the message is already stored, and each reported message id is alerted
once.

## What the platform never does for an externally managed tenant

- It never plans or provisions mail for the tenant, whatever the records look
  like.
- It never derives the mailbox from the site origin. A domain change does not
  move the tenant's mail.
- It never delivers the tenant's Mailflare runtime settings as a first
  bootstrap release. A tenant that already has an active HelloAda mailbox
  keeps it, and its website enquiries keep arriving.

# Positioning — Ada, your webmaster

**Status:** working positioning for `site-agent`. Proof of concept runs on OceanicVibes (customer #0).

## One-liner

> Ada is your webmaster. She audits your SEO, reads your traffic, writes about what's happening in your world, updates your site when you ask, and tells you every week what happened — in plain language, not dashboards. You own everything. Every change she makes is visible and reversible.

## Target customer

Owner-operated service businesses where the website *is* the lead machine:

- instructors, guides, tours, retreats (freediving, diving, surf, yoga)
- boutique accommodation, niche craftspeople, independent practitioners

Traits:

- can't justify a $500+/mo agency retainer
- will never buy an SEO suite ($99–249/mo, jargon walls)
- understands "Google" and "Instagram", not GSC / GA4
- feels quiet guilt about their neglected website

## What they're actually buying

Not "an AI agent". They are buying:

**"My site takes care of itself, Google can find me, and when I want something changed I just say so."**

The enemy is not other tools. It is the expensive web-guy retainer and the do-nothing option.

## Competitive frame

| Against | Message |
|---|---|
| Doing nothing | "Your site is quietly dying in Google." |
| Agencies ($500+/mo) | "What you pay an agency, Ada does for coffee money — and you see every change." |
| SaaS suites (OTTO, Alli AI, vaza, SEOmatic…) | No dashboard to learn. No jargon. No pixel injected into your site. You own everything. |

Those suites sell like scams to anyone outside marketing. We win by being the opposite: transparent, plain-spoken, owned by the customer.

## Four pillars

1. **Trust through transparency** — every action is a git commit she shows you; nothing goes live without approval (`ask_first` default). The category has a trust problem; trust is our brand.
2. **Plain-language reporting** — "214 people found you this week searching 'freediving Playa del Carmen', up 12%. I refreshed your courses page because…" Never "your AEO score dropped".
3. **You own everything** — runs on your VPS, your GitHub, your GA4. Cancel tomorrow and every word stays yours.
4. **She knows your business** — memory + personality means continuity: she remembers what worked last month and builds on it. Faceless tools reset; she compounds.

## Pricing posture

Price against the retainer, not against SaaS tiers. Flat, one-number tiers by *how much she does* — never feature-gate basics.

| Tier | ~Price | Includes |
|---|---|---|
| Starter | $29/mo | audit + monthly report + edits on request |
| Active | $59/mo | + weekly report/article + social post proposals |
| Hands-off | $99/mo | + auto-publish within guardrails |

LLM cost per light-use site ≈ $5–15/mo, so margins hold at the bottom tier.

## Retention & risk notes

- **Perceived value must be weekly**, or customers churn before SEO compounds (2–3 months). The plain-language weekly report is the retention engine, not a nice-to-have. It is a hero feature, not an afterthought.
- **Support burden**: non-technical users break things and ask basic questions. Sell productized first (we install and operate each instance); open self-serve only after 5–10 paying sites taught us the failure modes.
- **Message test before scale**: pitch paragraph + mockup of the weekly report to 3–5 real owners. If "she writes about our world and I just approve" beats "AI-powered SEO agent", positioning confirmed.

## Proof of concept: OceanicVibes

OceanicVibes is customer #0 and the validation vehicle.

- Run Ada live on the real site: daily learning from freediving sources, GA4-aware, weekly report, editor chat, articles on approval.
- Use it as the live demo when approaching similar businesses in freediving / water-sports communities.
- Validation signals (what "interest triggered" looks like):
  - owners ask "can it run my site too?" unprompted
  - willingness to pay ~$29+/mo without heavy convincing
  - the owner engages with the weekly report most weeks
- If signals don't appear, we learn whether the wedge is the message, the price, or the segment — before building more.

## Roadmap implication

Hero features, in priority order:

1. **Weekly report** (plain language, from her senses + her own actions)
2. **Editor chat** ("change the hero subtitle… add a section…" → preview → approve → commit)
3. Audit / GA4 analysis underneath, feeding the report

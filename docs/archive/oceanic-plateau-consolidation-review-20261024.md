# Oceanic plateau articles: owner review

Read-only comparison from the registered Payload gateway and current public pages on 2026-10-24. No content was edited, removed, fact-checked, or published.

## The two articles today

| Payload post | Public URL | Payload read state | Dates | Length and structure |
|---|---|---|---|---|
| **#2 — “Why Your Freediving Progress Has Plateaued — and Why That's Normal”** | [Current article](https://oceanicvibes.com/blog/why-your-freediving-progress-has-plateaued-and-why-thats-normal) | `published`; `published=true` | `publishedAt` 2026-08-28; created 2026-09-30, updated 2026-10-05 | 771 words; 4 sections: “The wall you're hitting isn't a ceiling,” “You can't test your way to a new max,” “What a training trip should be for,” “Patience is the skill.” |
| **#5 — “Why Your Freediving Progress Has Plateaued — and Why That's Normal”** | [Second article](https://oceanicvibes.com/blog/why-your-freediving-progress-has-plateaued-and-why-that-s-normal) | `_status=draft`; `published=true` | `publishedAt` empty; created and updated 2026-10-16 | 505 words; 4 sections: “Separate a plateau from a warning sign,” “Test less and practice better,” “Build a training week around skill,” “Patience is part of the method.” |

Both URLs currently return HTTP 200 and the public blog listing links to both. The Payload records have the same title but distinct slugs and distinct bodies. The first URL renders the story-led #2 text, beginning with a student's apnea logs; the second renders #5, beginning with a plain definition of a plateau. The public renderer selects content by slug with `published=true`; this is why #5 is reachable despite its draft marker. Keep these as separate observed facts, not as evidence of a write or approval.

## What overlaps and what differs

Both pieces address the same reader need: a freediver sees progress stall and wants to know how to respond without treating every session as a max test. They share advice around spacing max attempts, practicing skills, recovery, and making a Riviera Maya training week about comfort rather than records.

The articles take different approaches. #2 uses a specific student story and develops the plateau as a normal adaptation phase, then connects it to Playa del Carmen and Bacalar. #5 is a shorter, more structured explainer. It separates a stable plateau from warning signs and advises rest or qualified guidance when fatigue, pain, discomfort, or confidence changes. Those are differences in editorial treatment; this comparison does not validate the safety or factual claims in either piece.

## Links and search signals

- Home links to `/blog`; the blog listing links to both article URLs. Each article page links back to `/blog`. No link between the two articles was found.
- #2 has no public canonical tag. #5's Payload `canonicalUrl` and rendered canonical tag point to `https://oceanicvibes.com/post/why-your-freediving-progress-has-plateaued-and-why-that-s-normal`; that URL currently returns 404. Its live article is at the `/blog/` URL above.
- The shared route reader resolves a post by its slug and `published=true`; the shared SEO helper can emit a canonical URL from the document. The inspected shared route resolver has no redirect rule, and no redirect implementation was found in the shared Next/Payload template. If an owner selects consolidation, the old #5 URL needs an intentional permanent redirect to the retained URL, the canonical tag must point to the retained URL, and the listing must stop presenting #5 as a separate article. Do this only through a supported shared route/release mechanism; do not patch a tenant template ad hoc. No redirect or canonical change is proposed or applied here.

## Editorial recommendation for the owner's decision

I recommend one authoritative article for this reader question. Keep #2's existing URL and story-led article as the starting point because it gives the reader a concrete situation and location-specific context. Treat #5 as source material for an owner-reviewed revision if its clearer warning-sign distinction is desired; do not keep two public articles with the same title and near-identical intent. This is an editorial recommendation only. It does not authorize editing, unpublishing, redirecting, or publishing either post. The owner still needs to choose whether to consolidate or keep both with differentiated titles and intent.

The comparison is based on current text and routing only. Neither article's claims or cited/provenance basis have been independently fact-checked.

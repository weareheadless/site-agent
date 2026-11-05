# Oceanic content cleanup inventory — 2026-10-23

Read-only inventory from the registered OceanicVibes Payload gateway (`/api/workspace`) and its registered `memory.db` opened with SQLite `mode=ro`. The private full-fingerprint audit is `/tmp/oceanic-content-cleanup-inventory-20261023-audit.json` (mode 0600); it contains hashes and local row metadata, no body text or credentials.

## Canonical Payload posts

Canonical per-ID reads with `draft=false` returned IDs 1–2 as `_status=published` and IDs 3–7 as `_status=draft`; all seven also carried `published=true`. The public blog listing links to all seven routes, and each route returned HTTP 200. Record the Payload status marker and public reachability as separate observed facts; do not infer a content effect or change either state from this inventory. Fingerprints below are SHA-256 of canonicalized `body` JSON; full hashes are in the private audit.

| ID | Title | Slug | `_status` / `published` | Body SHA-256 prefix |
|---:|---|---|---|---|
| 1 | Beyond the Course: How to Find a Freediving Teacher Who Adapts to You | `beyond-the-course-how-to-find-a-freediving-teacher-who-adapts-to-you` | published / true | `66014b6a0310` |
| 2 | Why Your Freediving Progress Has Plateaued — and Why That's Normal | `why-your-freediving-progress-has-plateaued-and-why-thats-normal` | published / true | `3ef89090f025` |
| 3 | Frenzel Works on Land, Not Underwater: What to Do When Equalization Stalls on the Depth Line — and Whether That Means Freediving Isn't for You | `frenzel-works-on-land-not-underwater-what-to-do-when-equalization-stalls-on-the-depth-line-and-wheth` | draft / true | `7777bf0c84df` |
| 4 | What to Practise on Land Before a Freediving Course in Playa del Carmen or Bacalar — and Whether CO2 Tables Are Worth Your Three Months | `what-to-practise-on-land-before-a-freediving-course-in-playa-del-carmen-or-bacalar-and-whether-co2-t` | draft / true | `f6c5197a083f` |
| 5 | Why Your Freediving Progress Has Plateaued — and Why That's Normal | `why-your-freediving-progress-has-plateaued-and-why-that-s-normal` | draft / true | `56cf550a1a34` |
| 6 | How to Choose a Freediving Course in Playa del Carmen: A Local's Guide | `how-to-choose-a-freediving-course-in-playa-del-carmen-a-local-s-guide` | draft / true | `cfea0730b06a` |
| 7 | Cenote or Ocean: Where Your First Freediving Course Should Happen | `cenote-or-ocean-first-freediving-course` | draft / true | `46955b22ec9f` |

### Public route and overlap assessment

- **No exact cross-document duplicates found:** Bodies for distinct IDs do not have matching canonical hashes or identical normalized prose. Matching a body's hash in a draft and published read of the same ID is just the same document revision, not duplicate content.
- **Plateau article collision in editorial identity:** IDs 2 and 5 share the exact title but have different slugs (the `that's` contraction is normalized differently) and different body hashes. Both public routes return 200. The ID 2 route renders text beginning “This week a student sent me a month of static apnea logs”; the ID 5 route renders text beginning “A plateau is a period in which a measured result stays close to the same level.” This proves two distinct public article versions under separate URLs, not a duplicate URL or identical article. **Review/merge** if one current article is intended.
- **Other topic overlap:** ID 6 (choosing a course) and ID 1 (choosing an instructor) are separate articles with adjacent reader intents; their shared broad theme alone is not a merge case. ID 7's cenote/ocean comparison also has a distinct angle from course choice and land practice.
- **Current navigation:** The live home page links to `/blog` in its header and footer. The public `/blog` listing links to all seven article routes in the table. Preserve all canonical documents and their history during any local cleanup.

## Canonical page

| ID | Title | Slug | `_status` / `published` | Sections SHA-256 prefix |
|---:|---|---|---|---|
| 1 | Master your depth | `home` | published / true | `70eca1ea7e6b` |

The published and draft reads of this page have the same sections fingerprint. Its current home content links to `#philosophy`, `#training`, and `#contact`, and out to `/blog`; the public home page returned HTTP 200. No other Payload pages were listed.

## Local legacy drafts and ideas

The registered local store contains 55 rows in `drafts`, 12 `article_ideas`, and one `rejected_article_ideas` row. `drafts` includes non-article operational/site-edit records as well as articles; only the article rows below are editorial candidates. These are legacy workflow records, not canonical published content.

| Local draft | State | Linked idea | Relationship / recommendation |
|---|---|---:|---|
| #44 “Beyond the Course: How to Find a Freediving Teacher Who Adapts to You” | approved | #1 drafted | Same title as Payload post #1; retain as history, **review** before any new action. Local body equivalence to Payload is not proven. |
| #49 same title | pending | — | Pending local record. `payload_sync` is blocked because route content differs and is not linked to its exact sync record; **retire obsolete local generation intent**, preserving the local row and all Payload history. |
| #46 “Why Your Freediving Progress Has Plateaued — and Why That's Normal” | approved | #5 drafted | Same title as Payload posts #2 and #5; local body identity to either is unproven. **Review** rather than merge based on title alone. |
| #50 same title | pending | — | Second local record on the plateau topic. `payload_sync` is blocked by route-content mismatch; **retire obsolete local generation intent**, preserving the local row and all Payload history. |
| #45 “How to Choose a Freediving Course in Playa del Carmen: A Local's Guide” | pending | #4 drafted | Local sync is blocked by route-content mismatch; **retire obsolete local generation intent**, preserving the local row and all Payload history. Do not merge with instructor article #1 based only on broad subject overlap. |
| #58 “What to Practise on Land Before a Freediving Course in Playa del Carmen or Bacalar — and Whether CO2 Tables Are Worth Your Three Months” | pending | #10 drafted | Local sync is blocked by route-content mismatch; **retire obsolete local generation intent**, preserving the local row and all Payload history. Same title as Payload #4; local body equivalence is unproven. |
| #60 “Frenzel Works on Land, Not Underwater: What to Do When Equalization Stalls on the Depth Line — and Whether That Means Freediving Isn't for You” | pending | #11 drafted | Local sync is blocked by route-content mismatch; **retire obsolete local generation intent**, preserving the local row and all Payload history. Same title as Payload #3; local body equivalence is unproven. |
| #2 “AIDA, PADI, or Molchanovs? Choosing the Right Freediving Certification for Playa & Bacalar” | discarded | — | Older certification-choice topic overlaps course-choice content; **archive**. |
| #8 “The Slow Teacher: Why Breath Control Is a Practice, Not a Performance” | discarded | — | Broad training-philosophy overlap; **archive**. |
| #9 “The Halocline in Bacalar: How a Density Shift Teaches Calm” | declined | — | Narrow cenote/halocline idea; related to #7 but not a duplicate; **archive** unless revived with evidence. |

For pending local drafts #45/#49/#50/#58/#60, `meta.payload_sync` contains only `state=blocked` and a validation explanation; it has no exact operation key, package hash, or effect receipt. There are no direct `owner_actions`, `approval_requests`, `publishes`, or matching `chat_jobs` references for these IDs; draft-to-idea links exist for #45/#58/#60. These are local generation intents whose cleanup must use the explicit retirement path and preserve destination documents/history. Retirement records the prior effect as unknown; it does not assert that no historical write occurred.

Remaining idea records: #2 failed (wetsuit), #3 held (finding a buddy), #6 held (AIDA membership), #7 held (sinus/equalization), #8 held (finding freediving vs scuba training), #9 held (safe post-course buddy training), and #12 failed (CO2 tables vs max hold). These are distinct possible angles; **review** evidence and owner relevance before reuse. Ideas #1, #4, #5, #10, and #11 link to the article drafts above. The single rejected-idea row is retained as history.

## Suggested disposition

- **Keep:** all canonical Payload records, their current revisions, and their history; preserve local draft and idea rows as retirement history.
- **Review:** the two plateau articles (#2/#5) for editorial consolidation because they share a title and topic but have different bodies and routes; held ideas with possible future value.
- **Merge:** only if the owner chooses one plateau article to retain as the canonical editorial piece; the current records remain separate in Payload until then. No broad-theme merge is proposed for the instructor and course-choice articles.
- **Archive:** withdraw obsolete local generation intent for pending drafts #45/#49/#50/#58/#60 through the explicit retirement path, preserving their local rows and any destination records. Locally discarded/declined drafts remain history. No published deletion is proposed.

This inventory establishes identity, overlap and workflow linkage only. Some local ideas cite community sources, but this review did not validate their provenance or the factual accuracy of any article.

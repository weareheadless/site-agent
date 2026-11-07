# Content recovery: versions, restores and draft reverts

Source is recoverable through Git. Content lives in Payload, so it needs its
own equivalent: every write names the exact revision it replaced, and every
revert restores that exact version instead of reconstructing content.

## What a write records

A Payload write already carries the exact revision it read (compare-and-swap).
The write paths now also capture the **version id** of that revision before the
mutation, and return it as `baseVersionId`:

- `POST /api/workspace/content` (operation `update`)
- `POST /api/workspace/global` (operation `update`)

Ada's gateway attaches it to the returned document as
`_helloadaBaseVersionId`; the content-effect receipt stores it as
`base_version_id`, and the effect manifest hash covers it. A receipt without a
base version id cannot be reverted exactly; it is reported, never guessed.

## What a restore guarantees

`POST /api/workspace/content` with operation `restore`, and
`POST /api/helloada/content/history` from the owner workspace, restore one
version into the draft:

- the version must belong to the requested document (or the requested global);
- the current draft must still be the revision the caller reviewed, unless it
  is already at the target version (a revert is idempotent);
- the restored draft is re-read and its revision hash must equal the selected
  version's hash, or the response fails closed;
- production is untouched. A restore only changes the draft; publication stays
  a separate owner approval.

`GET /api/helloada/content/history?collection=pages&documentId=2` lists that
document's versions with their revision hashes; `?global=navigation` does the
same for a global. The History drawer shows the selected page's versions and
offers a restore with the same rules.

## What discarding a design draft does

Discarding a pending `design`, `merge` or `rollback` draft now restores the
content versions that draft replaced, in the same action:

- each effect with a `base_version_id` is restored by id;
- a destination the owner changed after the draft is reported as `superseded`
  and left alone, so a discard never overwrites newer work;
- a version that no longer exists is reported as `superseded` with
  `version-not-found`;
- effects without a recorded base version are returned under `unsupported` and
  left untouched;
- an unreadable or unreachable gateway aborts the discard, so the owner never
  loses both the review and the content;
- the draft response includes `content_restore` with what was restored,
  superseded or unsupported.

## The write lease

The lease serializes writers of one destination; it is no longer tenant-wide.
A stranded page write blocks that page, not the menu or another page. Creates
take no lease because they overwrite nothing. The lease is kept because
Payload's D1 adapter has no transactions: it is what proves a partial write
either did not land or already matched the intended data.

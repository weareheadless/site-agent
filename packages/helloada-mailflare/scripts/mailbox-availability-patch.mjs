function replaceExactlyOnce(source, before, after, label) {
  const first = source.indexOf(before)
  if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
    throw new Error(`Pinned Mailflare mailbox availability patch no longer applies exactly once: ${label}`)
  }
  return source.slice(0, first) + after + source.slice(first + before.length)
}

/**
 * A tenant's mailbox belongs to the workspace service account and is shared
 * with its owner, so owning a mailbox is the wrong test for "this person has a
 * mailbox". Reporting `hasMailboxes: false` told the UI a provisioned workspace
 * had none. Access, not ownership, is the answer.
 */
export function applyMailboxAvailabilityPatch(source) {
  let patched = replaceExactlyOnce(
    source,
    'import { hasPrimaryDomain, userHasMailboxes } from "@/lib/user";',
    'import { hasPrimaryDomain, userHasAccessibleMailboxes } from "@/lib/user";',
    "mailbox availability import",
  )
  patched = replaceExactlyOnce(
    patched,
    "userHasMailboxes(env, user.id),",
    "userHasAccessibleMailboxes(env, user),",
    "owner mailbox availability",
  )
  if (patched.includes("userHasMailboxes")) {
    throw new Error("Pinned Mailflare mailbox availability patch left an ownership check behind")
  }
  return patched
}

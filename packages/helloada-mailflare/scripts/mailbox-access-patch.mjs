function replaceExactlyOnce(source, before, after, label) {
  const first = source.indexOf(before)
  if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
    throw new Error(`Pinned Mailflare mailbox access patch no longer applies exactly once: ${label}`)
  }
  return source.slice(0, first) + after + source.slice(first + before.length)
}

export function applyMailboxAccessPatch(source) {
  let patched = replaceExactlyOnce(
    source,
    'import { isTeamMailboxSharingEnabled } from "./access-utils";\n',
    "",
    "team-sharing import",
  )
  patched = replaceExactlyOnce(
    patched,
    'if (mailbox.type !== "shared" || !(await isTeamMailboxSharingEnabled(db))) return null;',
    'if (mailbox.type !== "shared") return null;',
    "explicit mailbox access lookup",
  )
  patched = replaceExactlyOnce(
    patched,
    '\tif (!(await isTeamMailboxSharingEnabled(db))) return owned;\n',
    "",
    "explicit shared mailbox listing",
  )
  if (patched.includes("isTeamMailboxSharingEnabled")) {
    throw new Error("Pinned Mailflare mailbox access patch left an entitlement check behind")
  }
  return patched
}

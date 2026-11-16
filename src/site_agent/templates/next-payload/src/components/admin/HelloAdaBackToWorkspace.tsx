import React from 'react'

import { helloAdaWorkspaceHref } from '@/lib/helloada-admin-entry'
import { runtimeValue } from '@/lib/runtime-env'

/**
 * The owner runs their site from helloada.app; this admin is the advanced
 * editor beside it, so the first thing in the nav is the way back. It is a
 * plain link, not a second workspace: the control plane resolves the address
 * from the tenant identity the Worker already carries.
 *
 * Without that identity there is no link at all. A guessed address would send
 * an owner to a site that is not theirs, which is worse than no shortcut.
 */
export const HelloAdaBackToWorkspace: React.FC = () => {
  const href = workspaceHref()
  if (!href) return null
  return (
    <a className="helloada-admin-back" href={href}>
      <span className="helloada-admin-back__arrow" aria-hidden="true">
        &larr;
      </span>
      Back to workspace
    </a>
  )
}

const workspaceHref = (): string | undefined => {
  try {
    return helloAdaWorkspaceHref(runtimeValue('HELLOADA_HANDOFF_ISSUER'), runtimeValue('HELLOADA_TENANT_ID'))
  } catch {
    // Outside a request for this tenant Worker (build, CLI, contract check)
    // there are no bindings to read; the nav simply has no platform link.
    return undefined
  }
}

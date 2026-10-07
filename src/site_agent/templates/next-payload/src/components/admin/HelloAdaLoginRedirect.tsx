'use client'

import { useEffect } from 'react'

export function HelloAdaLoginRedirect() {
  useEffect(() => {
    window.location.replace('/api/helloada/admin-entry')
  }, [])

  return (
    <p role="status" aria-live="polite">
      Connecting to your HelloAda account…
    </p>
  )
}

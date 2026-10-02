'use client'

import { useEffect, useState } from 'react'
import { fetchHelloAda } from './fetchHelloAda'

export function useAdaConnection() {
  const [connection, setConnection] = useState<'checking' | 'connected' | 'unavailable'>('checking')
  useEffect(() => {
    let active = true
    let controller: AbortController | undefined
    const check = async () => {
      controller?.abort()
      const request = new AbortController()
      controller = request
      const timeout = window.setTimeout(() => request.abort(), 10000)
      try {
        const response = await fetchHelloAda('/api/helloada/ada?status=1', { cache: 'no-store', signal: request.signal })
        if (!response.ok) throw new Error('unavailable')
        const body = await response.json() as { phase?: string; mode?: string }
        if (active && controller === request) setConnection(body.phase || body.mode ? 'connected' : 'unavailable')
      } catch {
        if (active && controller === request) setConnection('unavailable')
      } finally {
        window.clearTimeout(timeout)
      }
    }
    void check()
    const timer = window.setInterval(() => { if (!document.hidden) void check() }, 30000)
    return () => { active = false; controller?.abort(); window.clearInterval(timer) }
  }, [])
  return connection
}

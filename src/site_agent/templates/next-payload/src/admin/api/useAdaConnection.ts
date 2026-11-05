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
        const response = await fetchHelloAda('/api/helloada/connection', { cache: 'no-store', signal: request.signal })
        if (!response.ok) throw new Error('unavailable')
        const body = await response.json() as { connected?: boolean; ready?: boolean }
        if (active && controller === request) setConnection(body.connected && body.ready ? 'connected' : 'unavailable')
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

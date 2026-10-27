import { HelloAdaNav as SharedNav, HelloAdaSiteProvider } from '@weareheadless/helloada-payload-admin'
import type { ComponentProps } from 'react'
import { helloAdaSite } from '@/helloada.config'

export function HelloAdaNav({ user }: ComponentProps<typeof SharedNav>) {
  // Payload also supplies req, payload and i18n to this server component.
  // Only the plain user document may cross into the client navigation.
  return <HelloAdaSiteProvider config={helloAdaSite}><SharedNav user={user} /></HelloAdaSiteProvider>
}

export default HelloAdaNav

import { HelloAdaNav as SharedNav, HelloAdaSiteProvider } from '@weareheadless/helloada-payload-admin'
import type { ComponentProps } from 'react'
import { helloAdaSite } from '@/helloada.config'

export function HelloAdaNav(props: ComponentProps<typeof SharedNav>) {
  return <HelloAdaSiteProvider config={helloAdaSite}><SharedNav {...props} /></HelloAdaSiteProvider>
}

export default HelloAdaNav

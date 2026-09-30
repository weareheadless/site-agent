import type { ComponentProps } from 'react'

import { HelloAdaNav as SharedHelloAdaNav, HelloAdaSiteProvider } from '@weareheadless/helloada-payload-admin'

import { helloAdaSite } from '@/helloada.config'

export default function HelloAdaNav(props: ComponentProps<typeof SharedHelloAdaNav>) {
  return <HelloAdaSiteProvider config={helloAdaSite}><SharedHelloAdaNav {...props} /></HelloAdaSiteProvider>
}

export { HelloAdaNav }

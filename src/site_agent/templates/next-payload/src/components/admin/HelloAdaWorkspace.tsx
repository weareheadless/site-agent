import { HelloAdaSiteProvider, WebsiteWorkspace } from '@weareheadless/helloada-payload-admin'

import { helloAdaSite } from '@/helloada.config'

export default function HelloAdaWorkspace() {
  return <HelloAdaSiteProvider config={helloAdaSite}><WebsiteWorkspace /></HelloAdaSiteProvider>
}

export { HelloAdaWorkspace }

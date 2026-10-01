import {
  HelloAdaSiteProvider,
  WebsiteWorkspaceServer,
} from '@weareheadless/helloada-payload-admin'

import { helloAdaSite } from '@/helloada.config'

export function WebsiteWorkspace() {
  return (
    <HelloAdaSiteProvider config={helloAdaSite}>
      <WebsiteWorkspaceServer />
    </HelloAdaSiteProvider>
  )
}

export { WebsiteWorkspace as HelloAdaWorkspace }

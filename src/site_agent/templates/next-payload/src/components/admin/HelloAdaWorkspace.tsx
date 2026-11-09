import { HelloAdaSiteProvider } from '@/admin/config/provider'
import { WebsiteWorkspace as WebsiteWorkspaceServer } from '@/admin/components/WebsiteWorkspaceServer'

import { helloAdaSite } from '@/helloada.config'

export function WebsiteWorkspace() {
  return (
    <HelloAdaSiteProvider config={helloAdaSite}>
      <WebsiteWorkspaceServer />
    </HelloAdaSiteProvider>
  )
}

export { WebsiteWorkspace as HelloAdaWorkspace }

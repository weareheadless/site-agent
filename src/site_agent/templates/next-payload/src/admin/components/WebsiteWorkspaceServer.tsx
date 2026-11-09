import { WebsiteWorkspace as WebsiteWorkspaceClient } from './WebsiteWorkspace'

/**
 * Payload's dashboard view includes its locale in client props. Keep the
 * Payload locale object on the server boundary and render the hook-driven
 * workspace without forwarding those props into the client component.
 */
export function WebsiteWorkspace() {
  return <WebsiteWorkspaceClient />
}

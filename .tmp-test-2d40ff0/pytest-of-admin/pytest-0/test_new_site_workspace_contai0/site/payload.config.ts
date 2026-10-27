import { buildConfig } from 'payload';

export default buildConfig({
  secret: process.env.PAYLOAD_SECRET || 'local-development-secret',
  collections: [],
});

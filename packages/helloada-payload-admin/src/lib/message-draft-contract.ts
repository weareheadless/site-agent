/** Draft hashes are SHA-256 values emitted by the shared Payload hash helper. */
export const isHelloAdaMessageDraftHash = (value: unknown): value is string =>
  typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value)

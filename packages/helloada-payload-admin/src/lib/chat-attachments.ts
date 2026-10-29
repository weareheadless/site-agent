export type ChatUploadState = 'uploading' | 'failed' | 'unsupported'

export function splitChatImageFiles<T extends { type: string }>(files: readonly T[]): { supported: T[]; unsupported: T[] } {
  return {
    supported: files.filter((file) => file.type.startsWith('image/')),
    unsupported: files.filter((file) => !file.type.startsWith('image/')),
  }
}

export function remainingChatAttachmentSlots(readyCount: number, uploadingCount: number): number {
  return Math.max(0, 12 - readyCount - uploadingCount)
}

export function canSendChatAttachments(hasText: boolean, readyCount: number, pendingStates: readonly ChatUploadState[]): boolean {
  return pendingStates.length === 0 && (hasText || readyCount > 0)
}

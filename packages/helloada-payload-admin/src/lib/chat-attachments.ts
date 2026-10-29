export type ChatUploadState = 'uploading' | 'failed' | 'unsupported'

export type ChatUploadEntry = { id: string; filename: string; status: ChatUploadState; reason?: string }
export type ChatUploadedAttachment = { asset_id: number | string }

export async function uploadChatImages<T extends { name: string }>(options: {
  files: readonly T[]
  entries: readonly ChatUploadEntry[]
  upload: (file: T) => Promise<ChatUploadedAttachment>
  addAttachment: (attachment: ChatUploadedAttachment) => void
  updateEntry: (entryId: string, update: Partial<ChatUploadEntry>) => void
  removeEntry: (entryId: string) => void
  reportFailure: (reason: string) => void
  fallbackError: string
}): Promise<void> {
  for (const [index, file] of options.files.entries()) {
    const entry = options.entries[index]
    try {
      const attachment = await options.upload(file)
      if (attachment?.asset_id === undefined || attachment.asset_id === null) {
        throw new Error(options.fallbackError)
      }
      options.addAttachment(attachment)
      options.removeEntry(entry.id)
    } catch (cause) {
      const reason = cause instanceof Error ? cause.message : options.fallbackError
      options.updateEntry(entry.id, { status: 'failed', reason })
      options.reportFailure(reason)
    }
  }
}

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

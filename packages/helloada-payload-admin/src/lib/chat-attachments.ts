export type ChatUploadState = 'uploading' | 'failed' | 'unsupported'

export type ChatUploadEntry = { id: string; filename: string; status: ChatUploadState; reason?: string; progress?: number; previewUrl?: string }
export type ChatUploadedAttachment = { asset_id: number | string }

const CHAT_UPLOAD_TIMEOUT_MS = 25_000

export function uploadChatImage<T>(file: File, options: {
  endpoint?: string
  timeoutMs?: number
  resolvePath: (path: string) => string
  onProgress?: (progress: number) => void
}): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', options.resolvePath(options.endpoint || '/api/helloada/media/upload'))
    request.withCredentials = true
    request.timeout = options.timeoutMs ?? CHAT_UPLOAD_TIMEOUT_MS
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable || event.total <= 0) return
      options.onProgress?.(Math.max(0, Math.min(100, Math.round(event.loaded / event.total * 100))))
    }
    request.onerror = () => reject(new Error('Image upload network error'))
    request.ontimeout = () => reject(new Error('Image upload timed out'))
    request.onabort = () => reject(new Error('Image upload was cancelled'))
    request.onload = () => {
      let body: { message?: string } & Record<string, unknown>
      try {
        body = JSON.parse(request.responseText || '{}') as typeof body
      } catch {
        reject(new Error('Image upload returned an invalid response'))
        return
      }
      if (request.status < 200 || request.status >= 300) {
        reject(new Error(body.message || `Image upload failed (${request.status})`))
        return
      }
      resolve(body as T)
    }
    const form = new FormData()
    form.append('file', file)
    request.send(form)
  })
}

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

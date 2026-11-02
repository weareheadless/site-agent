export type PendingReviewDraft = {
  id: number
  kind?: string
  meta?: unknown
}

export function selectReviewDraft<T extends PendingReviewDraft>(
  drafts: T[],
  projectedDesignDraftId?: number | null,
): T | undefined {
  const reviewDrafts = drafts.filter((draft) => draft.kind === 'design' || draft.kind === 'merge')
  if (projectedDesignDraftId != null) {
    return reviewDrafts.find((draft) => draft.id === projectedDesignDraftId)
  }
  return reviewDrafts[0]
}

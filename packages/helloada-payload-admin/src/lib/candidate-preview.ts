type CandidateIdentity = {
  run_id: string
  candidate_sha?: string
  preview?: { status: string; run_id: string; candidate_sha: string; job_id: string; preview_url?: string | null } | null
}

export const exactCandidatePreviewReady = (build?: CandidateIdentity | null): boolean => Boolean(
  build?.preview?.status === 'ready'
  && build.preview.job_id
  && build.preview.preview_url
  && /^[0-9a-f]{40}$/i.test(build.candidate_sha || '')
  && build.preview.run_id === build.run_id
  && build.preview.candidate_sha.toLowerCase() === build.candidate_sha?.toLowerCase(),
)

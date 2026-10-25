export type GrowthRow = Record<string, unknown>;

export type GrowthActivity = { id: string; enabled: boolean; nextRun?: string | null };

export const growthAreaKeys = [
  "content",
  "search_visibility",
  "website_health",
  "audience_competitors",
  "speed_experience",
] as const;

export type GrowthAreaKey = (typeof growthAreaKeys)[number];
export type GrowthResultTab = "analytics" | "search" | "competitionTab" | "health" | "content" | "connections";
export type GrowthPanelLocation = "home" | "decisions" | "work" | "results" | "areas" | "budget";
export function growthPanelFromSearch(search: string): GrowthPanelLocation {
  const value = new URLSearchParams(search).get("growth_panel");
  return value === "decisions" || value === "work" || value === "results" || value === "areas" || value === "budget" ? value : "home";
}
export function growthResultTabFromSearch(search: string): GrowthResultTab {
  const value = new URLSearchParams(search).get("growth_results");
  return value === "search" || value === "competitionTab" || value === "health" || value === "content" || value === "connections"
    ? value : "analytics";
}
export type GrowthAreaState = "awaiting_activation" | "needs_decision" | "blocked" | "preparing"
  | "waiting_for_capacity" | "deferred" | "stale" | "unavailable" | "assessed" | "not_assessed";
export type GrowthEvidenceState = "unavailable" | "stale" | "recorded" | "not_assessed";

export type GrowthAreaFinding = {
  id: string;
  runId: string;
  opportunityIndex: number;
  assessedAt: string | null;
  kind: string;
  title: string;
  problem: string | null;
  hypothesis: string | null;
  nextStep: string | null;
  primaryArea: GrowthAreaKey;
  secondaryAreas: GrowthAreaKey[];
  evidenceRefs: string[];
  requiredSources: string[];
  evidenceState: "unavailable" | "stale" | "current";
  target?: { collection?: string; documentId?: string };
  initiativeId?: string | number | null;
  candidateId?: string | null;
  status: string;
  statusReason?: string | null;
  capacityState?: "full" | "available";
  waitingOnWorkIds: string[];
};

export type GrowthServiceWork = {
  id: string;
  draftId?: number | null;
  ownerActionId?: number | null;
  approvalId?: number | null;
  reviewPackageHash?: string | null;
  conversationId?: number | null;
  primaryArea: GrowthAreaKey | null;
  secondaryAreas: GrowthAreaKey[];
  title?: string | null;
  why?: string | null;
  scope?: string | null;
  state: string;
  executionState?: string | null;
  actor: "owner" | "platform" | "ada";
  canApprove: boolean;
  evidenceRefs: string[];
  updatedAt?: string | null;
  nextRun?: string | null;
  executionIssue: boolean;
  dispositionReason?: string | null;
  reassessWhen?: string | null;
};

export type GrowthServiceArea = {
  id: GrowthAreaKey;
  state: GrowthAreaState;
  workIds: string[];
  capability: { scope: string; sourceIds: string[]; automatedMeasurement: string };
  evidenceState: GrowthEvidenceState;
  decisionIds: string[];
  blockedWorkIds: string[];
  activeWorkIds: string[];
  deferredWorkIds: string[];
  pendingRunIds: Array<string | number | null>;
  summary: string | null;
  evidenceRefs: string[];
  unresolvedEvidenceRefs: string[];
  limitations: string[];
  lastAssessedAt: string | null;
  nextAssessment: { activityId: string; at: string; scope: string } | null;
  findings?: GrowthAreaFinding[];
  ownerSummary?: { headline: string; problem: string; nextStep: string };
};

const currentGrowthWorkStates = new Set(["preparing", "validating", "publishing", "verifying_live", "building"]);

export function growthFindingsNewestFirst(area: Pick<GrowthServiceArea, "findings">) {
  return [...(area.findings || [])].sort((left, right) =>
    (Date.parse(right.assessedAt || "") || 0) - (Date.parse(left.assessedAt || "") || 0));
}

export type GrowthAreaAssessmentKind = "owner_summary" | "stale" | "unavailable" | "not_assessed" | "saved_finding" | "none";

export function growthAreaOwnerNextStepKey(work?: Pick<GrowthServiceWork, "canApprove" | "executionIssue" | "state" | "executionState"> | null) {
  if (!work) return null;
  if (work.canApprove) return "growth.areaOwnerReviewNextStep";
  if (work.executionIssue || work.state === "paused" || work.state === "blocked") return "growth.areaOwnerStoppedNextStep";
  if (["preparing", "building", "validating", "publishing", "verifying_live"].includes(work.state)) return "growth.areaOwnerPreparingNextStep";
  return "growth.areaOwnerStoppedNextStep";
}

export function growthAreaAssessmentKind(area: Pick<GrowthServiceArea, "evidenceState" | "findings" | "ownerSummary">): GrowthAreaAssessmentKind {
  if (area.evidenceState === "stale") return "stale" as const;
  if (area.evidenceState === "unavailable") return "unavailable" as const;
  if (area.evidenceState === "not_assessed") return "not_assessed" as const;
  if (area.ownerSummary && area.evidenceState === "recorded") return "owner_summary" as const;
  if (area.findings?.length) return "saved_finding" as const;
  return "none" as const;
}

export function growthAreaShowsReadyReview(kind: GrowthAreaAssessmentKind, canApprove: boolean, hasReviewTask: boolean) {
  return kind !== "owner_summary" && canApprove && hasReviewTask;
}

export function growthAreaNeedsAssessmentMessage(kind: GrowthAreaAssessmentKind, showsReadyReview: boolean, showsFinding: boolean) {
  return kind !== "owner_summary" && kind !== "saved_finding" && !showsReadyReview && !showsFinding;
}

export function growthAreaLeadWork(area: Pick<GrowthServiceArea, "workIds" | "activeWorkIds" | "blockedWorkIds" | "findings">,
  work: GrowthServiceWork[]): GrowthServiceWork | undefined {
  const currentIds = new Set([...area.activeWorkIds, ...area.blockedWorkIds, ...(area.findings || []).flatMap((finding) => finding.waitingOnWorkIds)]);
  return work.filter((item) => area.workIds.includes(item.id)
      && (item.canApprove || currentGrowthWorkStates.has(item.state) || currentIds.has(item.id)))
    .sort((left, right) => Number(right.canApprove) - Number(left.canApprove)
      || Number(currentGrowthWorkStates.has(right.state)) - Number(currentGrowthWorkStates.has(left.state))
      || String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0];
}

export function growthAreaCardCounts(area: Pick<GrowthServiceArea, "decisionIds" | "activeWorkIds" | "blockedWorkIds" | "deferredWorkIds" | "pendingRunIds">) {
  return {
    decisionCount: area.decisionIds.length,
    activeWorkCount: area.activeWorkIds.length,
    blockedWorkCount: area.blockedWorkIds.length,
    deferredWorkCount: area.deferredWorkIds.length,
    pendingRunCount: new Set(area.pendingRunIds.filter((id) => id !== null)).size,
    hasPendingRuns: area.pendingRunIds.length > 0,
    hasUnknownPendingRuns: area.pendingRunIds.some((id) => id === null),
  };
}

export function growthFeaturedAreaId(areas: GrowthServiceArea[]): GrowthAreaKey | undefined {
  return areas.find((area) => area.decisionIds.length > 0 || area.activeWorkIds.length > 0 || area.blockedWorkIds.length > 0)?.id;
}

export type GrowthServiceResult = {
  id: string;
  draftId?: number | null;
  ownerActionId?: number | null;
  approvalId?: number | null;
  reviewPackageHash?: string | null;
  conversationId?: number | null;
  title?: string | null;
  state: "verified";
  publishedRevision: string | number;
  releaseId?: string | null;
  sourceSha?: string | null;
  implementedAt?: string | null;
  impactState: "observed" | "awaiting_data";
  impact: Array<{ id?: number | null; horizonDays?: number | null; measuredAt?: string | null; assessment?: string | null;
    confidence?: string | null; metric?: string | null; baseline?: unknown; observed?: unknown; notes: string; causalAttribution: false }>;
  nextMeasurement: { horizonDays: number; at: string; state: "scheduled" | "overdue" } | null;
};

export type GrowthServicePreparation = {
  runId: string | number | null;
  state: "waiting_for_capacity";
  areaIds: GrowthAreaKey[];
  findingCount: number;
  eligibleAt?: string | null;
  executor?: string | null;
  nextReconciliationAt?: string | null;
};

export type GrowthServiceModel = {
  contractVersion: "growth-service-v1";
  websitePresent: boolean;
  areas: GrowthServiceArea[];
  work: GrowthServiceWork[];
  decisionIds: string[];
  recentResults: GrowthServiceResult[];
  preparation: GrowthServicePreparation[];
  unassignedWorkIds: string[];
  overdueActivityIds: string[];
  sources: Array<{ id: string; state: string; reason?: string | null; observedAt?: string | null; sourceRef?: string | null; freshnessHours?: number | null }>;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");
const nonEmptyString = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0;
const nullableString = (value: unknown): value is string | null => value === null || typeof value === "string";
const areaKey = (value: unknown): value is GrowthAreaKey =>
  typeof value === "string" && (growthAreaKeys as readonly string[]).includes(value);
const nullableArea = (value: unknown): value is GrowthAreaKey | null => value === null || areaKey(value);
const nullableDate = (value: unknown): value is string | null =>
  value === null || (typeof value === "string" && Number.isFinite(Date.parse(value)));

export function growthDecisionOrder(ownerQueue: unknown, decisionIds: unknown): string[] | null {
  if (!isRecord(ownerQueue) || !strings(decisionIds)
      || !(ownerQueue.featuredDecisionId === null || typeof ownerQueue.featuredDecisionId === "string")
      || !strings(ownerQueue.additionalDecisionIds)
      || !Number.isInteger(ownerQueue.decisionCount)) return null;
  const orderedIds = [
    ...(ownerQueue.featuredDecisionId === null ? [] : [ownerQueue.featuredDecisionId]),
    ...ownerQueue.additionalDecisionIds,
  ];
  if (orderedIds.some((id) => !id) || new Set(orderedIds).size !== orderedIds.length
      || ownerQueue.decisionCount !== orderedIds.length || decisionIds.length !== orderedIds.length) return null;
  const canonicalIds = new Set(decisionIds);
  return orderedIds.every((id) => canonicalIds.has(id)) ? orderedIds : null;
}

export function readableReviewValue(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(readableReviewValue).filter((item) => item !== "—").join(" · ") || "—";
  if (!isRecord(value)) return String(value);
  return Object.entries(value).map(([key, item]) => `${key}: ${readableReviewValue(item)}`).join(" · ");
}

export function isGrowthServiceModel(value: unknown): value is GrowthServiceModel {
  if (!isRecord(value) || value.contractVersion !== "growth-service-v1" || typeof value.websitePresent !== "boolean") return false;
  if (!Array.isArray(value.areas) || value.areas.length !== growthAreaKeys.length
      || !Array.isArray(value.work) || !Array.isArray(value.decisionIds)
      || !Array.isArray(value.recentResults) || !Array.isArray(value.preparation)
      || !strings(value.unassignedWorkIds) || !strings(value.overdueActivityIds)
      || !value.overdueActivityIds.every((id) => id === "growth_initial" || id === "growth_weekly")) return false;
  const areaRows: unknown[] = value.areas;
  const workRows: unknown[] = value.work;
  const decisionIds: unknown[] = value.decisionIds;
  const unassignedWorkIds: string[] = value.unassignedWorkIds;

  const workIds = new Set<string>();
  for (const row of workRows) {
    if (!isRecord(row) || typeof row.id !== "string" || workIds.has(row.id)
        || !nullableArea(row.primaryArea) || !Array.isArray(row.secondaryAreas)
        || !row.secondaryAreas.every(areaKey) || typeof row.state !== "string") return false;
    for (const key of ["title", "why", "scope"]) {
      if (row[key] !== undefined && !nullableString(row[key])) return false;
    }
    workIds.add(row.id);
  }
  const idsReferToWork = (ids: unknown): ids is string[] => strings(ids) && ids.every((id) => workIds.has(id));
  if (!strings(decisionIds) || new Set(decisionIds).size !== decisionIds.length) return false;
  const canonicalDecisionIds = decisionIds;
  if (!idsReferToWork(canonicalDecisionIds)
      || workRows.filter((row: unknown) => isRecord(row) && row.state === "awaiting_owner")
        .some((row: unknown) => !canonicalDecisionIds.includes((row as Record<string, unknown>).id as string))
      || canonicalDecisionIds.some((id: string) => !workRows.some((row: unknown) => isRecord(row) && row.id === id && row.state === "awaiting_owner"))
      || !unassignedWorkIds.every((id: string) => workIds.has(id))) return false;

  const areaIds = new Set<string>();
  for (const area of areaRows) {
    if (!isRecord(area) || !areaKey(area.id) || areaIds.has(area.id)
        || !["awaiting_activation", "needs_decision", "blocked", "preparing", "waiting_for_capacity", "deferred", "stale", "unavailable", "assessed", "not_assessed"].includes(String(area.state))
        || !idsReferToWork(area.workIds) || new Set(area.workIds).size !== area.workIds.length || !idsReferToWork(area.decisionIds)
        || !idsReferToWork(area.blockedWorkIds) || !idsReferToWork(area.activeWorkIds) || !idsReferToWork(area.deferredWorkIds)
        || !Array.isArray(area.pendingRunIds) || !area.pendingRunIds.every((id) => id === null || typeof id === "string" || (typeof id === "number" && Number.isFinite(id)))
        || new Set(area.decisionIds).size !== area.decisionIds.length || new Set(area.blockedWorkIds).size !== area.blockedWorkIds.length
        || new Set(area.activeWorkIds).size !== area.activeWorkIds.length || new Set(area.deferredWorkIds).size !== area.deferredWorkIds.length
        || !["unavailable", "stale", "recorded", "not_assessed"].includes(String(area.evidenceState))
        || !nullableString(area.summary) || !strings(area.evidenceRefs)
        || !strings(area.unresolvedEvidenceRefs) || !strings(area.limitations)
        || !nullableDate(area.lastAssessedAt)) return false;
    if (area.ownerSummary !== undefined && (!isRecord(area.ownerSummary)
        || !nonEmptyString(area.ownerSummary.headline) || !nonEmptyString(area.ownerSummary.problem)
        || !nonEmptyString(area.ownerSummary.nextStep))) return false;
    if (area.findings !== undefined && (!Array.isArray(area.findings) || !area.findings.every((finding: unknown) => {
      if (!isRecord(finding) || !nonEmptyString(finding.id) || !nonEmptyString(finding.runId)
          || !Number.isInteger(finding.opportunityIndex) || (finding.opportunityIndex as number) < 0
          || !nullableDate(finding.assessedAt) || !nonEmptyString(finding.kind) || !nonEmptyString(finding.title)
          || !nullableString(finding.problem) || !nullableString(finding.hypothesis) || !nullableString(finding.nextStep)
          || !areaKey(finding.primaryArea) || !Array.isArray(finding.secondaryAreas) || !finding.secondaryAreas.every(areaKey)
          || !strings(finding.evidenceRefs) || !strings(finding.requiredSources)
          || !["unavailable", "stale", "current"].includes(String(finding.evidenceState)) || !nonEmptyString(finding.status)
          || !Array.isArray(finding.waitingOnWorkIds) || !finding.waitingOnWorkIds.every((id: unknown) => typeof id === "string" && workIds.has(id))) return false;
      if (finding.statusReason !== undefined && !nullableString(finding.statusReason)) return false;
      if (finding.capacityState !== undefined && !["full", "available"].includes(String(finding.capacityState))) return false;
      if (finding.status === "waiting_for_capacity" && finding.capacityState === undefined) return false;
      if (finding.initiativeId !== undefined && finding.initiativeId !== null
          && typeof finding.initiativeId !== "string" && typeof finding.initiativeId !== "number") return false;
      if (finding.candidateId !== undefined && finding.candidateId !== null && !nullableString(finding.candidateId)) return false;
      if (finding.target !== undefined && (!isRecord(finding.target)
          || (finding.target.collection !== undefined && !nonEmptyString(finding.target.collection))
          || (finding.target.documentId !== undefined && !nonEmptyString(finding.target.documentId)))) return false;
      return true;
    }))) return false;
    if (area.nextAssessment !== null && (!isRecord(area.nextAssessment)
        || typeof area.nextAssessment.activityId !== "string"
        || typeof area.nextAssessment.at !== "string" || !nullableDate(area.nextAssessment.at)
        || typeof area.nextAssessment.scope !== "string")) return false;
    areaIds.add(area.id);
  }
  if (growthAreaKeys.some((area) => !areaIds.has(area))) return false;
  if (areaRows.some((area: unknown) => {
    const row = area as Record<string, unknown>;
    const linked = workRows.filter((item: unknown) => isRecord(item) && (item.primaryArea === row.id || (item.secondaryAreas as unknown[]).includes(row.id))).map((item: unknown) => (item as Record<string, unknown>).id);
    const linkedDecisions = workRows.filter((item: unknown) => isRecord(item) && item.state === "awaiting_owner"
      && (item.primaryArea === row.id || (item.secondaryAreas as unknown[]).includes(row.id))).map((item: unknown) => (item as Record<string, unknown>).id);
    return new Set(linked).size !== new Set(row.workIds as string[]).size
      || linked.some((id) => !(row.workIds as string[]).includes(id as string))
      || new Set(linkedDecisions).size !== new Set(row.decisionIds as string[]).size
      || linkedDecisions.some((id) => !(row.decisionIds as string[]).includes(id as string));
  })) return false;
  if (new Set(unassignedWorkIds).size !== unassignedWorkIds.length
      || unassignedWorkIds.length !== workRows.filter((row: unknown) => isRecord(row) && row.primaryArea === null).length
      || unassignedWorkIds.some((id: string) => {
        const row = workRows.find((candidate: unknown): candidate is Record<string, unknown> => isRecord(candidate) && candidate.id === id);
        return row?.primaryArea !== null;
      })) return false;

  for (const row of value.preparation) {
    if (!isRecord(row) || (typeof row.runId !== "string" && typeof row.runId !== "number" && row.runId !== null)
        || row.state !== "waiting_for_capacity" || typeof row.findingCount !== "number" || !Number.isInteger(row.findingCount) || row.findingCount < 0
        || !nullableDate(row.eligibleAt ?? null)
        || !nullableDate(row.nextReconciliationAt ?? null)) return false;
  }
  for (const row of value.recentResults) {
    if (!isRecord(row) || typeof row.id !== "string" || row.state !== "verified"
        || (typeof row.publishedRevision !== "string" && (typeof row.publishedRevision !== "number" || !Number.isFinite(row.publishedRevision)))
        || !["observed", "awaiting_data"].includes(String(row.impactState))
        || (row.nextMeasurement !== null && (!isRecord(row.nextMeasurement)
          || typeof row.nextMeasurement.horizonDays !== "number" || !Number.isFinite(row.nextMeasurement.horizonDays)
          || typeof row.nextMeasurement.at !== "string" || !nullableDate(row.nextMeasurement.at)
          || !["scheduled", "overdue"].includes(String(row.nextMeasurement.state))))) return false;
    if (row.title !== undefined && !nullableString(row.title)) return false;
  }
  return true;
}

export function growthPlan(activities: GrowthActivity[] = []) {
  const upcoming = activities.filter(item => item.enabled).sort((a, b) =>
    (a.nextRun || "9999").localeCompare(b.nextRun || "9999"));
  return {
    upcoming,
    unscheduled: activities.filter(item => !item.enabled),
    nextRun: upcoming.find(item => item.nextRun)?.nextRun || null,
  };
}

export function growthDate(value: unknown): string {
  const raw = String(value ?? "");
  return /^\d{8}$/.test(raw)
    ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6)}`
    : raw;
}

export function growthNumber(value: unknown, locale: string, key = ""): string {
  if (typeof value !== "number" || !Number.isFinite(value))
    return value == null ? "—" : String(value);
  if (["ctr", "engagementRate", "competition"].includes(key))
    return new Intl.NumberFormat(locale, {
      style: "percent",
      maximumFractionDigits: 1,
    }).format(value);
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: key === "cpc" ? 2 : 1,
  }).format(value);
}

export function growthSeries(
  rows: GrowthRow[],
  metric: string,
  dateKey: string,
) {
  return rows
    .map((row) => ({ date: growthDate(row[dateKey]), value: row[metric] }))
    .filter(
      (point): point is { date: string; value: number } =>
        /^\d{4}-\d{2}-\d{2}$/.test(point.date) &&
        Number.isFinite(Date.parse(point.date)) &&
        typeof point.value === "number" &&
        Number.isFinite(point.value),
    )
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function growthCSV(
  rows: GrowthRow[],
  columns: Array<[string, string]>,
): string {
  // Prevent formulas when owner-exported text is opened in a spreadsheet.
  const cell = (value: unknown) => {
    const raw = String(value ?? "");
    const safe = typeof value === "string" && /^[\s]*[=+@-]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  return [
    columns.map(([, title]) => cell(title)).join(","),
    ...rows.map((row) => columns.map(([key]) => cell(row[key])).join(",")),
  ].join("\r\n");
}

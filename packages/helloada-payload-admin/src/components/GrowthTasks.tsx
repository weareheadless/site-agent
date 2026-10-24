"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { HelloAdaMark } from "./HelloAdaLogo";
import { HelloAdaChatMessage } from "./HelloAdaChatMessage";
import { getDecisionPresentation } from "../lib/growth-review";
import { GrowthChangeReview } from "./GrowthChangeReview";
import { type GrowthAreaKey, type GrowthResultTab, type GrowthServiceArea, type GrowthServiceModel, type GrowthServiceWork } from "../lib/growth-data";

type Focus = "needs_you" | "preparing" | "planned" | "paused" | "opportunity" | "completed";
type ArticleReviewData = {
  title?: string; body?: unknown; bodyFormat?: "markdown" | "lexical"; reviewable?: boolean;
  slug?: string; path?: string; excerpt?: string; metaDescription?: string;
  primaryKeyword?: string; rationale?: string; readerQuestion?: string; demandInterpretation?: string;
  featuredImage?: { url?: string; alt?: string; filename?: string; width?: number; height?: number; id?: string } | null;
  sources?: { url: string; label?: string }[];
};
export type GrowthTask = {
  id: string; kind?: string; title?: string; titleKey?: string; summary?: string; summaryKey?: string; scope?: string;
  focus: Focus; state: string; nextRun?: string | null; draftId?: number | null;
  ownerActionId?: number | null; canApprove?: boolean; reviewPackageHash?: string | null;
  priority?: string; requirement?: string;
  lastError?: string; executionIssue?: boolean; needsPreparation?: boolean; updatedAt?: string; conversationId?: number | null;
  evidence?: string[]; measurementHorizon?: number; measurementMetric?: string;
  outcomes?: { id: number; horizon_days: number; assessment: string; confidence: string; notes?: string; measured_ts?: string }[];
  history?: { initiativeId: number; title?: string; state?: string }[]; previewUrl?: string;
  review?: { before?: Record<string, unknown>; after?: Record<string, unknown>; changes?: Record<string, unknown>;
    route?: string; setting?: string; article?: ArticleReviewData; source?: { candidateSha?: string; baseSha?: string; changedPaths?: string[]; previewUrl?: string };
    changeOperations?: { path: string; find: string; replace: string }[] };
};

type ArticleResponse = { article: ArticleReviewData; reviewable: boolean; blockedReasonCode: string | null; reviewPackageHash?: string | null };
type GrowthPanel = "home" | "decisions" | "work" | "results";
const AREA_LABELS: Record<GrowthAreaKey, string> = {
  content: "growth.areaContent", search_visibility: "growth.areaSearchVisibility",
  website_health: "growth.areaWebsiteHealth", audience_competitors: "growth.areaAudienceCompetitors",
  speed_experience: "growth.areaSpeedExperience",
};
const AREA_TABS: Record<GrowthAreaKey, GrowthResultTab> = {
  content: "content", search_visibility: "search", website_health: "health",
  audience_competitors: "competitionTab", speed_experience: "health",
};
const FILTERS: Focus[] = ["needs_you", "preparing", "planned", "paused", "opportunity", "completed"];

function writeGrowthLocation(nextFocus: Focus, nextSelected?: string, mode: "pushState" | "replaceState" = "replaceState") {
  const url = new URL(window.location.href);
  url.searchParams.set("growth_focus", nextFocus);
  if (nextSelected) url.searchParams.set("growth_task", nextSelected);
  else url.searchParams.delete("growth_task");
  window.history[mode]({ ...window.history.state, helloAdaGrowthSelection: Boolean(nextSelected) }, "", url.toString());
}

function renderLexicalNode(node: unknown, key: string): ReactNode {
  if (Array.isArray(node)) return node.map((child, index) => renderLexicalNode(child, key + "-" + index));
  if (!node || typeof node !== "object") return null;
  const value = node as Record<string, unknown>;
  const children = Array.isArray(value.children) ? value.children.map((child, index) => renderLexicalNode(child, key + "-" + index)) : [];
  if (value.type === "root") return <>{children}</>;
  if (value.type === "text") {
    let content: ReactNode = String(value.text || "");
    const format = Number(value.format || 0);
    if (format & 16) content = <code>{content}</code>;
    if (format & 8) content = <u>{content}</u>;
    if (format & 2) content = <em>{content}</em>;
    if (format & 1) content = <strong>{content}</strong>;
    return <span key={key}>{content}</span>;
  }
  if (value.type === "link") {
    const fields = value.fields && typeof value.fields === "object" ? value.fields as Record<string, unknown> : {};
    const href = String(fields.url || "");
    if (!/^(https?:\/\/|mailto:|\/(?!\/)|#)/i.test(href)) return <>{children}</>;
    return <a key={key} href={href} target={fields.newTab ? "_blank" : undefined} rel={fields.newTab ? "noreferrer noopener" : undefined}>{children}</a>;
  }
  if (value.type === "heading") {
    const tag = String(value.tag || "h2");
    const Heading = (["h1", "h2", "h3", "h4", "h5", "h6"].includes(tag) ? tag : "h2") as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
    return <Heading key={key}>{children}</Heading>;
  }
  if (value.type === "paragraph") return <p key={key}>{children}</p>;
  if (value.type === "list") return value.listType === "number"
    ? <ol key={key}>{children}</ol>
    : <ul key={key}>{children}</ul>;
  if (value.type === "listitem") return <li key={key}>{children}</li>;
  if (value.type === "quote") return <blockquote key={key}>{children}</blockquote>;
  return <span key={key}>{children}</span>;
}

export function GrowthTasks({ mode, serviceModel, decisionOrder, onNavigate, tasks = [], pending, refresh, ask, date, goal, brief }: {
  mode: "home" | "decisions" | "work";
  serviceModel: GrowthServiceModel;
  decisionOrder: string[];
  onNavigate: (panel: GrowthPanel, resultsTab?: GrowthResultTab) => void;
  tasks?: GrowthTask[]; pending: boolean; refresh: () => void; ask: (prompt?: string) => string;
  date: (value: unknown) => string; goal?: { objective?: string; goal_key?: string };
  brief?: { headline?: string; summary_md?: string };
}) {
  const { t } = useHelloAdaTranslations();
  const [focus, setFocus] = useState<Focus>("needs_you");
  const [selected, setSelected] = useState<string>();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const [articleResult, setArticleResult] = useState<{ key: string; result: ArticleResponse }>();
  const [articleLoading, setArticleLoading] = useState<string>();
  const [articleError, setArticleError] = useState<string>();
  const [articleRefresh, setArticleRefresh] = useState(0);
  const lastOpenedTask = useRef<string | undefined>(undefined);
  useEffect(() => {
    const restoreLocation = () => {
      const params = new URLSearchParams(window.location.search);
      const requestedFocus = params.get("growth_focus") as Focus | null;
      setFocus(requestedFocus && FILTERS.includes(requestedFocus) ? requestedFocus : "needs_you");
      setSelected(params.get("growth_task") || undefined);
    };
    restoreLocation();
    window.addEventListener("popstate", restoreLocation);
    return () => window.removeEventListener("popstate", restoreLocation);
  }, []);
  useEffect(() => {
    if (selected && !pending && !tasks.some(row => row.id === selected)) {
      setSelected(undefined);
      writeGrowthLocation(focus);
    }
  }, [selected, pending, tasks, focus]);
  useEffect(() => {
    if (selected || !lastOpenedTask.current) return;
    const taskId = lastOpenedTask.current;
    lastOpenedTask.current = undefined;
    requestAnimationFrame(() => {
      const row = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-growth-task-id]"))
        .find(item => item.dataset.growthTaskId === taskId);
      row?.focus();
    });
  }, [selected, focus]);
  const selectedTask = tasks.find(row => row.id === selected);
  const ownerInformation = selectedTask?.requirement === "owner_information";
  const articleKey = selectedTask?.kind === "article" && selectedTask.draftId
    ? String(selectedTask.draftId) + ":" + String(selectedTask.reviewPackageHash || "inspection")
    : "";
  const taskById = new Map(tasks.map(task => [task.id, task] as const));
  const agendaTask = (id: string | null | undefined) => id ? taskById.get(id) : undefined;
  const serviceWorkById = new Map(serviceModel.work.map((row) => [row.id, row] as const));
  const decisionRows = decisionOrder.map(agendaTask).filter((row): row is GrowthTask => Boolean(row));
  const canonicalDecisionIds = new Set(serviceModel.decisionIds);
  const featuredDecision = decisionRows[0];
  const featuredPresentation = featuredDecision ? getDecisionPresentation(featuredDecision, t) : null;
  const additionalDecisions = decisionRows.slice(1);
  const visible = decisionRows;
  const recentWork = serviceModel.recentResults;
  const recentWorkIds = new Set(recentWork.map(row => row.id));
  const workRows = tasks.filter(row => row.focus !== "needs_you" && row.focus !== "opportunity"
    && (row.focus !== "completed" || recentWorkIds.has(row.id)));
  const nextAssessment = serviceModel.areas.map((area) => area.nextAssessment).filter((row): row is NonNullable<GrowthServiceArea["nextAssessment"]> => Boolean(row))
    .sort((left, right) => left.at.localeCompare(right.at))[0];
  const nextAssessmentScope = nextAssessment?.scope === "shared_growth_review"
    ? t("growth.scopeSharedGrowthReview") : nextAssessment ? t("growth.scopeGenericAssessment") : "";
  const activeWork = serviceModel.work.find((row) => row.state === "preparing");
  const workPriority: Record<Focus, number> = { preparing: 0, paused: 1, planned: 2, completed: 3, needs_you: 4, opportunity: 5 };
  workRows.sort((left, right) => workPriority[left.focus] - workPriority[right.focus]
    || (left.focus === "planned" ? String(left.nextRun || "").localeCompare(String(right.nextRun || ""))
      : String(right.updatedAt || "").localeCompare(String(left.updatedAt || ""))));
  const loaded = articleResult?.key === articleKey ? articleResult.result : undefined;

  useEffect(() => {
    if (!articleKey || !selectedTask?.draftId) {
      setArticleResult(undefined);
      setArticleLoading(undefined);
      setArticleError(undefined);
      return;
    }
    const requestKey = articleKey;
    const controller = new AbortController();
    setArticleResult(undefined);
    setArticleError(undefined);
    setArticleLoading(requestKey);
    void fetchHelloAda("/api/helloada/growth/articles/" + selectedTask.draftId, {
      signal: controller.signal,
      cache: "no-store",
    }).then(async response => {
      const body = await response.json().catch(() => ({}));
      const blockedCodes = ["articleImageNeeded", "articlePayloadUnavailable", "articlePayloadChanged", "articlePayloadEmpty", "articlePayloadSyncBlocked", "articlePayloadSyncPending", "articlePayloadConflict"];
      if (!response.ok || !body.article || typeof body.reviewable !== "boolean"
        || (body.reviewable && body.blockedReasonCode !== null)
        || (!body.reviewable && !blockedCodes.includes(String(body.blockedReasonCode)))) {
        throw new Error(t("growth.articleLoadFailed"));
      }
      if (!controller.signal.aborted) setArticleResult({ key: requestKey, result: body as ArticleResponse });
    }).catch(reason => {
      if (!controller.signal.aborted) setArticleError(reason instanceof Error ? reason.message : "");
    }).finally(() => {
      if (!controller.signal.aborted) setArticleLoading(undefined);
    });
    return () => controller.abort();
  }, [articleKey, selectedTask?.draftId, articleRefresh]);

  const title = (task: GrowthTask) => task.titleKey ? t("growth." + task.titleKey) : task.title || "—";
  const discuss = (task: GrowthTask) => {
    const prompt = task.requirement === "owner_information"
      ? [title(task), task.scope || fullTaskSummary(task), t("growth.ownerAnswerLabel")].filter(Boolean).join("\n\n")
      : task.focus === "opportunity"
      ? title(task) + ". " + (task.scope || fullTaskSummary(task)) + ". " + t("growth.opportunityPrompt")
      : task.needsPreparation
        ? title(task) + ". " + t(task.kind === "settings_proposal" ? "growth.settingsPreparePrompt" : "growth.changePreparePrompt")
      : task.kind === "code" && task.canApprove
        ? title(task) + ". " + (task.scope || fullTaskSummary(task)) + ". " + t("growth.codeRevisionPrompt")
      : task.kind === "article"
        ? title(task) + ". " + (task.canApprove ? t("growth.articleRevisionPrompt") : t("growth.articleResolvePrompt"))
      : task.canApprove && task.draftId && task.reviewPackageHash
        ? title(task) + ". " + (task.scope || fullTaskSummary(task)) + ". " + t("growth.taskResolvePrompt")
        : task.executionIssue
          ? title(task) + ". " + (task.scope || fullTaskSummary(task)) + ". " + t("growth.taskResolvePrompt")
        : title(task) + ". " + t("growth.decisionPrompt");
    const url = new URL(ask(prompt), "https://workspace.invalid");
    url.searchParams.set("growth_task", task.id);
    if ((task.kind === "code" || task.kind === "payload_content") && task.canApprove) url.searchParams.set("growth_task_action", "revise");
    if (task.conversationId) url.searchParams.set("conversation_id", String(task.conversationId));
    return url.pathname + url.search;
  };
  const stateLabel = (task: GrowthTask) => {
    if (task.kind === "measurement") return t(task.state === "due" ? "growth.measurementDue" : "growth.measurementScheduled");
    if (task.kind === "schedule" && task.state === "uncertain") return t("growth.taskState_uncertain");
    if (task.kind === "schedule" && ["scheduled", "paused", "unscheduled", "queued", "running", "blocked"].includes(task.state)) return t("growth." + task.state);
    return t("growth.taskState_" + task.state) === "growth.taskState_" + task.state
      ? t("growth.task_" + task.focus)
      : t("growth.taskState_" + task.state);
  };
  const fullTaskSummary = (task: GrowthTask) => task.summaryKey
    ? t("growth." + task.summaryKey)
    : task.summary || "";
  const taskSummary = (task: GrowthTask) => {
    const summary = fullTaskSummary(task).replace(/\s+/g, " ").trim();
    return summary.length > 132 ? summary.slice(0, 131).trimEnd() + "…" : summary;
  };
  const workTaskButton = (task: GrowthTask) => <button type="button" className="helloada-growth-task-row"
    data-growth-task-id={task.id} onClick={() => openTask(task)}>
    <i aria-hidden="true" />
    <span className="helloada-growth-task-label"><strong>{title(task)}</strong>
      <small>{[taskSummary(task) || stateLabel(task), task.nextRun
        ? t(task.kind === "assessment" ? "growth.assessmentNextRetry" : "growth.nextReview") + ": " + date(task.nextRun)
        : ""].filter(Boolean).join(" · ")}</small>
    </span>
    <span className={"helloada-growth-task-badge is-" + task.focus}>{stateLabel(task)}</span>
    <span className="helloada-growth-row-open">{t("growth.openTask")} →</span>
  </button>;
  const effect = async (task: GrowthTask | undefined, operation: string) => {
    if (busy) return;
    setBusy(task?.id || operation);
    setError(undefined);
    try {
      const endpoint = task ? "/api/helloada/drafts/" + task.draftId + "/" + operation : "/api/helloada/growth/check";
      const response = await fetchHelloAda(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_package_hash: task?.reviewPackageHash }),
      });
      const body = await response.json();
      if (!response.ok || body.ok === false) throw new Error(String(body.detail || body.message || t("growth.taskFailed")));
      lastOpenedTask.current = undefined;
      setSelected(undefined);
      writeGrowthLocation(focus);
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("growth.taskFailed"));
    } finally {
      setBusy(undefined);
    }
  };
  const openTask = (task: GrowthTask) => {
    lastOpenedTask.current = task.id;
    setFocus(task.focus);
    setSelected(task.id);
    writeGrowthLocation(task.focus, task.id, "pushState");
    setError(undefined);
  };
  const closeTask = () => {
    lastOpenedTask.current = selected;
    if (window.history.state?.helloAdaGrowthSelection) {
      window.history.back();
      return;
    }
    setSelected(undefined);
    writeGrowthLocation(focus);
  };
  const exactArticleReview = Boolean(
    selectedTask?.canApprove && loaded?.reviewable && loaded.reviewPackageHash
    && loaded.reviewPackageHash === selectedTask.reviewPackageHash
  );

  const panelTitleKey = mode === "home" ? "growth.homeTitle" : mode === "decisions" ? "growth.decisionListTitle" : "growth.workTitle";
  const panelNoteKey = mode === "home" ? "growth.homeIntro" : mode === "decisions" ? "growth.decisionListIntro" : "growth.workIntro";
  return <section className={"helloada-growth-task-shell" + (mode === "home" ? " is-dashboard" : "")} aria-label={t(panelTitleKey)}>
    <div className="helloada-growth-task-core">
      <header className="helloada-growth-task-header">
        <div className="helloada-growth-identity">
          <HelloAdaMark size={28} />
          <div><h2>{t(panelTitleKey)}</h2><small>{t(panelNoteKey)}</small></div>
        </div>
        {mode === "work" ? <button type="button" className="helloada-growth-secondary" onClick={() => onNavigate("results", "search")}>{t("growth.workResearchLink")}</button> : null}
      </header>

      {mode === "home" && !selectedTask ? <details className="helloada-growth-task-goal"><summary>{t("growth.goalLabel")}</summary><span><strong>{goal?.goal_key === "relevant_visitors" ? t("growth.visitorGoal") : goal?.objective || t("growth.goalNotSet")}</strong></span><Link href={ask(t("growth.goalPrompt"))}>{t("growth.changeGoal")} ↗</Link></details> : null}

      {mode === "home" && !selectedTask && brief?.headline ? <details className="helloada-growth-task-brief">
        <summary>{brief.headline}</summary><HelloAdaChatMessage text={brief.summary_md || ""} />
      </details> : null}
      {mode === "home" && !selectedTask ? <section className="helloada-growth-owner-agenda" aria-label={t("growth.homeTitle")}>
        <div className="helloada-growth-agenda-grid">
          {pending ? <div className="helloada-growth-agenda-empty" role="status">{t("growth.loading")}</div> : featuredDecision ? <article className="helloada-growth-featured-decision">
            <span className="helloada-growth-decision-eyebrow">{t("growth.decisionEyebrow")}</span>
            <h3>{featuredPresentation?.heading || title(featuredDecision)}</h3>
            <p>{featuredDecision.requirement === "owner_information"
              ? featuredDecision.scope || taskSummary(featuredDecision) || title(featuredDecision)
              : featuredPresentation?.purpose || t("growth.clarityPurposeProposal")}</p>
            {taskSummary(featuredDecision) ? <details className="helloada-growth-featured-evidence">
              <summary>{t("growth.clarityEvidenceLabel")}</summary><p>{taskSummary(featuredDecision)}</p>
            </details> : null}
            {featuredPresentation?.target ? <small className="helloada-growth-featured-target">
              {[featuredPresentation.target.title, featuredPresentation.target.path].filter(Boolean).join(" · ")}
            </small> : null}
            <button type="button" className="helloada-growth-primary" data-growth-task-id={featuredDecision.id} onClick={() => openTask(featuredDecision)}>
              {t(featuredDecision.requirement === "owner_information" ? "growth.decisionCtaAnswer"
                : featuredDecision.kind === "article" ? "growth.decisionCtaArticle"
                : featuredDecision.canApprove ? "growth.decisionCtaChanges" : "growth.decisionCtaReview")} <span aria-hidden="true">→</span>
            </button>
          </article> : serviceModel.preparation.length ? <article className="helloada-growth-featured-decision" role="status">
            <span className="helloada-growth-decision-eyebrow">{t("growth.preparationTitle")}</span>
            <h3>{t("growth.preparationWaiting")}</h3>
            <p>{t("growth.clarityMoreWork")}</p>
          </article> : nextAssessment ? <article className="helloada-growth-featured-decision" role="status">
            <span className="helloada-growth-decision-eyebrow">{t("growth.nextAssessment")}</span>
            <h3>{date(nextAssessment.at)}</h3>
            <p>{nextAssessmentScope}</p>
          </article> : serviceModel.areas.some((area) => area.summary || area.lastAssessedAt) ? <article className="helloada-growth-featured-decision" role="status">
            <span className="helloada-growth-decision-eyebrow">{t("growth.latestAssessment")}</span>
            <h3>{t("growth.assessmentRecorded")}</h3>
            <p>{serviceModel.areas.find((area) => area.summary)?.summary || t("growth.assessmentNoSummary")}</p>
            {serviceModel.areas.find((area) => area.lastAssessedAt)?.lastAssessedAt
              ? <small>{t("growth.lastGrowthReview")}: {date(serviceModel.areas.find((area) => area.lastAssessedAt)?.lastAssessedAt)}</small> : null}
          </article> : <div className="helloada-growth-agenda-empty" role="status">
            <strong>{t("growth.noNextStep")}</strong><span>{t("growth.noNextStepNote")}</span>
          </div>}
          {additionalDecisions.length ? <ul className="helloada-growth-additional-decisions">
            {additionalDecisions.map(task => <li key={task.id}>
              <button type="button" data-growth-task-id={task.id} onClick={() => openTask(task)}>
                <span><strong>{title(task)}</strong><small>{taskSummary(task) || stateLabel(task)}</small></span><span aria-hidden="true">→</span>
              </button>
            </li>)}
          </ul> : null}
        </div>
        {serviceModel.decisionIds.length ? <div className="helloada-growth-agenda-actions">
          <span>{serviceModel.decisionIds.length} {t("growth.decisionsCount")}</span>
          <button type="button" onClick={() => onNavigate("decisions")}>{t("growth.seeAllDecisions")} →</button>
        </div> : null}
        {activeWork ? <p className="helloada-growth-handling-note">{t("growth.activeLabel")}: <strong>{activeWork.title || activeWork.id}</strong>{activeWork.why ? ` · ${activeWork.why}` : ""}</p> : serviceModel.preparation.length ? <p className="helloada-growth-handling-note">{t("growth.preparationWaiting")}</p> : null}
        <details className="helloada-growth-agenda-details">
          <summary>{t("growth.clarityMoreWork")}</summary>
        <div className="helloada-growth-agenda-status">
          {activeWork ? <div className="helloada-growth-service-status is-active">
            <small>{t("growth.activeLabel")}</small>
            <strong>{activeWork.title || activeWork.id}</strong>
            <span>{activeWork.why || activeWork.state}</span>
          </div> : null}
          {nextAssessment ? <div className="helloada-growth-service-status">
            <small>{t("growth.nextScheduledLabel")}</small><strong>{date(nextAssessment.at)}</strong><span>{nextAssessmentScope}</span>
          </div> : null}
          {serviceModel.preparation.length ? <div className="helloada-growth-service-status">
            <small>{t("growth.preparationWaiting")}</small>
            <ul>{serviceModel.preparation.map((run) => <li key={String(run.runId)}>
              <strong>{run.findingCount} {t("growth.preparationFindings")}</strong>
              <span>{[
                run.eligibleAt ? `${t("growth.eligibleAt")} ${date(run.eligibleAt)}` : "",
                run.nextReconciliationAt ? `${t("growth.nextReconciliation")} ${date(run.nextReconciliationAt)}` : "",
              ].filter(Boolean).join(" · ")}</span>
            </li>)}</ul>
          </div> : null}
          {serviceModel.overdueActivityIds.length ? <div className="helloada-growth-service-status is-overdue">
            <small>{t("growth.overdueSchedule")}</small>
            <strong>{serviceModel.overdueActivityIds.map((id) => t("growth." + id)).join(" · ")}</strong>
          </div> : null}
          {recentWork.length ? <div className="helloada-growth-service-status helloada-growth-verified-results">
            <small>{t("growth.recentResultLabel")}</small>
            <ul>{recentWork.map((result) => <li key={result.id}>
              {taskById.get(result.id)
                ? <button type="button" className="helloada-growth-result-task" data-growth-task-id={result.id} onClick={() => openTask(taskById.get(result.id)!)}>
                    <strong>{result.title || result.id}</strong>
                  </button>
                : <strong>{result.title || result.id}</strong>}
              <span>{t("growth.resultVerified")} · {t(result.impactState === "observed" ? "growth.impactObserved" : "growth.impactAwaitingData")}
                {` · ${t("growth.publishedRevision")}: ${result.publishedRevision}`}
                {result.nextMeasurement ? ` · ${t("growth.nextMeasurement")}: ${date(result.nextMeasurement.at)}` : ""}</span>
              {result.releaseId || result.sourceSha || result.publishedRevision !== null && result.publishedRevision !== undefined
                ? <details className="helloada-growth-result-receipt">
                <summary>{t("growth.receiptDetails")}</summary>
                {result.publishedRevision !== null && result.publishedRevision !== undefined
                  ? <span>{t("growth.publishedRevision")}: <code>{result.publishedRevision}</code></span> : null}
                {result.releaseId ? <span>{t("growth.releaseId")}: <code>{result.releaseId}</code></span> : null}
                {result.sourceSha ? <span>{t("growth.sourceSha")}: <code>{result.sourceSha}</code></span> : null}
              </details> : null}
            </li>)}</ul>
          </div> : null}
        </div>
        </details>
      </section> : null}

      {mode === "home" && !selectedTask ? <details className="helloada-growth-areas" aria-label={t("growth.areasTitle")}>
        <summary>{t("growth.areasTitle")}</summary>
        <header>
          <div>
            <p>{t("growth.areasIntro")}</p>
          </div>
          <button type="button" className="helloada-growth-areas-results" onClick={() => onNavigate("results")}>{t("growth.exploreGrowthResults")} →</button>
        </header>
        <div className="helloada-growth-area-grid">
          {serviceModel.areas.map((area) => {
            const areaWork = area.workIds.map((id) => serviceWorkById.get(id)).filter((row): row is GrowthServiceWork => Boolean(row));
            const linkedWork = areaWork.filter((row) => !canonicalDecisionIds.has(row.id));
            const task = linkedWork.map((row) => taskById.get(row.id)).find((row): row is GrowthTask => Boolean(row));
            return <article className={`helloada-growth-area-card is-${area.state}`} key={area.id}>
              <div className="helloada-growth-area-copy">
                <h4>{t(AREA_LABELS[area.id])}</h4>
                <span className={`helloada-growth-state is-${area.state}`}>{t("growth.areaState_" + area.state)}</span>
                <p>{area.summary || t("growth.areaNoAssessmentSummary")}</p>
              </div>
              <small className="helloada-growth-area-evidence">{t("growth.evidenceState")}: {t("growth.evidence_" + area.evidenceState)}
                {area.lastAssessedAt ? ` · ${t("growth.lastGrowthReview")}: ${date(area.lastAssessedAt)}` : ""}</small>
              {area.decisionIds.length ? <small className="helloada-growth-area-decision-count">{area.decisionIds.length} {t("growth.areaDecisionCount")}</small> : null}
              {task ? <button type="button" className="helloada-growth-area-task" data-growth-task-id={task.id} onClick={() => openTask(task)}>
                <strong>{title(task)}</strong><small>{serviceWorkById.get(task.id)?.why || taskSummary(task) || stateLabel(task)}</small>
              </button> : linkedWork[0] ? <div className="helloada-growth-area-work"><strong>{linkedWork[0].title || linkedWork[0].id}</strong><small>{linkedWork[0].why || linkedWork[0].scope || linkedWork[0].state}</small></div>
                : areaWork.length ? <p className="helloada-growth-area-empty">{t("growth.areaDecisionOnly")}</p>
                  : <p className="helloada-growth-area-empty">{t("growth.areaNoLinkedWork")}</p>}
              {linkedWork.length > 1 ? <small className="helloada-growth-area-more">{linkedWork.length - 1} {t("growth.areaMoreLinkedWork")}</small> : null}
              {area.limitations.length ? <details className="helloada-growth-area-limitations"><summary>{t("growth.limitations")} ({area.limitations.length})</summary><ul>{area.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details> : null}
              {area.evidenceRefs.length || area.unresolvedEvidenceRefs.length ? <details className="helloada-growth-area-limitations">
                <summary>{t("growth.areaEvidenceRefs")}</summary>
                {area.evidenceRefs.length ? <p><strong>{t("growth.evidenceRecordedRefs")}</strong> {area.evidenceRefs.join(" · ")}</p> : null}
                {area.unresolvedEvidenceRefs.length ? <p><strong>{t("growth.evidenceUnresolvedRefs")}</strong> {area.unresolvedEvidenceRefs.join(" · ")}</p> : null}
              </details> : null}
              {area.nextAssessment ? <small className="helloada-growth-area-next">{t("growth.nextAssessment")}: {date(area.nextAssessment.at)}</small> : null}
              <button type="button" className="helloada-growth-area-link" onClick={() => onNavigate("results", AREA_TABS[area.id])}>{t("growth.areaExplore")} <span aria-hidden="true">→</span></button>
            </article>;
          })}
        </div>
        {serviceModel.unassignedWorkIds.length ? <details className="helloada-growth-unassigned">
          <summary>{t("growth.unassignedWork")} ({serviceModel.unassignedWorkIds.length})</summary>
          <p>{t("growth.unassignedWorkNote")}</p>
          <ul>{serviceModel.unassignedWorkIds.map((id) => {
            const item = serviceWorkById.get(id)!;
            const linkedTask = taskById.get(id);
            return <li key={id}>{linkedTask ? <button type="button" data-growth-task-id={id} onClick={() => openTask(linkedTask)}>{item.title || id} →</button>
              : <span>{item.title || id}</span>}<small>{item.why || item.scope || item.state}</small>
              {item.secondaryAreas.length ? <small>{t("growth.secondaryAreaLinks")}: {item.secondaryAreas.map((area) => t(AREA_LABELS[area])).join(" · ")}</small> : null}</li>;
          })}</ul>
        </details> : null}
      </details> : null}

      {error ? <p className="helloada-growth-error" role="alert">{error}</p> : null}
      {mode !== "home" || selectedTask ? <div className={"helloada-growth-task-columns" + (selectedTask ? " is-review" : "")}>
        <div id="helloada-growth-task-content" className="helloada-growth-workspace" role="tabpanel">
        {selectedTask ? <div className="helloada-growth-detail-view">
          <button type="button" className="helloada-growth-back" onClick={closeTask}>← {t("growth.backToTasks")}</button>
          <header className="helloada-growth-detail-heading">
            <div><span className={"helloada-growth-task-badge is-" + selectedTask.focus}>{stateLabel(selectedTask)}</span>
              <h3>{title(selectedTask)}</h3>
              <small>{selectedTask.updatedAt ? date(selectedTask.updatedAt) : selectedTask.nextRun ? date(selectedTask.nextRun) : t("growth.task_" + selectedTask.focus)}</small>
            </div>
            {selectedTask.kind === "article" && exactArticleReview ? <span className="helloada-growth-review-state">{t("growth.articleUnpublished")}</span> : null}
          </header>

          {selectedTask.kind === "article" ? <>
            {articleLoading ? <p role="status">{t("growth.articleLoading")}</p> : null}
            {articleError !== undefined ? <p className="helloada-growth-error" role="alert">
              {articleError || t("growth.articleLoadFailed")}
              <button type="button" onClick={() => setArticleRefresh(value => value + 1)}>{t("growth.retry")}</button>
            </p> : null}
            {loaded ? <>
              {loaded.blockedReasonCode ? <p className="helloada-growth-task-block" role="status">{t("growth." + loaded.blockedReasonCode)}</p> : null}
              {(loaded.article.rationale || fullTaskSummary(selectedTask)) ? <section className="helloada-growth-task-analysis-note">
                <strong>{t("growth.articleWhyThis")}</strong><p>{loaded.article.rationale || fullTaskSummary(selectedTask)}</p>
              </section> : null}
              {loaded.article.featuredImage?.url ? <figure className="helloada-growth-article-image">
                <img src={loaded.article.featuredImage.url} alt={loaded.article.featuredImage.alt || ""} loading="lazy" />
                {loaded.article.featuredImage.alt ? <figcaption>{loaded.article.featuredImage.alt}</figcaption> : null}
              </figure> : null}
              {loaded.article.excerpt ? <p className="helloada-growth-article-excerpt">{loaded.article.excerpt}</p> : null}
              <dl className="helloada-growth-article-meta">
                {loaded.article.path ? <div><dt>{t("growth.articleRoute")}</dt><dd><code>{loaded.article.path}</code></dd></div> : null}
                {loaded.article.primaryKeyword ? <div><dt>{t("growth.articleQuery")}</dt><dd>{loaded.article.primaryKeyword}</dd></div> : null}
                {loaded.article.metaDescription ? <div><dt>{t("growth.articleMetaDescription")}</dt><dd>{loaded.article.metaDescription}</dd></div> : null}
                {loaded.article.readerQuestion ? <div><dt>{t("growth.articleReaderQuestion")}</dt><dd>{loaded.article.readerQuestion}</dd></div> : null}
                {loaded.article.demandInterpretation ? <div><dt>{t("growth.articleResearchContext")}</dt><dd>{loaded.article.demandInterpretation}</dd></div> : null}
              </dl>
              {loaded.article.bodyFormat === "lexical"
                ? <div className="helloada-growth-article-body">{renderLexicalNode(loaded.article.body, "article")}</div>
                : loaded.article.body ? <div className="helloada-growth-article-body"><HelloAdaChatMessage text={String(loaded.article.body)} /></div> : null}
              {loaded.article.sources?.length ? <details className="helloada-growth-task-evidence">
                <summary>{t("growth.articleSources")}</summary>
                <ul>{loaded.article.sources.map((source, index) => <li key={source.url + index}>
                  <a href={source.url} target="_blank" rel="noreferrer noopener">{source.label || source.url}</a>
                </li>)}</ul>
              </details> : null}
            </> : null}
          </> : <>
            {ownerInformation ? <section className="helloada-growth-owner-question" aria-label={t("growth.ownerQuestionTitle")}>
              <div className="helloada-growth-owner-evidence is-question">
                <strong>{t("growth.clarityQuestion")}</strong>
                <p>{selectedTask.scope || title(selectedTask)}</p>
              </div>
              {fullTaskSummary(selectedTask) ? <details className="helloada-growth-owner-evidence">
                <summary>{t("growth.ownerQuestionObserved")}</summary><p>{fullTaskSummary(selectedTask)}</p>
              </details> : null}
              <p className="helloada-growth-owner-hint">{t("growth.ownerQuestionHint")}</p>
            </section> : fullTaskSummary(selectedTask) && !selectedTask.executionIssue ? <HelloAdaChatMessage text={fullTaskSummary(selectedTask)} /> : null}
            {selectedTask.kind === "article_research" && selectedTask.scope ? <section className="helloada-growth-task-analysis-note">
              <strong>{t("growth.articleOpportunityNeed")}</strong><p>{selectedTask.scope}</p>
            </section> : null}
            {selectedTask.kind === "article" && !selectedTask.canApprove && selectedTask.scope ? <section className="helloada-growth-task-analysis-note">
              <strong>{t("growth.articleWorkContext")}</strong><p>{selectedTask.scope}</p>
            </section> : null}
            {selectedTask.needsPreparation && selectedTask.scope && !selectedTask.review ? <section className="helloada-growth-task-analysis-note">
              <strong>{t("growth.proposedChange")}</strong><p>{selectedTask.scope}</p>
            </section> : null}
            {selectedTask.kind === "code" && selectedTask.scope && !selectedTask.review ? <section className="helloada-growth-task-analysis-note">
              <strong>{t("growth.codeScope")}</strong><p>{selectedTask.scope}</p>
            </section> : null}
            {selectedTask.kind === "analysis_insight" && selectedTask.scope ? <p className="helloada-growth-task-analysis-note">{selectedTask.scope}</p> : null}
            {selectedTask.kind === "schedule" ? <p>{t("growth." + selectedTask.state)}{selectedTask.nextRun ? " · " + date(selectedTask.nextRun) : ""}</p> : null}
            {selectedTask.kind === "measurement" ? <p>{t("growth.measurementDescription")
              .replace("{days}", String(selectedTask.measurementHorizon || ""))
              .replace("{metric}", t("growth.measurement_" + (selectedTask.measurementMetric || "").replaceAll(".", "_")))}</p> : null}
            {selectedTask.kind === "rollback" ? <p>{t("growth.rollbackScope")}</p> : null}
            {selectedTask.kind === "rollback" && selectedTask.previewUrl ? <a className="helloada-growth-task-preview" href={selectedTask.previewUrl} target="_blank" rel="noreferrer">{t("growth.rollbackPreview")} ↗</a> : null}
            {selectedTask.executionIssue && selectedTask.kind !== "assessment" ? <p className="helloada-growth-task-block">{t("growth.taskInternalIssue")}</p> : null}
            {(selectedTask.kind === "code" || selectedTask.kind === "merge") && selectedTask.lastError ? <details className="helloada-growth-task-evidence">
              <summary>{t("growth.taskStoppedReason")}</summary><p>{selectedTask.lastError}</p>
            </details> : null}
            {selectedTask.kind === "assessment" && selectedTask.nextRun ? <p className="helloada-growth-task-block">
              {t("growth.assessmentNextRetry")}: {date(selectedTask.nextRun)}
            </p> : null}
            {selectedTask.review ? <GrowthChangeReview review={selectedTask.review} /> : null}
            {selectedTask.kind === "code" && selectedTask.review?.source ? <section className="helloada-growth-task-analysis-note">
              <strong>{t("growth.codePreview")}</strong>
              {selectedTask.review.source.candidateSha ? <p>{t("growth.codeRevision")}: <code>{selectedTask.review.source.candidateSha.slice(0, 12)}</code></p> : null}
              {selectedTask.review.source.previewUrl ? <a className="helloada-growth-task-preview" href={selectedTask.review.source.previewUrl} target="_blank" rel="noreferrer noopener">{t("growth.codeOpenPreview")} ↗</a> : null}
              {selectedTask.review.source.changedPaths?.length ? <ul>{selectedTask.review.source.changedPaths.map(path => <li key={path}><code>{path}</code></li>)}</ul> : null}
            </section> : null}
            {selectedTask.outcomes?.length ? <section className="helloada-growth-task-outcomes"><h4>{t("growth.taskResults")}</h4>
              {selectedTask.outcomes.map(result => <article key={result.id}>
                <strong>{result.horizon_days} {t("growth.taskDays")} · {t("growth.result_" + result.assessment)}</strong>
                <small>{t("growth.taskConfidence")}: {t("growth.confidence_" + result.confidence)}{result.measured_ts ? " · " + date(result.measured_ts) : ""}</small>
                {result.notes ? <p>{result.notes}</p> : null}
              </article>)}
            </section> : null}
            {selectedTask.history?.length ? <details><summary>{t("growth.taskHistory")}</summary><ul>{selectedTask.history.map(item =>
              <li key={item.initiativeId}>{item.title || title(selectedTask)} · {t("growth.taskState_" + item.state)}</li>)}</ul></details> : null}
          </>}

          <footer className="helloada-growth-task-actions">
            {ownerInformation ? <Link className="helloada-growth-owner-answer" href={discuss(selectedTask)}>
              {t("growth.decisionCtaAnswer")} <span aria-hidden="true">→</span>
            </Link> : null}
            {selectedTask.canApprove && selectedTask.draftId && selectedTask.reviewPackageHash
              && (selectedTask.kind !== "article" || exactArticleReview) ? <>
              <button type="button" className="helloada-growth-primary" disabled={Boolean(busy)}
                onClick={() => void effect(selectedTask, "approve")}>
                {selectedTask.kind === "settings_proposal" ? t("growth.taskApplySettings")
                  : selectedTask.kind === "rollback" ? t("growth.restoreFrontend")
                  : selectedTask.kind === "article" ? t("growth.articlePublish")
                  : selectedTask.kind === "payload_content" ? t("growth.clarityPublishPayload") : t("growth.taskApprove")}
              </button>
              {selectedTask.kind === "payload_content" ? <small className="helloada-growth-publish-now">{t("growth.clarityPublishPayloadNow")}</small> : null}
              <button type="button" disabled={Boolean(busy)} onClick={() => void effect(selectedTask, "discard")}>
                {selectedTask.kind === "settings_proposal" ? t("growth.taskKeepSettings")
                  : selectedTask.kind === "rollback" ? t("growth.keepCurrentWebsite") : t("growth.taskDecline")}
              </button>
            </> : null}
            {selectedTask.focus === "opportunity" || selectedTask.kind === "analysis_insight"
              || selectedTask.canApprove && selectedTask.draftId && selectedTask.reviewPackageHash || selectedTask.kind === "owner_action" || selectedTask.needsPreparation
              ? <Link href={discuss(selectedTask)}>{selectedTask.needsPreparation ? t(selectedTask.kind === "settings_proposal" ? "growth.prepareSettingsWithAda" : "growth.prepareChangeWithAda") : selectedTask.executionIssue ? t("growth.resolveWithAda") : selectedTask.focus === "opportunity" ? t("growth.prepareWithAda") : selectedTask.canApprove && selectedTask.draftId && selectedTask.reviewPackageHash ? t(selectedTask.kind === "article" ? "growth.articleAskChanges" : "growth.codeAskChanges") : t("growth.ask")} ↗</Link>
              : null}
            {selectedTask.kind === "article" && !selectedTask.canApprove
              ? <Link href={discuss(selectedTask)}>{t("growth.articleResolve")} ↗</Link>
              : null}
          </footer>
        </div> : <>
          {mode === "work" ? workRows.length ? <ul className="helloada-growth-task-list helloada-growth-work-list">
            {workRows.map(task => <li key={task.id} className={"helloada-growth-task is-" + task.focus}>{workTaskButton(task)}</li>)}
          </ul> : <div className="helloada-growth-empty" role="status">
            <strong>{pending ? t("growth.loading") : t("growth.workEmptyTitle")}</strong>
            <p>{t("growth.workEmptyBody")}</p>
            <button type="button" className="helloada-growth-secondary" onClick={() => onNavigate("results", "search")}>{t("growth.workResearchLink")} →</button>
          </div> : visible.length ? <ul className="helloada-growth-task-list">
            {visible.map(task => <li key={task.id} className={"helloada-growth-task is-" + task.focus}>{workTaskButton(task)}</li>)}
          </ul> : <div className="helloada-growth-empty" role="status">
            <strong>{pending ? t("growth.loading") : t("growth.empty_needs_you_title")}</strong>
            <p>{t("growth.empty_needs_you")}</p>
          </div>}
        </>}
        </div>
      </div> : null}
      {mode !== "home" ? <p className="helloada-growth-footnote">{t("growth.approval")}</p> : null}
    </div>
  </section>;
}

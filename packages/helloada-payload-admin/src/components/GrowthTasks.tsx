"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { HelloAdaMark } from "./HelloAdaLogo";
import { HelloAdaChatMessage } from "./HelloAdaChatMessage";

type Focus = "needs_you" | "preparing" | "planned" | "paused" | "opportunity" | "completed";
type ArticleReviewData = {
  title?: string; body?: unknown; bodyFormat?: "markdown" | "lexical"; reviewable?: boolean;
  blockedReason?: string; slug?: string; path?: string; excerpt?: string; metaDescription?: string;
  primaryKeyword?: string; rationale?: string; readerQuestion?: string; demandInterpretation?: string;
  featuredImage?: { url?: string; alt?: string; filename?: string; width?: number; height?: number; id?: string } | null;
  sources?: { url: string; label?: string }[];
};
export type GrowthTask = {
  id: string; kind?: string; title?: string; titleKey?: string; summary?: string; summaryKey?: string; scope?: string;
  focus: Focus; state: string; nextRun?: string | null; draftId?: number | null;
  ownerActionId?: number | null; canApprove?: boolean; reviewPackageHash?: string | null;
  lastError?: string; executionIssue?: boolean; updatedAt?: string; conversationId?: number | null;
  evidence?: string[]; measurementHorizon?: number; measurementMetric?: string;
  outcomes?: { id: number; horizon_days: number; assessment: string; confidence: string; notes?: string; measured_ts?: string }[];
  history?: { initiativeId: number; title?: string; state?: string }[]; previewUrl?: string; area?: string;
  review?: { before?: Record<string, unknown>; after?: Record<string, unknown>; changes?: Record<string, unknown>;
    route?: string; setting?: string; article?: ArticleReviewData };
};

type ArticleResponse = { article: ArticleReviewData; reviewable: boolean; blockedReason?: string | null; reviewPackageHash?: string | null };
const FILTERS: Focus[] = ["needs_you", "preparing", "planned", "paused", "opportunity", "completed"];
const SUCCESS_STATES = new Set(["completed", "measuring", "reviewed", "published", "analysis_completed", "approved", "live"]);

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

export function GrowthTasks({ tasks = [], pending, refresh, ask, date, goal, brief }: {
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
      (row || document.querySelector<HTMLButtonElement>(`[data-growth-focus="${focus}"]`))?.focus();
    });
  }, [selected, focus]);
  const selectedTask = tasks.find(row => row.id === selected);
  const articleKey = selectedTask?.kind === "article" && selectedTask.draftId
    ? String(selectedTask.draftId) + ":" + String(selectedTask.reviewPackageHash || "inspection")
    : "";
  const visible = tasks.filter(row => row.focus === focus);
  const loaded = articleResult?.key === articleKey ? articleResult.result : undefined;
  const nextScheduled = tasks
    .filter(row => row.focus === "planned" && row.nextRun)
    .sort((a, b) => String(a.nextRun).localeCompare(String(b.nextRun)))[0];
  const recentWork = tasks
    .filter(row => row.focus === "completed" && SUCCESS_STATES.has(row.state) && !row.executionIssue
      && row.kind !== "article" && row.kind !== "article_research")
    .sort((a, b) => Date.parse(b.updatedAt || "") - Date.parse(a.updatedAt || ""))
    .slice(0, 3);

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
      if (!response.ok || !body.article) throw new Error(typeof body.detail === "string" ? body.detail : "");
      if (!controller.signal.aborted) setArticleResult({ key: requestKey, result: body as ArticleResponse });
    }).catch(reason => {
      if (!controller.signal.aborted) setArticleError(reason instanceof Error ? reason.message : "");
    }).finally(() => {
      if (!controller.signal.aborted) setArticleLoading(undefined);
    });
    return () => controller.abort();
  }, [articleKey, selectedTask?.draftId, articleRefresh]);

  const title = (task: GrowthTask) => task.titleKey ? t("growth." + task.titleKey) : task.title || "—";
  const readable = (value: unknown): string => {
    if (value == null || value === "") return "—";
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) return value.map(readable).filter(item => item !== "—").join(" · ") || "—";
    const record = value as Record<string, unknown>;
    if (record.root) return readable(record.root);
    if (typeof record.text === "string") return record.text;
    if (Array.isArray(record.children)) return readable(record.children);
    const label = record.title || record.alt || record.filename || record.url || record.slug || record.id;
    return label ? readable(label) : Object.values(record).map(readable).filter(item => item !== "—").join(" · ") || "—";
  };
  const discuss = (task: GrowthTask) => {
    const prompt = task.focus === "opportunity"
      ? title(task) + ". " + (task.scope || fullTaskSummary(task)) + ". " + t("growth.opportunityPrompt")
      : task.kind === "article"
        ? title(task) + ". " + (task.canApprove ? t("growth.articleRevisionPrompt") : t("growth.articleResolvePrompt"))
        : task.executionIssue
          ? title(task) + ". " + (task.scope || fullTaskSummary(task)) + ". " + t("growth.taskResolvePrompt")
        : title(task) + ". " + t("growth.decisionPrompt");
    const url = new URL(ask(prompt), "https://workspace.invalid");
    url.searchParams.set("growth_task", task.id);
    if (task.conversationId) url.searchParams.set("conversation_id", String(task.conversationId));
    return url.pathname + url.search;
  };
  const stateLabel = (task: GrowthTask) => {
    if (task.kind === "measurement") return t(task.state === "due" ? "growth.measurementDue" : "growth.measurementScheduled");
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
  const changeFocus = (next: Focus) => {
    setFocus(next);
    setSelected(undefined);
    lastOpenedTask.current = undefined;
    writeGrowthLocation(next);
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

  return <section className="helloada-growth-task-shell" aria-label={t("growth.taskTitle")}>
    <div className="helloada-growth-task-core">
      <header className="helloada-growth-task-header">
        <div className="helloada-growth-identity">
          <HelloAdaMark size={28} />
          <div><h2>{t("growth.taskTitle")}</h2><small>{t("growth.taskNote")}</small></div>
        </div>
        <button type="button" className="helloada-growth-primary" disabled={Boolean(busy) || pending} onClick={() => void effect(undefined, "check")}>
          {busy === "check" ? t("growth.working") : t("growth.runAnalysis")}
        </button>
      </header>

      <div className="helloada-growth-task-goal">
        <span>{t("growth.goalLabel")} · <strong>{goal?.goal_key === "relevant_visitors" ? t("growth.visitorGoal") : goal?.objective || t("growth.goalNotSet")}</strong></span>
        <Link href={ask(t("growth.goalPrompt"))}>{t("growth.changeGoal")} ↗</Link>
      </div>

      {brief?.headline ? <details className="helloada-growth-task-brief">
        <summary>{brief.headline}</summary><HelloAdaChatMessage text={brief.summary_md || ""} />
      </details> : null}

      <div className="helloada-growth-task-filters" role="tablist" aria-label={t("growth.taskFocus")}>
        {FILTERS.map(item => <button key={item} type="button" role="tab" aria-selected={focus === item}
          aria-controls="helloada-growth-task-content" data-growth-focus={item} onClick={() => changeFocus(item)}>
          {t("growth.task_" + item)}<span>{tasks.filter(row => row.focus === item).length}</span>
        </button>)}
      </div>

      {error ? <p className="helloada-growth-error" role="alert">{error}</p> : null}
      <div className={"helloada-growth-task-columns" + (selectedTask ? " is-review" : "")}>
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
              {loaded.blockedReason ? <p className="helloada-growth-task-block" role="status">{loaded.blockedReason}</p> : null}
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
            {fullTaskSummary(selectedTask) ? <HelloAdaChatMessage text={fullTaskSummary(selectedTask)} /> : null}
            {selectedTask.kind === "article_research" && selectedTask.scope ? <section className="helloada-growth-task-analysis-note">
              <strong>{t("growth.articleOpportunityNeed")}</strong><p>{selectedTask.scope}</p>
            </section> : null}
            {selectedTask.kind === "article" && !selectedTask.canApprove && selectedTask.scope ? <section className="helloada-growth-task-analysis-note">
              <strong>{t("growth.articleWorkContext")}</strong><p>{selectedTask.scope}</p>
            </section> : null}
            {selectedTask.kind === "analysis_insight" && selectedTask.scope ? <p className="helloada-growth-task-analysis-note">{selectedTask.scope}</p> : null}
            {selectedTask.kind === "schedule" ? <p>{t("growth." + selectedTask.state)}{selectedTask.nextRun ? " · " + date(selectedTask.nextRun) : ""}</p> : null}
            {selectedTask.kind === "measurement" ? <p>{t("growth.measurementDescription")
              .replace("{days}", String(selectedTask.measurementHorizon || ""))
              .replace("{metric}", t("growth.measurement_" + (selectedTask.measurementMetric || "").replaceAll(".", "_")))}</p> : null}
            {selectedTask.kind === "rollback" ? <p>{t("growth.rollbackScope")}</p> : null}
            {selectedTask.kind === "rollback" && selectedTask.previewUrl ? <a className="helloada-growth-task-preview" href={selectedTask.previewUrl} target="_blank" rel="noreferrer">{t("growth.rollbackPreview")} ↗</a> : null}
            {selectedTask.executionIssue ? <p className="helloada-growth-task-block">{t("growth.taskInternalIssue")}</p> : null}
            {selectedTask.review?.route ? <p className="helloada-growth-task-route">{t("growth.taskAffectedPage")}: <code>{selectedTask.review.route}</code></p> : null}
            {selectedTask.review?.changes ? <dl className="helloada-growth-task-diff">{Object.entries(selectedTask.review.changes).map(([field, value]) =>
              <div key={field}><dt>{t("growth.field_" + field) === "growth.field_" + field ? field.replace(/([A-Z])/g, " $1").replace(/^./, letter => letter.toUpperCase()) : t("growth.field_" + field)}
                </dt><dd><small>{t("growth.taskAfter")}</small><pre>{readable(value)}</pre></dd></div>)}</dl> : null}
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
            {selectedTask.canApprove && selectedTask.draftId && selectedTask.reviewPackageHash
              && (selectedTask.kind !== "article" || exactArticleReview) ? <>
              <button type="button" className="helloada-growth-primary" disabled={Boolean(busy)}
                onClick={() => void effect(selectedTask, "approve")}>
                {selectedTask.kind === "settings_proposal" ? t("growth.taskApplySettings")
                  : selectedTask.kind === "rollback" ? t("growth.restoreFrontend")
                  : selectedTask.kind === "article" ? t("growth.articlePublish") : t("growth.taskApprove")}
              </button>
              <button type="button" disabled={Boolean(busy)} onClick={() => void effect(selectedTask, "discard")}>
                {selectedTask.kind === "settings_proposal" ? t("growth.taskKeepSettings")
                  : selectedTask.kind === "rollback" ? t("growth.keepCurrentWebsite") : t("growth.taskDecline")}
              </button>
            </> : null}
            {selectedTask.focus === "opportunity" || selectedTask.kind === "analysis_insight" || selectedTask.kind === "article" || selectedTask.kind === "owner_action" || selectedTask.executionIssue
              ? <Link href={discuss(selectedTask)}>{selectedTask.focus === "opportunity" ? t("growth.prepareWithAda") : selectedTask.kind === "article" ? t(selectedTask.canApprove ? "growth.articleAskChanges" : "growth.articleResolve") : selectedTask.executionIssue ? t("growth.resolveWithAda") : t("growth.ask")} ↗</Link>
              : null}
          </footer>
        </div> : <>
          {visible.length ? <ul className="helloada-growth-task-list">
            {visible.map(task => <li key={task.id} className={"helloada-growth-task is-" + task.focus}>
              <button type="button" className="helloada-growth-task-row" data-growth-task-id={task.id} onClick={() => openTask(task)}>
                <i aria-hidden="true" />
                <span className="helloada-growth-task-label"><strong>{title(task)}</strong>
                  <small>{task.nextRun ? date(task.nextRun) : task.area || taskSummary(task) || stateLabel(task)}</small>
                </span>
                <span className={"helloada-growth-task-badge is-" + task.focus}>{stateLabel(task)}</span>
                <span className="helloada-growth-row-open">{t("growth.openTask")} →</span>
              </button>
            </li>)}
          </ul> : <div className="helloada-growth-empty" role="status">
            <strong>{pending ? t("growth.loading") : t("growth.empty_" + focus + "_title")}</strong>
            <p>{t("growth.empty_" + focus)}</p>
          </div>}
        </>}
        </div>
        {!selectedTask ? <aside className="helloada-growth-support-rail" aria-label={t("growth.nextReview")}>
          <section>
            <h3>{t("growth.nextReview")}</h3>
            {nextScheduled ? <button type="button" data-growth-task-id={nextScheduled.id} onClick={() => openTask(nextScheduled)}>
              <strong>{title(nextScheduled)}</strong><small>{date(nextScheduled.nextRun)}</small>
            </button> : <p>{t("growth.noNextReview")}</p>}
          </section>
          <section>
            <h3>{t("growth.recentWork")}</h3>
            {recentWork.length ? <ul>{recentWork.map(task => <li key={task.id}>
              <button type="button" data-growth-task-id={task.id} onClick={() => openTask(task)}>
                <strong>{title(task)}</strong><small>{task.updatedAt ? date(task.updatedAt) : stateLabel(task)}</small>
              </button>
            </li>)}</ul> : <p>{t("growth.noRecentWork")}</p>}
            <Link href="/admin?view=history">{t("growth.openActivity")} ↗</Link>
          </section>
        </aside> : null}
      </div>
      <p className="helloada-growth-footnote">{t("growth.approval")}</p>
    </div>
  </section>;
}

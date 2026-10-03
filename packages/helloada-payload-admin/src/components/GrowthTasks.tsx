"use client";

import Link from "next/link";
import { useState } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { HelloAdaMark } from "./HelloAdaLogo";
import { HelloAdaChatMessage } from "./HelloAdaChatMessage";

export type GrowthTask = {
  id: string; kind?: string; title?: string; titleKey?: string; summary?: string; scope?: string;
  focus: "needs_you" | "preparing" | "planned" | "paused" | "completed"; state: string;
  nextRun?: string | null; draftId?: number | null; ownerActionId?: number | null;
  canApprove?: boolean; reviewPackageHash?: string | null; lastError?: string; executionIssue?: boolean; updatedAt?: string;
  conversationId?: number | null;
  evidence?: string[];
  measurementHorizon?: number;
  measurementMetric?: string;
  outcomes?: { id: number; horizon_days: number; assessment: string; confidence: string; notes?: string; measured_ts?: string }[];
  history?: { initiativeId: number; title?: string; state?: string }[];
  previewUrl?: string;
  review?: { before?: Record<string, unknown>; after?: Record<string, unknown>; changes?: Record<string, unknown>; route?: string; setting?: string };
};

export function GrowthTasks({ tasks = [], pending, refresh, ask, date, goal, brief }: {
  tasks?: GrowthTask[]; pending: boolean; refresh: () => void; ask: (prompt?: string) => string;
  date: (value: unknown) => string; goal?: { objective?: string; goal_key?: string };
  brief?: { headline?: string; summary_md?: string };
}) {
  const { t } = useHelloAdaTranslations();
  const [focus, setFocus] = useState("needs_you");
  const [selected, setSelected] = useState<string>();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const filters = ["needs_you", "preparing", "planned", "paused", "completed"];
  const visible = tasks.filter(row => row.focus === focus);
  const recent = tasks.filter(row => ["reviewed", "published", "complete", "completed"].includes(row.state))
    .sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || ""))).slice(0, 6);
  const title = (task: GrowthTask) => task.titleKey ? t(`growth.${task.titleKey}`) : task.title || "—";
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
    const url = new URL(ask(`${title(task)}. ${t("growth.decisionPrompt")}`), "https://workspace.invalid");
    url.searchParams.set("growth_task", task.id);
    if (task.conversationId) url.searchParams.set("conversation_id", String(task.conversationId));
    return `${url.pathname}${url.search}`;
  };
  const stateLabel = (task: GrowthTask) => {
    if (task.kind === "measurement") return t(task.state === "due" ? "growth.measurementDue" : "growth.measurementScheduled");
    const key = task.kind === "schedule" ? task.state :
      ["reviewed", "rejected", "superseded", "measuring", "blocked", "failed", "publishing", "verifying_live", "snoozed", "ready_for_review", "unscheduled"].includes(task.state) ? `taskState_${task.state}` : `task_${task.focus}`;
    return t(`growth.${key}`);
  };
  const effect = async (task: GrowthTask | undefined, operation: string) => {
    if (busy) return;
    setBusy(task?.id || operation); setError(undefined);
    try {
      const endpoint = task ? `/api/helloada/drafts/${task.draftId}/${operation}` : "/api/helloada/growth/check";
      const response = await fetchHelloAda(endpoint, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_package_hash: task?.reviewPackageHash }) });
      const body = await response.json();
      if (!response.ok || body.ok === false) throw new Error(String(body.detail || body.message || t("growth.taskFailed")));
      refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("growth.taskFailed")); }
    finally { setBusy(undefined); }
  };
  return <section className="helloada-growth-task-shell" aria-label={t("growth.taskTitle")}>
    <div className="helloada-growth-task-core">
      <div className="helloada-growth-task-layout">
      <div className="helloada-growth-task-main">
      <header className="helloada-growth-task-header">
        <div className="helloada-growth-identity"><HelloAdaMark size={28} /><div><h2>{t("growth.taskTitle")}</h2>
          <small>{t("growth.taskNote")}</small></div></div>
        <button type="button" className="helloada-growth-primary" disabled={Boolean(busy) || pending} onClick={() => void effect(undefined, "check")}>{t("growth.runAnalysis")}</button>
      </header>
      <div className="helloada-growth-task-goal"><span>{t("growth.goalLabel")} · <strong>{goal?.goal_key === "relevant_visitors" ? t("growth.visitorGoal") : goal?.objective || t("growth.goalNotSet")}</strong></span>
        <Link href={ask(t("growth.goalPrompt"))}>{t("growth.changeGoal")} ↗</Link></div>
      {brief?.headline ? <details className="helloada-growth-task-brief"><summary>{brief.headline}</summary><HelloAdaChatMessage text={brief.summary_md || ""} /></details> : null}
      <div className="helloada-growth-task-filters" role="group" aria-label={t("growth.taskFocus")}>
        {filters.map(item => <button key={item} type="button" aria-pressed={focus === item} onClick={() => setFocus(item)}>
          {t(`growth.task_${item}`)}<span>{tasks.filter(row => row.focus === item).length}</span></button>)}
      </div>
      {error ? <p className="helloada-growth-error" role="alert">{error}</p> : null}
      <ul className="helloada-growth-task-list">
        {visible.map(task => <li key={task.id} className={`helloada-growth-task is-${task.focus}`}>
          <button type="button" className="helloada-growth-task-row" aria-expanded={selected === task.id} onClick={() => setSelected(selected === task.id ? undefined : task.id)}>
            <i aria-hidden="true" /><span className="helloada-growth-task-label"><strong>{title(task)}</strong>
              <small>{task.nextRun ? date(task.nextRun) : task.scope || task.summary || t(`growth.task_${task.focus}`)}</small></span>
            <span className={`helloada-growth-task-badge is-${task.focus}`}>{stateLabel(task)}</span><span aria-hidden="true">{selected === task.id ? "−" : "+"}</span>
          </button>
          {selected === task.id ? <div className="helloada-growth-task-detail">
            {task.summary ? <HelloAdaChatMessage text={task.summary} /> : null}
            {task.kind === "schedule" ? <p>{t(`growth.${task.state}`)}{task.nextRun ? ` · ${date(task.nextRun)}` : ""}</p> : null}
            {task.kind === "measurement" ? <p>{t("growth.measurementDescription").replace("{days}", String(task.measurementHorizon || "")).replace("{metric}", t(`growth.measurement_${(task.measurementMetric || "").replaceAll(".", "_")}`))}</p> : null}
            {task.kind === "rollback" ? <p>{t("growth.rollbackScope")}</p> : null}
            {task.kind === "rollback" && task.previewUrl ? <a className="helloada-growth-task-preview" href={task.previewUrl} target="_blank" rel="noreferrer">{t("growth.rollbackPreview")} ↗</a> : null}
            {task.executionIssue ? <p className="helloada-growth-task-block">{t("growth.taskInternalIssue")}</p> : null}
            {task.review?.route ? <p className="helloada-growth-task-route">{t("growth.taskAffectedPage")}: <code>{task.review.route}</code></p> : null}
            {task.kind === "settings_proposal" && task.review?.changes ? <section className="helloada-growth-settings-proposal">
              <p>{t("growth.settingsNoContentChange")}</p>
              {(["voice_notes", "avoid"] as const).map(field => <div key={field}>
                <h3>{t(`growth.${field === "voice_notes" ? "settingsVoiceNotes" : "settingsAvoid"}`)}</h3>
                <div className="helloada-growth-settings-columns">
                  <div><strong>{t("growth.settingsCurrent")}</strong><ul>{(Array.isArray(task.review?.before?.[field]) ? task.review.before[field] as unknown[] : []).map((item, index) => <li key={`current-${field}-${index}`}>{readable(item)}</li>)}</ul></div>
                  <div><strong>{t("growth.settingsProposed")}</strong><ul>{(Array.isArray(task.review?.after?.[field]) ? task.review.after[field] as unknown[] : []).map((item, index) => <li key={`proposed-${field}-${index}`}>{readable(item)}</li>)}</ul></div>
                </div>
              </div>)}
            </section> : null}
            {task.kind !== "settings_proposal" && task.review?.changes ? <dl className="helloada-growth-task-diff">{Object.entries(task.review.changes).map(([field, value]) => <div key={field}><dt>{t(`growth.field_${field}`) === `growth.field_${field}` ? field.replace(/([A-Z])/g, " $1").replace(/^./, letter => letter.toUpperCase()) : t(`growth.field_${field}`)}</dt><dd>
              <small>{t("growth.taskBefore")}</small><pre>{readable(task.review?.before?.[field])}</pre>
              <small>{t("growth.taskAfter")}</small><pre>{readable(value)}</pre></dd></div>)}</dl> : null}
            {task.evidence?.length ? <details className="helloada-growth-task-evidence"><summary>{t("growth.taskEvidence")}</summary><ul>{task.evidence.map((item, index) => <li key={`${task.id}-evidence-${index}`}>{item}</li>)}</ul></details> : null}
            {task.outcomes?.length ? <div className="helloada-growth-task-outcomes"><h3>{t("growth.taskResults")}</h3>
              {task.outcomes.map(result => <article key={result.id}><strong>{result.horizon_days} {t("growth.taskDays")} · {t(`growth.result_${result.assessment}`)}</strong>
                <small>{t("growth.taskConfidence")}: {t(`growth.confidence_${result.confidence}`)}{result.measured_ts ? ` · ${date(result.measured_ts)}` : ""}</small>
                {result.notes ? <p>{result.notes}</p> : null}</article>)}
            </div> : null}
            {task.history?.length ? <details><summary>{t("growth.taskHistory")}</summary><ul>{task.history.map(item => <li key={item.initiativeId}>
              {item.title || title(task)} · {t(`growth.taskState_${item.state}`)}</li>)}</ul></details> : null}
            <div className="helloada-growth-task-actions">
              {task.canApprove && task.draftId && task.reviewPackageHash ? <>
                <button type="button" className="helloada-growth-primary" disabled={Boolean(busy)} onClick={() => void effect(task, "approve")}>{task.kind === "settings_proposal" ? t("growth.taskApplySettings") : task.kind === "rollback" ? t("growth.restoreFrontend") : t("growth.taskApprove")}</button>
                <button type="button" disabled={Boolean(busy)} onClick={() => void effect(task, "discard")}>{task.kind === "settings_proposal" ? t("growth.taskKeepSettings") : task.kind === "rollback" ? t("growth.keepCurrentWebsite") : t("growth.taskDecline")}</button>
              </> : null}
              <Link href={discuss(task)}>{t("growth.ask")} ↗</Link>
            </div>
          </div> : null}
        </li>)}
      </ul>
      {!visible.length ? <p className="helloada-growth-empty" role="status">{pending ? t("growth.loading") : t("growth.taskEmpty")}</p> : null}
      <p className="helloada-growth-footnote">{t("growth.approval")}</p>
      </div>
      <aside className="helloada-growth-recent" aria-labelledby="helloada-growth-recent-title">
        <div className="helloada-growth-recent-heading"><span aria-hidden="true">↗</span><h3 id="helloada-growth-recent-title">{t("growth.recentWork")}</h3></div>
        {recent.length ? <ul>{recent.map(task => <li key={`recent-${task.id}`}>
          <strong>{title(task)}</strong><small>{stateLabel(task)}{task.updatedAt ? ` · ${date(task.updatedAt)}` : ""}</small>
          {task.summary ? <p>{task.summary}</p> : null}
        </li>)}</ul> : <p className="helloada-growth-recent-empty">{t("growth.noRecentWork")}</p>}
        <Link href="/admin?view=history">{t("growth.openActivity")} ↗</Link>
      </aside>
      </div>
    </div>
  </section>;
}

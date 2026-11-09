"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { growthDecisionOrder, growthPanelFromSearch, growthResultTabFromSearch, isGrowthServiceModel, type GrowthResultTab, type GrowthRow, type GrowthServiceModel } from "../lib/growth-data";
import { GrowthTasks, type GrowthTask } from "./GrowthTasks";
import { WorkspaceIcon } from "./WorkspaceIcon";
import {
  GrowthAnalytics,
  type GrowthAnalyticsData,
} from "./GrowthAnalytics";
import { GrowthEvidence } from "./GrowthEvidence";
import { GrowthCompetition } from "./GrowthCompetition";
type GrowthPanel = "home" | "decisions" | "work" | "results" | "areas" | "budget";
type ResearchBudget = { policyRevision: number; period: string; timeZone: string; currency: string; allowanceMicros: string | null; maxOperationMicros: string | null; committedMicros: string; reservedMicros: string; remainingMicros: string | null; configured: boolean };
type ResearchPolicy = { revision: number; topics: string[]; goals: string[]; exclusions: string[]; recencyDays: number; audience: string | null; market: string | null; language: string; providers: Array<"reddit" | "news" | "web" | "competitor">; cadence: "daily" | "weekly" | "monthly" | "manual"; enabled: boolean; maxSources: number; monthlyBudget: number; autoDraft: boolean; autoAgent: boolean };
const MICROS_PER_UNIT = BigInt(1_000_000);
const microsToAmount = (value: string | null) => {
  if (value === null) return "";
  const micros = BigInt(value);
  const magnitude = micros < 0 ? -micros : micros;
  const fraction = (magnitude % MICROS_PER_UNIT).toString().padStart(6, "0").replace(/0+$/, "");
  return `${micros < 0 ? "-" : ""}${magnitude / MICROS_PER_UNIT}.${fraction.padEnd(2, "0")}`;
};
type OwnerQueue = {
  featuredDecisionId: string | null;
  additionalDecisionIds: string[];
  decisionCount: number;
  activeTaskId: string | null;
  nextScheduledId: string | null;
  recentResultId: string | null;
  recentResultIds: string[];
  attentionTaskId: string | null;
  progression: {
    state: "ready_for_review" | "preparing" | "service_issue" | "assessing" | "scheduled" | "deferred_findings" | "assessed" | "not_started";
    primaryTaskId: string | null;
    serviceIssueTaskId: string | null;
    latestAssessmentAt: string | null;
    latestAssessmentStatus: string | null;
    latestAssessmentSummary: string | null;
    deferredFindingCount: number;
    deferredFindingTitle?: string | null;
    deferredFindingSummary?: string | null;
    deferredReassessWhen?: string | null;
    nextAssessmentAt?: string | null;
  };
};

type Insight = {
  headline?: string;
  summary_md?: string;
  ts?: string;
  period?: string;
  opportunities?: Array<{
    title?: string;
    rationale?: string;
    action?: string;
  }>;
};
type Growth = {
  tasks?: GrowthTask[];
  serviceModel: GrowthServiceModel;
  decisionOrder: string[];
  ownerQueue: OwnerQueue;
  ownerTimezone?: string | null;
  growthContractVersion: string;
  ownerQueueContractVersion: string;
  sources?: Array<{
    id: string;
    provider?: string;
    capability?: string;
    status: string;
    state?: string;
    reason?: string;
    property?: string;
    updatedAt?: string;
    title?: string;
    sourceRef?: string;
    observedAt?: string;
    retrievedAt?: string;
    freshnessHours?: number | null;
  }>;
  latestInsight?: Insight;
  insights?: Insight[];
  keywords?: GrowthRow[];
  keywordMetrics?: GrowthRow[];
  articles?: GrowthRow[];
  articleIdeas?: GrowthRow[];
  goal?: { objective?: string; goal_key?: string; revision?: number };
};

export function HelloAdaGrowth() {
  const { t, language } = useHelloAdaTranslations();
  const [panel, setPanel] = useState<GrowthPanel>("home");
  const [tab, setTab] = useState<GrowthResultTab>("analytics");
  const [days, setDays] = useState(28);
  const [revision, setRevision] = useState(0);
  const [growth, setGrowth] = useState<Growth>();
  const [analytics, setAnalytics] = useState<GrowthAnalyticsData>();
  const [errors, setErrors] = useState<Record<string, boolean>>({});
  const [budget, setBudget] = useState<ResearchBudget>();
  const [budgetAmount, setBudgetAmount] = useState("");
  const [budgetOperationAmount, setBudgetOperationAmount] = useState("");
  const [budgetBusy, setBudgetBusy] = useState(false);
  const [budgetError, setBudgetError] = useState("");
  const [researchPolicy, setResearchPolicy] = useState<ResearchPolicy>();
  const [policyTopics, setPolicyTopics] = useState("");
  const [policyGoals, setPolicyGoals] = useState("");
  const [policyExclusions, setPolicyExclusions] = useState("");
  const [policyBusy, setPolicyBusy] = useState(false);
  const [loading, setLoading] = useState<Record<string, boolean>>({
    growth: true,
    analytics: false,
  });
  const date = (value: unknown) => {
    const parsed = new Date(String(value ?? ""));
    return Number.isNaN(parsed.getTime())
      ? "—"
      : new Intl.DateTimeFormat(language, {
          dateStyle: "medium",
          timeStyle: "short",
          ...(growth?.ownerTimezone ? { timeZone: growth.ownerTimezone } : {}),
        }).format(parsed);
  };
  const ask = (prompt = t("growth.askPrompt")) =>
    `/admin?ask=${encodeURIComponent(prompt)}`;
  useEffect(() => {
    const restorePanel = () => {
      const search = window.location.search;
      setPanel(growthPanelFromSearch(search));
      setTab(growthResultTabFromSearch(search));
    };
    restorePanel();
    window.addEventListener("popstate", restorePanel);
    return () => window.removeEventListener("popstate", restorePanel);
  }, []);
  useEffect(() => {
    const tabs = document.querySelector<HTMLElement>(".helloada-growth-tabs");
    const active = tabs?.querySelector<HTMLElement>('button[aria-pressed="true"]');
    if (tabs && active) {
      const left = active.offsetLeft - Math.max(0, (tabs.clientWidth - active.clientWidth) / 2);
      tabs.scrollTo({ left: Math.max(0, left), behavior: "instant" });
    }
  }, [panel]);
  const navigatePanel = (next: GrowthPanel, resultsTab: GrowthResultTab = "analytics") => {
    setPanel(next);
    if (next === "results") setTab(resultsTab);
    const url = new URL(window.location.href);
    if (next === "home") url.searchParams.delete("growth_panel");
    else url.searchParams.set("growth_panel", next);
    if (next === "results") url.searchParams.set("growth_results", resultsTab);
    else url.searchParams.delete("growth_results");
    url.searchParams.delete("growth_task");
    url.searchParams.delete("growth_focus");
    window.history.pushState({ ...window.history.state, helloAdaGrowthPanel: next }, "", url.toString());
  };
  const navigateResultsTab = (next: GrowthResultTab) => {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("growth_panel", "results");
    url.searchParams.set("growth_results", next);
    url.searchParams.delete("growth_task");
    url.searchParams.delete("growth_focus");
    window.history.pushState({ ...window.history.state, helloAdaGrowthPanel: "results" }, "", url.toString());
  };
  // Changing the reporting period must not clear or refetch Ada's brief.
  useEffect(() => {
    const controller = new AbortController();
    setLoading((current) => ({ ...current, growth: true }));
    setErrors((current) => ({ ...current, growth: false }));
    void fetchHelloAda("/api/helloada/growth", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("unavailable");
        const body = await response.json();
        const progression = body?.ownerQueue?.progression;
        const progressionStates = ["ready_for_review", "preparing", "service_issue", "assessing", "scheduled", "deferred_findings", "assessed", "not_started"];
        if (!body || body.growthContractVersion !== "owner-decisions-v1"
          || body.ownerQueueContractVersion !== "owner-queue-progression-v1"
          || !isGrowthServiceModel(body.serviceModel)
          || !Array.isArray(body.tasks) || !body.ownerQueue
          || !Array.isArray(body.ownerQueue.additionalDecisionIds) || !Array.isArray(body.ownerQueue.recentResultIds)
          || !Number.isInteger(body.ownerQueue.decisionCount) || body.ownerQueue.decisionCount < 0
          || !progression || !progressionStates.includes(progression.state)
          || !Number.isInteger(progression.deferredFindingCount) || progression.deferredFindingCount < 0
          || !(progression.primaryTaskId === null || typeof progression.primaryTaskId === "string")
          || !(progression.serviceIssueTaskId === null || typeof progression.serviceIssueTaskId === "string")
          || !(progression.latestAssessmentAt === null || typeof progression.latestAssessmentAt === "string")
          || !(progression.latestAssessmentStatus === null || typeof progression.latestAssessmentStatus === "string")
          || !(progression.latestAssessmentSummary === null || typeof progression.latestAssessmentSummary === "string")
          || !(progression.deferredFindingTitle === undefined || progression.deferredFindingTitle === null || typeof progression.deferredFindingTitle === "string")
          || !(progression.deferredFindingSummary === undefined || progression.deferredFindingSummary === null || typeof progression.deferredFindingSummary === "string")
          || !(progression.deferredReassessWhen === undefined || progression.deferredReassessWhen === null || typeof progression.deferredReassessWhen === "string")
          || !(progression.nextAssessmentAt === undefined || progression.nextAssessmentAt === null || typeof progression.nextAssessmentAt === "string"))
          throw new Error("incompatible Growth response");
        const growthTaskIds = new Set(body.tasks.map((task: GrowthTask) => task?.id));
        if (body.serviceModel.decisionIds.some((id: string) => !growthTaskIds.has(id)))
          throw new Error("Growth service decision has no canonical review task");
        const decisionOrder = growthDecisionOrder(body.ownerQueue, body.serviceModel.decisionIds);
        if (!decisionOrder) throw new Error("Owner queue and Growth service decisions are incompatible");
        if (!controller.signal.aborted) setGrowth({ ...body, decisionOrder });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setErrors((current) => ({ ...current, growth: true }));
      })
      .finally(() => {
        if (!controller.signal.aborted)
          setLoading((current) => ({ ...current, growth: false }));
      });
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    if (panel !== "budget") return;
    const controller = new AbortController();
    setBudgetError("");
    void fetchHelloAda("/api/helloada/growth/budget", { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(t("growth.budgetUnavailable"));
        const body = await response.json();
        const row = body?.budget as ResearchBudget | undefined;
        if (!row || !Number.isInteger(row.policyRevision) || typeof row.currency !== "string" || typeof row.timeZone !== "string") throw new Error(t("growth.budgetInvalid"));
        if (!controller.signal.aborted) {
          setBudget(row);
          setBudgetAmount(microsToAmount(row.allowanceMicros));
          setBudgetOperationAmount(microsToAmount(row.maxOperationMicros));
        }
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setBudgetError(error instanceof Error ? error.message : t("growth.budgetUnavailable")); });
    return () => controller.abort();
  }, [panel, revision, t]);
  useEffect(() => {
    if (panel !== "budget") return;
    const controller = new AbortController();
    void fetchHelloAda("/api/helloada/growth/research-policy", { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(t("growth.policyUnavailable"));
        const body = await response.json();
        const row = body?.policy as ResearchPolicy | undefined;
        if (!row || !Number.isInteger(row.revision) || !Array.isArray(row.topics) || !Array.isArray(row.providers) || typeof row.enabled !== "boolean") throw new Error(t("growth.policyInvalid"));
        if (!controller.signal.aborted) { setResearchPolicy(row); setPolicyTopics(row.topics.join(", ")); setPolicyGoals(row.goals.join(", ")); setPolicyExclusions(row.exclusions.join(", ")); }
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setBudgetError(error instanceof Error ? error.message : t("growth.policyUnavailable")); });
    return () => controller.abort();
  }, [panel, revision, t]);
  useEffect(() => {
    if (panel !== "results" || tab !== "analytics") {
      setLoading((current) => ({ ...current, analytics: false }));
      return;
    }
    const controller = new AbortController();
    setLoading((current) => ({ ...current, analytics: true }));
    setAnalytics(undefined);
    setErrors((current) => ({ ...current, analytics: false }));
    void fetchHelloAda(`/api/helloada/seo/analytics?days=${days}`, {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("unavailable");
        const body = await response.json();
        if (!controller.signal.aborted) setAnalytics(body);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setErrors((current) => ({ ...current, analytics: true }));
      })
      .finally(() => {
        if (!controller.signal.aborted)
          setLoading((current) => ({ ...current, analytics: false }));
      });
    return () => controller.abort();
  }, [days, revision, panel, tab]);
  const refresh = () => setRevision((value) => value + 1);
  const saveBudget = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!budget) return;
    const value = budgetAmount.trim();
    if (!/^\d+(?:\.\d{1,6})?$/.test(value)) { setBudgetError(t("growth.budgetAmountInvalid")); return; }
    const [whole, fraction = ""] = value.split(".");
    const micros = (BigInt(whole) * MICROS_PER_UNIT + BigInt((fraction + "000000").slice(0, 6))).toString();
    const operationValue = budgetOperationAmount.trim();
    if (operationValue && !/^\d+(?:\.\d{1,6})?$/.test(operationValue)) { setBudgetError(t("growth.budgetAmountInvalid")); return; }
    const [operationWhole = "0", operationFraction = ""] = operationValue ? operationValue.split(".") : [];
    const maxOperationMicros = operationValue
      ? (BigInt(operationWhole) * MICROS_PER_UNIT + BigInt((operationFraction + "000000").slice(0, 6))).toString()
      : null;
    setBudgetBusy(true);
    setBudgetError("");
    try {
      const response = await fetchHelloAda("/api/helloada/growth/budget", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ expectedRevision: budget.policyRevision, monthlyAllowanceMicros: micros, maxOperationMicros, timeZone: budget.timeZone }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || body.error || t("growth.budgetSaveFailed"));
      const updated = body?.budget as ResearchBudget | undefined;
      if (!updated) throw new Error(t("growth.budgetVerifyFailed"));
      setBudget(updated);
      setBudgetAmount(microsToAmount(updated.allowanceMicros));
      setBudgetOperationAmount(microsToAmount(updated.maxOperationMicros));
    } catch (error) { setBudgetError(error instanceof Error ? error.message : t("growth.budgetSaveFailed")); }
    finally { setBudgetBusy(false); }
  };
  const saveResearchPolicy = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!researchPolicy) return;
    const topics = [...new Set(policyTopics.split(",").map((value) => value.trim()).filter(Boolean))];
    const goals = [...new Set(policyGoals.split(",").map((value) => value.trim()).filter(Boolean))];
    const exclusions = [...new Set(policyExclusions.split(",").map((value) => value.trim()).filter(Boolean))];
    if (topics.length > 12 || topics.some((value) => value.length > 120) || goals.length > 12 || goals.some((value) => value.length > 300) || exclusions.length > 30 || exclusions.some((value) => value.length > 200)) { setBudgetError(t("growth.policyTopicsInvalid")); return; }
    setPolicyBusy(true); setBudgetError("");
    try {
      const { revision: expectedRevision, ...fields } = researchPolicy;
      const response = await fetchHelloAda("/api/helloada/growth/research-policy", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...fields, topics, goals, exclusions, expectedRevision }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || body.error || t("growth.policySaveFailed"));
      const updated = body?.policy as ResearchPolicy | undefined;
      if (!updated || !Number.isInteger(updated.revision)) throw new Error(t("growth.policyVerifyFailed"));
      setResearchPolicy(updated); setPolicyTopics(updated.topics.join(", ")); setPolicyGoals(updated.goals.join(", ")); setPolicyExclusions(updated.exclusions.join(", "));
    } catch (error) { setBudgetError(error instanceof Error ? error.message : t("growth.policySaveFailed")); }
    finally { setPolicyBusy(false); }
  };
  const ErrorNotice = () => (
    <div className="helloada-growth-error" role="status">
      {t("growth.unavailable")}{" "}
      <button type="button" onClick={refresh}>
        {t("growth.retry")}
      </button>
    </div>
  );
  const insight = growth?.latestInsight;
  const Sources = () => (
    <div className="helloada-growth-sources">
      {(growth?.sources || []).map((source) => {
        const id = source.id;
        const knownConnector = ["ga4", "gsc", "dataforseo"].includes(id);
        return (
          <article key={id} className="helloada-growth-source">
            <header>
              <h3>{source.title || (knownConnector ? t(`growth.${id}`) : source.provider || id)}</h3>
              <span
                className={`helloada-growth-state is-${source.state || source.status || "unknown"}`}
              >
                {source
                  ? source.state
                    ? t(`growth.${source.provider === "crawlseo" ? "evidence_state" : "state"}_${source.state}`)
                    : t(`growth.${source.status}`)
                  : t("growth.noData")}
              </span>
            </header>
            {knownConnector ? <p>{t(`growth.${id}Note`)}</p> : null}
            {source.reason ? <small>{source.reason}</small> : null}
            {source.property ? <small>{source.property}</small> : null}
            {source.capability ? <small>{source.capability}</small> : null}
            {source.sourceRef ? <small>{source.sourceRef}</small> : null}
            {source.updatedAt || source.observedAt ? (
              <small>
                {source.observedAt ? `${t("growth.observed")} ${date(source.observedAt)}` : `${t("growth.updated")} ${date(source.updatedAt)}`}
              </small>
            ) : null}
            {source.retrievedAt ? <small>{t("growth.retrieved")} {date(source.retrievedAt)}</small> : null}
            {source.freshnessHours != null ? <small>{source.freshnessHours}h</small> : null}
          </article>
        );
      })}
    </div>
  );
  const Records = ({
    title,
    rows,
    empty,
  }: {
    title: string;
    rows?: GrowthRow[];
    empty: string;
  }) => (
    <section className="helloada-growth-card">
      <header>
        <h2>{title}</h2>
        <small>{rows?.length || 0}</small>
      </header>
      {rows?.length ? (
        rows.map((row, index) => (
          <details
            className="helloada-growth-record"
            key={String(row.id || index)}
          >
            <summary>
              <span>
                {String(
                  row.title ||
                    row.period ||
                    (row.idea_json as GrowthRow | undefined)?.working_title ||
                    (row.idea_json as GrowthRow | undefined)?.title ||
                    row.focus_keyword ||
                    "—",
                )}
              </span>
              <small>{String(row.status || "")}</small>
            </summary>
            <small>{date(row.updated_ts || row.created_ts)}</small>
            <p>
              {String(
                row.summary ||
                  (row.idea_json as GrowthRow | undefined)?.thesis ||
                  (row.idea_json as GrowthRow | undefined)?.rationale ||
                  row.focus_keyword ||
                  "",
              )}
            </p>
          </details>
        ))
      ) : (
        <p className="helloada-growth-empty">
          {loading.growth ? t("growth.loading") : empty}
        </p>
      )}
    </section>
  );
  return (
    <main className="helloada-growth" aria-label={t("growth.title")}>
      <div className="helloada-growth-toolbar">
        <div
          className="helloada-growth-tabs"
          role="group"
          aria-label={t("growth.title")}
        >
          <button type="button" aria-pressed={panel === "home"} onClick={() => navigatePanel("home")}>{t("growth.panel_next")}</button>
          <button type="button" aria-pressed={panel === "decisions"} onClick={() => navigatePanel("decisions")}>{t("growth.panel_decisions")}</button>
          <button type="button" aria-pressed={panel === "work"} onClick={() => navigatePanel("work")}>{t("growth.panel_work")}</button>
          <button type="button" aria-pressed={panel === "areas"} onClick={() => navigatePanel("areas")}>{t("growth.panel_areas")}</button>
          <button type="button" aria-pressed={panel === "results"} onClick={() => navigatePanel("results")}>{t("growth.panel_results")}</button>
          <button type="button" aria-pressed={panel === "budget"} onClick={() => navigatePanel("budget")}>{t("growth.panel_budget")}</button>
        </div>
        <div className="helloada-growth-controls">
          {panel === "results" && tab === "analytics" ? (
            <select
              aria-label={t("growth.days")}
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              {[7, 28, 90, 180, 365, 540].map((value) => (
                <option key={value} value={value}>
                  {value} {t("growth.days")}
                </option>
              ))}
            </select>
          ) : null}
          <button
            type="button"
            aria-label={t("growth.refresh")}
            title={t("growth.refresh")}
            onClick={refresh}
          >
            <WorkspaceIcon name="refresh" />
          </button>
        </div>
      </div>
      {errors.growth && panel === "results" ? <ErrorNotice /> : null}
      {panel === "results" ? (
        <section className="helloada-growth-results-heading">
          <div>
            <h2>{t("growth.resultsTitle")}</h2>
            <p>{t("growth.resultsIntro")}</p>
          </div>
          <div className="helloada-growth-results-nav" role="tablist" aria-label={t("growth.resultsTitle")}>
            {(["analytics", "search", "competitionTab", "health", "content", "connections"] as const).map((view) => (
              <button
                key={view}
                type="button"
                role="tab"
                aria-selected={tab === view}
                onClick={() => navigateResultsTab(view)}
              >
                {t(`growth.${view}`)}
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {panel !== "results" && panel !== "budget" && errors.growth ? <div className="helloada-growth-error" role="alert">
        {t("growth.unavailable")} <button type="button" onClick={refresh}>{t("growth.retry")}</button>
      </div> : null}
      {panel !== "results" && panel !== "budget" && !errors.growth && growth ? (
        <GrowthTasks
          key={panel}
          mode={panel === "home" ? "home" : panel === "decisions" ? "decisions" : panel === "areas" ? "areas" : "work"}
          tasks={growth?.tasks}
          serviceModel={growth.serviceModel}
          decisionOrder={growth.decisionOrder}
          pending={loading.growth}
          refresh={refresh}
          ask={ask}
          date={date}
          goal={growth?.goal}
          brief={insight}
          onNavigate={navigatePanel}
        />
      ) : panel !== "results" && panel !== "budget" && loading.growth ? <div className="helloada-growth-empty" role="status">{t("growth.loading")}</div> : null}
      {panel === "budget" ? (
        <section className="helloada-growth-card" aria-labelledby="helloada-research-budget-title">
          <header><h2 id="helloada-research-budget-title">{t("growth.budgetTitle")}</h2></header>
          {budgetError ? <div className="helloada-growth-error" role="alert">{budgetError}</div> : null}
          {budget ? <>
            <p>Allowance for {budget.period} · {budget.currency} · {budget.timeZone}</p>
            <p>{t("growth.budgetCommitted")}: {budget.currency} {microsToAmount(budget.committedMicros)} · {t("growth.budgetReserved")}: {budget.currency} {microsToAmount(budget.reservedMicros)}{budget.remainingMicros !== null ? ` · ${t("growth.budgetRemaining")}: ${budget.currency} ${microsToAmount(budget.remainingMicros)}` : ""}</p>
            {!budget.configured ? <p>{t("growth.budgetNoAllowance")}</p> : null}
            <form onSubmit={saveBudget} className="helloada-growth-budget-form">
              <label htmlFor="helloada-research-budget-amount">{t("growth.budgetMonthlyAllowance")} ({budget.currency})</label>
              <input id="helloada-research-budget-amount" inputMode="decimal" required value={budgetAmount} onChange={(event) => setBudgetAmount(event.target.value)} placeholder={t("growth.budgetAmountHint")} />
              <label htmlFor="helloada-research-operation-budget">{t("growth.budgetOperationCeiling")} ({budget.currency})</label>
              <input id="helloada-research-operation-budget" inputMode="decimal" value={budgetOperationAmount} onChange={(event) => setBudgetOperationAmount(event.target.value)} placeholder={t("growth.budgetAmountHint")} />
              <small>{t("growth.budgetOperationCeilingNote")}</small>
              <label htmlFor="helloada-research-budget-timezone">{t("growth.budgetTimezone")}</label>
              <input id="helloada-research-budget-timezone" required maxLength={100} value={budget.timeZone} onChange={(event) => setBudget({ ...budget, timeZone: event.target.value })} placeholder={t("growth.budgetTimezoneHint")} />
              <button type="submit" disabled={budgetBusy}>{budgetBusy ? t("growth.budgetSaving") : t("growth.budgetSave")}</button>
            </form>
          </> : <p role="status">{t("growth.budgetLoading")}</p>}
          {researchPolicy ? <form onSubmit={saveResearchPolicy} className="helloada-growth-budget-form">
            <h3>{t("growth.policyTitle")}</h3>
            <label htmlFor="helloada-research-goals">{t("growth.policyGoals")}</label>
            <input id="helloada-research-goals" value={policyGoals} onChange={(event) => setPolicyGoals(event.target.value)} />
            <label htmlFor="helloada-research-exclusions">{t("growth.policyExclusions")}</label>
            <input id="helloada-research-exclusions" value={policyExclusions} onChange={(event) => setPolicyExclusions(event.target.value)} />
            <label htmlFor="helloada-research-recency">{t("growth.policyRecency")}</label>
            <input id="helloada-research-recency" type="number" min="1" max="3650" value={researchPolicy.recencyDays} onChange={(event) => setResearchPolicy({ ...researchPolicy, recencyDays: Number(event.target.value) })} />
            <label htmlFor="helloada-research-topics">{t("growth.policyTopics")}</label>
            <input id="helloada-research-topics" value={policyTopics} onChange={(event) => setPolicyTopics(event.target.value)} placeholder={t("growth.policyTopicsHint")} />
            <label htmlFor="helloada-research-audience">{t("growth.policyAudience")}</label>
            <input id="helloada-research-audience" value={researchPolicy.audience || ""} onChange={(event) => setResearchPolicy({ ...researchPolicy, audience: event.target.value || null })} />
            <label htmlFor="helloada-research-market">{t("growth.policyMarket")}</label>
            <input id="helloada-research-market" value={researchPolicy.market || ""} onChange={(event) => setResearchPolicy({ ...researchPolicy, market: event.target.value || null })} />
            <label htmlFor="helloada-research-language">{t("growth.policyLanguage")}</label>
            <input id="helloada-research-language" value={researchPolicy.language} onChange={(event) => setResearchPolicy({ ...researchPolicy, language: event.target.value })} required />
            <label htmlFor="helloada-research-cadence">{t("growth.policyCadence")}</label>
            <select id="helloada-research-cadence" value={researchPolicy.cadence} onChange={(event) => setResearchPolicy({ ...researchPolicy, cadence: event.target.value as ResearchPolicy["cadence"] })}>{["manual", "weekly", "monthly", "daily"].map((value) => <option key={value} value={value}>{t(`growth.policyCadence_${value}`)}</option>)}</select>
            <label htmlFor="helloada-research-providers">{t("growth.policyProviders")}</label>
            <select id="helloada-research-providers" multiple value={researchPolicy.providers} onChange={(event) => setResearchPolicy({ ...researchPolicy, providers: Array.from(event.target.selectedOptions, (option) => option.value as ResearchPolicy["providers"][number]) })}>{["reddit", "news", "web", "competitor"].map((value) => <option key={value} value={value}>{t(`growth.policyProvider_${value}`)}</option>)}</select>
            <label htmlFor="helloada-research-max-sources">{t("growth.policyMaxSources")}</label>
            <input id="helloada-research-max-sources" type="number" min="1" max="100" value={researchPolicy.maxSources} onChange={(event) => setResearchPolicy({ ...researchPolicy, maxSources: Number(event.target.value) })} />
            <label htmlFor="helloada-research-monthly-budget">{t("growth.policyMonthlyBudget")}</label>
            <input id="helloada-research-monthly-budget" type="number" min="0" max="500" value={researchPolicy.monthlyBudget} onChange={(event) => setResearchPolicy({ ...researchPolicy, monthlyBudget: Number(event.target.value) })} />
            <label><input type="checkbox" checked={researchPolicy.enabled} onChange={(event) => setResearchPolicy({ ...researchPolicy, enabled: event.target.checked })} />{t("growth.policyEnabled")}</label>
            <label><input type="checkbox" checked={researchPolicy.autoDraft} onChange={(event) => setResearchPolicy({ ...researchPolicy, autoDraft: event.target.checked })} />{t("growth.policyAutoDraft")}</label>
            <label><input type="checkbox" checked={researchPolicy.autoAgent} onChange={(event) => setResearchPolicy({ ...researchPolicy, autoAgent: event.target.checked })} />{t("growth.policyAutoAgent")}</label>
            <button type="submit" disabled={policyBusy || researchPolicy.providers.length === 0}>{policyBusy ? t("growth.budgetSaving") : t("growth.policySave")}</button>
          </form> : <p role="status">{t("growth.budgetLoading")}</p>}
        </section>
      ) : null}
      {panel === "results" && tab === "analytics" ? (
        <>
          {errors.analytics ? <ErrorNotice /> : null}
          <GrowthAnalytics
            data={analytics}
            pending={loading.analytics}
            days={days}
            ask={ask(t("growth.analyticsPrompt"))}
            retry={refresh}
          />
        </>
      ) : null}
      {panel === "results" && (tab === "search" || tab === "health") ? (
        <GrowthEvidence
          key={tab}
          section={tab === "search" ? "research" : "health"}
          revision={revision}
          ask={ask}
          seeds={growth?.keywords}
        />
      ) : null}
      {panel === "results" && tab === "competitionTab" ? <GrowthCompetition revision={revision} ask={ask} /> : null}
      {panel === "results" && tab === "content" ? (
        <>
          <div className="helloada-growth-content-bar">
            <span>{t("growth.approval")}</span>
            <Link href="/admin/collections/posts">
              {t("growth.openBlog")} ↗
            </Link>
          </div>
          <div className="helloada-growth-detail-grid">
            <Records
              title={t("growth.articles")}
              rows={growth?.articles}
              empty={t("growth.emptyArticles")}
            />
            <Records
              title={t("growth.ideas")}
              rows={growth?.articleIdeas}
              empty={t("growth.emptyResearch")}
            />
          </div>
          <Link
            className="helloada-growth-text-action"
            href="/admin?view=history"
          >
            {t("growth.activity")} ↗
          </Link>
        </>
      ) : null}
      {panel === "results" && tab === "connections" ? (
        <>
          <div className="helloada-growth-section-head">
            <h2>{t("growth.connections")}</h2>
            <Link href={ask(t("growth.setupPrompt"))}>
              {t("growth.setup")} ↗
            </Link>
          </div>
          <p className="helloada-growth-footnote">{t("growth.setupNote")}</p>
          <Sources />
        </>
      ) : null}
      {analytics?.capturedAt && panel === "results" && tab === "analytics" ? (
        <p className="helloada-growth-captured">
          {t("growth.updated")} {date(analytics.capturedAt)}
        </p>
      ) : null}
    </main>
  );
}

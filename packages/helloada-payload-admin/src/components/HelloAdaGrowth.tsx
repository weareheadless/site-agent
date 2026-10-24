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
type GrowthPanel = "home" | "decisions" | "work" | "results" | "areas";
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
    status: string;
    state?: string;
    reason?: string;
    property?: string;
    updatedAt?: string;
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
      {["ga4", "gsc", "dataforseo"].map((id) => {
        const source = growth?.sources?.find((item) => item.id === id);
        return (
          <article key={id} className="helloada-growth-source">
            <header>
              <h3>{t(`growth.${id}`)}</h3>
              <span
                className={`helloada-growth-state is-${source?.state || source?.status || "unknown"}`}
              >
                {source
                  ? source.state
                    ? t(`growth.state_${source.state}`)
                    : t(`growth.${source.status}`)
                  : loading.growth
                    ? "…"
                    : t("growth.noData")}
              </span>
            </header>
            <p>{t(`growth.${id}Note`)}</p>
            {source?.reason ? <small>{source.reason}</small> : null}
            {source?.property ? <small>{source.property}</small> : null}
            {source?.updatedAt ? (
              <small>
                {t("growth.updated")} {date(source.updatedAt)}
              </small>
            ) : null}
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
      {panel !== "results" && errors.growth ? <div className="helloada-growth-error" role="alert">
        {t("growth.unavailable")} <button type="button" onClick={refresh}>{t("growth.retry")}</button>
      </div> : null}
      {panel !== "results" && !errors.growth && growth ? (
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
      ) : panel !== "results" && loading.growth ? <div className="helloada-growth-empty" role="status">{t("growth.loading")}</div> : null}
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

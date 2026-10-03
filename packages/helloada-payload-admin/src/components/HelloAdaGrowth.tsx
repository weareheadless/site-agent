"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { type GrowthRow } from "../lib/growth-data";
import { HelloAdaChatMessage } from "./HelloAdaChatMessage";
import { HelloAdaMark } from "./HelloAdaLogo";
import { WorkspaceIcon } from "./WorkspaceIcon";
import {
  GrowthAnalytics,
  GrowthMetrics,
  type GrowthAnalyticsData,
} from "./GrowthAnalytics";
import { GrowthEvidence } from "./GrowthEvidence";
import { GrowthCompetition } from "./GrowthCompetition";
import { ProductAction } from "./ProductAction";

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
  sources?: Array<{
    id: string;
    status: string;
    state?: string;
    reason?: string;
    property?: string;
    updatedAt?: string;
  }>;
  activities?: Array<{ id: string; enabled: boolean; nextRun?: string }>;
  latestInsight?: Insight;
  insights?: Insight[];
  keywords?: GrowthRow[];
  keywordMetrics?: GrowthRow[];
  articles?: GrowthRow[];
  articleIdeas?: GrowthRow[];
  weeklyReports?: GrowthRow[];
  monthlyReports?: GrowthRow[];
  goal?: { objective?: string; goal_key?: string; revision?: number };
  work?: { state?: string; summaryKey?: string; nextRun?: string; latestRun?: { completed_ts?: string } };
  reviewQueue?: Array<{ id?: number; title?: string; summary?: string; action_label?: string; state?: string }>;
  results?: { state?: string; message?: string };
};

export function HelloAdaGrowth() {
  const { t, language } = useHelloAdaTranslations();
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState(28);
  const [revision, setRevision] = useState(0);
  const [growth, setGrowth] = useState<Growth>();
  const [analytics, setAnalytics] = useState<GrowthAnalyticsData>();
  const [errors, setErrors] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({
    growth: true,
    analytics: true,
  });
  const date = (value: unknown) => {
    const parsed = new Date(String(value ?? ""));
    return Number.isNaN(parsed.getTime())
      ? "—"
      : new Intl.DateTimeFormat(language, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(parsed);
  };
  const ask = (prompt = t("growth.askPrompt")) =>
    `/admin?ask=${encodeURIComponent(prompt)}`;
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
        if (!controller.signal.aborted) setGrowth(body);
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
  }, [days, revision]);
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
            {row.body || row.body_md ? (
              <HelloAdaChatMessage text={String(row.body || row.body_md)} />
            ) : (
              <p>
                {String(
                  (row.idea_json as GrowthRow | undefined)?.thesis ||
                    (row.idea_json as GrowthRow | undefined)?.rationale ||
                    row.focus_keyword ||
                    "",
                )}
              </p>
            )}
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
          {[
            "overview",
            "analytics",
            "search",
            "competitionTab",
            "health",
            "content",
            "connections",
          ].map((view) => (
            <button
              key={view}
              type="button"
              aria-pressed={tab === view}
              onClick={() => setTab(view)}
            >
              {t(`growth.${view}`)}
            </button>
          ))}
        </div>
        <div className="helloada-growth-controls">
          {tab === "overview" || tab === "analytics" ? (
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
      <div className="helloada-growth-work-strip" role="status" aria-live="polite">
        <span className={`helloada-growth-work-dot is-${growth?.work?.state || "unknown"}`} aria-hidden="true" />
        <div>
          <strong>{t("growth.background")}</strong>
          <span>
            {growth?.work?.summaryKey ? t(`growth.${growth.work.summaryKey}`) : loading.growth ? t("growth.loading") : t("growth.backgroundIdle")}
          </span>
        </div>
        <div className="helloada-growth-work-meta">
          {growth?.goal?.objective ? <small>{growth.goal.objective}</small> : null}
          {growth?.work?.nextRun ? <small>{t("growth.next")} {date(growth.work.nextRun)}</small> : null}
        </div>
        <ProductAction href={ask(t("growth.askPrompt"))}>
          {t("growth.reviewNow")}
        </ProductAction>
        <Link href={ask(t("growth.goalPrompt"))}>{t("growth.changeGoal")} ↗</Link>
      </div>
      {errors.growth ? <ErrorNotice /> : null}
      {tab === "overview" ? (
        <>
          <div className="helloada-growth-overview-grid">
            <section className="helloada-growth-card helloada-growth-advice">
              <header>
                <div className="helloada-growth-identity">
                  <HelloAdaMark size={28} />
                  <h2>{t("growth.recommendations")}</h2>
                </div>
                <ProductAction href={ask()}>{t("growth.ask")}</ProductAction>
              </header>
              <div className="helloada-growth-brief-meta">
                <span>{t("growth.briefNote")}</span>
                {insight?.ts ? (
                  <small>{date(insight.ts)}</small>
                ) : insight?.period ? (
                  <small>{insight.period}</small>
                ) : null}
              </div>
              {insight?.headline ? (
                <>
                  <h3>{insight.headline}</h3>
                  <HelloAdaChatMessage text={insight.summary_md || ""} />
                  {insight.opportunities?.map((item, index) => (
                    <div className="helloada-growth-recommendation" key={index}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <div>
                        <strong>{item.title}</strong>
                        <p>{item.rationale}</p>
                        {item.action ? (
                          <Link
                            href={ask(
                              `${item.title}. ${item.action}. ${t("growth.askPrompt")}`,
                            )}
                          >
                            {t("growth.ask")} ↗
                          </Link>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </>
              ) : (
                <p className="helloada-growth-empty">
                  {loading.growth
                    ? t("growth.loading")
                    : t("growth.noRecommendations")}
                </p>
              )}
            </section>
            <aside className="helloada-growth-side">
              <section className="helloada-growth-card">
                <header>
                  <h2>{t("growth.schedule")}</h2>
                </header>
                <div className="helloada-growth-plan">
                  {growth?.activities?.map((item) => (
                    <div key={item.id}>
                      <i className={item.enabled ? "is-enabled" : ""} />
                      <div>
                        <strong>{t(`growth.${item.id}`)}</strong>
                        <small>
                          {item.enabled
                            ? item.nextRun
                              ? `${t("growth.next")} ${date(item.nextRun)}`
                              : t("growth.scheduled")
                            : t("growth.notScheduled")}
                        </small>
                      </div>
                    </div>
                  )) || (
                    <p className="helloada-growth-empty">
                      {loading.growth
                        ? t("growth.loading")
                        : t("growth.noData")}
                    </p>
                  )}
                </div>
                <Link
                  className="helloada-growth-text-action"
                  href={ask(t("growth.schedulePrompt"))}
                >
                  {t("growth.manageSchedule")} ↗
                </Link>
                <p className="helloada-growth-footnote">
                  {t("growth.approval")}
                </p>
              </section>
              <section className="helloada-growth-card helloada-growth-review">
                <header>
                  <h2>{t("growth.readyForReview")}</h2>
                </header>
                <p>
                  {growth
                    ? `${growth.reviewQueue?.length || growth.articles?.filter((row) => row.status !== "published").length || 0} ${t("growth.reviewItems").toLocaleLowerCase(language)}`
                    : "—"}
                </p>
                <button type="button" onClick={() => setTab("content")}>
                  {t("growth.openContent")} ↗
                </button>
              </section>
            </aside>
          </div>
          <div className="helloada-growth-section-head">
            <h2>{t("growth.performance")}</h2>
            <button type="button" onClick={() => setTab("analytics")}>
              {t("growth.exploreData")} ↗
            </button>
          </div>
          {errors.analytics ? <ErrorNotice /> : null}
          <div className="helloada-growth-overview-metrics">
            <GrowthMetrics
              pending={loading.analytics}
              provider={analytics?.ga4}
              metrics={[
                ["activeUsers", t("growth.visitors")],
                ["sessions", t("growth.sessions")],
              ]}
            />
            <GrowthMetrics
              pending={loading.analytics}
              provider={analytics?.gsc}
              metrics={[
                ["clicks", t("growth.clicks")],
                ["impressions", t("growth.impressions")],
              ]}
            />
          </div>
          <p className="helloada-growth-footnote">
            {days} {t("growth.days")} · {t("growth.briefPeriodNote")}
          </p>
        </>
      ) : null}
      {tab === "analytics" ? (
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
      {tab === "search" || tab === "health" ? (
        <GrowthEvidence
          key={tab}
          section={tab === "search" ? "research" : "health"}
          revision={revision}
          ask={ask}
          seeds={growth?.keywords}
        />
      ) : null}
      {tab === "competitionTab" ? <GrowthCompetition revision={revision} ask={ask} /> : null}
      {tab === "content" ? (
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
            <Records
              title={t("growth.weeklyReports")}
              rows={growth?.weeklyReports}
              empty={t("growth.emptyReports")}
            />
            <Records
              title={t("growth.monthlyReports")}
              rows={growth?.monthlyReports}
              empty={t("growth.emptyReports")}
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
      {tab === "connections" ? (
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
      {analytics?.capturedAt && (tab === "overview" || tab === "analytics") ? (
        <p className="helloada-growth-captured">
          {t("growth.updated")} {date(analytics.capturedAt)}
        </p>
      ) : null}
    </main>
  );
}

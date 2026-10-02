"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { HelloAdaChatMessage } from "./HelloAdaChatMessage";
import { HelloAdaMark } from "./HelloAdaLogo";
import { WorkspaceIcon } from "./WorkspaceIcon";

type Row = Record<string, unknown>;
type Insight = {
  headline?: string;
  summary_md?: string;
  opportunities?: Array<{
    title?: string;
    rationale?: string;
    action?: string;
  }>;
  next_action?: string;
};
type Growth = {
  sources?: Array<{
    id: string;
    status: string;
    property?: string;
    updatedAt?: string;
  }>;
  activities?: Array<{ id: string; enabled: boolean; nextRun?: string }>;
  latestInsight?: Insight;
  keywords?: Row[];
  keywordMetrics?: Row[];
  articles?: Row[];
  articleIdeas?: Row[];
  weeklyReports?: Row[];
  monthlyReports?: Row[];
};
type Provider = {
  overview?: { current?: Row; deltaPct?: Row };
  trend?: Row[];
  pages?: Row[];
  channels?: Row[];
  queries?: Row[];
  devices?: Row[];
  countries?: Row[];
  events?: Row[];
};
type Analytics = {
  capturedAt?: string;
  ga4?: Provider;
  gsc?: Provider;
  errors?: Record<string, string>;
};
const text = (value: unknown) => (value == null ? "" : String(value));
const label = (value: string) =>
  value.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ");

export function HelloAdaGrowth() {
  const { t, language } = useHelloAdaTranslations();
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState(28);
  const [revision, setRevision] = useState(0);
  const [growth, setGrowth] = useState<Growth>();
  const [analytics, setAnalytics] = useState<Analytics>();
  const [errors, setErrors] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const format = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value)
      ? new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(
          value,
        )
      : "—";
  const date = (value: unknown) => {
    const parsed = new Date(text(value));
    return Number.isNaN(parsed.getTime())
      ? "—"
      : new Intl.DateTimeFormat(language, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(parsed);
  };
  const ask = (prompt = t("growth.askPrompt")) =>
    `/admin?ask=${encodeURIComponent(prompt)}`;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setErrors({});
    setAnalytics(undefined);
    setGrowth(undefined);
    const read = async (key: string, path: string) => {
      try {
        const response = await fetchHelloAda(path, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error("unavailable");
        const body = await response.json();
        if (!controller.signal.aborted) {
          if (key === "growth") setGrowth(body as Growth);
          else setAnalytics(body as Analytics);
        }
      } catch {
        if (!controller.signal.aborted)
          setErrors((current) => ({ ...current, [key]: true }));
      }
    };
    void Promise.all([
      read("growth", "/api/helloada/growth"),
      read("analytics", `/api/helloada/seo/analytics?days=${days}`),
    ]).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [days, revision]);
  const Empty = ({ children }: { children: string }) => (
    <p className="helloada-growth-empty">{children}</p>
  );
  const ErrorNotice = () => (
    <div className="helloada-growth-error" role="status">
      {t("growth.unavailable")}{" "}
      <button type="button" onClick={() => setRevision((value) => value + 1)}>
        {t("growth.retry")}
      </button>
    </div>
  );
  const Table = ({
    rows,
    columns,
    empty = t("growth.noData"),
  }: {
    rows?: Row[];
    columns: Array<[string, string]>;
    empty?: string;
  }) =>
    !rows?.length ? (
      <Empty>{empty}</Empty>
    ) : (
      <div className="helloada-growth-table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map(([key, title]) => (
                <th key={key} scope="col">
                  {title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map(([key]) => (
                  <td key={key}>
                    {typeof row[key] === "number"
                      ? format(row[key])
                      : text(row[key]) || "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  const ga = analytics?.ga4?.overview?.current;
  const gsc = analytics?.gsc?.overview?.current;
  const insight = growth?.latestInsight;
  const sources = ["ga4", "gsc", "dataforseo"];
  const Sources = () => (
    <div className="helloada-growth-sources">
      {sources.map((id) => {
        const source = growth?.sources?.find((item) => item.id === id);
        return (
          <article key={id} className="helloada-growth-source">
            <header>
              <h3>{t(`growth.${id}`)}</h3>
              <span
                className={`helloada-growth-state is-${source?.status || "unknown"}`}
              >
                {source
                  ? t(`growth.${source.status}`)
                  : errors.growth
                    ? t("growth.unavailable")
                    : loading
                      ? "…"
                      : t("growth.noData")}
              </span>
            </header>
            <p>{t(`growth.${id}Note`)}</p>
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
    rows?: Row[];
    empty: string;
  }) => (
    <section className="helloada-growth-card">
      <header>
        <h2>{title}</h2>
      </header>
      {rows?.length ? (
        rows.map((row) => (
          <details className="helloada-growth-record" key={text(row.id)}>
            <summary>
              <span>
                {text(
                  row.title ||
                    row.period ||
                    (row.idea_json as Row | undefined)?.working_title ||
                    (row.idea_json as Row | undefined)?.title ||
                    row.focus_keyword,
                )}
              </span>
              <small>{text(row.status)}</small>
            </summary>
            <small>{date(row.updated_ts || row.created_ts)}</small>
            {row.body || row.body_md ? (
              <HelloAdaChatMessage text={text(row.body || row.body_md)} />
            ) : (
              <p>
                {text(
                  (row.idea_json as Row | undefined)?.thesis ||
                    (row.idea_json as Row | undefined)?.rationale ||
                    row.focus_keyword,
                )}
              </p>
            )}
          </details>
        ))
      ) : (
        <Empty>{empty}</Empty>
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
          {["overview", "search", "content", "connections"].map((view) => (
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
          <select
            aria-label={t("growth.days")}
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            {[7, 28, 90].map((value) => (
              <option key={value} value={value}>
                {value} {t("growth.days")}
              </option>
            ))}
          </select>
          <button
            type="button"
            aria-label={t("growth.refresh")}
            title={t("growth.refresh")}
            onClick={() => setRevision((value) => value + 1)}
          >
            <WorkspaceIcon name="refresh" />
          </button>
        </div>
      </div>
      {errors.growth ? <ErrorNotice /> : null}
      {tab === "overview" ? (
        <>
          <div className="helloada-growth-metrics">
            {[
              ["visitors", ga?.activeUsers],
              ["sessions", ga?.sessions],
              ["clicks", gsc?.clicks],
              ["impressions", gsc?.impressions],
            ].map(([key, value]) => (
              <article key={text(key)}>
                <span>{t(`growth.${key}`)}</span>
                <strong>{loading && !analytics ? "…" : format(value)}</strong>
                <small>
                  {value === undefined
                    ? t("growth.noData")
                    : `${days} ${t("growth.days")}`}
                </small>
              </article>
            ))}
          </div>
          {errors.analytics ? <ErrorNotice /> : null}
          <div className="helloada-growth-overview-grid">
            <section className="helloada-growth-card helloada-growth-advice">
              <header>
                <div className="helloada-growth-identity">
                  <HelloAdaMark size={28} />
                  <h2>{t("growth.recommendations")}</h2>
                </div>
                <Link href={ask()}>
                  {t("growth.ask")}
                  <WorkspaceIcon name="arrow" size={16} />
                </Link>
              </header>
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
                            {t("growth.ask")}
                            <WorkspaceIcon name="arrow" size={14} />
                          </Link>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </>
              ) : (
                <Empty>{t("growth.noRecommendations")}</Empty>
              )}
            </section>
            <section className="helloada-growth-card">
              <header>
                <h2>{t("growth.schedule")}</h2>
              </header>
              <div className="helloada-growth-plan">
                {(
                  growth?.activities ||
                  ["article", "seo_insight", "weekly_report"].map((id) => ({
                    id,
                    enabled: false,
                    nextRun: undefined,
                  }))
                ).map((item) => (
                  <div key={item.id}>
                    <i className={item.enabled ? "is-enabled" : ""} />
                    <div>
                      <strong>{t(`growth.${item.id}`)}</strong>
                      <small>
                        {item.enabled
                          ? item.nextRun
                            ? `${t("growth.next")} ${date(item.nextRun)}`
                            : t("growth.scheduled")
                          : errors.growth || !growth
                            ? t("growth.noData")
                            : t("growth.notScheduled")}
                      </small>
                    </div>
                  </div>
                ))}
              </div>
              <Link
                className="helloada-growth-text-action"
                href={ask(t("growth.schedulePrompt"))}
              >
                {t("growth.manageSchedule")}
                <WorkspaceIcon name="arrow" size={16} />
              </Link>
              <p className="helloada-growth-footnote">{t("growth.approval")}</p>
            </section>
          </div>
          <Sources />
        </>
      ) : null}
      {tab === "search" ? (
        <>
          <div className="helloada-growth-detail-grid">
            <section className="helloada-growth-card">
              <header>
                <h2>{t("growth.queries")}</h2>
              </header>
              <Table
                rows={analytics?.gsc?.queries}
                columns={[
                  ["key", t("growth.keyword")],
                  ["clicks", t("growth.clicks")],
                  ["impressions", t("growth.impressions")],
                  ["position", t("growth.position")],
                ]}
              />
            </section>
            <section className="helloada-growth-card">
              <header>
                <h2>{t("growth.dataforseo")}</h2>
                <Link href={ask()}>
                  {t("growth.ask")}
                  <WorkspaceIcon name="arrow" size={16} />
                </Link>
              </header>
              <Table
                rows={growth?.keywordMetrics}
                columns={[
                  ["keyword", t("growth.keyword")],
                  ["search_volume", t("growth.volume")],
                  ["competition", t("growth.competition")],
                  ["cpc", "CPC"],
                ]}
                empty={t("growth.emptyResearch")}
              />
              <details className="helloada-growth-advanced">
                <summary>{t("growth.researched")}</summary>
                <Table
                  rows={growth?.keywords}
                  columns={[
                    ["keyword", t("growth.keyword")],
                    ["market", t("growth.market")],
                    ["research_count", t("growth.researched")],
                  ]}
                  empty={t("growth.emptyResearch")}
                />
              </details>
            </section>
          </div>
          {errors.analytics ? <ErrorNotice /> : null}
          <div className="helloada-growth-detail-grid">
            <section className="helloada-growth-card">
              <header>
                <h2>{t("growth.pages")}</h2>
              </header>
              <Table
                rows={analytics?.ga4?.pages}
                columns={[
                  ["landingPagePlusQueryString", t("growth.pages")],
                  ["sessions", t("growth.sessions")],
                  ["screenPageViews", "Views"],
                ]}
              />
            </section>
            <section className="helloada-growth-card">
              <header>
                <h2>{t("growth.channels")}</h2>
              </header>
              <Table
                rows={analytics?.ga4?.channels}
                columns={[
                  ["sessionDefaultChannelGroup", t("growth.channels")],
                  ["sessions", t("growth.sessions")],
                  ["activeUsers", t("growth.visitors")],
                ]}
              />
            </section>
          </div>
          <details className="helloada-growth-card helloada-growth-advanced">
            <summary>GA4 · GSC — {t("owner.advanced")}</summary>
            {[analytics?.ga4, analytics?.gsc].map((provider, index) => (
              <div key={index}>
                {(["devices", "countries", "events"] as const).map((key) =>
                  provider?.[key]?.length ? (
                    <section key={key}>
                      <h3>{label(key)}</h3>
                      <Table
                        rows={provider[key]}
                        columns={Object.keys(provider[key]![0]).map(
                          (column) => [column, label(column)],
                        )}
                      />
                    </section>
                  ) : null,
                )}
              </div>
            ))}
          </details>
        </>
      ) : null}
      {tab === "content" ? (
        <>
          <div className="helloada-growth-content-bar">
            <span>{t("growth.approval")}</span>
            <Link href="/admin/collections/posts">
              {t("growth.openBlog")}
              <WorkspaceIcon name="arrow" size={16} />
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
            {t("growth.activity")}
            <WorkspaceIcon name="arrow" size={16} />
          </Link>
        </>
      ) : null}
      {tab === "connections" ? (
        <>
          <section className="helloada-growth-card">
            <header>
              <h2>{t("growth.connections")}</h2>
              <Link href={ask(t("growth.setupPrompt"))}>
                {t("growth.setup")}
                <WorkspaceIcon name="arrow" size={16} />
              </Link>
            </header>
            <p className="helloada-growth-footnote">{t("growth.setupNote")}</p>
            <Sources />
          </section>
        </>
      ) : null}
      {analytics?.capturedAt ? (
        <p className="helloada-growth-captured">
          {t("growth.updated")} {date(analytics.capturedAt)}
        </p>
      ) : null}
    </main>
  );
}

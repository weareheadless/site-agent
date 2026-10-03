"use client";

import Link from "next/link";
import { useState } from "react";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { growthNumber, type GrowthRow } from "../lib/growth-data";
import { GrowthTable, GrowthTrend } from "./GrowthWidgets";

export type GrowthProvider = {
  available?: boolean;
  overview?: { current?: GrowthRow; deltaPct?: GrowthRow };
  trend?: GrowthRow[];
  pages?: GrowthRow[];
  channels?: GrowthRow[];
  queries?: GrowthRow[];
  devices?: GrowthRow[];
  countries?: GrowthRow[];
  events?: GrowthRow[];
};
export type GrowthAnalyticsData = {
  capturedAt?: string;
  window?: { startDate: string; endDate: string; days: number };
  entity?: { siteUrl?: string; gscProperty?: string; ga4PropertyId?: string };
  ga4?: GrowthProvider;
  gsc?: GrowthProvider;
  errors?: Record<string, string>;
};

export function GrowthMetrics({
  provider,
  metrics,
  pending = false,
}: {
  provider?: GrowthProvider;
  metrics: Array<[string, string]>;
  pending?: boolean;
}) {
  const { t, language } = useHelloAdaTranslations();
  return (
    <div className="helloada-growth-metrics">
      {metrics.map(([key, title]) => {
        const value = provider?.overview?.current?.[key],
          delta = provider?.overview?.deltaPct?.[key];
        const positive =
          typeof delta === "number" &&
          (key === "position" ? delta < 0 : delta > 0);
        return (
          <article key={key}>
            <span>{title}</span>
            <strong>
              {pending ? "…" : growthNumber(value, language, key)}
            </strong>
            <small
              className={
                typeof delta === "number" && delta !== 0
                  ? positive
                    ? "is-positive"
                    : "is-negative"
                  : ""
              }
            >
              {typeof delta === "number"
                ? `${delta > 0 ? "+" : ""}${growthNumber(delta, language)}%`
                : "—"}{" "}
              <span>{t("growth.vsPrevious")}</span>
            </small>
          </article>
        );
      })}
    </div>
  );
}

export function GrowthAnalytics({
  data,
  pending,
  days,
  ask,
  retry,
}: {
  data?: GrowthAnalyticsData;
  pending: boolean;
  days: number;
  ask: string;
  retry: () => void;
}) {
  const { t } = useHelloAdaTranslations();
  const [source, setSource] = useState<"ga4" | "gsc">("ga4");
  const [dimension, setDimension] = useState("pages");
  const [metric, setMetric] = useState("sessions");
  const ga = source === "ga4";
  const provider = data?.[source];
  const metrics: Array<[string, string]> = ga
    ? [
        ["activeUsers", t("growth.visitors")],
        ["sessions", t("growth.sessions")],
        ["screenPageViews", t("growth.views")],
        ["engagementRate", t("growth.engagement")],
      ]
    : [
        ["clicks", t("growth.clicks")],
        ["impressions", t("growth.impressions")],
        ["ctr", t("growth.ctr")],
        ["position", t("growth.position")],
      ];
  const dimensions = ga
    ? ["pages", "channels", "events", "devices", "countries", "history"]
    : ["queries", "pages", "devices", "countries", "history"];
  const currentDimension = dimensions.includes(dimension)
    ? dimension
    : dimensions[0];
  const trendMetrics = ga ? metrics.slice(0, 3) : metrics;
  const currentMetric = trendMetrics.some(([key]) => key === metric)
    ? metric
    : trendMetrics[0][0];
  const gaKey: Record<string, string> = {
    pages: "landingPagePlusQueryString",
    channels: "sessionDefaultChannelGroup",
    events: "eventName",
    devices: "deviceCategory",
    countries: "country",
    history: "date",
  };
  const firstKey = ga ? gaKey[currentDimension] : "key";
  const rows =
    currentDimension === "history"
      ? provider?.trend
      : (provider?.[currentDimension as keyof GrowthProvider] as
          | GrowthRow[]
          | undefined);
  const columns: Array<[string, string]> = [
    [
      firstKey,
      t(`growth.${currentDimension === "history" ? "date" : currentDimension}`),
    ],
    ...((ga
      ? currentDimension === "events"
        ? [["eventCount", t("growth.count")]]
        : currentDimension === "pages"
          ? [
              ["sessions", t("growth.sessions")],
              ["screenPageViews", t("growth.views")],
            ]
          : [
              ["sessions", t("growth.sessions")],
              ["activeUsers", t("growth.visitors")],
              ...(currentDimension === "channels"
                ? [["engagementRate", t("growth.engagement")]]
                : []),
            ]
      : [
          ["clicks", t("growth.clicks")],
          ["impressions", t("growth.impressions")],
          ["ctr", t("growth.ctr")],
          ["position", t("growth.position")],
        ]) as Array<[string, string]>),
  ];
  const failed = Object.keys(data?.errors || {}).filter((key) =>
    key.startsWith(`${source}.`),
  );
  return (
    <section aria-busy={pending}>
      <div className="helloada-growth-section-head">
        <div
          className="helloada-growth-segment"
          role="group"
          aria-label={t("growth.source")}
        >
          {(["ga4", "gsc"] as const).map((id) => (
            <button
              type="button"
              key={id}
              aria-pressed={source === id}
              onClick={() => setSource(id)}
            >
              {t(id === "ga4" ? "growth.trafficTab" : "growth.searchTab")}
              <small>{id.toUpperCase()}</small>
            </button>
          ))}
        </div>
        <Link href={ask}>
          {t("growth.interpretWithAda")} <span aria-hidden="true">↗</span>
        </Link>
      </div>
      <p className="helloada-growth-footnote">
        {t(ga ? "growth.ga4Note" : "growth.gscNote")} ·{" "}
        {data?.window
          ? `${data.window.startDate} — ${data.window.endDate}`
          : `${days} ${t("growth.days")}`}
      </p>
      {failed.length ? (
        <div className="helloada-growth-error" role="status">
          {t("growth.partialError")}{" "}
          <button type="button" onClick={retry}>
            {t("growth.retry")}
          </button>
          <details>
            <summary>{t("owner.advanced")}</summary>
            {failed.map((key) => (
              <p key={key}>
                {key}: {data?.errors?.[key]}
              </p>
            ))}
          </details>
        </div>
      ) : null}
      {provider?.available === false ? (
        <p className="helloada-growth-empty">{t("growth.not_configured")}</p>
      ) : null}
      <GrowthMetrics provider={provider} metrics={metrics} pending={pending} />
      {ga ? (
        <details className="helloada-growth-card helloada-growth-advanced">
          <summary>{t("growth.additionalMetrics")}</summary>
          <GrowthMetrics
            provider={provider}
            pending={pending}
            metrics={[
              ["newUsers", t("growth.newVisitors")],
              ["engagedSessions", t("growth.engagedVisits")],
              ["eventCount", t("growth.events")],
              ["averageSessionDuration", t("growth.averageDuration")],
            ]}
          />
        </details>
      ) : null}
      <section className="helloada-growth-card">
        <header>
          <h2>{t(ga ? "growth.ga4History" : "growth.gscHistory")}</h2>
          <select
            aria-label={t("growth.metric")}
            value={currentMetric}
            onChange={(event) => setMetric(event.target.value)}
          >
            {trendMetrics.map(([key, title]) => (
              <option value={key} key={key}>
                {title}
              </option>
            ))}
          </select>
        </header>
        {pending ? (
          <p className="helloada-growth-empty" role="status">
            {t("growth.loading")}
          </p>
        ) : data?.errors?.[`${source}.trend`] ? (
          <p className="helloada-growth-empty">{t("growth.unavailable")}</p>
        ) : (
          <GrowthTrend
            rows={provider?.trend}
            metric={currentMetric}
            dateKey={ga ? "date" : "key"}
            title={trendMetrics.find(([key]) => key === currentMetric)![1]}
          />
        )}
      </section>
      <section className="helloada-growth-card">
        <header>
          <h2>{t("growth.exploreData")}</h2>
          <select
            aria-label={t("growth.dimension")}
            value={currentDimension}
            onChange={(event) => setDimension(event.target.value)}
          >
            {dimensions.map((key) => (
              <option key={key} value={key}>
                {t(`growth.${key}`)}
              </option>
            ))}
          </select>
        </header>
        {pending ? (
          <p className="helloada-growth-empty" role="status">
            {t("growth.loading")}
          </p>
        ) : (
          <GrowthTable
            key={`${source}-${currentDimension}-${days}`}
            rows={rows}
            columns={columns}
            empty={
              data?.errors?.[
                `${source}.${currentDimension === "history" ? "trend" : currentDimension}`
              ]
                ? t("growth.unavailable")
                : undefined
            }
          />
        )}
        <p className="helloada-growth-footnote">{t("growth.coverage")}</p>
      </section>
    </section>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { growthNumber, type GrowthRow } from "../lib/growth-data";
import { GrowthTable } from "./GrowthWidgets";

type Evidence = {
  keywords?: GrowthRow[];
  domains?: GrowthRow[];
  backlinks?: GrowthRow[];
  reports?: GrowthRow[];
  updatedAt?: string;
  capturedAt?: string;
  period?: string;
  summary?: GrowthRow;
  issues?: GrowthRow[];
  errors?: Record<string, string>;
};

export function GrowthEvidence({
  section,
  revision,
  ask,
  seeds,
}: {
  section: "research" | "health";
  revision: number;
  ask: (prompt: string) => string;
  seeds?: GrowthRow[];
}) {
  const { t, language } = useHelloAdaTranslations();
  const [data, setData] = useState<Evidence>();
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<GrowthRow>();
  const [market, setMarket] = useState("");
  const [severity, setSeverity] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    setData(undefined);
    setSelected(undefined);
    void fetchHelloAda(`/api/helloada/seo/evidence?section=${section}`, {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("unavailable");
        const body = await response.json();
        if (!controller.signal.aborted) setData(body);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [section, revision, retry]);
  const failed = error || Object.keys(data?.errors || {}).length > 0;
  const markets = Array.from(
    new Set(
      (data?.keywords || []).map(
        (row) => `${row.language || "—"} · ${row.market || "—"}`,
      ),
    ),
  );
  const rows = (data?.keywords || []).filter(
    (row) =>
      !market || `${row.language || "—"} · ${row.market || "—"}` === market,
  );
  const selectedTrend = Array.isArray(selected?.trend)
    ? (selected.trend.filter((value) => typeof value === "number") as number[])
    : [];
  return (
    <div aria-busy={loading}>
      <div className="helloada-growth-section-head">
        <div>
          <h2>
            {t(
              section === "research"
                ? "growth.researchTitle"
                : "growth.healthTitle",
            )}
          </h2>
          <p>
            {t(
              section === "research"
                ? "growth.researchNote"
                : "growth.healthNote",
            )}
          </p>
        </div>
        <Link
          href={ask(
            t(
              section === "research"
                ? "growth.researchPrompt"
                : "growth.healthPrompt",
            ),
          )}
        >
          {t("growth.ask")} ↗
        </Link>
      </div>
      {loading ? (
        <p className="helloada-growth-empty" role="status">
          {t("growth.loading")}
        </p>
      ) : null}
      {failed ? (
        <div className="helloada-growth-error" role="status">
          {t(error ? "growth.unavailable" : "growth.partialError")}{" "}
          <button type="button" onClick={() => setRetry((value) => value + 1)}>
            {t("growth.retry")}
          </button>
          {data?.errors ? (
            <details>
              <summary>{t("owner.advanced")}</summary>
              {Object.entries(data.errors).map(([key, message]) => (
                <p key={key}>
                  {key}: {message}
                </p>
              ))}
            </details>
          ) : null}
        </div>
      ) : null}
      {!loading && !error && section === "research" ? (
        <>
          <section className="helloada-growth-card">
            <header>
              <div>
                <h2>{t("growth.keywordLibrary")}</h2>
                <small>
                  DataForSEO · {data?.period || "—"}{" "}
                  {data?.updatedAt ? `· ${data.updatedAt.slice(0, 10)}` : ""}
                </small>
              </div>
              <select
                aria-label={t("growth.market")}
                value={market}
                onChange={(event) => {
                  setMarket(event.target.value);
                  setSelected(undefined);
                }}
              >
                <option value="">{t("growth.allMarkets")}</option>
                {markets.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </header>
            <GrowthTable
              rows={rows}
              columns={[
                ["keyword", t("growth.keyword")],
                ["volume", t("growth.volume")],
                ["difficulty", t("growth.difficulty")],
                ["intent", t("growth.intent")],
                ["cpc", "CPC"],
                ["competition", t("growth.paidCompetition")],
                ["market", t("growth.market")],
              ]}
              empty={
                data?.errors?.report && data?.errors?.articleResearch
                  ? t("growth.unavailable")
                  : t("growth.emptyResearch")
              }
              onSelect={setSelected}
            />
            <p className="helloada-growth-footnote">{t("growth.metricNote")}</p>
          </section>
          {selected ? (
            <section className="helloada-growth-card helloada-keyword-detail">
              <header>
                <div>
                  <small>{t("growth.selectedKeyword")}</small>
                  <h2>{String(selected.keyword)}</h2>
                </div>
                <button
                  type="button"
                  aria-label={t("growth.closeDetail")}
                  onClick={() => setSelected(undefined)}
                >
                  ×
                </button>
              </header>
              <div className="helloada-keyword-meta">
                <span>
                  {String(selected.language || "—")} ·{" "}
                  {String(selected.market || "—")}
                </span>
                <span>
                  {t("growth.updated")}{" "}
                  {String(selected.updatedAt || "—").slice(0, 10)}
                </span>
              </div>
              {selectedTrend.length ? (
                <div className="helloada-keyword-trend">
                  <span>{t("growth.demandHistory")}</span>
                  <div>
                    {selectedTrend.map((volume, i) => (
                      <i
                        key={i}
                        style={{
                          height: `${Math.max(2, (volume / Math.max(...selectedTrend, 1)) * 48)}px`,
                        }}
                        title={`${i + 1}: ${growthNumber(volume, language)}`}
                      />
                    ))}
                  </div>
                  <small>{t("growth.demandNote")}</small>
                </div>
              ) : null}
              <Link
                href={ask(
                  `${t("growth.researchPrompt")}\n${JSON.stringify({ keyword: selected.keyword, language: selected.language, market: selected.market, source: selected.source, observedAt: selected.updatedAt })}`,
                )}
              >
                {t("growth.planKeyword")} ↗
              </Link>
            </section>
          ) : null}
          <div className="helloada-growth-detail-grid">
            <section className="helloada-growth-card">
              <header>
                <h2>{t("growth.competitorTitle")}</h2>
              </header>
              <GrowthTable
                rows={data?.domains}
                columns={[
                  ["domain", t("growth.domain")],
                  ["organicKeywords", t("growth.rankedKeywords")],
                  ["organicTraffic", t("growth.estimatedTraffic")],
                ]}
              />
              <p className="helloada-growth-footnote">
                {t("growth.estimateNote")}
              </p>
            </section>
            <section className="helloada-growth-card">
              <header>
                <h2>{t("growth.backlinksTitle")}</h2>
              </header>
              <GrowthTable
                rows={data?.backlinks}
                columns={[
                  ["domain", t("growth.domain")],
                  ["totalBacklinks", t("growth.links")],
                  ["referringDomains", t("growth.referringDomains")],
                  ["dofollow", "Dofollow"],
                  ["nofollow", "Nofollow"],
                ]}
              />
            </section>
          </div>
          <details className="helloada-growth-card helloada-growth-advanced">
            <summary>{t("growth.researchHistory")}</summary>
            <GrowthTable
              rows={data?.reports}
              columns={[
                ["period", t("growth.date")],
                ["status", t("growth.state")],
                ["task_count", t("growth.researched")],
              ]}
            />
            <h3>{t("growth.seeds")}</h3>
            <GrowthTable
              rows={seeds}
              columns={[
                ["keyword", t("growth.keyword")],
                ["language", t("growth.language")],
                ["market", t("growth.market")],
                ["research_count", t("growth.researched")],
              ]}
            />
          </details>
        </>
      ) : null}
      {!loading && !error && section === "health" ? (
        <>
          <div className="helloada-growth-metrics">
            {[
              ["health_score", t("growth.healthScore")],
              ["page_count", t("growth.crawledPages")],
              ["issue_count", t("growth.issues")],
            ].map(([key, title]) => (
              <article key={key}>
                <span>{title}</span>
                <strong>{growthNumber(data?.summary?.[key], language)}</strong>
                <small>
                  {data?.summary?.finished_at
                    ? String(data.summary.finished_at).slice(0, 10)
                    : t("growth.noCrawl")}
                </small>
              </article>
            ))}
          </div>
          <section className="helloada-growth-card">
            <header>
              <h2>{t("growth.issues")}</h2>
              <select
                aria-label={t("growth.severity")}
                value={severity}
                onChange={(event) => setSeverity(event.target.value)}
              >
                <option value="">{t("growth.allSeverities")}</option>
                {["CRITICAL", "WARNING", "INFO"].map((value) => (
                  <option key={value} value={value}>
                    {t(`growth.${value}`)}
                  </option>
                ))}
              </select>
            </header>
            <GrowthTable
              rows={(data?.issues || []).filter(
                (row) => !severity || row.severity === severity,
              )}
              columns={[
                ["severity", t("growth.severity")],
                ["type", t("growth.issueType")],
                ["url", t("growth.pages")],
                ["message", t("growth.description")],
              ]}
              empty={
                data?.errors?.issues
                  ? t("growth.unavailable")
                  : data?.summary?.status === "none"
                    ? t("growth.noCrawl")
                    : t("growth.noIssues")
              }
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

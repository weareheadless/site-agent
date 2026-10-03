"use client";

import { useEffect, useState } from "react";
import { fetchHelloAda } from "../api/fetchHelloAda";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import { HelloAdaMark } from "./HelloAdaLogo";
import { ProductAction } from "./ProductAction";

type Benchmark = { domain: string; isOwn: boolean; isSelected: boolean; organicKeywords: number | null; organicTraffic: number | null; referringDomains: number | null; totalBacklinks: number | null };
type Serp = { query: string; country?: string; language?: string; updatedAt?: string; ownPosition: number | null; organic: Array<{ rank: number | null; domain: string; title: string; url: string; isOwn: boolean }> };
type Evidence = { errors: Record<string, string>; benchmarks: Benchmark[]; selectedCompetitor?: string; period?: string; updatedAt?: string; market?: { language?: string; country?: string }; serps: Serp[]; rivals: Array<{ domain: string; country?: string; language?: string; appearances: number; bestPosition: number | null; queries: string[] }> };

export function GrowthCompetition({ revision, ask }: { revision: number; ask: (prompt: string) => string }) {
  const { t, language } = useHelloAdaTranslations();
  const [data, setData] = useState<Evidence>();
  const [pending, setPending] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [domain, setDomain] = useState("");
  const [query, setQuery] = useState(0);
  const [view, setView] = useState("benchmark");
  useEffect(() => {
    const controller = new AbortController();
    setPending(true); setFailed(false); setData(undefined);
    void fetchHelloAda("/api/helloada/seo/evidence?section=competition", { signal: controller.signal, cache: "no-store" })
      .then(async response => { if (!response.ok) throw new Error("unavailable"); const body = await response.json(); if (!controller.signal.aborted) { setData(body); setQuery(0); } })
      .catch(() => { if (!controller.signal.aborted) setFailed(true); })
      .finally(() => { if (!controller.signal.aborted) setPending(false); });
    return () => controller.abort();
  }, [revision, retry]);
  const number = (value: number | null | undefined) => value == null ? "—" : new Intl.NumberFormat(language, { maximumFractionDigits: 0 }).format(value);
  const market = (item?: { country?: string; language?: string }) => [item?.country, item?.language].filter(Boolean).join(" · ");
  const date = (value?: string) => value && !Number.isNaN(Date.parse(value)) ? new Intl.DateTimeFormat(language, { dateStyle: "medium" }).format(new Date(value)) : "—";
  const serp = data?.serps[query];
  const peers = data?.benchmarks.filter(row => row.isOwn || row.isSelected) ?? [];
  const prompt = `${t("growth.competitorPrompt")} ${domain.trim() ? `${t("growth.competitorDomain")}: ${domain.trim()}.` : data?.selectedCompetitor || ""}`;
  return <>
    <div className="helloada-growth-section-head"><div><h2>{t("growth.competitorTitle")}</h2><p>{t("growth.competitorIntro")}</p></div></div>
    <div className="helloada-competition-layout">
      <section className="helloada-growth-card">
        <div className="helloada-growth-segment" role="group" aria-label={t("growth.competitorTitle")}>
          {["benchmark", "rivals"].map(id => <button type="button" key={id} aria-pressed={view === id} onClick={() => setView(id)}>{t(`growth.${id}`)}</button>)}
        </div>
        {failed || Object.keys(data?.errors || {}).length ? <div className="helloada-growth-error" role="status">{t("growth.unavailable")} <button type="button" onClick={() => setRetry(value => value + 1)}>{t("growth.retry")}</button></div> : null}
        {pending ? <p className="helloada-growth-empty" role="status">{t("growth.loading")}</p> : null}
        {!pending && view === "benchmark" ? <>
          <div className="helloada-competition-meta"><span className="helloada-competition-market">{market(data?.market) || t("growth.marketUnspecified")}</span><small>{data?.period || "—"} · {date(data?.updatedAt)}</small></div>
          {peers.length ? <div className="helloada-competition-table-scroll"><table className="helloada-competition-benchmark"><thead><tr><th scope="col">{t("growth.metric")}</th>{peers.map(row => <th scope="col" key={row.domain} className={row.isOwn ? "is-own" : ""}>{row.domain}<small>{t(row.isOwn ? "growth.yourSite" : "growth.selectedCompetitor")}</small></th>)}</tr></thead><tbody>{(["organicKeywords", "organicTraffic", "referringDomains", "totalBacklinks"] as const).map(key => <tr key={key}><td>{t(`growth.${key}`)}</td>{peers.map(row => <td key={row.domain} className={row.isOwn ? "is-own" : ""}>{number(row[key])}</td>)}</tr>)}</tbody></table></div> : !failed && !data?.errors.report ? <div className="helloada-competition-empty"><span>01</span><h3>{t("growth.benchmarkEmpty")}</h3><p>{t("growth.benchmarkEmptyNote")}</p></div> : null}
          <p className="helloada-growth-footnote">{t("growth.competitorSource")}</p>
        </> : null}
        {!pending && view === "rivals" ? <>
          <p className="helloada-growth-footnote">{t("growth.rivalsNote")}</p>
          {data?.rivals.length ? <div className="helloada-competition-table-scroll"><table className="helloada-competition-benchmark"><thead><tr><th scope="col">{t("growth.domain")}</th><th scope="col">{t("growth.sampleAppearances")}</th><th scope="col">{t("growth.bestPosition")}</th></tr></thead><tbody>{data.rivals.slice(0, 20).map(row => <tr key={`${row.domain}-${row.country}-${row.language}`}><td>{row.domain}<small>{market(row)}</small></td><td>{number(row.appearances)}</td><td>{number(row.bestPosition)}</td></tr>)}</tbody></table></div> : !failed && !data?.errors.serps ? <div className="helloada-competition-empty"><span>02</span><h3>{t("growth.rivalsEmpty")}</h3><p>{t("growth.rivalsEmptyNote")}</p></div> : null}
        </> : null}
      </section>
      <aside className="helloada-competition-plan"><HelloAdaMark size={32}/><h3>{t("growth.competitorPlan")}</h3><p>{t("growth.competitorPlanNote")}</p><label htmlFor="helloada-competitor-domain">{t("growth.competitorDomain")}</label><input id="helloada-competitor-domain" value={domain} maxLength={253} onChange={event => setDomain(event.target.value)} placeholder={data?.selectedCompetitor || "example.com"}/><ProductAction href={ask(prompt)}>{t("growth.competitorAction")}</ProductAction><p className="helloada-growth-footnote">{t("growth.competitorApproval")}</p></aside>
    </div>
    {data?.serps.length ? <section className="helloada-growth-card helloada-competition-results"><header><div><h2>{t("growth.winningPages")}</h2><p>{t("growth.sampleNote")}</p></div><select aria-label={t("growth.keyword")} value={query} onChange={event => setQuery(Number(event.target.value))}>{data.serps.map((row, index) => <option key={`${row.query}-${row.country}-${row.language}`} value={index}>{row.query} · {market(row)}</option>)}</select></header><div className="helloada-competition-meta"><span className="helloada-competition-market">{market(serp)}</span><small>{date(serp?.updatedAt)} · {t("growth.yourPosition")}: {serp?.ownPosition == null ? t("growth.notInSample") : number(serp.ownPosition)}</small></div><ol className="helloada-serp-pages">{serp?.organic.map(row => <li className={row.isOwn ? "is-own" : ""} key={`${row.rank}-${row.url}`}><strong>{number(row.rank)}</strong><div><a href={row.url} target="_blank" rel="noopener noreferrer">{row.title || row.domain}</a><small>{row.domain}</small>{row.isOwn ? <em>{t("growth.yourSite")}</em> : null}</div></li>)}</ol><ProductAction href={ask(`${t("growth.serpPrompt")} ${serp?.query} (${market(serp)}).`)}>{t("growth.interpretWithAda")}</ProductAction></section> : null}
  </>;
}

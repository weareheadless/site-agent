"use client";

import { useId, useMemo, useState } from "react";
import { useHelloAdaTranslations } from "../api/useHelloAdaTranslations";
import {
  growthCSV,
  growthDate,
  growthNumber,
  growthSeries,
  type GrowthRow,
} from "../lib/growth-data";

export function GrowthTable({
  rows = [],
  columns,
  empty,
  onSelect,
}: {
  rows?: GrowthRow[];
  columns: Array<[string, string]>;
  empty?: string;
  onSelect?: (row: GrowthRow) => void;
}) {
  const { t, language } = useHelloAdaTranslations();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: string; desc: boolean }>();
  const [page, setPage] = useState(0);
  const filtered = useMemo(() => {
    const result = rows.filter((row) =>
      columns.some(([key]) =>
        String(row[key] ?? "")
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()),
      ),
    );
    if (sort)
      result.sort((a, b) => {
        const av = a[sort.key],
          bv = b[sort.key];
        if (av == null) return 1;
        if (bv == null) return -1;
        const cmp =
          typeof av === "number" && typeof bv === "number"
            ? av - bv
            : String(av).localeCompare(String(bv), language, { numeric: true });
        return sort.desc ? -cmp : cmp;
      });
    return result;
  }, [rows, columns, query, sort, language]);
  const pages = Math.max(1, Math.ceil(filtered.length / 10));
  const current = Math.min(page, pages - 1);
  const exportRows = () => {
    const url = URL.createObjectURL(
      new Blob(["\ufeff", growthCSV(filtered, columns)], {
        type: "text/csv;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "helloada-growth.csv";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  if (!rows.length)
    return (
      <p className="helloada-growth-empty">{empty || t("growth.noData")}</p>
    );
  return (
    <div className="helloada-data-table">
      <div className="helloada-table-tools">
        <input
          type="search"
          aria-label={t("growth.filter")}
          placeholder={t("growth.filter")}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(0);
          }}
        />
        <span>
          {filtered.length} {t("growth.rows")}
        </span>
        <button type="button" onClick={exportRows}>
          {t("growth.export")}
        </button>
      </div>
      <div className="helloada-growth-table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map(([key, title]) => (
                <th
                  key={key}
                  scope="col"
                  aria-sort={
                    sort?.key === key
                      ? sort.desc
                        ? "descending"
                        : "ascending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    onClick={() => {
                      setSort({
                        key,
                        desc:
                          sort?.key === key
                            ? !sort.desc
                            : typeof rows[0]?.[key] === "number",
                      });
                      setPage(0);
                    }}
                  >
                    {title}
                    <span aria-hidden="true">
                      {sort?.key === key ? (sort.desc ? "↓" : "↑") : "↕"}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered
              .slice(current * 10, (current + 1) * 10)
              .map((row, index) => (
                <tr key={index}>
                  {columns.map(([key], col) => (
                    <td key={key}>
                      {col === 0 && onSelect ? (
                        <button
                          className="helloada-table-detail"
                          type="button"
                          onClick={() => onSelect(row)}
                        >
                          {growthNumber(row[key], language, key)}
                        </button>
                      ) : col === 0 && !["date"].includes(key) && !/^\d{8}$/.test(String(row[key])) ? (
                        <span className="helloada-table-label" title={String(row[key] ?? "")}>
                          {growthNumber(row[key], language, key)}
                        </span>
                      ) : ["date", "key"].includes(key) &&
                        /^\d{8}$/.test(String(row[key])) ? (
                        growthDate(row[key])
                      ) : (
                        growthNumber(row[key], language, key)
                      )}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {!filtered.length ? (
        <p className="helloada-growth-empty">{t("growth.noMatches")}</p>
      ) : null}
      <div className="helloada-table-pagination">
        <span>
          {current + 1} / {pages}
        </span>
        <button
          type="button"
          disabled={current === 0}
          onClick={() => setPage(current - 1)}
          aria-label={t("growth.previous")}
        >
          ←
        </button>
        <button
          type="button"
          disabled={current >= pages - 1}
          onClick={() => setPage(current + 1)}
          aria-label={t("growth.nextPage")}
        >
          →
        </button>
      </div>
    </div>
  );
}

export function GrowthTrend({
  rows = [],
  metric,
  dateKey,
  title,
}: {
  rows?: GrowthRow[];
  metric: string;
  dateKey: string;
  title: string;
}) {
  const { t, language } = useHelloAdaTranslations();
  const id = useId().replace(/:/g, "");
  const series = useMemo(
    () => growthSeries(rows, metric, dateKey),
    [rows, metric, dateKey],
  );
  const [active, setActive] = useState<number>();
  if (!series.length)
    return <p className="helloada-growth-empty">{t("growth.noData")}</p>;
  const width = 900,
    height = 180,
    pad = 14;
  const start = Date.parse(series[0].date),
    end = Date.parse(series[series.length - 1].date);
  const max = Math.max(...series.map((point) => point.value), 1);
  const points = series.map((point) => ({
    ...point,
    x:
      end === start
        ? width / 2
        : pad +
          ((Date.parse(point.date) - start) / (end - start)) *
            (width - pad * 2),
    y: height - pad - (point.value / max) * (height - pad * 2),
  }));
  // Missing reporting dates stay gaps; they are never silently turned into zero.
  const path = points
    .map(
      (p, i) =>
        `${i === 0 || Date.parse(p.date) - Date.parse(points[i - 1].date) > 86400000 ? "M" : "L"}${p.x},${p.y}`,
    )
    .join(" ");
  const selected = active == null ? undefined : points[active];
  return (
    <div className="helloada-growth-chart">
      <div className="helloada-chart-caption">
        <span>{title} · 0–{growthNumber(max, language, metric)}</span>
        <strong aria-live="polite">
          {selected
            ? `${selected.date} · ${growthNumber(selected.value, language, metric)}`
            : t("growth.exploreChart")}
        </strong>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby={`${id}-title`}
        onMouseMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          const x = (event.clientX - bounds.left) / bounds.width * width;
          let nearest = 0;
          for (let i = 1; i < points.length; i++) {
            if (Math.abs(points[i].x - x) < Math.abs(points[nearest].x - x)) nearest = i;
          }
          setActive(nearest);
        }}
      >
        <title id={`${id}-title`}>
          {title} · {series[0].date} — {series[series.length - 1].date}
        </title>
        {[0, 0.5, 1].map((ratio) => (
          <line
            key={ratio}
            x1={pad}
            x2={width - pad}
            y1={pad + ratio * (height - pad * 2)}
            y2={pad + ratio * (height - pad * 2)}
            className="helloada-chart-grid"
          />
        ))}
        <path d={path} fill="none" className="helloada-chart-line" />
        {selected ? (
          <line
            x1={selected.x}
            x2={selected.x}
            y1={pad}
            y2={height - pad}
            className="helloada-chart-crosshair"
          />
        ) : null}
        {points.map((p, i) => (
          <circle
            key={p.date}
            cx={p.x}
            cy={p.y}
            r={active === i ? 5 : points.length === 1 ? 4 : 2}
            className="helloada-chart-point"
            tabIndex={i === (active ?? 0) ? 0 : -1}
            role="button"
            aria-label={`${p.date}: ${growthNumber(p.value, language, metric)}`}
            onFocus={() => setActive(i)}
            onMouseEnter={() => setActive(i)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                event.preventDefault();
                const next = Math.max(
                  0,
                  Math.min(
                    points.length - 1,
                    i + (event.key === "ArrowRight" ? 1 : -1),
                  ),
                );
                const sibling =
                  event.currentTarget.parentElement?.querySelectorAll("circle")[
                    next
                  ] as SVGElement | undefined;
                sibling?.focus();
              }
            }}
          >
            <title>
              {p.date}: {growthNumber(p.value, language, metric)}
            </title>
          </circle>
        ))}
      </svg>
      <div className="helloada-chart-axis">
        <span>{series[0].date}</span>
        <span>{t("growth.chartNote")}</span>
        <span>{series[series.length - 1].date}</span>
      </div>
    </div>
  );
}

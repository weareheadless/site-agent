export type GrowthRow = Record<string, unknown>;

export type GrowthActivity = { id: string; enabled: boolean; nextRun?: string | null };

export function growthPlan(activities: GrowthActivity[] = []) {
  const upcoming = activities.filter(item => item.enabled).sort((a, b) =>
    (a.nextRun || "9999").localeCompare(b.nextRun || "9999"));
  return {
    upcoming,
    unscheduled: activities.filter(item => !item.enabled),
    nextRun: upcoming.find(item => item.nextRun)?.nextRun || null,
  };
}

export function growthDate(value: unknown): string {
  const raw = String(value ?? "");
  return /^\d{8}$/.test(raw)
    ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6)}`
    : raw;
}

export function growthNumber(value: unknown, locale: string, key = ""): string {
  if (typeof value !== "number" || !Number.isFinite(value))
    return value == null ? "—" : String(value);
  if (["ctr", "engagementRate", "competition"].includes(key))
    return new Intl.NumberFormat(locale, {
      style: "percent",
      maximumFractionDigits: 1,
    }).format(value);
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: key === "cpc" ? 2 : 1,
  }).format(value);
}

export function growthSeries(
  rows: GrowthRow[],
  metric: string,
  dateKey: string,
) {
  return rows
    .map((row) => ({ date: growthDate(row[dateKey]), value: row[metric] }))
    .filter(
      (point): point is { date: string; value: number } =>
        /^\d{4}-\d{2}-\d{2}$/.test(point.date) &&
        Number.isFinite(Date.parse(point.date)) &&
        typeof point.value === "number" &&
        Number.isFinite(point.value),
    )
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function growthCSV(
  rows: GrowthRow[],
  columns: Array<[string, string]>,
): string {
  // Prevent formulas when owner-exported text is opened in a spreadsheet.
  const cell = (value: unknown) => {
    const raw = String(value ?? "");
    const safe = typeof value === "string" && /^[\s]*[=+@-]/.test(raw) ? `'${raw}` : raw;
    return `"${safe.replace(/"/g, '""')}"`;
  };
  return [
    columns.map(([, title]) => cell(title)).join(","),
    ...rows.map((row) => columns.map(([key]) => cell(row[key])).join(",")),
  ].join("\r\n");
}

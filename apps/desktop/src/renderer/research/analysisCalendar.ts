import type { JsonObject } from "../../../../../packages/contracts/src/research";

const rowDate = (row: JsonObject) => String(row.date ?? row.datetime ?? row.trade_date ?? "").slice(0, 10);
/** Calendar gaps stay null; never infer sessions from non-null factor results. */
export function analysisSessionRows(rows: JsonObject[], columns: string[], tradingDates: string[] | null): JsonObject[] {
  if (!rows.length) return [];
  if (tradingDates) {
    const dated = new Map(rows.map(row => [rowDate(row), row]));
    const dates = [...dated.keys()].filter(date => /^\d{4}-\d{2}-\d{2}$/.test(date)).sort();
    if (!dates.length) return rows;
    return [...new Set(tradingDates)].sort().filter(date => date >= dates[0] && date <= dates[dates.length - 1]).map(date => dated.get(date) ?? { date });
  }
  return rows.filter(row => {
    const day = new Date(`${rowDate(row)}T00:00:00Z`).getUTCDay();
    // Old experiments without a calendar: remove only certainly empty weekends.
    return ![0, 6].includes(day) || columns.some(key => typeof row[key] === "number" && Number.isFinite(row[key]));
  });
}

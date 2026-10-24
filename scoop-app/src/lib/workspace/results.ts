import type { ExecuteResult } from "@/lib/api";

/** Number of rows in a columnar result. */
export function rowCount(result: ExecuteResult): number {
  const first = result.columns[0];
  return first ? (result.data[first.name]?.length ?? 0) : 0;
}

/** Row-major slice of a columnar result for one page (0-based `page`). */
export function pageRows(
  result: ExecuteResult,
  page: number,
  pageSize: number,
): unknown[][] {
  const start = page * pageSize;
  const end = Math.min(start + pageSize, rowCount(result));
  const columns = result.columns.map((c) => result.data[c.name] ?? []);
  const rows: unknown[][] = [];
  for (let i = start; i < end; i++) {
    rows.push(columns.map((values) => values[i]));
  }
  return rows;
}

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

const MAX_CELL_CHARS = 200;

/** Display text for a cell; `full` is set when `text` was truncated. */
export function formatCell(value: unknown): {
  text: string;
  full?: string;
  isNull: boolean;
} {
  if (value === null || value === undefined) {
    return { text: "NULL", isNull: true };
  }
  const full =
    typeof value === "object" ? JSON.stringify(value) : String(value);
  if (full.length > MAX_CELL_CHARS) {
    return { text: `${full.slice(0, MAX_CELL_CHARS)}…`, full, isNull: false };
  }
  return { text: full, isNull: false };
}

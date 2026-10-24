import { toError, type ConnectorKind, type Query } from "@/lib/api";

/**
 * The editor's text for `query`. Unset fields come back from the API as null
 * and are dropped, except a literal's `value`, where null is SQL NULL.
 */
export function formatQuery(query: Query): string {
  return JSON.stringify(
    query,
    (key, value: unknown) =>
      value === null && key !== "value" ? undefined : value,
    2,
  );
}

/**
 * Parses editor text as a query AST. Only the outer shape is checked here;
 * the API validates the rest and reports what's wrong.
 */
export function parseQuery(
  text: string,
): { query: Query; error?: undefined } | { query?: undefined; error: string } {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (e) {
    return { error: toError(e).message };
  }
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !Array.isArray((value as { select?: unknown }).select)
  ) {
    return { error: "A query is a JSON object with a `select` array." };
  }
  return { query: value as Query };
}

export function isQuery(text: string): boolean {
  return parseQuery(text).query !== undefined;
}

/** SELECT * FROM `path`, optionally with a LIMIT. */
export function selectAll(path: string[], limit?: number): Query {
  return {
    select: [{ expr: { kind: "star" } }],
    from: { kind: "table", path },
    ...(limit === undefined ? {} : { limit }),
  };
}

/** SELECT count(*) FROM `path`. */
export function countRows(path: string[]): Query {
  return {
    select: [
      {
        expr: { kind: "call", name: "count", args: [{ kind: "star" }] },
        alias: "count",
      },
    ],
    from: { kind: "table", path },
  };
}

/** Quote an identifier for the connector's SQL dialect. */
function quoteIdent(name: string, kind?: ConnectorKind): string {
  if (kind === "mysql") return `\`${name.replaceAll("`", "``")}\``;
  return `"${name.replaceAll('"', '""')}"`;
}

/** A table path as the connector's SQL dialect would write it. */
export function qualifiedName(path: string[], kind?: ConnectorKind): string {
  return path.map((part) => quoteIdent(part, kind)).join(".");
}

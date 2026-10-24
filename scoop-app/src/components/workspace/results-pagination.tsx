"use client";

import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsLeftIcon,
  ChevronsRightIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
} from "@/components/ui/pagination";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { pageCount, rowCount } from "@/lib/workspace/results";
import { MAX_ROWS } from "@/lib/workspace/use-run-query";
import { PAGE_SIZES, useWorkspace, type Tab } from "@/lib/workspace/store";

const fmt = new Intl.NumberFormat();

/** Page indexes to show: first, last, and a window around the current page. */
function visiblePages(current: number, total: number): (number | "gap")[] {
  const pages = new Set([0, total - 1, current - 1, current, current + 1]);
  const sorted = [...pages]
    .filter((p) => p >= 0 && p < total)
    .sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push("gap");
    out.push(p);
  });
  return out;
}

function formatElapsed(ms: number) {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

export function ResultsPagination({ tab }: { tab: Tab }) {
  const { dispatch } = useWorkspace();
  const { run } = tab;
  const elapsed = run.elapsedMs !== undefined && (
    <span className="tabular-nums">{formatElapsed(run.elapsedMs)}</span>
  );

  if (run.status !== "done" || !run.result) {
    return (
      <div className="flex h-10 shrink-0 items-center gap-2 border-t px-3 text-xs text-muted-foreground">
        {run.status === "running" && "Running…"}
        {run.status === "error" && "Failed"}
        {run.status === "done" && "Done"}
        {run.status !== "running" && elapsed}
      </div>
    );
  }

  const total = rowCount(run.result);
  const pages = pageCount(total, run.pageSize);
  const page = Math.min(run.page, pages - 1);
  const first = total === 0 ? 0 : page * run.pageSize + 1;
  const last = Math.min((page + 1) * run.pageSize, total);
  const setPage = (p: number) =>
    dispatch({ type: "setPage", id: tab.id, page: p });

  return (
    <div className="flex h-10 shrink-0 items-center gap-3 border-t px-3 text-xs text-muted-foreground">
      <span className="tabular-nums">
        {fmt.format(first)}–{fmt.format(last)} of {fmt.format(total)} rows
      </span>
      {run.result.truncated && (
        <Badge
          variant="outline"
          className="border-amber-500/40 text-amber-700 dark:text-amber-400"
          title={`The query returned more than ${fmt.format(MAX_ROWS)} rows; only the first ${fmt.format(MAX_ROWS)} are shown. Add a LIMIT or WHERE clause to narrow it.`}
        >
          Truncated at {fmt.format(MAX_ROWS)}
        </Badge>
      )}
      {elapsed}

      <Pagination className="mx-0 ml-auto w-auto">
        <PaginationContent>
          <PaginationItem>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="First page"
              disabled={page === 0}
              onClick={() => setPage(0)}
            >
              <ChevronsLeftIcon />
            </Button>
          </PaginationItem>
          <PaginationItem>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Previous page"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              <ChevronLeftIcon />
            </Button>
          </PaginationItem>
          {visiblePages(page, pages).map((p, i) =>
            p === "gap" ? (
              <PaginationItem key={`gap-${i}`} className="hidden md:block">
                <PaginationEllipsis className="size-7" />
              </PaginationItem>
            ) : (
              <PaginationItem key={p} className="hidden md:block">
                <Button
                  variant={p === page ? "outline" : "ghost"}
                  size="sm"
                  className="min-w-7 px-1.5 tabular-nums"
                  aria-current={p === page ? "page" : undefined}
                  onClick={() => setPage(p)}
                >
                  {p + 1}
                </Button>
              </PaginationItem>
            ),
          )}
          <PaginationItem>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Next page"
              disabled={page >= pages - 1}
              onClick={() => setPage(page + 1)}
            >
              <ChevronRightIcon />
            </Button>
          </PaginationItem>
          <PaginationItem>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Last page"
              disabled={page >= pages - 1}
              onClick={() => setPage(pages - 1)}
            >
              <ChevronsRightIcon />
            </Button>
          </PaginationItem>
        </PaginationContent>
      </Pagination>

      <Select
        value={run.pageSize}
        onValueChange={(value) =>
          value !== null &&
          dispatch({ type: "setPageSize", id: tab.id, pageSize: Number(value) })
        }
      >
        <SelectTrigger size="sm" className="text-xs" aria-label="Rows per page">
          <SelectValue>{(value: number) => `${value} / page`}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {PAGE_SIZES.map((size) => (
            <SelectItem key={size} value={size}>
              {size} / page
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

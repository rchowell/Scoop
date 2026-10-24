"use client";

import * as React from "react";
import { TableIcon } from "lucide-react";

import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ExecuteResult } from "@/lib/api";
import { formatCell, pageRows, rowCount } from "@/lib/workspace/results";
import type { RunState } from "@/lib/workspace/store";

import { ProblemAlert } from "./problem-alert";

export function ResultsGrid({ run }: { run: RunState }) {
  if (run.status === "idle") {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <TableIcon />
          </EmptyMedia>
          <EmptyTitle>No results yet</EmptyTitle>
          <EmptyDescription>
            Write a query and press Run (⌘↵) to see results here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (run.status === "running") {
    return (
      <div className="flex flex-col gap-2 p-3" aria-busy>
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-6 w-full" />
        ))}
      </div>
    );
  }

  if (run.status === "error") {
    return (
      <div className="p-3">
        <ProblemAlert
          error={run.error ?? new Error("Unknown error")}
          fallbackTitle="Query failed"
          mono
        />
      </div>
    );
  }

  return (
    <ResultTable result={run.result!} page={run.page} pageSize={run.pageSize} />
  );
}

/** Memoized so typing in the editor doesn't re-render the grid. */
const ResultTable = React.memo(function ResultTable({
  result,
  page,
  pageSize,
}: {
  result: ExecuteResult;
  page: number;
  pageSize: number;
}) {
  const rows = pageRows(result, page, pageSize);
  const offset = page * pageSize;
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // Back to the top-left when paging.
  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [page, pageSize, result]);

  return (
    <div ref={scrollRef} className="h-full overflow-auto">
      <table className="w-max min-w-full caption-bottom border-separate border-spacing-0 text-sm">
        <TableHeader className="sticky top-0 z-10 bg-muted [&_tr]:border-b-0">
          <TableRow className="hover:bg-transparent">
            <TableHead className="sticky left-0 z-20 h-auto w-12 border-r border-b bg-muted px-2 py-1.5 text-right text-xs text-muted-foreground">
              #
            </TableHead>
            {result.columns.map((column) => (
              <TableHead
                key={column.name}
                className="h-auto border-r border-b px-2 py-1.5 align-top"
              >
                <div className="flex flex-col leading-tight">
                  <span className="text-xs font-semibold">{column.name}</span>
                  {column.type && (
                    <span className="font-mono text-[0.7rem] font-normal text-muted-foreground">
                      {column.type.toLowerCase()}
                    </span>
                  )}
                </div>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody className="font-mono text-xs">
          {rows.map((row, r) => (
            <TableRow key={offset + r} className="border-b-0">
              <TableCell className="sticky left-0 border-r border-b bg-background px-2 py-1 text-right text-muted-foreground tabular-nums">
                {offset + r + 1}
              </TableCell>
              {row.map((value, c) => {
                const cell = formatCell(value);
                return (
                  <TableCell
                    key={c}
                    title={cell.full}
                    className={
                      cell.isNull
                        ? "border-r border-b px-2 py-1 text-muted-foreground/60 italic"
                        : "max-w-md truncate border-r border-b px-2 py-1"
                    }
                  >
                    {cell.text}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
          {rowCount(result) === 0 && (
            <TableRow className="hover:bg-transparent">
              <TableCell
                colSpan={result.columns.length + 1}
                className="px-2 py-6 text-center font-sans text-muted-foreground"
              >
                No rows
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </table>
    </div>
  );
});

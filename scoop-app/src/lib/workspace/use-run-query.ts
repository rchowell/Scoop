"use client";

import * as React from "react";

import { toError, useExecuteConnectorQuery, type Query } from "@/lib/api";

import { newId, useWorkspace } from "./store";

/** Rows fetched per run; the grid pages through these client-side. */
export const MAX_ROWS = 10_000;

/**
 * Returns `run(tabId, connectorId, query)`, which executes `query` and stores the
 * outcome on the tab. Results live in the workspace store rather than in the
 * mutation hook, so each tab keeps its own result across tab switches.
 */
export function useRunQuery() {
  const { dispatch } = useWorkspace();
  const { trigger } = useExecuteConnectorQuery();

  return React.useCallback(
    async (tabId: string, connectorId: string, query: Query) => {
      const runId = newId();
      const started = performance.now();
      dispatch({ type: "runStarted", id: tabId, runId });
      try {
        const result = await trigger({
          id: connectorId,
          body: { query, max_rows: MAX_ROWS },
        });
        dispatch({
          type: "runSucceeded",
          id: tabId,
          runId,
          result,
          elapsedMs: performance.now() - started,
        });
      } catch (error) {
        dispatch({
          type: "runFailed",
          id: tabId,
          runId,
          error: toError(error),
          elapsedMs: performance.now() - started,
        });
      }
    },
    [dispatch, trigger],
  );
}

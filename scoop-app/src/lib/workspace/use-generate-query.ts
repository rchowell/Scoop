"use client";

import * as React from "react";

import { streamGenerate, toError, type Query } from "@/lib/api";

import { newId, useWorkspace } from "./store";

/** In-flight generations by tab id; module-level so they outlive tab switches. */
const controllers = new Map<string, AbortController>();

/**
 * Returns `generate(tabId, connectorId, prompt, context?)`, which has the query
 * assistant author a query for `prompt` while reporting progress on the tab, and
 * `cancel(tabId)`. `generate` resolves to the query, or undefined when the
 * request failed (the error is on the tab) or was cancelled.
 */
export function useGenerateQuery() {
  const { dispatch } = useWorkspace();

  const generate = React.useCallback(
    async (
      tabId: string,
      connectorId: string,
      prompt: string,
      context?: string,
    ): Promise<Query | undefined> => {
      controllers.get(tabId)?.abort();
      const controller = new AbortController();
      controllers.set(tabId, controller);
      const runId = newId();
      dispatch({ type: "assistStarted", id: tabId, runId });

      let query: Query | undefined;
      let error: string | undefined;
      try {
        await streamGenerate(
          connectorId,
          { prompt, context },
          {
            signal: controller.signal,
            onEvent: (event) => {
              if (event.type === "status") {
                dispatch({
                  type: "assistStep",
                  id: tabId,
                  runId,
                  step: event.message,
                });
              } else if (event.type === "query") {
                query = event.query;
              } else if (event.type === "error") {
                error = event.detail;
              }
            },
          },
        );
        if (query === undefined)
          error ??= "The assistant didn't return a query.";
      } catch (e) {
        if (!controller.signal.aborted) {
          error = toError(e).message;
        }
      } finally {
        if (controllers.get(tabId) === controller) controllers.delete(tabId);
      }

      if (controller.signal.aborted) {
        dispatch({ type: "assistFinished", id: tabId, runId });
        return undefined;
      }
      if (error !== undefined) {
        dispatch({ type: "assistFailed", id: tabId, runId, error });
        return undefined;
      }
      dispatch({ type: "assistFinished", id: tabId, runId });
      return query;
    },
    [dispatch],
  );

  const cancel = React.useCallback((tabId: string) => {
    controllers.get(tabId)?.abort();
  }, []);

  return { generate, cancel };
}

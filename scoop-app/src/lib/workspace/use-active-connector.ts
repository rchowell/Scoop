"use client";

import { useConnectors, type Connector } from "@/lib/api";

import { useActiveTab, useWorkspace } from "./store";

/** The API caps page_size at 200; enough for a switcher. */
const CONNECTOR_QUERY = { page_size: 200 };

export function useConnectorList() {
  return useConnectors(CONNECTOR_QUERY);
}

/**
 * Resolves the selected connector against the live list. A stored id that no
 * longer exists (deleted, or from an old session) falls back to the first one.
 */
export function useActiveConnector(): {
  connector: Connector | undefined;
  connectors: Connector[];
  isLoading: boolean;
  error: Error | undefined;
} {
  const { state } = useWorkspace();
  const { data, isLoading, error } = useConnectorList();
  const connectors = data?.items ?? [];
  const connector =
    connectors.find((c) => c.id === state.activeConnectorId) ?? connectors[0];
  return { connector, connectors, isLoading, error };
}

/**
 * The connector the active tab runs against. `stale` is set when the tab was
 * bound to a connector that no longer exists, and the active one is used.
 */
export function useTabConnector(): {
  connector: Connector | undefined;
  stale: boolean;
} {
  const tab = useActiveTab();
  const { connector: active, connectors, isLoading } = useActiveConnector();
  if (!tab.connectorId || isLoading) return { connector: active, stale: false };
  const bound = connectors.find((c) => c.id === tab.connectorId);
  return bound
    ? { connector: bound, stale: false }
    : { connector: active, stale: true };
}

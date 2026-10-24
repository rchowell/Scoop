import useSWR, { useSWRConfig, type SWRConfiguration } from "swr";
import useSWRMutation, { type SWRMutationConfiguration } from "swr/mutation";

import { api, unwrap, type ApiError } from "./client";
import type {
  ConnectorKindList,
  ConnectorPage,
  Connector,
  CreateConnector,
  ExecuteRequest,
  ExecuteResult,
  operations,
  Table,
  TableList,
  UpdateConnector,
} from "./schema";

type Query<Op extends keyof operations> = NonNullable<
  operations[Op]["parameters"]["query"]
>;

type ListConnectorsQuery = Query<"ListConnectors">;
type ListConnectorTablesQuery = Query<"ListConnectorTables">;

// ============================================================================
// Cache keys
// ============================================================================

/**
 * SWR keys are `[pathTemplate, params]`. Mutations invalidate by matching on
 * the path template prefix, so every key under `/v1/connectors` is refreshed
 * after a connector changes.
 */
const keys = {
  connectorKinds: () => ["/v1/connector-kinds"] as const,
  connectors: (query: ListConnectorsQuery = {}) =>
    ["/v1/connectors", query] as const,
  connectorTables: (id: string, query: ListConnectorTablesQuery = {}) =>
    ["/v1/connectors/{id}/tables", { id, ...query }] as const,
  connectorTable: (id: string, path: string[]) =>
    ["/v1/connectors/{id}/table", { id, path }] as const,
};

/**
 * Matches cached keys whose path starts with `prefix`. Given an `id`, keys for
 * other connectors are skipped; keys for no connector match unless `exact`.
 */
function matchKeys(prefix: string, id?: string, exact = false) {
  return (key: unknown) =>
    Array.isArray(key) &&
    typeof key[0] === "string" &&
    key[0].startsWith(prefix) &&
    (id === undefined ||
      (key[1]?.id === undefined ? !exact : key[1].id === id));
}

/** Returns a function that revalidates the keys `matchKeys(prefix, id)` matches. */
function useInvalidate() {
  const { mutate } = useSWRConfig();
  return (prefix: string, id?: string) => mutate(matchKeys(prefix, id));
}

// ============================================================================
// Connector kinds
// ============================================================================

/** GET /v1/connector-kinds */
export function useConnectorKinds(
  config?: SWRConfiguration<ConnectorKindList, ApiError>,
) {
  return useSWR<ConnectorKindList, ApiError>(
    keys.connectorKinds(),
    () => unwrap(api.GET("/v1/connector-kinds")),
    config,
  );
}

// ============================================================================
// Connectors
// ============================================================================

/** GET /v1/connectors */
export function useConnectors(
  query: ListConnectorsQuery = {},
  config?: SWRConfiguration<ConnectorPage, ApiError>,
) {
  return useSWR<ConnectorPage, ApiError>(
    keys.connectors(query),
    () => unwrap(api.GET("/v1/connectors", { params: { query } })),
    config,
  );
}

/** POST /v1/connectors */
export function useCreateConnector(
  config?: SWRMutationConfiguration<
    Connector,
    ApiError,
    string,
    CreateConnector
  >,
) {
  const invalidate = useInvalidate();
  return useSWRMutation<Connector, ApiError, string, CreateConnector>(
    "POST /v1/connectors",
    (_, { arg }) =>
      unwrap(api.POST("/v1/connectors", { body: arg })).then(async (data) => {
        await invalidate("/v1/connectors");
        return data;
      }),
    config,
  );
}

export type UpdateConnectorArg = { id: string; body: UpdateConnector };

/** PATCH /v1/connectors/{id} */
export function useUpdateConnector(
  config?: SWRMutationConfiguration<
    Connector,
    ApiError,
    string,
    UpdateConnectorArg
  >,
) {
  const invalidate = useInvalidate();
  return useSWRMutation<Connector, ApiError, string, UpdateConnectorArg>(
    "PATCH /v1/connectors/{id}",
    (_, { arg: { id, body } }) =>
      unwrap(
        api.PATCH("/v1/connectors/{id}", { params: { path: { id } }, body }),
      ).then(async (data) => {
        await invalidate("/v1/connectors", id);
        return data;
      }),
    config,
  );
}

export type DeleteConnectorArg = { id: string };

/** DELETE /v1/connectors/{id} */
export function useDeleteConnector(
  config?: SWRMutationConfiguration<void, ApiError, string, DeleteConnectorArg>,
) {
  const { mutate } = useSWRConfig();
  const invalidate = useInvalidate();
  return useSWRMutation<void, ApiError, string, DeleteConnectorArg>(
    "DELETE /v1/connectors/{id}",
    async (_, { arg: { id } }) => {
      await unwrap(
        api.DELETE("/v1/connectors/{id}", { params: { path: { id } } }),
      );
      // Drop the deleted connector's entries rather than refetching into a 404.
      await mutate(matchKeys("/v1/connectors/{id}", id, true), undefined, {
        revalidate: false,
      });
      await invalidate("/v1/connectors");
    },
    config,
  );
}

/** GET /v1/connectors/{id}/tables — pass `null` id to skip fetching. */
export function useConnectorTables(
  id: string | null | undefined,
  query: ListConnectorTablesQuery = {},
  config?: SWRConfiguration<TableList, ApiError>,
) {
  return useSWR<TableList, ApiError>(
    id ? keys.connectorTables(id, query) : null,
    () =>
      unwrap(
        api.GET("/v1/connectors/{id}/tables", {
          params: { path: { id: id! }, query },
        }),
      ),
    config,
  );
}

/** GET /v1/connectors/{id}/table — skips fetching until both `id` and a non-empty `path` are set. */
export function useConnectorTable(
  id: string | null | undefined,
  path: string[] | null | undefined,
  config?: SWRConfiguration<Table, ApiError>,
) {
  return useSWR<Table, ApiError>(
    id && path?.length ? keys.connectorTable(id, path) : null,
    () =>
      unwrap(
        api.GET("/v1/connectors/{id}/table", {
          params: { path: { id: id! }, query: { path: path! } },
        }),
      ),
    config,
  );
}

export type ExecuteConnectorQueryArg = { id: string; body: ExecuteRequest };

/**
 * POST /v1/connectors/{id}/execute
 *
 * A mutation rather than a query, so it runs only on `trigger()`.
 */
export function useExecuteConnectorQuery(
  config?: SWRMutationConfiguration<
    ExecuteResult,
    ApiError,
    string,
    ExecuteConnectorQueryArg
  >,
) {
  return useSWRMutation<
    ExecuteResult,
    ApiError,
    string,
    ExecuteConnectorQueryArg
  >(
    "POST /v1/connectors/{id}/execute",
    (_, { arg: { id, body } }) =>
      unwrap(
        api.POST("/v1/connectors/{id}/execute", {
          params: { path: { id } },
          body,
        }),
      ),
    config,
  );
}

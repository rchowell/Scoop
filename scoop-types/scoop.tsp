import "@typespec/http";
import "@typespec/openapi";
import "@typespec/rest";

using TypeSpec.Http;
using TypeSpec.Rest;
using TypeSpec.OpenAPI;

// ============================================================================
// Service
// ============================================================================

@service(#{ title: "Scoop" })
@server("http://localhost:8000", "Development")
@useAuth(BearerAuth)
namespace Scoop;

// ============================================================================
// Routes
// ============================================================================

@get
@route("/v1/health")
@doc("Service health check")
@useAuth(NoAuth)
op GetHealth(): Health;

@get
@route("/v1/connectors")
@doc("List connectors with pagination")
@list
op ListConnectors(
  @query
  @doc("Page number (1-indexed)")
  @minValue(1)
  page?: int32 = 1,

  @query
  @doc("Number of connectors per page")
  @minValue(1)
  @maxValue(200)
  page_size?: int32 = 50,
): Page<Connector> | ProblemDetail;

@get
@route("/v1/connections")
@doc("List available connector kinds and the options each one takes")
op ListConnectorKinds(): ConnectorKindList;

@get
@route("/v1/connectors/{id}")
@doc("Get a single connector")
op GetConnector(@path id: UUID): GetResponse<Connector>;

@post
@route("/v1/connectors")
@doc("Create a connector")
op CreateConnector(@body body: Create<Connector>): {
  @statusCode statusCode: 201;
  @body body: Connector;
} | ProblemDetail;

#suppress "@typespec/http/patch-implicit-optional" ""
@patch
@route("/v1/connectors/{id}")
@doc("Replace a connector's name and options; kind is immutable")
op UpdateConnector(
  @path id: UUID,
  @body body: Update<Connector>,
): Connector | ProblemDetail;

@delete
@route("/v1/connectors/{id}")
@doc("Delete a connector")
op DeleteConnector(@path id: UUID): NoContentResponse | ProblemDetail;

@get
@route("/v1/connectors/{id}/tables")
@doc("List tables and views whose path starts with `namespace`")
op ListConnectorTables(
  @path id: UUID,

  @query(#{ explode: true })
  @doc("Path prefix, one element per repeated param (e.g. ?namespace=main)")
  `namespace`?: string[],
): TableList | ProblemDetail;

@get
@route("/v1/connectors/{id}/table")
@doc("Describe a table or view")
op GetConnectorTable(
  @path id: UUID,

  @query(#{ explode: true })
  @doc("Table path, one element per repeated param (e.g. ?path=main&path=users)")
  path: string[],
): GetResponse<Table>;

@post
@route("/v1/connectors/{id}/execute")
@doc("Run a query and return up to `max_rows` rows in columnar form")
op ExecuteConnectorQuery(
  @path id: UUID,
  @body body: ExecuteRequest,
): ExecuteResult | ProblemDetail;

@post
@route("/v1/connectors/{id}/generate")
@doc("""
  Have an agent author a query for `prompt`, streaming progress as server-sent
  events. Each event's name is an AssistEvent `type` and its data is the JSON
  event: zero or more `status`, then `sql` and `done`, or `error`.
  """)
op GenerateConnectorQuery(
  @path id: UUID,
  @body body: GenerateRequest,
): {
  @header contentType: "text/event-stream";
  @body events: string;
} | ProblemDetail;

// ============================================================================
// Helpers
// ============================================================================

alias GetResponse<T> = {
  ...OkResponse;
  ...Body<T>;
} | {
  ...NotFoundResponse;
  ...ProblemDetail;
};

@doc("Paginated list response following RFC 8288 link relations")
@friendlyName("{name}Page", T)
model Page<T> {
  @pageItems
  @doc("Items in this page")
  items: T[];

  @doc("Pagination parameters")
  pagination: Pagination;
}

@doc("Pagination parameters following RFC 8288 link relations")
model Pagination {
  @query
  @doc("Page number (1-indexed)")
  @minValue(1)
  page?: int32 = 1;

  @query
  @doc("Number of items in this page, can be empty")
  @minValue(0)
  @maxValue(200)
  page_size?: int32 = 50;

  @nextLink
  @doc("Link to next page if one exists")
  next?: url;

  @prevLink
  @doc("Link to previous page if one exists")
  prev?: url;
}

// ============================================================================
// Errors
// ============================================================================

/**
 * RFC 9457 JSON Problem Details.
 *
 * Standard error response format for all API errors.
 */
@error
@doc("Standard error response format following RFC 9457 JSON Problem Details")
model ProblemDetail {
  @doc("A URI reference that identifies the problem type")
  type: url;

  @doc("A short, human-readable summary of the problem type")
  title: string;

  @doc("The HTTP status code for this occurrence of the problem")
  status: int32;

  @doc("A human-readable explanation specific to this occurrence of the problem")
  detail?: string;

  @doc("A URI reference that identifies the specific occurrence of the problem")
  instance?: url;
}

// ============================================================================
// Types
// ============================================================================

@format("uuid")
scalar UUID extends string;

scalar url extends string;

@doc("Service health status")
enum HealthStatus {
  Ok: "ok",
  Degraded: "degraded",
}

model Health {
  @doc("Overall service status")
  status: HealthStatus;

  @doc("Deployed service version")
  version: string;
}

@doc("Database backend a connector talks to")
enum ConnectorKind {
  Sqlite: "sqlite",
  DuckDB: "duckdb",
  Postgres: "postgres",
  MySQL: "mysql",
}

model Connector {
  @key
  @doc("Unique connector identifier")
  @visibility(Lifecycle.Read)
  id: UUID;

  @doc("Connector display name")
  @visibility(Lifecycle.Read, Lifecycle.Create, Lifecycle.Update)
  @maxLength(100)
  name: string;

  @doc("Database backend; immutable after creation")
  @visibility(Lifecycle.Read, Lifecycle.Create)
  kind: ConnectorKind;

  @doc("Kind-specific options; see GET /v1/connections")
  @visibility(Lifecycle.Read, Lifecycle.Create, Lifecycle.Update)
  options: Record<unknown>;

  @doc("Creation timestamp")
  @visibility(Lifecycle.Read)
  created_at: utcDateTime;
}

@doc("Value type of a connector option")
enum OptionType {
  String: "string",
  Integer: "integer",
  Boolean: "boolean",
}

@doc("Describes one option needed to instantiate a connector")
model ConnectorOption {
  @doc("Option key, as used in Connector.options")
  name: string;

  type: OptionType;

  @doc("Human-readable description")
  description: string;

  required: boolean;

  @doc("Value used when the option is omitted")
  default?: unknown;

  @doc("Whether the value is sensitive (e.g. a password) and should be masked in UIs")
  secret: boolean;
}

model ConnectorKindInfo {
  kind: ConnectorKind;

  @doc("Display name, e.g. \"PostgreSQL\"")
  name: string;

  @doc("Options in declaration order")
  options: ConnectorOption[];
}

model ConnectorKindList {
  kinds: ConnectorKindInfo[];
}

model Column {
  @doc("Column name, de-duplicated within a result (a, a -> a, a_1)")
  name: string;

  @doc("Backend-native type name; null when the backend can't say")
  type: string | null;

  @doc("Whether the column accepts nulls; null when unknown")
  nullable?: boolean | null;
}

model Table {
  @doc("Hierarchical table identifier, e.g. [\"main\", \"users\"]")
  path: string[];

  @doc("Whether this is a table or a view")
  kind: "table" | "view";

  columns: Column[];
}

model TableList {
  @doc("Table paths")
  tables: string[][];
}

model ExecuteRequest {
  @doc("SQL to run")
  query: string;

  @doc("DB-API parameters: an array for positional, an object for named")
  params?: unknown[] | Record<unknown>;

  @doc("Maximum rows to return")
  @minValue(1)
  @maxValue(10000)
  max_rows?: int32 = 1000;
}

model ExecuteResult {
  columns: Column[];

  @doc("Columnar rows: {column_name: [values...]}")
  data: Record<unknown[]>;

  @doc("True if the query produced more than max_rows rows")
  truncated: boolean;
}

model GenerateRequest {
  @doc("What the query should do, in plain language")
  @minLength(1)
  prompt: string;

  @doc("The editor's full text, so the agent can refine an existing query")
  context?: string;
}

@doc("A progress step, e.g. \"Describing main.trips…\"")
model AssistStatusEvent {
  type: "status";
  message: string;
}

@doc("The authored query")
model AssistSqlEvent {
  type: "sql";
  sql: string;
}

@doc("The agent failed; no query was authored")
model AssistErrorEvent {
  type: "error";
  detail: string;
}

@doc("The stream is complete")
model AssistDoneEvent {
  type: "done";
}

@discriminated(#{ envelope: "none", discriminatorPropertyName: "type" })
union AssistEvent {
  status: AssistStatusEvent,
  sql: AssistSqlEvent,
  error: AssistErrorEvent,
  done: AssistDoneEvent,
}

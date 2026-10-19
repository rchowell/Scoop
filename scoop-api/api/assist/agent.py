"""An agent that authors a SQL query from a plain-language request.

Claude explores the connector through a few tools (list tables, describe a
table, sample a query) and finishes by calling `submit_query` with a query AST.
Progress is reported as AssistEvents for the client to stream.

The AST is recursive, which strict structured outputs can't express, so the
query tools carry its JSON Schema without `strict` and validate input here,
returning the errors to Claude to fix. The other tools are strict.
"""

import json
from collections.abc import Iterator
from typing import Annotated, Any

import anthropic
from anthropic import beta_tool
from fastapi import Depends
from pydantic import BaseModel, ValidationError

from api.assist.sample import run_sample
from api.config import Settings, get_settings
from api.connector import Connector, TableNotFoundError, TablePath
from api.problem import Problem
from api.query import CLIENT_ERRORS
from models import (
    AssistDoneEvent,
    AssistErrorEvent,
    AssistQueryEvent,
    AssistStatusEvent,
    Query,
)

AssistEvent = AssistStatusEvent | AssistQueryEvent | AssistErrorEvent | AssistDoneEvent

MAX_TURNS = 15
MAX_LISTED_TABLES = 500
# Below this many tables, the whole list goes in the first message to save a round trip.
MAX_SEEDED_TABLES = 200
SAMPLE_ROWS = 20

SYSTEM_PROMPT = """\
You write queries for a database query editor. The user describes what they \
want in plain language; you write one query that does it.

A query is a JSON syntax tree (the `query` argument of run_query and \
submit_query), which is rendered to SQL for the database. Every expression and \
row source has a `kind`. Table paths have one element per part, as in the \
table list (e.g. ["main", "trips"]); column paths are [column] or \
[table_alias, column]. Literals are bound as parameters, so write values \
as-is with no quoting.

The request comes with the SQL dialect, the database's tables (or how many \
there are), and possibly the editor's current query as JSON. If it does, the \
request is asking you to change that query; keep what still applies.

Work like this:
- Inspect the tables you plan to use with describe_table before writing a \
query. Never guess column names or types.
- When the query depends on actual values (category spellings, date formats, \
units), check them with run_query. Keep sample queries small.
- Function names and cast types are passed through to the database, so use \
ones the dialect supports.
- Write what the user asked for. Include an ORDER BY or LIMIT only when the \
request implies one. Give computed columns clear aliases.
- Finish by calling submit_query with the final query. It replaces the \
request in the editor and is the only output the user sees.
"""


def _strict_defs(defs: dict[str, Any]) -> dict[str, Any]:
    """Close every object in the AST's $defs and require discriminator tags."""
    out = {}
    for name, schema in defs.items():
        # `discriminator` is OpenAPI, not JSON Schema; the required `kind` const does its job.
        schema = {
            k: v for k, v in schema.items() if k not in ("title", "discriminator")
        }
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
            tags = [k for k, p in schema["properties"].items() if "const" in p]
            schema["required"] = [*tags, *schema.get("required", [])]
        out[name] = schema
    return out


QUERY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"$ref": "#/$defs/Query"}},
    "required": ["query"],
    "additionalProperties": False,
    "$defs": _strict_defs(Query.model_json_schema(by_alias=True)["$defs"]),
}


def _unknown_fields(node: Any, loc: str = "query") -> Iterator[str]:
    # The generated models allow extra fields, which would silently drop a typo.
    if isinstance(node, BaseModel):
        for key in node.model_extra or {}:
            yield f"{loc}.{key}: unknown field"
        for name, field in type(node).model_fields.items():
            yield from _unknown_fields(
                getattr(node, name), f"{loc}.{field.alias or name}"
            )
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _unknown_fields(item, f"{loc}[{i}]")


def _path(path: TablePath) -> str:
    return ".".join(path)


class QueryToolkit:
    """The agent's tools, as plain methods over one connector."""

    def __init__(self, connector: Connector, dialect: str) -> None:
        self.connector = connector
        self.dialect = dialect
        self.final_query: Query | None = None

    def parse_query(self, raw: Any) -> Query | str:
        """The validated query, or a description of what's wrong with it."""
        try:
            query = Query.model_validate(raw)
        except ValidationError as e:
            return "\n".join(
                f"{'.'.join(map(str, ('query', *err['loc'])))}: {err['msg']}"
                for err in e.errors(include_url=False)
            )
        if unknown := list(_unknown_fields(query)):
            return "\n".join(unknown)
        try:
            self.connector.dialect.compile(query)
        except ValueError as e:
            return str(e)
        return query

    def list_tables(self, namespace: list[str] | None = None) -> str:
        try:
            paths = self.connector.list_tables(tuple(namespace or ()))
        except CLIENT_ERRORS as e:
            return f"Error: {e}"
        lines = [_path(p) for p in paths[:MAX_LISTED_TABLES]]
        if len(paths) > MAX_LISTED_TABLES:
            lines.append(
                f"... {len(paths) - MAX_LISTED_TABLES} more; pass a namespace to narrow the list"
            )
        return "\n".join(lines) or "No tables."

    def describe_table(self, path: list[str]) -> str:
        try:
            table = self.connector.get_table(tuple(path))
        except TableNotFoundError:
            return f"Error: no table {_path(tuple(path))}. Use list_tables to find it."
        except CLIENT_ERRORS as e:
            return f"Error: {e}"
        return json.dumps(
            {
                "path": list(table.path),
                "kind": table.kind,
                "columns": [
                    {"name": c.name, "type": c.type, "nullable": c.nullable}
                    for c in table.columns
                ],
            }
        )

    def run_query(self, query: Any) -> str:
        parsed = self.parse_query(query)
        if isinstance(parsed, str):
            return f"Error: invalid query:\n{parsed}"
        try:
            sample = run_sample(self.connector, parsed, SAMPLE_ROWS)
        except CLIENT_ERRORS as e:
            return f"Error: {e}"
        return json.dumps(
            {
                "columns": [c.name for c in sample.columns],
                "rows": sample.rows,
                "truncated": sample.truncated,
            },
            default=str,
        )

    def submit_query(self, query: Any) -> str:
        parsed = self.parse_query(query)
        if isinstance(parsed, str):
            return (
                f"Not accepted:\n{parsed}\nFix the query and call submit_query again."
            )
        try:
            # Run it for no rows so unknown tables and columns are caught here.
            with self.connector.execute(parsed.model_copy(update={"limit": 0})):
                pass
        except CLIENT_ERRORS as e:
            return f"Not accepted: {e}. Fix the query and call submit_query again."
        self.final_query = parsed
        return "Accepted."

    def tools(self) -> list[Any]:
        @beta_tool(strict=True)
        def list_tables(namespace: list[str] | None = None) -> str:
            """List tables and views, one dotted path per line.

            Args:
                namespace: Only list tables under this path prefix, e.g. ["main"].
            """
            return self.list_tables(namespace)

        @beta_tool(strict=True)
        def describe_table(path: list[str]) -> str:
            """Get a table's kind and its columns' names, types and nullability.

            Args:
                path: The table's path, one element per part, e.g. ["main", "trips"].
            """
            return self.describe_table(path)

        @beta_tool(input_schema=QUERY_INPUT_SCHEMA)
        def run_query(query: dict[str, Any]) -> str:
            """Run a query and get at most 20 rows back.

            Use it to look at real values; long text values are clipped.
            """
            return self.run_query(query)

        @beta_tool(input_schema=QUERY_INPUT_SCHEMA)
        def submit_query(query: dict[str, Any]) -> str:
            """Submit the finished query; it replaces the user's request in the editor."""
            return self.submit_query(query)

        return [list_tables, describe_table, run_query, submit_query]


def step_label(name: str, input: dict[str, Any]) -> str:
    """A short, human-readable description of a tool call."""
    match name:
        case "list_tables":
            namespace = input.get("namespace")
            return (
                f"Listing tables in {'.'.join(namespace)}…"
                if namespace
                else "Listing tables…"
            )
        case "describe_table":
            return f"Reading {'.'.join(input.get('path') or [])}…"
        case "run_query":
            return "Sampling data…"
        case "submit_query":
            return "Checking the query…"
    return "Working…"


def _first_message(toolkit: QueryToolkit, prompt: str, context: str | None) -> str:
    try:
        paths = toolkit.connector.list_tables()
    except CLIENT_ERRORS:
        paths = None
    if paths is None:
        tables = "Unknown; use list_tables."
    elif len(paths) <= MAX_SEEDED_TABLES:
        tables = "\n".join(_path(p) for p in paths) or "None."
    else:
        tables = f"{len(paths)} tables; use list_tables with a namespace to browse."
    parts = [
        f"<dialect>{toolkit.dialect}</dialect>",
        f"<tables>\n{tables}\n</tables>",
    ]
    if context and context.strip() != prompt.strip():
        # The editor's query AST as JSON, minus the request.
        parts.append(f"<editor>\n{context}\n</editor>")
    parts.append(f"<request>\n{prompt}\n</request>")
    return "\n\n".join(parts)


class QueryAgent:
    def __init__(self, client: anthropic.Anthropic, model: str) -> None:
        self.client = client
        self.model = model

    def generate(
        self,
        connector: Connector,
        dialect: str,
        prompt: str,
        context: str | None = None,
    ) -> Iterator[AssistEvent]:
        toolkit = QueryToolkit(connector, dialect)
        try:
            yield from self._run(toolkit, prompt, context)
        except anthropic.AuthenticationError:
            yield AssistErrorEvent(
                type="error", detail="ANTHROPIC_API_KEY was rejected."
            )
        except anthropic.RateLimitError:
            yield AssistErrorEvent(
                type="error",
                detail="Rate limited by the Claude API; try again shortly.",
            )
        except anthropic.APIStatusError as e:
            yield AssistErrorEvent(
                type="error", detail=f"Claude API error ({e.status_code}): {e.message}"
            )
        except anthropic.APIConnectionError:
            yield AssistErrorEvent(
                type="error", detail="Couldn't reach the Claude API."
            )

    def _run(
        self, toolkit: QueryToolkit, prompt: str, context: str | None
    ) -> Iterator[AssistEvent]:
        runner = self.client.beta.messages.tool_runner(
            model=self.model,
            max_tokens=16000,
            max_iterations=MAX_TURNS,
            system=SYSTEM_PROMPT,
            tools=toolkit.tools(),
            messages=[
                {"role": "user", "content": _first_message(toolkit, prompt, context)}
            ],
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},
            # On a safety refusal, retry on a fallback model instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        for message in runner:
            if message.stop_reason == "refusal":
                yield AssistErrorEvent(
                    type="error", detail="Claude declined to write this query."
                )
                return
            for block in message.content:
                if block.type == "tool_use":
                    yield AssistStatusEvent(
                        type="status", message=step_label(block.name, block.input)
                    )
            # Run this turn's tools now (the runner reuses the result) so we can
            # stop as soon as a query is accepted, without another model turn.
            runner.generate_tool_call_response()
            if toolkit.final_query is not None:
                yield AssistQueryEvent(type="query", query=toolkit.final_query)
                yield AssistDoneEvent(type="done")
                return
        yield AssistErrorEvent(
            type="error", detail="The assistant stopped without writing a query."
        )


def get_query_agent(
    settings: Annotated[Settings, Depends(get_settings)],
) -> QueryAgent:
    if not settings.anthropic_api_key:
        raise Problem(503, "Assistant Unavailable", "ANTHROPIC_API_KEY is not set.")
    return QueryAgent(
        anthropic.Anthropic(api_key=settings.anthropic_api_key),
        settings.assist_model,
    )


QueryAgentDep = Annotated[QueryAgent, Depends(get_query_agent)]

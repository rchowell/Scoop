"""An agent that authors a SQL query from a plain-language request.

Claude explores the connector through a few tools (list tables, describe a
table, run a small read-only sample) and finishes by calling `submit_query`.
Progress is reported as AssistEvents for the client to stream.
"""

import json
from collections.abc import Iterator
from typing import Annotated, Any

import anthropic
from anthropic import beta_tool
from fastapi import Depends
from sqlglot.errors import ParseError

from api.assist.readonly import NotReadOnlyError, parse_one, run_read_only
from api.config import Settings, get_settings
from api.connector import Connector, TableNotFoundError, TablePath
from api.problem import Problem
from api.query import CLIENT_ERRORS
from models import (
    AssistDoneEvent,
    AssistErrorEvent,
    AssistSqlEvent,
    AssistStatusEvent,
)

AssistEvent = AssistStatusEvent | AssistSqlEvent | AssistErrorEvent | AssistDoneEvent

MAX_TURNS = 15
MAX_LISTED_TABLES = 500
# Below this many tables, the whole list goes in the first message to save a round trip.
MAX_SEEDED_TABLES = 200
SAMPLE_ROWS = 20

SYSTEM_PROMPT = """\
You write SQL for a database query editor. The user describes what they want \
in plain language; you write one query that does it.

The request comes with the SQL dialect, the database's tables (or how many \
there are), and the editor's current text. If the editor already holds a \
query, the request may be asking you to change it; keep what still applies.

Work like this:
- Inspect the tables you plan to use with describe_table before writing SQL. \
Never guess column names or types.
- When the query depends on actual values (category spellings, date formats, \
units), check them with run_sql. Keep sample queries small.
- Write exactly one statement in the given dialect. Qualify tables the way \
they appear in the table list. Prefer readable SQL: explicit column lists, \
clear aliases, one clause per line.
- Write what the user asked for. Include an ORDER BY or LIMIT only when the \
request implies one.
- Finish by calling submit_query with the final SQL. It replaces the request in the editor \
and is the only output the user sees.
- Start the submitted SQL with the request as `--` comment lines, in the \
user's words. When refining a query that already has such a comment, keep it \
and add the new request on its own line. Put any caveats in further comment \
lines.
"""


def _path(path: TablePath) -> str:
    return ".".join(path)


class QueryToolkit:
    """The agent's tools, as plain methods over one connector."""

    def __init__(self, connector: Connector, dialect: str) -> None:
        self.connector = connector
        self.dialect = dialect
        self.final_sql: str | None = None

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

    def run_sql(self, sql: str) -> str:
        try:
            sample = run_read_only(self.connector, self.dialect, sql, SAMPLE_ROWS)
        except NotReadOnlyError as e:
            return f"Refused: {e}. run_sql only runs read-only queries."
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

    def submit_query(self, sql: str) -> str:
        try:
            parse_one(sql, self.dialect)
        except (NotReadOnlyError, ParseError) as e:
            return f"Not accepted: {e}. Fix the SQL and call submit_query again."
        self.final_sql = sql.strip()
        return "Accepted."

    def tools(self) -> list[Any]:
        @beta_tool
        def list_tables(namespace: list[str] | None = None) -> str:
            """List tables and views, one dotted path per line.

            Args:
                namespace: Only list tables under this path prefix, e.g. ["main"].
            """
            return self.list_tables(namespace)

        @beta_tool
        def describe_table(path: list[str]) -> str:
            """Get a table's kind and its columns' names, types and nullability.

            Args:
                path: The table's path, one element per part, e.g. ["main", "trips"].
            """
            return self.describe_table(path)

        @beta_tool
        def run_sql(sql: str) -> str:
            """Run a read-only query (SELECT, DESCRIBE or SHOW) and get at most 20 rows back.

            Use it to look at real values; long text values are clipped.

            Args:
                sql: One read-only statement in the database's dialect.
            """
            return self.run_sql(sql)

        @beta_tool
        def submit_query(sql: str) -> str:
            """Submit the finished query; it replaces the user's request in the editor.

            Args:
                sql: The final SQL, one statement in the database's dialect.
            """
            return self.submit_query(sql)

        return [list_tables, describe_table, run_sql, submit_query]


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
        case "run_sql":
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
            if toolkit.final_sql is not None:
                yield AssistSqlEvent(type="sql", sql=toolkit.final_sql)
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

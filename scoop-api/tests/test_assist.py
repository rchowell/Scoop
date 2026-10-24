import json
import os
import sqlite3
from types import SimpleNamespace

import pytest

from api.assist.agent import (
    QUERY_INPUT_SCHEMA,
    QueryAgent,
    QueryToolkit,
    get_query_agent,
    run_sample,
    step_label,
)
from api.config import Settings
from api.connector import MySQLDialect, SQLiteConnector
from api.main import app
from api.models import AssistDoneEvent, AssistQueryEvent, AssistStatusEvent, Query
from tests.helpers import col


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "data.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE trips (id INTEGER, zone TEXT, fare REAL)")
    conn.executemany(
        "INSERT INTO trips VALUES (?, ?, ?)",
        [(i, f"zone{i % 3}", i * 1.5) for i in range(50)],
    )
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def connector(db_path):
    with SQLiteConnector(db_path) as c:
        yield c


def zones_query(**extra):
    return {
        "distinct": True,
        "select": [{"expr": col("zone")}],
        "from": {"kind": "table", "path": ["main", "trips"]},
        "order_by": [{"expr": col("zone")}],
        **extra,
    }


FARE_BY_ZONE = {
    "select": [
        {"expr": col("zone")},
        {
            "expr": {"kind": "call", "name": "sum", "args": [col("fare")]},
            "alias": "total",
        },
    ],
    "from": {"kind": "table", "path": ["main", "trips"]},
    "group_by": [col("zone")],
    "order_by": [{"expr": col("total"), "direction": "desc"}],
}


# ============================================================================
# Sampling
# ============================================================================


def test_run_sample_caps_rows(connector):
    query = Query.model_validate(
        {
            "select": [{"expr": {"kind": "star"}}],
            "from": {"kind": "table", "path": ["trips"]},
        }
    )
    sample = run_sample(connector, query, max_rows=20)
    assert [c.name for c in sample.columns] == ["id", "zone", "fare"]
    assert len(sample.rows) == 20
    assert sample.rows[0] == [0, "zone0", 0.0]
    assert sample.truncated


def test_run_sample_keeps_smaller_limit(connector):
    query = Query.model_validate(
        {
            "select": [{"expr": col("id")}],
            "from": {"kind": "table", "path": ["trips"]},
            "limit": 5,
        }
    )
    sample = run_sample(connector, query, max_rows=20)
    assert sample.rows == [[i] for i in range(5)]
    assert not sample.truncated


def test_run_sample_clips_long_text(connector):
    printf = {
        "kind": "call",
        "name": "printf",
        "args": [
            {"kind": "literal", "value": "%.500c"},
            {"kind": "literal", "value": "x"},
        ],
    }
    query = Query.model_validate({"select": [{"expr": printf, "alias": "s"}]})
    sample = run_sample(connector, query)
    assert sample.rows[0][0] == "x" * 200 + "…"


# ============================================================================
# Query validation
# ============================================================================


def test_parse_query_accepts_ast(connector):
    parsed = QueryToolkit(connector).parse_query(FARE_BY_ZONE)
    assert isinstance(parsed, Query)
    assert parsed.group_by[0].path == ["zone"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"from": {"kind": "table", "path": ["trips"]}},
            "query.select: Field required",
        ),
        ({"select": [{"expr": {"kind": "col", "path": ["x"]}}]}, "query.select.0.expr"),
        (
            {"select": [{"expr": col("zone")}], "wher": col("x")},
            "query.wher: unknown field",
        ),
        (
            {"select": [{"expr": {**col("zone"), "alias": "z"}}]},
            "query.select[0].expr.alias: unknown field",
        ),
        (
            {"select": [{"expr": {"kind": "call", "name": "f;x", "args": []}}]},
            "function name",
        ),
    ],
)
def test_parse_query_reports_errors(connector, raw, expected):
    error = QueryToolkit(connector).parse_query(raw)
    assert isinstance(error, str)
    assert expected in error


def test_parse_query_reports_unsupported_syntax(connector):
    connector.dialect = MySQLDialect  # the instance attribute shadows the classmethod
    full_join = {
        "select": [{"expr": {"kind": "star"}}],
        "from": {
            "kind": "join",
            "join_type": "full",
            "left": {"kind": "table", "path": ["a"]},
            "right": {"kind": "table", "path": ["b"]},
            "on": {"kind": "literal", "value": True},
        },
    }
    assert QueryToolkit(connector).parse_query(full_join) == (
        "MySQL does not support FULL JOIN"
    )


# ============================================================================
# Toolkit
# ============================================================================


def test_toolkit_list_and_describe(connector):
    toolkit = QueryToolkit(connector)
    assert toolkit.list_tables() == "main.trips"
    assert toolkit.list_tables(["temp"]) == "No tables."
    described = json.loads(toolkit.describe_table(["main", "trips"]))
    assert [c["name"] for c in described["columns"]] == ["id", "zone", "fare"]
    assert toolkit.describe_table(["main", "nope"]).startswith("Error: no table")


def test_toolkit_run_query(connector):
    toolkit = QueryToolkit(connector)
    assert json.loads(toolkit.run_query(zones_query())) == {
        "columns": ["zone"],
        "rows": [["zone0"], ["zone1"], ["zone2"]],
        "truncated": False,
    }
    assert toolkit.run_query({"select": []}).startswith("Error:")
    # Qualified: SQLite reads an unknown bare "nope" as a string literal
    bad_column = zones_query(select=[{"expr": col("trips", "nope")}], order_by=None)
    assert toolkit.run_query(bad_column).startswith("Error:")


def test_toolkit_submit_query(connector):
    toolkit = QueryToolkit(connector)
    assert toolkit.submit_query({"selec": []}).startswith("Not accepted")
    unknown_column = zones_query(select=[{"expr": col("trips", "nope")}], order_by=None)
    assert "no such column" in toolkit.submit_query(unknown_column)
    assert toolkit.final_query is None
    assert toolkit.submit_query(FARE_BY_ZONE) == "Accepted."
    assert toolkit.final_query == Query.model_validate(FARE_BY_ZONE)


def test_step_label():
    assert step_label("list_tables", {}) == "Listing tables…"
    assert step_label("describe_table", {"path": ["main", "trips"]}) == (
        "Reading main.trips…"
    )
    assert step_label("run_query", {"query": {}}) == "Sampling data…"


# ============================================================================
# Tool schemas
# ============================================================================


def _refs(node):
    if isinstance(node, dict):
        if "$ref" in node:
            yield node["$ref"]
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def test_tool_definitions(connector):
    tools = {t.name: t.to_dict() for t in QueryToolkit(connector).tools()}
    assert tools["list_tables"]["strict"] is True
    assert tools["describe_table"]["strict"] is True
    for name in ("run_query", "submit_query"):
        # Recursive schemas can't be strict
        assert "strict" not in tools[name]
        assert tools[name]["input_schema"] == QUERY_INPUT_SCHEMA


def test_query_input_schema():
    schema = QUERY_INPUT_SCHEMA
    assert schema["required"] == ["query"]
    defs = schema["$defs"]
    assert {"Query", "Expr", "FromItem"} <= defs.keys()
    for ref in _refs(schema):
        assert ref.removeprefix("#/$defs/") in defs
    for name, d in defs.items():
        assert "discriminator" not in d
        if d.get("type") == "object":
            assert d["additionalProperties"] is False, name
    assert defs["ColumnExpr"]["required"] == ["kind", "path"]
    assert defs["Query"]["required"] == ["select"]


def test_query_round_trips_by_alias():
    query = Query.model_validate(FARE_BY_ZONE)
    dumped = query.model_dump(by_alias=True, exclude_none=True)
    assert "from" in dumped and "from_" not in dumped
    assert Query.model_validate(dumped) == query


# ============================================================================
# Agent loop (fake Claude client)
# ============================================================================


def _tool_use(name, **input):
    return SimpleNamespace(type="tool_use", name=name, input=input)


def _message(*blocks, stop_reason="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class FakeRunner:
    """Replays scripted assistant messages, running their tool calls like the SDK runner."""

    def __init__(self, turns, tools):
        self.turns = turns
        self.tools = {t.name: t for t in tools}
        self.calls = 0
        self.results = []

    def __iter__(self):
        for message in self.turns:
            self.last, self.cached = message, None
            yield message

    def generate_tool_call_response(self):
        if self.cached is None:
            self.calls += 1
            self.cached = [
                self.tools[b.name].call(b.input)
                for b in self.last.content
                if b.type == "tool_use"
            ]
            self.results.extend(self.cached)
        return self.cached


class FakeClient:
    def __init__(self, turns):
        self.turns = turns
        self.requests = []
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(tool_runner=self._tool_runner)
        )

    def _tool_runner(self, **kwargs):
        self.requests.append(kwargs)
        self.runner = FakeRunner(self.turns, kwargs["tools"])
        return self.runner


def test_agent_streams_steps_then_sql(connector):
    client = FakeClient(
        [
            _message(_tool_use("describe_table", path=["main", "trips"])),
            _message(_tool_use("submit_query", query={"from": FARE_BY_ZONE["from"]})),
            _message(_tool_use("submit_query", query=FARE_BY_ZONE)),
            _message(stop_reason="end_turn"),  # never reached
        ]
    )
    agent = QueryAgent(client, "claude-sonnet-5-5")
    events = list(agent.generate(connector, "zones", "zones"))
    assert events == [
        AssistStatusEvent(message="Reading main.trips…"),
        AssistStatusEvent(message="Checking the query…"),
        AssistStatusEvent(message="Checking the query…"),
        AssistQueryEvent(query=Query.model_validate(FARE_BY_ZONE)),
        AssistDoneEvent(),
    ]
    assert client.runner.calls == 3
    _, rejected, accepted = client.runner.results
    assert rejected.startswith("Not accepted:\nquery.select: Field required")
    assert accepted == "Accepted."

    request = client.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    first = request["messages"][0]["content"]
    assert "<dialect>sqlite</dialect>" in first
    assert "main.trips" in first
    assert "<editor>" not in first  # context identical to the prompt


def test_agent_includes_editor_context(connector):
    client = FakeClient([_message(stop_reason="end_turn")])
    agent = QueryAgent(client, "m")
    events = list(agent.generate(connector, "add fare", "SELECT 1"))
    assert (
        "<editor>\nSELECT 1\n</editor>" in client.requests[0]["messages"][0]["content"]
    )
    assert events[-1].type == "error"


def test_agent_reports_refusal(connector):
    client = FakeClient([_message(stop_reason="refusal")])
    events = list(QueryAgent(client, "m").generate(connector, "x"))
    assert [e.type for e in events] == ["error"]


# ============================================================================
# Route
# ============================================================================


def _create(client, db_path):
    body = {"name": "db", "kind": "sqlite", "options": {"database": db_path}}
    return client.post("/v1/connectors", json=body).json()["id"]


def test_generate_without_key_is_503(client, db_path):
    id = _create(client, db_path)
    r = client.post(f"/v1/connectors/{id}/generate", json={"prompt": "x"})
    assert r.status_code == 503
    assert r.json()["title"] == "Assistant Unavailable"


def test_generate_streams_sse(client, db_path):
    id = _create(client, db_path)
    seen = {}

    class FakeAgent:
        def generate(self, connector, prompt, context):
            seen.update(kind=connector.kind(), prompt=prompt, context=context)
            yield AssistStatusEvent(message="Listing tables…")
            yield AssistQueryEvent(
                query=Query.model_validate(
                    {
                        "select": [{"expr": {"kind": "star"}}],
                        "from": {"kind": "table", "path": ["trips"]},
                    }
                ),
            )
            yield AssistDoneEvent()

    app.dependency_overrides[get_query_agent] = FakeAgent
    r = client.post(
        f"/v1/connectors/{id}/generate",
        json={"prompt": "one", "context": "-- one"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert seen == {"kind": "sqlite", "prompt": "one", "context": "-- one"}
    assert r.text == (
        'event: status\ndata: {"type":"status","message":"Listing tables…"}\n\n'
        'event: query\ndata: {"type":"query","query":{"distinct":false,'
        '"select":[{"expr":{"kind":"star","qualifier":null},"alias":null}],'
        '"from":{"kind":"table","path":["trips"],"alias":null},"where":null,'
        '"group_by":null,"having":null,"order_by":null,"limit":null,"offset":null}}\n\n'
        'event: done\ndata: {"type":"done"}\n\n'
    )


def test_generate_unknown_connector_is_404(client):
    app.dependency_overrides[get_query_agent] = lambda: None
    r = client.post(
        "/v1/connectors/00000000-0000-0000-0000-000000000000/generate",
        json={"prompt": "x"},
    )
    assert r.status_code == 404


# ============================================================================
# Live (Claude API)
# ============================================================================


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY is not set"
)
def test_agent_live(connector):
    import anthropic

    agent = QueryAgent(anthropic.Anthropic(), Settings().assist_model)
    prompt = "total fare per zone, highest first"
    events = list(agent.generate(connector, prompt, prompt))
    assert events[-1] == AssistDoneEvent(), events
    query = next(e.query for e in events if e.type == "query")
    with connector.execute(query) as result:
        names = [c.name for c in result.columns]
        rows = [row for page in result for row in zip(*page.data.values())]
    assert len(rows) == 3
    fares = [row[names.index(n)] for row in rows for n in names if n != "zone"]
    assert fares == sorted(fares, reverse=True)

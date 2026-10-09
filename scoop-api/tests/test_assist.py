import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.assist.agent import QueryAgent, QueryToolkit, get_query_agent, step_label
from api.assist.readonly import NotReadOnlyError, check_read_only, run_read_only
from api.config import Settings, get_settings
from api.connector import SqliteConnector
from api.main import app
from models import AssistDoneEvent, AssistSqlEvent, AssistStatusEvent


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
    with SqliteConnector(db_path) as c:
        yield c


# ============================================================================
# Read-only guard
# ============================================================================


@pytest.mark.parametrize(
    ("sql", "dialect"),
    [
        ("SELECT 1", "duckdb"),
        ("WITH a AS (SELECT 1) SELECT * FROM a", "postgres"),
        ("SELECT 1 UNION SELECT 2", "mysql"),
        ("DESCRIBE t", "duckdb"),
        ("SHOW TABLES", "mysql"),
        ("SELECT * FROM t -- trailing comment", "sqlite"),
    ],
)
def test_read_only_allows(sql, dialect):
    check_read_only(sql, dialect)


@pytest.mark.parametrize(
    ("sql", "dialect"),
    [
        ("DELETE FROM t", "sqlite"),
        ("DROP TABLE t", "duckdb"),
        ("INSERT INTO t SELECT 1", "mysql"),
        ("CREATE TABLE x AS SELECT 1", "duckdb"),
        ("SELECT 1; SELECT 2", "duckdb"),
        ("WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d", "postgres"),
        ("SELECT * INTO copy FROM t", "postgres"),
        ("COPY t TO 'x.csv'", "duckdb"),
        ("ATTACH 'x.db'", "duckdb"),
        ("PRAGMA writable_schema = 1", "sqlite"),
        ("SET x = 1", "mysql"),
        ("SELEC oops", "sqlite"),
    ],
)
def test_read_only_refuses(sql, dialect):
    with pytest.raises(NotReadOnlyError):
        check_read_only(sql, dialect)


def test_run_read_only_caps_rows(connector):
    sample = run_read_only(connector, "sqlite", "SELECT * FROM trips;", max_rows=20)
    assert [c.name for c in sample.columns] == ["id", "zone", "fare"]
    assert len(sample.rows) == 20
    assert sample.rows[0] == [0, "zone0", 0.0]
    assert sample.truncated


def test_run_read_only_keeps_smaller_limit(connector):
    sample = run_read_only(
        connector, "sqlite", "SELECT id FROM trips LIMIT 5", max_rows=20
    )
    assert sample.rows == [[i] for i in range(5)]
    assert not sample.truncated


def test_run_read_only_clips_long_text(connector):
    sample = run_read_only(connector, "sqlite", "SELECT printf('%.500c', 'x') AS s")
    assert sample.rows[0][0] == "x" * 200 + "…"


def test_run_read_only_refuses_writes(connector):
    with pytest.raises(NotReadOnlyError):
        run_read_only(connector, "sqlite", "DELETE FROM trips")
    sample = run_read_only(connector, "sqlite", "SELECT count(*) AS n FROM trips")
    assert sample.rows == [[50]]


# ============================================================================
# Toolkit
# ============================================================================


def test_toolkit_list_and_describe(connector):
    toolkit = QueryToolkit(connector, "sqlite")
    assert toolkit.list_tables() == "main.trips"
    assert toolkit.list_tables(["temp"]) == "No tables."
    described = json.loads(toolkit.describe_table(["main", "trips"]))
    assert [c["name"] for c in described["columns"]] == ["id", "zone", "fare"]
    assert toolkit.describe_table(["main", "nope"]).startswith("Error: no table")


def test_toolkit_run_sql(connector):
    toolkit = QueryToolkit(connector, "sqlite")
    result = json.loads(
        toolkit.run_sql("SELECT DISTINCT zone FROM trips ORDER BY zone")
    )
    assert result == {
        "columns": ["zone"],
        "rows": [["zone0"], ["zone1"], ["zone2"]],
        "truncated": False,
    }
    assert toolkit.run_sql("DROP TABLE trips").startswith("Refused:")
    assert toolkit.run_sql("SELECT nope FROM trips").startswith("Error:")


def test_toolkit_submit_query(connector):
    toolkit = QueryToolkit(connector, "sqlite")
    assert toolkit.submit_query("SELECT 1; SELECT 2").startswith("Not accepted")
    assert toolkit.final_sql is None
    assert toolkit.submit_query("  SELECT zone FROM trips\n") == "Accepted."
    assert toolkit.final_sql == "SELECT zone FROM trips"


def test_step_label():
    assert step_label("list_tables", {}) == "Listing tables…"
    assert step_label("describe_table", {"path": ["main", "trips"]}) == (
        "Reading main.trips…"
    )


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
            _message(_tool_use("submit_query", sql="SELECT 1; SELECT 2")),
            _message(_tool_use("submit_query", sql="SELECT zone FROM trips")),
            _message(stop_reason="end_turn"),  # never reached
        ]
    )
    agent = QueryAgent(client, "claude-sonnet-5-5")
    events = list(agent.generate(connector, "sqlite", "zones", "zones"))
    assert events == [
        AssistStatusEvent(type="status", message="Reading main.trips…"),
        AssistStatusEvent(type="status", message="Checking the query…"),
        AssistStatusEvent(type="status", message="Checking the query…"),
        AssistSqlEvent(type="sql", sql="SELECT zone FROM trips"),
        AssistDoneEvent(type="done"),
    ]
    assert client.runner.calls == 3

    request = client.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    first = request["messages"][0]["content"]
    assert "<dialect>sqlite</dialect>" in first
    assert "main.trips" in first
    assert "<editor>" not in first  # context identical to the prompt


def test_agent_includes_editor_context(connector):
    client = FakeClient([_message(stop_reason="end_turn")])
    agent = QueryAgent(client, "m")
    events = list(agent.generate(connector, "sqlite", "add fare", "SELECT 1"))
    assert (
        "<editor>\nSELECT 1\n</editor>" in client.requests[0]["messages"][0]["content"]
    )
    assert events[-1].type == "error"


def test_agent_reports_refusal(connector):
    client = FakeClient([_message(stop_reason="refusal")])
    events = list(QueryAgent(client, "m").generate(connector, "sqlite", "x"))
    assert [e.type for e in events] == ["error"]


# ============================================================================
# Route
# ============================================================================


@pytest.fixture
def api(tmp_path):
    settings = Settings(db_path=str(tmp_path / "app.sqlite3"))
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create(api, db_path):
    body = {"name": "db", "kind": "sqlite", "options": {"path": db_path}}
    return api.post("/v1/connectors", json=body).json()["id"]


def test_generate_without_key_is_503(api, db_path):
    id = _create(api, db_path)
    r = api.post(f"/v1/connectors/{id}/generate", json={"prompt": "x"})
    assert r.status_code == 503
    assert r.json()["title"] == "Assistant Unavailable"


def test_generate_streams_sse(api, db_path):
    id = _create(api, db_path)
    seen = {}

    class FakeAgent:
        def generate(self, connector, dialect, prompt, context):
            seen.update(dialect=dialect, prompt=prompt, context=context)
            yield AssistStatusEvent(type="status", message="Listing tables…")
            yield AssistSqlEvent(type="sql", sql="SELECT 1")
            yield AssistDoneEvent(type="done")

    app.dependency_overrides[get_query_agent] = FakeAgent
    r = api.post(
        f"/v1/connectors/{id}/generate",
        json={"prompt": "one", "context": "-- one"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert seen == {"dialect": "sqlite", "prompt": "one", "context": "-- one"}
    assert r.text == (
        'event: status\ndata: {"type":"status","message":"Listing tables…"}\n\n'
        'event: sql\ndata: {"type":"sql","sql":"SELECT 1"}\n\n'
        'event: done\ndata: {"type":"done"}\n\n'
    )


def test_generate_unknown_connector_is_404(api):
    app.dependency_overrides[get_query_agent] = lambda: None
    r = api.post(
        "/v1/connectors/00000000-0000-0000-0000-000000000000/generate",
        json={"prompt": "x"},
    )
    assert r.status_code == 404

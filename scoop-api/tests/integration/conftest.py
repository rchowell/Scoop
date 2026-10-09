"""Backend specs and fixtures for driving the HTTP API against every connector kind."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.connector import FACTORIES, create_connector
from api.main import app

RESET = ["DROP VIEW IF EXISTS named_users", "DROP TABLE IF EXISTS users"]


def seed(varchar: str = "VARCHAR", blob: str = "BLOB") -> list[str]:
    return [
        f"CREATE TABLE users (id INTEGER NOT NULL, name {varchar}, avatar {blob})",
        "INSERT INTO users (id, name) VALUES (1, 'a'), (2, 'b'), (3, 'c'), (4, NULL)",
        "CREATE VIEW named_users AS SELECT * FROM users WHERE name IS NOT NULL",
    ]


@dataclass(frozen=True)
class Backend:
    kind: str
    prefix: list[str]
    types: tuple[str | None, str | None]  # native types of users.id, users.name
    seed: list[str]
    positional: str  # positional parameter marker
    named: Callable[[str], str]  # named parameter marker for `name`
    blob_literal: str  # SQL literal for the bytes FF 00
    # Builds the stored options; `bad` gives options that validate but can't connect.
    options: Callable[[Path, pytest.FixtureRequest, bool], dict[str, Any]]


def _file_options(key: str, suffix: str):
    def build(tmp_path: Path, request: pytest.FixtureRequest, bad: bool):
        parent = tmp_path / "missing" if bad else tmp_path
        return {key: str(parent / f"data.{suffix}")}

    return build


def _server_options(fixture: str):
    def build(tmp_path: Path, request: pytest.FixtureRequest, bad: bool):
        options = dict(request.getfixturevalue(fixture))
        if bad:
            options["password"] = "wrong-password"
        return options

    return build


BACKENDS = {
    b.kind: b
    for b in [
        Backend(
            kind="sqlite",
            prefix=["main"],
            types=("INTEGER", "VARCHAR"),
            seed=seed(),
            positional="?",
            named=lambda n: f":{n}",
            blob_literal="X'FF00'",
            options=_file_options("path", "sqlite"),
        ),
        Backend(
            kind="duckdb",
            prefix=["data", "main"],  # catalog is the database file's stem
            types=("INTEGER", "VARCHAR"),
            seed=seed(),
            positional="?",
            named=lambda n: f"${n}",
            blob_literal=r"'\xFF\x00'::BLOB",
            options=_file_options("database", "duckdb"),
        ),
        Backend(
            kind="postgres",
            prefix=["public"],
            types=("integer", "character varying"),
            seed=seed(blob="BYTEA"),
            positional="%s",
            named=lambda n: f"%({n})s",
            blob_literal=r"'\xff00'::bytea",
            options=_server_options("postgres_options"),
        ),
        Backend(
            kind="mysql",
            prefix=["test"],
            types=("int", "varchar"),
            seed=seed(varchar="VARCHAR(255)"),
            positional="%s",
            named=lambda n: f"%({n})s",
            blob_literal="X'FF00'",
            options=_server_options("mysql_options"),
        ),
    ]
}


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_settings] = lambda: Settings(
        db_path=str(tmp_path / "app.sqlite3")
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(params=list(FACTORIES))
def spec(request) -> Backend:
    """Every registered connector kind; a kind without a Backend spec fails here."""
    return BACKENDS[request.param]


@pytest.fixture
def options(spec, tmp_path, request) -> dict[str, Any]:
    return spec.options(tmp_path, request, False)


@pytest.fixture
def bad_options(spec, tmp_path, request) -> dict[str, Any]:
    return spec.options(tmp_path, request, True)


@pytest.fixture
def target(client, spec, options) -> str:
    """Seed the backend directly, register it through the API, and return its id."""
    with create_connector(spec.kind, options) as conn:
        for stmt in [*RESET, *spec.seed]:
            conn.execute(stmt).close()
    resp = client.post(
        "/v1/connectors",
        json={"name": spec.kind, "kind": spec.kind, "options": options},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]

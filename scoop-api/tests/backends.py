"""Per-backend specs: how to reach each connector kind and what to expect from it."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

RESET = ["DROP VIEW IF EXISTS named_users", "DROP TABLE IF EXISTS users"]


def seed(blob_literal: str, varchar: str = "VARCHAR", blob: str = "BLOB") -> list[str]:
    """users(id, name, avatar): four rows, the last with a NULL name; only id 1 has
    an avatar, the bytes FF 00."""
    return [
        f"CREATE TABLE users (id INTEGER NOT NULL, name {varchar}, avatar {blob})",
        "INSERT INTO users (id, name) VALUES (1, 'a'), (2, 'b'), (3, 'c'), (4, NULL)",
        f"UPDATE users SET avatar = {blob_literal} WHERE id = 1",
        "CREATE VIEW named_users AS SELECT * FROM users WHERE name IS NOT NULL",
    ]


@dataclass(frozen=True)
class Backend:
    kind: str
    prefix: list[str]
    types: tuple[str | None, str | None]  # native types of users.id, users.name
    seed: list[str]
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
            seed=seed("X'FF00'"),
            options=_file_options("database", "sqlite"),
        ),
        Backend(
            kind="duckdb",
            prefix=["data", "main"],  # catalog is the database file's stem
            types=("INTEGER", "VARCHAR"),
            seed=seed(r"'\xFF\x00'::BLOB"),
            options=_file_options("database", "duckdb"),
        ),
        Backend(
            kind="postgres",
            prefix=["public"],
            types=("integer", "character varying"),
            seed=seed(r"'\xff00'::bytea", blob="BYTEA"),
            options=_server_options("postgres_options"),
        ),
        Backend(
            kind="mysql",
            prefix=["test"],
            types=("int", "varchar"),
            seed=seed("X'FF00'", varchar="VARCHAR(255)"),
            options=_server_options("mysql_options"),
        ),
    ]
}

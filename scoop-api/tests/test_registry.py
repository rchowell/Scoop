import pytest

from api.connector import (
    CONNECTORS,
    ConnectorError,
    DuckDBConnector,
    InvalidOptionsError,
    PostgresConnector,
    SQLiteConnector,
    connector_class,
    create_connector,
    validate_options,
)
from api.models import ConnectorKind
from tests.helpers import alias, lit, select


def test_registry():
    assert set(CONNECTORS) == {"sqlite", "duckdb", "postgres", "mysql"}
    for kind, cls in CONNECTORS.items():
        assert cls.kind() == kind
        assert cls.display_name()
        assert cls.options()


def test_api_kinds_match_registry():
    assert {k.value for k in ConnectorKind} == set(CONNECTORS)


def test_unknown_kind():
    with pytest.raises(ConnectorError):
        connector_class("oracle")


def test_password_is_secret():
    for kind in ("postgres", "mysql"):
        options = connector_class(kind).options()
        assert options["password"].secret
        assert not options["password"].required
        assert not options["host"].secret


@pytest.mark.parametrize(
    ("kind", "options", "cls"),
    [
        ("sqlite", {"database": "t.sqlite3"}, SQLiteConnector),
        ("duckdb", {}, DuckDBConnector),
    ],
)
def test_create(kind, options, cls, tmp_path):
    if "database" in options:
        options = {"database": str(tmp_path / options["database"])}
    with create_connector(kind, options) as conn:
        assert isinstance(conn, cls)
        with conn.execute(select(alias(lit(1), "x"))) as result:
            assert [p.data for p in result] == [{"x": [1]}]


def test_validate_defaults_and_coercion():
    opts = validate_options(
        PostgresConnector.options(),
        {"host": "h", "port": "6543", "user": "u", "database": "d"},
    )
    assert opts == {
        "host": "h",
        "port": 6543,
        "user": "u",
        "password": None,
        "database": "d",
    }
    minimal = {"host": "h", "user": "u", "database": "d"}
    assert validate_options(PostgresConnector.options(), minimal)["port"] == 5432
    assert validate_options(DuckDBConnector.options(), {}) == {"database": ":memory:"}


@pytest.mark.parametrize(
    ("options", "problem"),
    [
        (
            {"host": "h", "user": "u", "database": "d", "bogus": 1},
            "unknown option: bogus",
        ),
        ({"host": "h", "user": "u"}, "missing required option: database"),
        (
            {"host": "h", "user": "u", "database": "d", "port": "abc"},
            "port: expected int",
        ),
        (
            {"host": "h", "user": "u", "database": "d", "port": True},
            "port: expected int",
        ),
        ({"host": 1, "user": "u", "database": "d"}, "host: expected str"),
    ],
)
def test_validate_rejects(options, problem):
    with pytest.raises(InvalidOptionsError) as exc:
        create_connector("postgres", options)
    assert exc.value.problems == [problem]


def test_validate_reports_all_problems():
    with pytest.raises(InvalidOptionsError) as exc:
        validate_options(connector_class("mysql").options(), {"bogus": 1})
    assert set(exc.value.problems) == {
        "unknown option: bogus",
        "missing required option: host",
        "missing required option: user",
        "missing required option: database",
    }

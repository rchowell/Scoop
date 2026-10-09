import pytest

from api.connector import (
    FACTORIES,
    ConnectorError,
    DuckDBConnector,
    InvalidOptionsError,
    SqliteConnector,
    create_connector,
    get_factory,
)
from models import ConnectorKind


def test_registry():
    assert set(FACTORIES) == {"sqlite", "duckdb", "postgres", "mysql"}
    for kind, factory in FACTORIES.items():
        assert factory.kind() == kind
        assert factory.name()
        assert factory.options()


def test_api_kinds_match_registry():
    assert {k.value for k in ConnectorKind} == set(FACTORIES)


def test_unknown_kind():
    with pytest.raises(ConnectorError):
        get_factory("oracle")


def test_password_is_secret():
    for kind in ("postgres", "mysql"):
        options = get_factory(kind).options()
        assert options["password"].secret
        assert not options["host"].secret


@pytest.mark.parametrize(
    ("kind", "options", "cls"),
    [
        ("sqlite", {"path": "t.sqlite3"}, SqliteConnector),
        ("duckdb", {}, DuckDBConnector),
    ],
)
def test_create(kind, options, cls, tmp_path):
    if "path" in options:
        options = {"path": str(tmp_path / options["path"])}
    with create_connector(kind, options) as conn:
        assert isinstance(conn, cls)
        with conn.execute("SELECT 1 AS x") as result:
            assert [p.data for p in result] == [{"x": [1]}]


def test_validate_defaults_and_coercion():
    factory = get_factory("postgres")
    opts = factory.validate({"host": "h", "port": "6543", "user": "u", "dbname": "d"})
    assert opts == {
        "host": "h",
        "port": 6543,
        "user": "u",
        "password": None,
        "dbname": "d",
    }
    assert factory.validate({"host": "h", "user": "u", "dbname": "d"})["port"] == 5432
    assert get_factory("duckdb").validate({}) == {"database": ":memory:"}


@pytest.mark.parametrize(
    ("options", "problem"),
    [
        (
            {"host": "h", "user": "u", "dbname": "d", "bogus": 1},
            "unknown option: bogus",
        ),
        ({"host": "h", "user": "u"}, "missing required option: dbname"),
        (
            {"host": "h", "user": "u", "dbname": "d", "port": "abc"},
            "port: expected int",
        ),
        ({"host": "h", "user": "u", "dbname": "d", "port": True}, "port: expected int"),
        ({"host": 1, "user": "u", "dbname": "d"}, "host: expected str"),
    ],
)
def test_validate_rejects(options, problem):
    with pytest.raises(InvalidOptionsError) as exc:
        get_factory("postgres").create(options)
    assert exc.value.problems == [problem]


def test_validate_reports_all_problems():
    with pytest.raises(InvalidOptionsError) as exc:
        get_factory("mysql").validate({"bogus": 1})
    assert set(exc.value.problems) == {
        "unknown option: bogus",
        "missing required option: host",
        "missing required option: user",
        "missing required option: database",
    }

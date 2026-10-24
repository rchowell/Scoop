from typing import Any

import pytest
from docker.errors import DockerException
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.connector import CONNECTORS
from api.main import app
from tests.backends import BACKENDS, Backend

DB_FILE = "app.sqlite3"


@pytest.fixture
def client(tmp_path):
    """A client for the app, backed by a fresh database in tmp_path / DB_FILE."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        db_path=str(tmp_path / DB_FILE)
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# -- backends ----------------------------------------------------------------


@pytest.fixture(params=list(CONNECTORS))
def spec(request) -> Backend:
    """Every registered connector kind; a kind without a Backend spec fails here."""
    return BACKENDS[request.param]


@pytest.fixture
def options(spec, tmp_path, request) -> dict[str, Any]:
    return spec.options(tmp_path, request, False)


@pytest.fixture
def bad_options(spec, tmp_path, request) -> dict[str, Any]:
    """Options that validate but can't connect."""
    return spec.options(tmp_path, request, True)


def _container(cls):
    try:
        container = cls().start()
    except DockerException as e:  # Docker unavailable or image pull failed
        pytest.skip(f"{cls.__name__} unavailable: {e}")
    return container


@pytest.fixture(scope="session")
def postgres_options():
    from testcontainers.community.postgres import PostgresContainer

    container = _container(PostgresContainer)
    yield {
        "host": container.get_container_host_ip(),
        "port": int(container.get_exposed_port(5432)),
        "user": container.username,
        "password": container.password,
        "database": container.dbname,
    }
    container.stop()


@pytest.fixture(scope="session")
def mysql_options():
    from testcontainers.community.mysql import MySqlContainer

    container = _container(MySqlContainer)
    yield {
        "host": container.get_container_host_ip(),
        "port": int(container.get_exposed_port(3306)),
        "user": container.username,
        "password": container.password,
        "database": container.dbname,
    }
    container.stop()

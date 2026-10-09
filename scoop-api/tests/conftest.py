import pytest
from docker.errors import DockerException


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
        "dbname": container.dbname,
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

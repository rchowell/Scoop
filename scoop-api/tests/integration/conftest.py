"""Fixtures for driving the HTTP API against every connector kind."""

import pytest

from api.connector import create_connector
from tests.backends import RESET
from tests.helpers import run_sql


@pytest.fixture
def target(client, spec, options) -> str:
    """Seed the backend directly, register it through the API, and return its id."""
    with create_connector(spec.kind, options) as conn:
        run_sql(conn, [*RESET, *spec.seed])
    resp = client.post(
        "/v1/connectors",
        json={"name": spec.kind, "kind": spec.kind, "options": options},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]

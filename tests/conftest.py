"""Shared pytest fixtures.

A fixture is a function pytest runs before a test and passes in by name:
``def test_x(conn): ...`` receives a fresh in-memory database.
"""

from __future__ import annotations

import pytest

from flexsched.db import connect
from flexsched.engine_bridge import EngineNotFoundError, find_engine
from flexsched.synthetic import generate_history


@pytest.fixture
def conn():
    connection = connect(":memory:")  # brand-new, isolated DB for every test
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def history_conn():
    """A database with 90 days of synthetic history (built once per module)."""
    connection = connect(":memory:")
    generate_history(connection, days=90, seed=1)
    yield connection
    connection.close()


def _engine_missing() -> bool:
    try:
        find_engine()
        return False
    except EngineNotFoundError:
        return True


requires_engine = pytest.mark.skipif(_engine_missing(),
                                     reason="C++ engine not built (see README)")

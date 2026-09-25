"""Integration-test harness.

Runs against a real Postgres, not SQLite. That's deliberate: the columns are
DateTime(timezone=True) and the ids are native UUIDs, and SQLite silently drops
both distinctions -- which is exactly the class of bug these tests exist to
catch. A test suite that can't see naive-vs-aware datetimes is worse than none.

Each test runs inside an outer transaction that is rolled back afterwards. The
routes call db.commit(); with join_transaction_mode="create_savepoint" those
become savepoint releases, so the data is visible within the test and gone after.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  -- registers tables on Base.metadata
from app.config import get_settings
from app.db import Base, get_db
from app.main import app as fastapi_app


def _test_database_url() -> str:
    override = os.getenv("TEST_DATABASE_URL")
    if override:
        return override
    base, _, _ = get_settings().database_url.rpartition("/")
    return f"{base}/cadence_test"


@pytest.fixture(scope="session")
def engine():
    url = _test_database_url()
    base, _, name = url.rpartition("/")

    # CREATE DATABASE cannot run inside a transaction.
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"No Postgres available for integration tests: {exc}")
    finally:
        admin.dispose()

    eng = create_engine(url)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def connection(engine):
    """One connection per test, wrapped in a transaction that is rolled back."""
    conn = engine.connect()
    outer = conn.begin()
    try:
        yield conn
    finally:
        outer.rollback()
        conn.close()


def _session_on(conn) -> Session:
    return Session(bind=conn, join_transaction_mode="create_savepoint")


@pytest.fixture
def db(connection):
    session = _session_on(connection)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db, connection, monkeypatch):
    """A client whose requests all share the test's transaction.

    The dependency override covers routes that take Depends(get_db). The
    SessionLocal patch covers the streaming endpoint, which deliberately opens
    its own session (FastAPI closes yield-dependencies before a streaming body is
    sent). Without the patch those writes would commit outside the test
    transaction and leak into the next run.
    """
    import app.api.routes as routes

    fastapi_app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(routes, "SessionLocal", lambda: _session_on(connection))
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()

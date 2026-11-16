"""Shared test helpers. No real addresses or credentials: reserved test names
(RFC 2606 .test / .invalid) and a password generated on every run."""
from __future__ import annotations

import secrets
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pricing import price_order

ALLOWED_ORIGIN = "https://shop.example.test"

CATALOG = {
    1: ("Instant Film Camera", Decimal("99.99")),
    3: ('Compact Smartphone 4.7"', Decimal("299.00")),
    19: ("Smart TV 01", Decimal("399.00")),
}


class FakeRepository:
    """Stands in for PostgreSQL: prices from a fixed catalog, or raises the given error."""

    def __init__(self, catalog=None, error=None):
        self.catalog = CATALOG if catalog is None else catalog
        self.error = error
        self.calls = []

    def create_order(self, items):
        self.calls.append(list(items))
        if self.error is not None:
            raise self.error
        lines, total = price_order(items, self.catalog)
        return {"id": uuid.uuid4(), "total": total, "items": lines}


@pytest.fixture
def settings():
    return Settings(
        db_host="db.invalid",
        db_port=5432,
        db_user="test_user",
        db_password=secrets.token_urlsafe(16),
        db_name="test_db",
        db_sslmode="prefer",
        cors_allowed_origin=ALLOWED_ORIGIN,
    )


@pytest.fixture
def make_client(settings):
    def _make(repository):
        # raise_server_exceptions=False: we test the real 500 response, not the exception.
        return TestClient(create_app(settings, repository), raise_server_exceptions=False)

    return _make

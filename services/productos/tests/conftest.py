"""Shared test helpers. No real addresses or credentials: reserved test names
(RFC 2606 .test / .invalid) and a password generated on every run."""
from __future__ import annotations

import secrets
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ALLOWED_ORIGIN = "https://shop.example.test"


def make_row(**overrides):
    row = {
        "id": 1,
        "name": "Instant Film Camera",
        "category": "Electronics & Computer",
        "price": Decimal("99.99"),
        "image_file": "product-1.png",
    }
    row.update(overrides)
    return row


SAMPLE_ROWS = [
    make_row(),
    make_row(id=3, name='Compact Smartphone 4.7"', category="Mobiles & Tablets",
             price=Decimal("299.00"), image_file="product-3.png"),
    make_row(id=19, name="Smart TV 01", category="Smart TV",
             price=Decimal("399.00"), image_file="smart-tv-01.png"),
]


class FakeRepository:
    """Stands in for PostgreSQL: returns rows, or raises the given error."""

    def __init__(self, rows=None, error=None):
        self.rows = SAMPLE_ROWS if rows is None else rows
        self.error = error

    def list_products(self):
        if self.error is not None:
            raise self.error
        return self.rows


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

"""Shared test helpers. No real addresses or credentials: reserved test names
(RFC 2606 .test / .invalid) and a password generated on every run."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthError
from app.config import Settings
from app.main import create_app
from app.pricing import price_order

ALLOWED_ORIGIN = "https://shop.example.test"

# Made-up values. The fake verifier below stands in for Cognito: it accepts one
# token and answers with one subject.
GOOD_TOKEN = "aaaa.bbbb.cccc"
SUB = "1be5a62d-ccb5-438b-b8a4-62ecbd8f2912"

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
        self.calls = []   # the items of each order
        self.users = []   # the user_id of each order, same order as calls
        self.stored = []  # (user_id, order) of each saved order, oldest first
        self.listed = []  # (user_id, limit) of each history request

    def create_order(self, user_id, items):
        self.users.append(user_id)
        self.calls.append(list(items))
        if self.error is not None:
            raise self.error
        lines, total = price_order(items, self.catalog)
        order = {"id": uuid.uuid4(), "total": total, "items": lines}
        self.stored.append((user_id, order))
        return order

    def list_orders(self, user_id, limit):
        self.listed.append((user_id, limit))
        if self.error is not None:
            raise self.error
        mine = [dict(o, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
                for owner, o in reversed(self.stored) if owner == user_id]
        return mine[:limit]


class FakeVerifier:
    """Accepts GOOD_TOKEN (answers SUB). Anything else is an invalid token.
    `error` makes every call raise it (for example AuthUnavailable)."""

    def __init__(self, error=None):
        self.error = error
        self.tokens = []

    def verify(self, token):
        self.tokens.append(token)
        if self.error is not None:
            raise self.error
        if token != GOOD_TOKEN:
            raise AuthError
        return SUB


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
        cognito_issuer="https://idp.example.test/pool-one",
        cognito_jwks_url="https://idp.example.test/pool-one/.well-known/jwks.json",
        cognito_app_client_id="testclient0123456789abcdef01",
    )


@pytest.fixture
def make_client(settings):
    def _make(repository, verifier=None, token=GOOD_TOKEN):
        # raise_server_exceptions=False: we test the real 500 response, not the exception.
        client = TestClient(
            create_app(settings, repository, verifier or FakeVerifier()),
            raise_server_exceptions=False,
        )
        if token is not None:
            client.headers["Authorization"] = f"Bearer {token}"
        return client

    return _make

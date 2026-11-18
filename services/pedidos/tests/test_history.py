"""GET /orders: the signed-in customer's own history. The isolation itself is
enforced by PostgreSQL (see tests/integration/test_rls.py); these tests cover the
HTTP layer with a fake repository."""
from __future__ import annotations

import pytest

from app.auth import AuthUnavailable
from conftest import SUB, FakeRepository, FakeVerifier

OTHER = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
ONE_ITEM = {"items": [{"product_id": 1, "quantity": 2}]}


def seeded_repo():
    repo = FakeRepository()
    repo.create_order(OTHER, [(3, 1)])      # another customer's order
    repo.create_order(SUB, [(1, 2)])
    repo.create_order(SUB, [(19, 1)])
    return repo


def test_history_requires_a_token(make_client):
    repo = seeded_repo()
    response = make_client(repo, token=None).get("/orders")
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert repo.listed == []


def test_history_with_an_invalid_token_is_401(make_client):
    repo = seeded_repo()
    response = make_client(repo, token="wrong.token.value").get("/orders")
    assert response.status_code == 401
    assert repo.listed == []


def test_history_answers_503_when_signing_keys_are_unavailable(make_client):
    client = make_client(seeded_repo(), verifier=FakeVerifier(error=AuthUnavailable()))
    response = client.get("/orders")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service temporarily unavailable"}


def test_history_returns_only_the_token_owners_orders(make_client):
    repo = seeded_repo()
    response = make_client(repo).get("/orders")
    assert response.status_code == 200
    orders = response.json()
    assert len(orders) == 2
    assert repo.listed == [(SUB, 20)]          # user from the token, default limit
    assert [o["items"][0]["product_id"] for o in orders] == [19, 1]   # newest first


def test_history_never_exposes_the_user_id(make_client):
    response = make_client(seeded_repo()).get("/orders")
    text = response.text
    assert SUB not in text and OTHER not in text and "user_id" not in text
    for order in response.json():
        assert set(order) == {"id", "total", "items", "created_at"}


@pytest.mark.parametrize(
    "query", [f"user_id={OTHER}", f"sub={OTHER}", f"owner={OTHER}", f"userId={OTHER}"]
)
def test_history_ignores_any_user_in_the_query(make_client, query):
    repo = seeded_repo()
    response = make_client(repo).get(f"/orders?{query}")
    assert response.status_code == 200
    assert repo.listed == [(SUB, 20)]
    assert len(response.json()) == 2


def test_history_ignores_user_headers(make_client):
    repo = seeded_repo()
    response = make_client(repo).get(
        "/orders", headers={"X-User-Id": OTHER, "X-Forwarded-User": OTHER}
    )
    assert response.status_code == 200
    assert repo.listed == [(SUB, 20)]


def test_history_limit_is_applied(make_client):
    repo = seeded_repo()
    response = make_client(repo).get("/orders?limit=1")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert repo.listed == [(SUB, 1)]


@pytest.mark.parametrize("limit", ["0", "-1", "51", "1000", "abc", "1.5", ""])
def test_history_limit_out_of_range_is_422_with_a_fixed_message(make_client, limit):
    repo = seeded_repo()
    response = make_client(repo).get(f"/orders?limit={limit}")
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request"}
    assert limit not in response.text or limit == ""
    assert repo.listed == []


def test_history_of_a_customer_without_orders_is_empty(make_client):
    response = make_client(FakeRepository()).get("/orders")
    assert response.status_code == 200
    assert response.json() == []


def test_history_database_error_is_503_without_details(make_client):
    import psycopg

    repo = FakeRepository(error=psycopg.OperationalError("boom-secret"))
    response = make_client(repo).get("/orders")
    assert response.status_code == 503
    assert "boom-secret" not in response.text

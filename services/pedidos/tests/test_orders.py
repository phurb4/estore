import logging

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from app.auth import AuthUnavailable
from app.db import OrderLimitExceeded
from conftest import ALLOWED_ORIGIN, GOOD_TOKEN, SUB, FakeRepository, FakeVerifier


def post(client, body):
    return client.post("/orders", json=body)


def test_health(make_client):
    response = make_client(FakeRepository()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_order_is_priced_by_the_server(make_client):
    repo = FakeRepository()
    response = post(
        make_client(repo),
        {"items": [{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 1}]},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["total"] == "498.98"
    assert [line["unit_price"] for line in body["items"]] == ["99.99", "299.00"]
    assert repo.calls == [[(1, 2), (3, 1)]]


@pytest.mark.parametrize(
    "extra",
    [{"price": "0.01"}, {"unit_price": 1}, {"name": "x"}],
)
def test_client_cannot_send_item_prices(make_client, extra):
    repo = FakeRepository()
    item = {"product_id": 1, "quantity": 1, **extra}
    response = post(make_client(repo), {"items": [item]})
    assert response.status_code == 422
    assert repo.calls == []


def test_client_cannot_send_a_total(make_client):
    repo = FakeRepository()
    response = post(
        make_client(repo),
        {"items": [{"product_id": 1, "quantity": 1}], "total": "0.01"},
    )
    assert response.status_code == 422
    assert repo.calls == []


@pytest.mark.parametrize(
    "item",
    [
        {"product_id": 1, "quantity": 0},
        {"product_id": 1, "quantity": -1},
        {"product_id": 1, "quantity": 100},
        {"product_id": 1, "quantity": "2"},
        {"product_id": 1, "quantity": 1.5},
        {"product_id": 1, "quantity": True},
        {"product_id": 0, "quantity": 1},
        {"product_id": "1", "quantity": 1},
        {"product_id": 2_147_483_648, "quantity": 1},
        {"quantity": 1},
        {"product_id": 1},
    ],
)
def test_invalid_items_are_rejected(make_client, item):
    repo = FakeRepository()
    response = post(make_client(repo), {"items": [item]})
    assert response.status_code == 422
    assert repo.calls == []


def test_empty_too_many_and_duplicate_items_are_rejected(make_client):
    repo = FakeRepository()
    client = make_client(repo)
    assert post(client, {"items": []}).status_code == 422
    many = [{"product_id": n, "quantity": 1} for n in range(1, 52)]
    assert post(client, {"items": many}).status_code == 422
    dup = [{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}]
    assert post(client, {"items": dup}).status_code == 422
    assert post(client, {}).status_code == 422
    assert repo.calls == []


def test_validation_error_does_not_echo_the_input(make_client):
    marker = "marker-should-not-come-back"
    response = post(
        make_client(FakeRepository()),
        {"items": [{"product_id": 1, "quantity": 1, "price": marker}]},
    )
    assert response.status_code == 422
    assert marker not in response.text
    assert response.json() == {"detail": "Invalid order"}


def test_unknown_product_is_rejected(make_client):
    response = post(
        make_client(FakeRepository()),
        {"items": [{"product_id": 999, "quantity": 1}]},
    )
    assert response.status_code == 422
    assert "999" not in response.text


@pytest.mark.parametrize(
    "error", [psycopg.OperationalError("boom-secret"), PoolTimeout("boom-secret")]
)
def test_database_errors_give_503_without_details(make_client, error):
    response = post(
        make_client(FakeRepository(error=error)),
        {"items": [{"product_id": 1, "quantity": 1}]},
    )
    assert response.status_code == 503
    assert "boom-secret" not in response.text


def test_unexpected_error_gives_generic_500(make_client):
    response = post(
        make_client(FakeRepository(error=RuntimeError("boom-secret"))),
        {"items": [{"product_id": 1, "quantity": 1}]},
    )
    assert response.status_code == 500
    assert "boom-secret" not in response.text


ONE_ITEM = {"items": [{"product_id": 1, "quantity": 1}]}


# ---------- authentication ----------
@pytest.mark.parametrize(
    "headers",
    [
        {},                                        # no header
        {"Authorization": "Bearer"},
        {"Authorization": "Basic aaaa.bbbb.cccc"},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Bearer wrong.token.value"},   # well formed, not accepted
    ],
)
def test_order_without_a_valid_token_is_401(make_client, headers):
    repo = FakeRepository()
    client = make_client(repo, token=None)
    response = client.post("/orders", json=ONE_ITEM, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert repo.calls == []


def test_401_comes_before_body_validation(make_client):
    repo = FakeRepository()
    response = make_client(repo, token=None).post("/orders", json={"items": []})
    assert response.status_code == 401
    assert repo.calls == []


def test_signing_keys_unavailable_is_503_with_a_fixed_message(make_client):
    repo = FakeRepository()
    client = make_client(repo, verifier=FakeVerifier(error=AuthUnavailable()))
    response = post(client, ONE_ITEM)
    assert response.status_code == 503
    assert response.json() == {"detail": "Service temporarily unavailable"}
    assert repo.calls == []


# ---------- the customer comes only from the verified token ----------
def test_user_id_is_the_verified_sub(make_client):
    repo = FakeRepository()
    assert post(make_client(repo), ONE_ITEM).status_code == 201
    assert repo.users == [SUB]


@pytest.mark.parametrize("field", ["user_id", "userId", "sub", "owner"])
def test_user_id_in_the_body_is_rejected(make_client, field):
    repo = FakeRepository()
    response = post(make_client(repo), {**ONE_ITEM, field: "someone-else"})
    assert response.status_code == 422
    assert repo.calls == []


def test_user_id_in_an_item_is_rejected(make_client):
    repo = FakeRepository()
    item = {"product_id": 1, "quantity": 1, "user_id": "someone-else"}
    assert post(make_client(repo), {"items": [item]}).status_code == 422
    assert repo.calls == []


def test_user_id_in_query_string_and_other_headers_is_ignored(make_client):
    repo = FakeRepository()
    response = make_client(repo).post(
        "/orders?user_id=someone-else&sub=someone-else",
        json=ONE_ITEM,
        headers={"X-User-Id": "someone-else", "X-Forwarded-User": "someone-else"},
    )
    assert response.status_code == 201
    assert repo.users == [SUB]


# ---------- per-customer limit ----------
def test_order_limit_gives_429_with_a_fixed_message(make_client):
    repo = FakeRepository(error=OrderLimitExceeded())
    response = post(make_client(repo), ONE_ITEM)
    assert response.status_code == 429
    assert response.json() == {"detail": "Order limit reached"}


# ---------- the token never appears in logs or responses ----------
SECRET_TOKEN = "aaaa.secret-marker-in-token.cccc"


@pytest.mark.parametrize(
    "verifier,repo_error",
    [
        (None, None),                                 # invalid token -> 401
        (FakeVerifier(error=AuthUnavailable()), None),  # keys down -> 503
        (None, RuntimeError("boom")),                 # unexpected -> 500
    ],
)
def test_token_is_never_logged_or_echoed(make_client, caplog, verifier, repo_error):
    caplog.set_level(logging.DEBUG)
    token = GOOD_TOKEN if repo_error else SECRET_TOKEN
    client = make_client(FakeRepository(error=repo_error), verifier=verifier, token=token)
    response = post(client, ONE_ITEM)
    assert response.status_code in (401, 503, 500)
    assert "secret-marker-in-token" not in response.text
    assert "secret-marker-in-token" not in caplog.text
    assert GOOD_TOKEN not in caplog.text
    assert "Bearer" not in caplog.text


def test_insecure_jwks_flag_is_announced_in_the_log(settings, caplog):
    from dataclasses import replace
    from app.main import create_app

    caplog.set_level(logging.WARNING)
    create_app(replace(settings, cognito_allow_insecure_jwks=True), FakeRepository(), FakeVerifier())
    assert "COGNITO_ALLOW_INSECURE_JWKS" in caplog.text


def test_only_get_and_post_are_allowed_on_orders(make_client):
    client = make_client(FakeRepository())
    for method in ("put", "patch", "delete"):
        assert getattr(client, method)("/orders").status_code == 405


def test_no_docs_or_openapi(make_client):
    client = make_client(FakeRepository())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_cors_preflight_allows_only_the_configured_origin(make_client):
    client = make_client(FakeRepository())
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    ok = client.options("/orders", headers={"Origin": ALLOWED_ORIGIN, **headers})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    other = client.options("/orders", headers={"Origin": "https://evil.example.test", **headers})
    assert "access-control-allow-origin" not in other.headers

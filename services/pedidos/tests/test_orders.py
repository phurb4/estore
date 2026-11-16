import psycopg
import pytest
from psycopg_pool import PoolTimeout

from conftest import ALLOWED_ORIGIN, FakeRepository


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


def test_get_orders_is_not_allowed(make_client):
    assert make_client(FakeRepository()).get("/orders").status_code == 405


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

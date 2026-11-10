"""Contract with frontend/js/store.js, output validation and error handling."""
import re
from decimal import Decimal

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from conftest import FakeRepository, make_row

# The same rules store.js applies (ID_RE, safeImage, cleanText, cleanPrice).
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
IMAGE_RE = re.compile(r"^img/[\w.\-]+\.(png|jpe?g|webp|gif)$", re.IGNORECASE)
PRICE_RE = re.compile(r"^\d{1,8}\.\d{2}$")

GENERIC_500 = {"detail": "Internal server error"}
GENERIC_503 = {"detail": "Service temporarily unavailable"}


def test_contract_with_store_js(make_client):
    client = make_client(FakeRepository())
    resp = client.get("/products", follow_redirects=False)

    assert resp.status_code == 200  # store.js uses redirect: "error"
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert isinstance(data, list) and len(data) <= 200

    for item in data:
        assert set(item) == {"id", "name", "category", "price", "image"}
        assert ID_RE.match(str(item["id"]))
        assert 1 <= len(item["name"]) <= 120
        assert 1 <= len(item["category"]) <= 60
        assert isinstance(item["price"], str) and PRICE_RE.match(item["price"])
        assert 0 <= Decimal(item["price"]) <= 10_000_000
        assert IMAGE_RE.match(item["image"])


def test_price_keeps_two_decimals_and_image_gets_img_prefix(make_client):
    data = make_client(FakeRepository()).get("/products").json()
    assert [p["price"] for p in data] == ["99.99", "299.00", "399.00"]
    assert [p["image"] for p in data] == [
        "img/product-1.png",
        "img/product-3.png",
        "img/smart-tv-01.png",
    ]
    assert data[1]["category"] == "Mobiles & Tablets"


def test_empty_catalog_is_an_empty_list(make_client):
    resp = make_client(FakeRepository(rows=[])).get("/products")
    assert resp.status_code == 200 and resp.json() == []


@pytest.mark.parametrize(
    "bad_row",
    [
        make_row(price=Decimal("-1")),
        make_row(price=Decimal("10000000.01")),
        make_row(image_file="../x.png"),
        make_row(image_file="x.svg"),
        make_row(image_file="javascript:alert(1).png"),
        make_row(name=""),
        make_row(name="x" * 121),
        make_row(category="x" * 61),
    ],
)
def test_invalid_rows_fail_closed(make_client, bad_row):
    resp = make_client(FakeRepository(rows=[bad_row])).get("/products")
    assert resp.status_code == 500
    assert resp.json() == GENERIC_500
    assert "x.svg" not in resp.text and "../x.png" not in resp.text


@pytest.mark.parametrize(
    "error",
    [
        psycopg.OperationalError("password=SECRET host=10.0.0.5"),
        PoolTimeout("couldn't get a connection after 5 sec"),
    ],
)
def test_database_errors_are_503_without_details(make_client, error):
    resp = make_client(FakeRepository(error=error)).get("/products")
    assert resp.status_code == 503
    assert resp.json() == GENERIC_503
    assert "SECRET" not in resp.text and "10.0.0.5" not in resp.text


def test_unexpected_errors_are_500_without_details(make_client):
    repo = FakeRepository(error=RuntimeError("secret-internal-detail"))
    resp = make_client(repo).get("/products")
    assert resp.status_code == 500
    assert resp.json() == GENERIC_500
    assert "secret-internal-detail" not in resp.text

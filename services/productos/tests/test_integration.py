"""Runs against a real PostgreSQL seeded with db/schema.sql and db/seed.sql.
Skipped unless the DB_* and CORS_ALLOWED_ORIGIN variables are set."""
import re
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, load_settings
from app.main import create_app

pytestmark = pytest.mark.integration

IMAGE_RE = re.compile(r"^img/[\w.\-]+\.(png|jpe?g|webp|gif)$", re.IGNORECASE)


@pytest.fixture(scope="module")
def products():
    try:
        settings = load_settings()
    except ConfigError:
        pytest.skip("Database environment variables are not set")
    with TestClient(create_app(settings)) as client:  # the with-block runs the lifespan
        resp = client.get("/products")
    assert resp.status_code == 200
    return resp.json()


def test_catalog_has_21_products(products):
    assert [p["id"] for p in products] == list(range(1, 22))


def test_products_per_category(products):
    assert Counter(p["category"] for p in products) == {
        "Accessories": 3,
        "Electronics & Computer": 6,
        "Laptops & Desktops": 3,
        "Mobiles & Tablets": 6,
        "Smart TV": 3,
    }


def test_smart_tv_placeholders_and_formats(products):
    tvs = [p for p in products if p["category"] == "Smart TV"]
    assert [p["image"] for p in tvs] == [f"img/smart-tv-0{n}.png" for n in (1, 2, 3)]
    assert all(IMAGE_RE.match(p["image"]) for p in products)
    assert all(re.match(r"^\d{1,8}\.\d{2}$", p["price"]) for p in products)

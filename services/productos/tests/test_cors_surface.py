"""CORS limited to one origin, and a minimal exposed surface."""
import pytest

from conftest import ALLOWED_ORIGIN, FakeRepository


def test_allowed_origin_is_echoed(make_client):
    resp = make_client(FakeRepository()).get("/products", headers={"Origin": ALLOWED_ORIGIN})
    assert resp.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert "access-control-allow-credentials" not in resp.headers


def test_other_origin_gets_no_cors_header(make_client):
    resp = make_client(FakeRepository()).get(
        "/products", headers={"Origin": "https://evil.example.test"}
    )
    assert "access-control-allow-origin" not in resp.headers


def test_wildcard_is_never_used(make_client):
    client = make_client(FakeRepository())
    for origin in (ALLOWED_ORIGIN, "https://evil.example.test"):
        resp = client.get("/products", headers={"Origin": origin})
        assert resp.headers.get("access-control-allow-origin") != "*"


def test_preflight_allows_get_only(make_client):
    client = make_client(FakeRepository())
    ok = client.options(
        "/products",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert ok.status_code == 200
    assert "POST" not in ok.headers["access-control-allow-methods"]

    bad = client.options(
        "/products",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert bad.status_code == 400


def test_post_is_not_allowed(make_client):
    assert make_client(FakeRepository()).post("/products").status_code == 405


@pytest.mark.parametrize("path", ["/products/1", "/docs", "/redoc", "/openapi.json"])
def test_nothing_else_is_exposed(make_client, path):
    assert make_client(FakeRepository()).get(path).status_code == 404

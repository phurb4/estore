"""GET /health: liveness only, no database and no data."""
from conftest import FakeRepository


def test_health_is_ok(make_client):
    resp = make_client(FakeRepository()).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_does_not_touch_the_database(make_client):
    # A repository that always fails must not affect the health answer.
    resp = make_client(FakeRepository(error=RuntimeError("db down"))).get("/health")
    assert resp.status_code == 200

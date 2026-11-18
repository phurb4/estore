"""Token verification tests. A real PyJWKClient talks to a throwaway HTTP server
that serves a JWKS built in the test (keys are generated on every run, nothing
is stored). The server binds to the loopback interface on a free port chosen by
the operating system, so no address or port is fixed. Issuer, client ID and
subject are made up (RFC 2606 .test names)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.auth import AuthError, AuthUnavailable, TokenVerifier, extract_bearer

ISSUER = "https://idp.example.test/pool-one"
CLIENT_ID = "testclient0123456789abcdef01"
KID = "key-one"
LOOPBACK = "127.0.0.1"  # test server only; the port is chosen by the OS


def _new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private_key, kid):
    data = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    data.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return data


class JwksServer:
    def __init__(self):
        self.keys = []
        self.hits = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (http.server API)
                outer.hits += 1
                body = json.dumps({"keys": outer.keys}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer((LOOPBACK, 0), Handler)
        self.url = f"http://{LOOPBACK}:{self._server.server_address[1]}/jwks.json"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture(scope="module")
def key():
    return _new_key()


@pytest.fixture
def server(key):
    srv = JwksServer()
    srv.keys = [_jwk(key, KID)]
    yield srv
    try:
        srv.stop()
    except Exception:  # already stopped by the test
        pass


@pytest.fixture
def verifier(server):
    return TokenVerifier(ISSUER, server.url, CLIENT_ID, jwks_cooldown=0)


def make_token(key, *, kid=KID, alg="RS256", **overrides):
    now = int(time.time())
    claims = {
        "sub": str(uuid.uuid4()),
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    for name in [n for n, v in claims.items() if v is None]:
        del claims[name]          # an override of None removes the claim
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


# ---------- valid token ----------
def test_valid_token_returns_sub(verifier, key):
    sub = str(uuid.uuid4())
    assert verifier.verify(make_token(key, sub=sub)) == sub


def test_sub_is_lowercased(verifier, key):
    sub = str(uuid.uuid4())
    assert verifier.verify(make_token(key, sub=sub.upper())) == sub


def test_clock_skew_within_leeway_is_accepted(verifier, key):
    assert verifier.verify(make_token(key, iat=int(time.time()) + 2))


# ---------- claims ----------
@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 600},                 # expired
        {"exp": None},                                   # no exp
        {"iss": "https://idp.example.test/other-pool"},  # other issuer
        {"iss": None},
        {"client_id": "someoneelsesclient000000001"},    # other app client
        {"client_id": None},
        {"token_use": "id"},                             # an ID token
        {"token_use": None},
        {"sub": "not-a-uuid"},
        {"sub": None},
        {"sub": 12345},
        {"sub": str(uuid.uuid4()) + "'; --"},
    ],
)
def test_bad_claims_are_rejected(verifier, key, overrides):
    with pytest.raises(AuthError):
        verifier.verify(make_token(key, **overrides))


def test_id_token_shape_is_rejected(verifier, key):
    # ID token: aud instead of client_id, token_use "id".
    token = make_token(key, client_id=None, aud=CLIENT_ID, token_use="id")
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_aud_claim_is_not_required(verifier, key):
    # Access tokens have no aud unless a resource binding was requested.
    assert verifier.verify(make_token(key))


# ---------- signature and algorithm ----------
def test_token_signed_by_another_key_is_rejected(verifier):
    with pytest.raises(AuthError):
        verifier.verify(make_token(_new_key()))


def test_tampered_payload_is_rejected(verifier, key):
    header, payload, signature = make_token(key).split(".")
    padded = payload + "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    claims["sub"] = str(uuid.uuid4())
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(AuthError):
        verifier.verify(f"{header}.{forged}.{signature}")


def test_alg_none_is_rejected(verifier):
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iss": ISSUER, "client_id": CLIENT_ID,
         "token_use": "access", "exp": int(time.time()) + 3600},
        None, algorithm="none", headers={"kid": KID},
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_hs256_with_public_key_as_secret_is_rejected(verifier, key):
    # Algorithm-confusion attempt. PyJWT refuses to build such a token, so it
    # is assembled by hand: HMAC-SHA256 keyed with the public JWK text.
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
    payload = b64(json.dumps({
        "sub": str(uuid.uuid4()), "iss": ISSUER, "client_id": CLIENT_ID,
        "token_use": "access", "exp": int(time.time()) + 3600,
    }).encode())
    secret = json.dumps(_jwk(key, KID)).encode()
    signature = b64(hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    token = f"{header}.{payload}.{signature}"
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_unknown_kid_is_rejected(verifier, key):
    with pytest.raises(AuthError):
        verifier.verify(make_token(key, kid="key-unknown"))


def test_token_without_kid_is_rejected_without_network(server, key):
    verifier = TokenVerifier(ISSUER, server.url, CLIENT_ID)
    token = jwt.encode({"sub": str(uuid.uuid4())}, key, algorithm="RS256")
    with pytest.raises(AuthError):
        verifier.verify(token)
    assert server.hits == 0


@pytest.mark.parametrize(
    "token", ["", "abc", "a.b", "a.b.c", "....", " ", "x" * 5000, None, 123]
)
def test_malformed_tokens_are_rejected(verifier, token):
    with pytest.raises(AuthError):
        verifier.verify(token)


# ---------- JWKS cache, rotation and outage ----------
def test_key_set_is_cached(server, key):
    verifier = TokenVerifier(ISSUER, server.url, CLIENT_ID)
    for _ in range(3):
        verifier.verify(make_token(key))
    assert server.hits == 1


def test_unknown_kid_forces_refresh_and_picks_up_rotated_key(server, key):
    verifier = TokenVerifier(ISSUER, server.url, CLIENT_ID, jwks_cooldown=0)
    verifier.verify(make_token(key))
    new_key = _new_key()
    server.keys.append(_jwk(new_key, "key-two"))
    assert verifier.verify(make_token(new_key, kid="key-two"))


def test_forced_refresh_respects_cooldown(server, key):
    verifier = TokenVerifier(ISSUER, server.url, CLIENT_ID, jwks_cooldown=3600)
    verifier.verify(make_token(key))
    hits = server.hits
    for _ in range(5):
        with pytest.raises(AuthError):
            verifier.verify(make_token(key, kid="key-unknown"))
    assert server.hits == hits   # random kids cannot make us hammer the endpoint


def test_cached_keys_still_work_while_endpoint_is_down(server, key):
    verifier = TokenVerifier(ISSUER, server.url, CLIENT_ID)
    verifier.verify(make_token(key))
    server.stop()
    assert verifier.verify(make_token(key))


def test_endpoint_down_with_cold_cache_is_unavailable(server, key):
    server.stop()
    verifier = TokenVerifier(ISSUER, server.url, CLIENT_ID, timeout=1)
    with pytest.raises(AuthUnavailable):
        verifier.verify(make_token(key))


# ---------- the whole service with the real verifier ----------
def _client(settings, server, repo):
    from fastapi.testclient import TestClient
    from app.main import create_app

    verifier = TokenVerifier(ISSUER, server.url, CLIENT_ID, timeout=1)
    return TestClient(create_app(settings, repo, verifier), raise_server_exceptions=False)


ONE_ITEM = {"items": [{"product_id": 1, "quantity": 1}]}


def test_service_end_to_end_stores_the_normalized_sub(settings, server, key):
    from conftest import FakeRepository

    repo = FakeRepository()
    sub = str(uuid.uuid4())
    token = make_token(key, sub=sub.upper())
    response = _client(settings, server, repo).post(
        "/orders", json=ONE_ITEM, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    assert repo.users == [sub]


def test_service_rejects_an_id_token_and_never_logs_the_token(settings, server, key, caplog):
    import logging
    from conftest import FakeRepository

    caplog.set_level(logging.DEBUG)
    repo = FakeRepository()
    token = make_token(key, client_id=None, aud=CLIENT_ID, token_use="id")
    response = _client(settings, server, repo).post(
        "/orders", json=ONE_ITEM, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert repo.calls == []
    assert token not in caplog.text and token not in response.text
    assert token.split(".")[1] not in caplog.text


def test_service_answers_503_when_keys_are_unreachable_and_logs_no_token(settings, server, key, caplog):
    import logging
    from conftest import FakeRepository

    caplog.set_level(logging.DEBUG)
    server.stop()
    repo = FakeRepository()
    token = make_token(key)
    response = _client(settings, server, repo).post(
        "/orders", json=ONE_ITEM, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Service temporarily unavailable"}
    assert repo.calls == []
    assert token not in caplog.text and token.split(".")[1] not in caplog.text


# ---------- Authorization header ----------
def test_extract_bearer_accepts_the_standard_form():
    token = "aaa.bbb.ccc"
    assert extract_bearer(f"Bearer {token}") == token
    assert extract_bearer(f"bearer {token}") == token


@pytest.mark.parametrize(
    "value",
    [None, "", "Bearer", "Bearer ", "Basic aaa.bbb.ccc", "Bearer aaa.bbb",
     "Bearer aaa.bbb.ccc extra", "Bearer  aaa.bbb.ccc", "Bearer aaa.bbb.c c",
     "Bearer " + "a" * 5000 + ".b.c"],
)
def test_extract_bearer_rejects_other_forms(value):
    with pytest.raises(AuthError):
        extract_bearer(value)

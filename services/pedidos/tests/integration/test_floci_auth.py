"""Token validation against REAL Floci tokens (Cognito emulator).

Run from a container on the Compose network (see the runner in the README of
the tests / the session notes):

    pytest -m integration tests/integration/test_floci_auth.py

Needs these variables (the runner passes them; none is written here):
  INTEGRATION_FLOCI_URL          address of Floci inside the network
  INTEGRATION_FLOCI_ISSUER_BASE  address Floci puts in the "iss" claim (its
                                 FLOCI_BASE_URL); the issuer is <base>/<pool>
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
                                 any placeholder values: Floci does not check them

The module creates its own throwaway user pool and app client (with
ALLOW_ADMIN_USER_PASSWORD_AUTH, only so the test can obtain tokens without a
browser) and deletes the pool at the end. It touches nothing else in Floci.
Passwords are random and live only in memory.
"""
from __future__ import annotations

import os
import secrets
import uuid

import pytest

# boto3 is only in requirements-dev.txt: without it the module is skipped, so a
# plain "pytest" never fails at collection.
boto3 = pytest.importorskip("boto3")
from botocore.config import Config  # noqa: E402

from app.auth import AuthError, TokenVerifier  # noqa: E402
from conftest import FakeRepository  # noqa: E402

pytestmark = pytest.mark.integration

ONE_ITEM = {"items": [{"product_id": 1, "quantity": 1}]}


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set (run through the Floci test runner)")
    return value


def _password() -> str:
    return "Aa1!" + secrets.token_hex(12)


class Pool:
    """A throwaway pool + client, and helpers to create users and tokens."""

    def __init__(self):
        self.url = _env("INTEGRATION_FLOCI_URL").rstrip("/")
        self.issuer_base = _env("INTEGRATION_FLOCI_ISSUER_BASE").rstrip("/")
        self.client = boto3.client(
            "cognito-idp",
            endpoint_url=self.url,
            region_name=_env("AWS_DEFAULT_REGION"),
            config=Config(retries={"max_attempts": 1}, connect_timeout=5, read_timeout=10),
        )
        self.pool_id = self.client.create_user_pool(PoolName=f"it-{uuid.uuid4().hex[:8]}")[
            "UserPool"
        ]["Id"]
        self.client_id = self.client.create_user_pool_client(
            UserPoolId=self.pool_id,
            ClientName="integration",
            GenerateSecret=False,
            ExplicitAuthFlows=["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        )["UserPoolClient"]["ClientId"]

    @property
    def issuer(self) -> str:
        return f"{self.issuer_base}/{self.pool_id}"

    @property
    def jwks_url(self) -> str:
        return f"{self.url}/{self.pool_id}/.well-known/jwks.json"

    def verifier(self, **overrides) -> TokenVerifier:
        args = dict(issuer=self.issuer, jwks_url=self.jwks_url, client_id=self.client_id)
        args.update(overrides)
        return TokenVerifier(
            args["issuer"], args["jwks_url"], args["client_id"], timeout=5
        )

    def user_with_tokens(self):
        """Creates a user; returns (sub, access_token, id_token)."""
        username = f"user-{uuid.uuid4().hex[:10]}@example.test"
        password = _password()
        self.client.admin_create_user(
            UserPoolId=self.pool_id,
            Username=username,
            MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": username}],
        )
        self.client.admin_set_user_password(
            UserPoolId=self.pool_id, Username=username, Password=password, Permanent=True
        )
        user = self.client.admin_get_user(UserPoolId=self.pool_id, Username=username)
        sub = next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")
        auth = self.client.admin_initiate_auth(
            UserPoolId=self.pool_id,
            ClientId=self.client_id,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )["AuthenticationResult"]
        return sub, auth["AccessToken"], auth["IdToken"]

    def delete(self):
        self.client.delete_user_pool(UserPoolId=self.pool_id)


@pytest.fixture(scope="module")
def pool():
    p = Pool()
    try:
        yield p
    finally:
        p.delete()


@pytest.fixture(scope="module")
def alice(pool):
    return pool.user_with_tokens()


@pytest.fixture(scope="module")
def bob(pool):
    return pool.user_with_tokens()


def test_a_real_access_token_is_accepted_and_gives_the_sub(pool, alice):
    sub, access, _ = alice
    assert pool.verifier().verify(access) == sub.lower()


def test_each_user_gets_their_own_sub(pool, alice, bob):
    assert pool.verifier().verify(alice[1]) != pool.verifier().verify(bob[1])


def test_a_real_id_token_is_rejected(pool, alice):
    with pytest.raises(AuthError):
        pool.verifier().verify(alice[2])


def test_a_token_of_another_client_is_rejected(pool, alice):
    other_client = "x" * len(pool.client_id)
    with pytest.raises(AuthError):
        pool.verifier(client_id=other_client).verify(alice[1])


def test_a_different_issuer_is_rejected(pool, alice):
    with pytest.raises(AuthError):
        pool.verifier(issuer=f"{pool.issuer_base}/other_pool").verify(alice[1])


def test_a_tampered_signature_is_rejected(pool, alice):
    head, payload, signature = alice[1].split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(AuthError):
        pool.verifier().verify(f"{head}.{payload}.{flipped}")


def test_a_tampered_payload_is_rejected(pool, alice, bob):
    head, _, signature = alice[1].split(".")
    other_payload = bob[1].split(".")[1]
    with pytest.raises(AuthError):
        pool.verifier().verify(f"{head}.{other_payload}.{signature}")


def test_the_whole_service_accepts_a_real_token(pool, alice, settings):
    """GET and POST /orders with the real verifier; the fake repository records
    which user the service passed down (only the sub of the token)."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    sub, access, id_token = alice
    repo = FakeRepository()
    client = TestClient(
        create_app(settings, repo, pool.verifier()), raise_server_exceptions=False
    )

    created = client.post(
        "/orders", json=ONE_ITEM, headers={"Authorization": f"Bearer {access}"}
    )
    assert created.status_code == 201
    listed = client.get("/orders", headers={"Authorization": f"Bearer {access}"})
    assert listed.status_code == 200
    assert repo.users == [sub.lower()]
    assert repo.listed[0][0] == sub.lower()

    rejected = client.get("/orders", headers={"Authorization": f"Bearer {id_token}"})
    assert rejected.status_code == 401

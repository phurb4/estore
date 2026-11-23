"""Reading database credentials from a REAL Secrets Manager call (Floci).

Needs INTEGRATION_FLOCI_URL, AWS_DEFAULT_REGION and placeholder
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (Floci does not check them). The test
creates its own throwaway secret with a random password, reads it through the
service code (AWS_ENDPOINT_URL points boto3 at Floci) and deletes it.
"""
from __future__ import annotations

import json
import os
import secrets
import uuid

import pytest

boto3 = pytest.importorskip("boto3")

from app.config import ConfigError, load_settings  # noqa: E402
from app.db_secret import SecretError, read_db_credentials  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def floci_secret(monkeypatch):
    url = os.environ.get("INTEGRATION_FLOCI_URL")
    if not url:
        pytest.skip("INTEGRATION_FLOCI_URL is not set (run through the Floci test runner)")
    monkeypatch.setenv("AWS_ENDPOINT_URL", url)
    client = boto3.client("secretsmanager", endpoint_url=url)
    name = f"it/{uuid.uuid4().hex[:8]}"
    password = secrets.token_hex(12)
    client.create_secret(
        Name=name, SecretString=json.dumps({"username": "it_user", "password": password})
    )
    yield name, password, client
    client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)


def test_reads_username_and_password(floci_secret):
    name, password, _ = floci_secret
    assert read_db_credentials(name) == ("it_user", password)


def test_settings_use_the_secret(floci_secret):
    name, password, _ = floci_secret
    env = {
        "DB_HOST": "db.invalid",
        "DB_PORT": "5432",
        "DB_NAME": "test_db",
        "CORS_ALLOWED_ORIGIN": "https://shop.example.test",
        "COGNITO_ISSUER": "https://idp.example.test/pool-one",
        "COGNITO_JWKS_URL": "https://idp.example.test/pool-one/.well-known/jwks.json",
        "COGNITO_APP_CLIENT_ID": "testclient0123456789abcdef01",
        "DB_SECRET_ID": name,
    }
    settings = load_settings(env)
    assert (settings.db_user, settings.db_password) == ("it_user", password)


def test_missing_secret_fails_without_leaking(floci_secret):
    with pytest.raises(SecretError) as err:
        read_db_credentials("it/does-not-exist")
    assert "does-not-exist" not in str(err.value)


def test_wrong_shape_is_refused(floci_secret):
    name, _, client = floci_secret
    client.put_secret_value(SecretId=name, SecretString=json.dumps({"username": "only"}))
    with pytest.raises(SecretError):
        read_db_credentials(name)


def test_config_error_when_secret_is_missing(floci_secret):
    env = {
        "DB_HOST": "db.invalid",
        "DB_PORT": "5432",
        "DB_NAME": "test_db",
        "CORS_ALLOWED_ORIGIN": "https://shop.example.test",
        "COGNITO_ISSUER": "https://idp.example.test/pool-one",
        "COGNITO_JWKS_URL": "https://idp.example.test/pool-one/.well-known/jwks.json",
        "COGNITO_APP_CLIENT_ID": "testclient0123456789abcdef01",
        "DB_SECRET_ID": "it/does-not-exist",
    }
    with pytest.raises(ConfigError):
        load_settings(env)

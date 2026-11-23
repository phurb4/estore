"""Credentials from Secrets Manager: a fake reader stands in for AWS, so these
tests need no network. Values are generated on every run."""
from __future__ import annotations

import secrets

import pytest

from app.config import ConfigError, load_settings
from app.db_secret import SecretError, is_valid_secret_id

CLIENT = "testclient0123456789abcdef01"


@pytest.fixture
def env():
    return {
        "DB_HOST": "db.invalid",
        "DB_PORT": "5432",
        "DB_NAME": "test_db",
        "CORS_ALLOWED_ORIGIN": "https://shop.example.test",
        "COGNITO_ISSUER": "https://idp.example.test/pool-one",
        "COGNITO_JWKS_URL": "https://idp.example.test/pool-one/.well-known/jwks.json",
        "COGNITO_APP_CLIENT_ID": CLIENT,
        "DB_SECRET_ID": "estore/db/test",
    }


def test_credentials_come_from_the_secret_not_the_environment(env):
    password = secrets.token_urlsafe(16)
    settings = load_settings(env, secret_reader=lambda _id: ("secret_user", password))
    assert (settings.db_user, settings.db_password) == ("secret_user", password)
    assert password not in repr(settings)


def test_reader_receives_the_secret_id(env):
    seen = []
    load_settings(env, secret_reader=lambda sid: seen.append(sid) or ("u", "p"))
    assert seen == ["estore/db/test"]


@pytest.mark.parametrize("name", ["DB_USER", "DB_PASSWORD"])
def test_secret_and_environment_credentials_together_are_refused(env, name):
    env[name] = "x"
    with pytest.raises(ConfigError, match="not both"):
        load_settings(env, secret_reader=lambda _id: ("u", "p"))


@pytest.mark.parametrize("bad", ["has space", "a;b", "x" * 513, "ok\n"])
def test_invalid_secret_id_is_refused(env, bad):
    env["DB_SECRET_ID"] = bad
    called = []
    with pytest.raises(ConfigError, match="DB_SECRET_ID"):
        load_settings(env, secret_reader=lambda sid: called.append(sid) or ("u", "p"))
    assert called == []


def test_reader_failure_becomes_a_config_error_without_values(env):
    def failing(_secret_id):
        raise SecretError("Could not read the database secret (Boom)")

    with pytest.raises(ConfigError, match="Could not read"):
        load_settings(env, secret_reader=failing)


def test_without_secret_id_the_environment_is_used(env):
    del env["DB_SECRET_ID"]
    env["DB_USER"] = "env_user"
    env["DB_PASSWORD"] = secrets.token_urlsafe(8)
    settings = load_settings(env, secret_reader=lambda _id: pytest.fail("not expected"))
    assert settings.db_user == "env_user"


def test_secret_id_validation():
    assert is_valid_secret_id("estore/db/orders")
    assert not is_valid_secret_id("")
    assert not is_valid_secret_id("a b")

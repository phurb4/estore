"""Configuration comes only from the environment and is validated."""
import secrets

import pytest

from app.config import ConfigError, load_settings


@pytest.fixture
def env():
    return {
        "DB_HOST": "db.invalid",
        "DB_PORT": "5432",
        "DB_USER": "test_user",
        "DB_PASSWORD": secrets.token_urlsafe(16),
        "DB_NAME": "test_db",
        "CORS_ALLOWED_ORIGIN": "https://shop.example.test",
    }


def test_valid_environment(env):
    s = load_settings(env)
    assert (s.db_host, s.db_port, s.db_user, s.db_name) == ("db.invalid", 5432, "test_user", "test_db")
    assert s.db_sslmode == "prefer"  # default
    assert s.cors_allowed_origin == "https://shop.example.test"


def test_password_is_not_in_repr(env):
    assert env["DB_PASSWORD"] not in repr(load_settings(env))


@pytest.mark.parametrize(
    "name",
    ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "CORS_ALLOWED_ORIGIN"],
)
def test_missing_variable_is_named_but_no_values_leak(env, name):
    del env[name]
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert name in str(exc.value)
    assert env["DB_PASSWORD"] not in str(exc.value) if name != "DB_PASSWORD" else True


def test_empty_variable_counts_as_missing(env):
    env["DB_HOST"] = ""
    with pytest.raises(ConfigError):
        load_settings(env)


@pytest.mark.parametrize("port", ["abc", "0", "70000", "-1", "5432.0", " 5432"])
def test_invalid_port(env, port):
    env["DB_PORT"] = port
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert env["DB_PASSWORD"] not in str(exc.value)


def test_sslmode_is_validated(env):
    env["DB_SSLMODE"] = "verify-full"
    assert load_settings(env).db_sslmode == "verify-full"
    env["DB_SSLMODE"] = "nope"
    with pytest.raises(ConfigError):
        load_settings(env)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.test",
        "https://shop.example.test/",
        "https://shop.example.test/path",
        "https://shop.example.test?a=1",
        "https://user:pw@shop.example.test",
        "https://shop.example.test:abc",
        "ftp://shop.example.test",
        "shop.example.test",
    ],
)
def test_invalid_origin_is_rejected(env, origin):
    env["CORS_ALLOWED_ORIGIN"] = origin
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert origin not in str(exc.value)


@pytest.mark.parametrize("origin", ["https://shop.example.test", "http://host.test:5500"])
def test_valid_origin_is_accepted(env, origin):
    env["CORS_ALLOWED_ORIGIN"] = origin
    assert load_settings(env).cors_allowed_origin == origin

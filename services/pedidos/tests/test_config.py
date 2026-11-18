"""Configuration tests. Values are made up (RFC 2606 .test names, a client ID and
a password generated on every run). Errors must name the variable, never print
its value."""
from __future__ import annotations

import secrets

import pytest

from app.config import ConfigError, load_settings

ISSUER = "https://idp.example.test/pool-one"
JWKS = "https://idp.example.test/pool-one/.well-known/jwks.json"
CLIENT = "testclient0123456789abcdef01"


@pytest.fixture
def env():
    return {
        "DB_HOST": "db.invalid",
        "DB_PORT": "5432",
        "DB_USER": "test_user",
        "DB_PASSWORD": secrets.token_urlsafe(16),
        "DB_NAME": "test_db",
        "CORS_ALLOWED_ORIGIN": "https://shop.example.test",
        "COGNITO_ISSUER": ISSUER,
        "COGNITO_JWKS_URL": JWKS,
        "COGNITO_APP_CLIENT_ID": CLIENT,
    }


def test_valid_environment_loads_with_safe_defaults(env):
    settings = load_settings(env)
    assert settings.cognito_issuer == ISSUER
    assert settings.cognito_jwks_url == JWKS
    assert settings.cognito_app_client_id == CLIENT
    assert settings.cognito_allow_insecure_jwks is False
    assert settings.max_orders_per_hour == 10


@pytest.mark.parametrize(
    "name", ["COGNITO_ISSUER", "COGNITO_JWKS_URL", "COGNITO_APP_CLIENT_ID"]
)
def test_missing_cognito_variable_stops_the_service(env, name):
    del env[name]
    with pytest.raises(ConfigError, match=name):
        load_settings(env)


# ---------- http is refused unless the local flag is on ----------
@pytest.mark.parametrize("name", ["COGNITO_ISSUER", "COGNITO_JWKS_URL"])
def test_http_url_is_rejected_by_default(env, name):
    env[name] = "http://idp.example.test/pool-one"
    with pytest.raises(ConfigError, match=name):
        load_settings(env)


@pytest.mark.parametrize("flag", ["false", ""])
def test_http_is_still_rejected_when_the_flag_is_off(env, flag):
    env["COGNITO_JWKS_URL"] = "http://idp.example.test/jwks.json"
    env["COGNITO_ALLOW_INSECURE_JWKS"] = flag
    with pytest.raises(ConfigError, match="COGNITO_JWKS_URL"):
        load_settings(env)


def test_http_is_accepted_only_with_the_flag_on(env):
    env["COGNITO_ISSUER"] = "http://idp.example.test/pool-one"
    env["COGNITO_JWKS_URL"] = "http://idp.example.test/pool-one/jwks.json"
    env["COGNITO_ALLOW_INSECURE_JWKS"] = "true"
    settings = load_settings(env)
    assert settings.cognito_allow_insecure_jwks is True
    assert settings.cognito_jwks_url.startswith("http://")


@pytest.mark.parametrize("flag", ["TRUE", "True", "1", "yes", "on", " true", "truee"])
def test_flag_only_accepts_the_exact_words(env, flag):
    env["COGNITO_ALLOW_INSECURE_JWKS"] = flag
    with pytest.raises(ConfigError, match="COGNITO_ALLOW_INSECURE_JWKS"):
        load_settings(env)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://idp.example.test/pool",
        "javascript:alert(1)",
        "https://",
        "https://user:pw@idp.example.test/pool",
        "https://idp.example.test/pool?x=1",
        "https://idp.example.test/pool#frag",
        "https://idp.example.test:notaport/pool",
        "https://idp.example.test/po ol",
        "https://idp.example.test/pool\n",
        "idp.example.test/pool",
    ],
)
def test_malformed_urls_are_rejected_even_with_the_flag(env, url):
    env["COGNITO_ALLOW_INSECURE_JWKS"] = "true"
    env["COGNITO_JWKS_URL"] = url
    with pytest.raises(ConfigError, match="COGNITO_JWKS_URL"):
        load_settings(env)


# ---------- client ID and limit ----------
@pytest.mark.parametrize("client", ["", "has space", "semi;colon", "a" * 129, "ñandú"])
def test_bad_client_id_is_rejected(env, client):
    env["COGNITO_APP_CLIENT_ID"] = client
    with pytest.raises(ConfigError):
        load_settings(env)


@pytest.mark.parametrize("raw,expected", [("1", 1), ("25", 25), ("1000", 1000)])
def test_orders_limit_accepts_a_whole_number(env, raw, expected):
    env["ORDERS_MAX_PER_HOUR"] = raw
    assert load_settings(env).max_orders_per_hour == expected


@pytest.mark.parametrize("raw", ["0", "1001", "-5", "1.5", "ten", "٣", "1e3"])
def test_orders_limit_rejects_other_values(env, raw):
    env["ORDERS_MAX_PER_HOUR"] = raw
    with pytest.raises(ConfigError, match="ORDERS_MAX_PER_HOUR"):
        load_settings(env)


# ---------- errors never print values ----------
def test_errors_do_not_print_the_values(env):
    marker = "marker-should-not-appear"
    env["COGNITO_ISSUER"] = f"http://{marker}.test/pool"
    with pytest.raises(ConfigError) as caught:
        load_settings(env)
    assert marker not in str(caught.value)
    assert env["DB_PASSWORD"] not in repr(load_settings({**env, "COGNITO_ISSUER": ISSUER}))

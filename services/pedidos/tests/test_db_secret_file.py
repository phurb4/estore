"""Credentials from a mounted JSON file (DB_SECRET_FILE). Files are created in
pytest's tmp_path and values are generated on every run."""
from __future__ import annotations

import json
import secrets

import pytest

from app.config import ConfigError, load_settings
from app.db_secret import SecretError, read_db_credentials_file


@pytest.fixture
def env(tmp_path):
    return {
        "DB_HOST": "db.invalid",
        "DB_PORT": "5432",
        "DB_NAME": "test_db",
        "CORS_ALLOWED_ORIGIN": "https://shop.example.test",
        "COGNITO_ISSUER": "https://idp.example.test/pool-one",
        "COGNITO_JWKS_URL": "https://idp.example.test/pool-one/.well-known/jwks.json",
        "COGNITO_APP_CLIENT_ID": "abcdefghij1234567890klmnop",
        "DB_SECRET_FILE": str(tmp_path / "db.json"),
    }


def _write(env, payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    with open(env["DB_SECRET_FILE"], "w", encoding="utf-8") as handle:
        handle.write(text)


def test_credentials_come_from_the_file(env):
    password = secrets.token_urlsafe(16)
    _write(env, {"username": "file_user", "password": password})
    settings = load_settings(env)
    assert (settings.db_user, settings.db_password) == ("file_user", password)
    assert password not in repr(settings)


def test_file_reader_is_injectable_and_gets_the_path(env):
    seen = []

    def fake(path):
        seen.append(path)
        return "u", "p"

    settings = load_settings(env, file_reader=fake)
    assert seen == [env["DB_SECRET_FILE"]]
    assert settings.db_user == "u"


@pytest.mark.parametrize("name", ["DB_USER", "DB_PASSWORD"])
def test_file_and_environment_credentials_together_are_refused(env, name):
    env[name] = "x"
    with pytest.raises(ConfigError, match="not both"):
        load_settings(env, file_reader=lambda _p: ("u", "p"))


def test_file_and_secret_id_together_are_refused(env):
    env["DB_SECRET_ID"] = "estore/db/test"
    with pytest.raises(ConfigError, match="not both"):
        load_settings(env, file_reader=lambda _p: ("u", "p"))


def test_missing_file_is_a_config_error_without_the_path_contents(env):
    with pytest.raises(ConfigError, match="Could not read the database secret file"):
        load_settings(env)


def test_relative_path_is_refused(env):
    env["DB_SECRET_FILE"] = "relative/db.json"
    with pytest.raises(ConfigError, match="absolute"):
        load_settings(env)


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        {"username": "u"},
        {"password": "p"},
        {"username": "", "password": "p"},
        {"username": "u", "password": 5},
    ],
)
def test_malformed_file_is_refused_without_leaking_values(env, payload):
    _write(env, payload)
    with pytest.raises(ConfigError, match="database secret"):
        load_settings(env)


def test_oversized_file_is_refused(env):
    _write(env, "x" * (64 * 1024 + 1))
    with pytest.raises(SecretError, match="too large"):
        read_db_credentials_file(env["DB_SECRET_FILE"])


def test_trailing_newline_in_file_is_accepted(env):
    _write(env, json.dumps({"username": "u", "password": "p"}) + "\n")
    assert read_db_credentials_file(env["DB_SECRET_FILE"]) == ("u", "p")

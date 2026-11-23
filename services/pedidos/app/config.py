"""Settings, read only from environment variables.

No address, port or credential is written in the code. A missing or invalid
variable stops the service at start-up; error messages name the variable but
never print its value.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Mapping
from urllib.parse import urlsplit

from .db_secret import SecretError, is_valid_secret_id, read_db_credentials

_REQUIRED = (
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "CORS_ALLOWED_ORIGIN",
    "COGNITO_ISSUER",
    "COGNITO_JWKS_URL",
    "COGNITO_APP_CLIENT_ID",
)
_SSLMODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
_DEFAULT_SSLMODE = "prefer"
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9]{1,128}$")
_DEFAULT_MAX_ORDERS_PER_HOUR = 10
_MAX_ORDERS_PER_HOUR_LIMIT = 1000


class ConfigError(RuntimeError):
    """Invalid or missing configuration. The message never contains values."""


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_user: str
    db_password: str = field(repr=False)
    db_name: str
    db_sslmode: str
    cors_allowed_origin: str
    cognito_issuer: str
    cognito_jwks_url: str
    cognito_app_client_id: str
    cognito_allow_insecure_jwks: bool = False
    max_orders_per_hour: int = _DEFAULT_MAX_ORDERS_PER_HOUR


def _parse_port(raw: str) -> int:
    if not raw.isascii() or not raw.isdigit():
        raise ConfigError("DB_PORT must be a whole number between 1 and 65535")
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ConfigError("DB_PORT must be a whole number between 1 and 65535")
    return port


def _parse_origin(raw: str) -> str:
    """Accept only scheme://host[:port]: no wildcard, path, query or userinfo."""
    message = "CORS_ALLOWED_ORIGIN must look like scheme://host[:port]"
    if "*" in raw:
        raise ConfigError(message)
    try:
        parts = urlsplit(raw)
        _ = parts.port  # raises ValueError when the port is not valid
    except ValueError:
        raise ConfigError(message) from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError(message)
    if parts.username or parts.password:
        raise ConfigError(message)
    if f"{parts.scheme}://{parts.netloc}" != raw:
        raise ConfigError(message)
    return raw


def _parse_bool(name: str, raw: str | None) -> bool:
    """Only the exact words true / false. Unset means false."""
    if raw is None or raw == "":
        return False
    if raw not in ("true", "false"):
        raise ConfigError(f"{name} must be true or false")
    return raw == "true"


def _parse_https_url(name: str, raw: str, allow_http: bool) -> str:
    """scheme://host[:port][/path]: no userinfo, query or fragment.

    https is required. http is accepted only when COGNITO_ALLOW_INSECURE_JWKS
    is true (local emulator inside the Compose network, never real AWS).
    """
    message = f"{name} must be an https URL without credentials, query or fragment"
    if any(ch.isspace() or ord(ch) < 32 for ch in raw):
        raise ConfigError(message)
    try:
        parts = urlsplit(raw)
        _ = parts.port  # raises ValueError when the port is not valid
    except ValueError:
        raise ConfigError(message) from None
    allowed = ("https", "http") if allow_http else ("https",)
    if parts.scheme not in allowed or not parts.hostname:
        raise ConfigError(message)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError(message)
    return raw


def _parse_client_id(raw: str) -> str:
    if not _CLIENT_ID_RE.match(raw):
        raise ConfigError("COGNITO_APP_CLIENT_ID is not a valid app client ID")
    return raw


def _parse_max_orders(raw: str | None) -> int:
    if raw is None or raw == "":
        return _DEFAULT_MAX_ORDERS_PER_HOUR
    message = f"ORDERS_MAX_PER_HOUR must be a whole number between 1 and {_MAX_ORDERS_PER_HOUR_LIMIT}"
    if not raw.isascii() or not raw.isdigit():
        raise ConfigError(message)
    value = int(raw)
    if not 1 <= value <= _MAX_ORDERS_PER_HOUR_LIMIT:
        raise ConfigError(message)
    return value


def _resolve_db_credentials(
    source: Mapping[str, str],
    secret_reader: Callable[[str], tuple[str, str]],
) -> tuple[str, str]:
    """(user, password): from Secrets Manager when DB_SECRET_ID is set, else from
    DB_USER / DB_PASSWORD. Using both is refused: with a secret there must be no
    password in the environment."""
    secret_id = source.get("DB_SECRET_ID")
    if not secret_id:
        return source["DB_USER"], source["DB_PASSWORD"]
    if source.get("DB_USER") or source.get("DB_PASSWORD"):
        raise ConfigError("Set DB_SECRET_ID or DB_USER/DB_PASSWORD, not both")
    if not is_valid_secret_id(secret_id):
        raise ConfigError("DB_SECRET_ID is not a valid secret name")
    try:
        return secret_reader(secret_id)
    except SecretError as exc:
        raise ConfigError(str(exc)) from None


def load_settings(
    env: Mapping[str, str] | None = None,
    secret_reader: Callable[[str], tuple[str, str]] = read_db_credentials,
) -> Settings:
    source = os.environ if env is None else env
    required = _REQUIRED
    if source.get("DB_SECRET_ID"):
        required = tuple(n for n in _REQUIRED if n not in ("DB_USER", "DB_PASSWORD"))
    missing = [name for name in required if not source.get(name)]
    if missing:
        raise ConfigError("Missing environment variables: " + ", ".join(missing))

    sslmode = source.get("DB_SSLMODE") or _DEFAULT_SSLMODE
    if sslmode not in _SSLMODES:
        raise ConfigError("DB_SSLMODE is not a valid value")

    allow_insecure = _parse_bool(
        "COGNITO_ALLOW_INSECURE_JWKS", source.get("COGNITO_ALLOW_INSECURE_JWKS")
    )

    db_user, db_password = _resolve_db_credentials(source, secret_reader)

    return Settings(
        db_host=source["DB_HOST"],
        db_port=_parse_port(source["DB_PORT"]),
        db_user=db_user,
        db_password=db_password,
        db_name=source["DB_NAME"],
        db_sslmode=sslmode,
        cors_allowed_origin=_parse_origin(source["CORS_ALLOWED_ORIGIN"]),
        cognito_issuer=_parse_https_url("COGNITO_ISSUER", source["COGNITO_ISSUER"], allow_insecure),
        cognito_jwks_url=_parse_https_url(
            "COGNITO_JWKS_URL", source["COGNITO_JWKS_URL"], allow_insecure
        ),
        cognito_app_client_id=_parse_client_id(source["COGNITO_APP_CLIENT_ID"]),
        cognito_allow_insecure_jwks=allow_insecure,
        max_orders_per_hour=_parse_max_orders(source.get("ORDERS_MAX_PER_HOUR")),
    )

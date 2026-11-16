"""Settings, read only from environment variables.

No address, port or credential is written in the code. A missing or invalid
variable stops the service at start-up; error messages name the variable but
never print its value.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlsplit

_REQUIRED = (
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
    "CORS_ALLOWED_ORIGIN",
)
_SSLMODES = frozenset(
    {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
)
_DEFAULT_SSLMODE = "prefer"


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


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    missing = [name for name in _REQUIRED if not source.get(name)]
    if missing:
        raise ConfigError("Missing environment variables: " + ", ".join(missing))

    sslmode = source.get("DB_SSLMODE") or _DEFAULT_SSLMODE
    if sslmode not in _SSLMODES:
        raise ConfigError("DB_SSLMODE is not a valid value")

    return Settings(
        db_host=source["DB_HOST"],
        db_port=_parse_port(source["DB_PORT"]),
        db_user=source["DB_USER"],
        db_password=source["DB_PASSWORD"],
        db_name=source["DB_NAME"],
        db_sslmode=sslmode,
        cors_allowed_origin=_parse_origin(source["CORS_ALLOWED_ORIGIN"]),
    )

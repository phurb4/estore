"""Database credentials read from AWS Secrets Manager or from a mounted file.

The secret (or the file) is JSON: {"username": "...", "password": "..."}. Where AWS is
reached (region, endpoint, credentials) comes from the standard AWS variables
or the identity of the workload (AWS_REGION, AWS_ENDPOINT_URL for the local
emulator): nothing is written here. Error messages never contain the secret.
"""
from __future__ import annotations

import json
import os
import re

_SECRET_ID_RE = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,512}$")
_MAX_SECRET_FILE_BYTES = 64 * 1024


class SecretError(RuntimeError):
    """The secret could not be read or has the wrong shape. No values inside."""


def is_valid_secret_id(raw: str) -> bool:
    return bool(_SECRET_ID_RE.fullmatch(raw))


def _credentials_from_json(text: str | bytes) -> tuple[str, str]:
    """Parse {"username": ..., "password": ...}; raises SecretError, no values."""
    try:
        data = json.loads(text)
        user, password = data["username"], data["password"]
    except Exception as exc:  # noqa: BLE001 - message must not leak any value
        raise SecretError(
            f"Could not read the database secret ({type(exc).__name__})"
        ) from None
    if not (isinstance(user, str) and isinstance(password, str) and user and password):
        raise SecretError("The database secret must hold a username and a password")
    return user, password


def read_db_credentials(secret_id: str) -> tuple[str, str]:
    """Return (username, password) stored in the Secrets Manager secret."""
    try:
        import boto3  # imported here: only needed when a secret is used

        client = boto3.client("secretsmanager")
        text = client.get_secret_value(SecretId=secret_id)["SecretString"]
    except Exception as exc:  # noqa: BLE001 - message must not leak any value
        raise SecretError(
            f"Could not read the database secret ({type(exc).__name__})"
        ) from None
    return _credentials_from_json(text)


def read_db_credentials_file(path: str) -> tuple[str, str]:
    """Return (username, password) from a JSON file (e.g. a mounted secret).

    The path comes from the environment (DB_SECRET_FILE); nothing is written
    here. Error messages never contain the path contents.
    """
    if not os.path.isabs(path):
        raise SecretError("DB_SECRET_FILE must be an absolute path")
    try:
        with open(path, "rb") as handle:
            raw = handle.read(_MAX_SECRET_FILE_BYTES + 1)
    except OSError as exc:
        raise SecretError(
            f"Could not read the database secret file ({type(exc).__name__})"
        ) from None
    if len(raw) > _MAX_SECRET_FILE_BYTES:
        raise SecretError("The database secret file is too large")
    return _credentials_from_json(raw)

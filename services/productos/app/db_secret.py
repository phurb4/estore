"""Database credentials read from AWS Secrets Manager.

The secret is JSON: {"username": "...", "password": "..."}. Where AWS is
reached (region, endpoint, credentials) comes from the standard AWS variables
or the identity of the workload (AWS_REGION, AWS_ENDPOINT_URL for the local
emulator): nothing is written here. Error messages never contain the secret.
"""
from __future__ import annotations

import json
import re

_SECRET_ID_RE = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,512}$")


class SecretError(RuntimeError):
    """The secret could not be read or has the wrong shape. No values inside."""


def is_valid_secret_id(raw: str) -> bool:
    return bool(_SECRET_ID_RE.fullmatch(raw))


def read_db_credentials(secret_id: str) -> tuple[str, str]:
    """Return (username, password) stored in the secret."""
    try:
        import boto3  # imported here: only needed when a secret is used

        client = boto3.client("secretsmanager")
        data = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
        user, password = data["username"], data["password"]
    except Exception as exc:  # noqa: BLE001 - message must not leak any value
        raise SecretError(
            f"Could not read the database secret ({type(exc).__name__})"
        ) from None
    if not (isinstance(user, str) and isinstance(password, str) and user and password):
        raise SecretError("The database secret must hold a username and a password")
    return user, password

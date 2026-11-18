"""Amazon Cognito access-token verification for the Orders service.

The browser sends the ACCESS token (Authorization: Bearer ...). AWS describes
the access token as the one meant to authorize API operations; the ID token
carries the customer's email and is not sent to this service.

Checks, all mandatory (AWS "Verifying a JSON web token" + PyJWT docs):
  - header: alg is exactly RS256 (fixed here, never taken from the token) and
    a kid is present;
  - signature, against the key of the user pool's JWKS that matches the kid;
  - exp present and not expired; iss equals COGNITO_ISSUER;
  - token_use equals "access" (an ID token is refused);
  - client_id equals COGNITO_APP_CLIENT_ID. The access token has no "aud"
    claim (only with a resource binding), so aud is not verified;
  - sub is a UUID. It is the value stored in orders.user_id.

Limits worth knowing:
  - Offline validation cannot see revocation: a token stays valid until its exp
    (60 minutes in this project) even after the customer signs out.
  - KNOWN LIMITATION: a malformed JWKS response (not a JSON object, or no usable
    keys) reaches us as PyJWKClientError, the same class as "unknown kid", so
    it answers 401 and not 503. It still fails closed; only the status code
    is less precise. Network failures and timeouts do answer 503.
  - The JWKS is cached for JWKS_LIFESPAN seconds (AWS: cache by kid and
    refresh periodically). An unknown kid forces one refresh, at most once per
    cooldown. LOCAL ONLY: if Floci restarts and generates a new signing key
    with the SAME kid, this cache keeps the old key and valid tokens fail with
    401 for up to JWKS_LIFESPAN seconds. Restart the Orders service.

This module never logs a token or a claim value.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKSetError,
    PyJWTError,
)

logger = logging.getLogger("pedidos.auth")

ALGORITHM = "RS256"
JWKS_LIFESPAN = 3600      # seconds the key set is kept
JWKS_COOLDOWN = 30        # seconds between forced refreshes (unknown kid)
JWKS_TIMEOUT = 3          # seconds to reach the JWKS endpoint
LEEWAY = 5                # seconds of clock skew accepted on exp / iat
MAX_TOKEN_LENGTH = 4096

_BEARER_RE = re.compile(r"^Bearer ([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$", re.IGNORECASE)
_KID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SUB_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_REQUIRED_CLAIMS = ["exp", "iss", "sub", "client_id", "token_use"]


class AuthError(Exception):
    """The token is missing or not valid. Maps to 401. Carries no detail."""


class AuthUnavailable(Exception):
    """The signing keys could not be fetched. Maps to 503 (fail closed)."""


def extract_bearer(authorization: str | None) -> str:
    """Return the token from an 'Authorization: Bearer <jwt>' header value."""
    if not isinstance(authorization, str) or len(authorization) > MAX_TOKEN_LENGTH + 7:
        raise AuthError
    match = _BEARER_RE.match(authorization)
    if not match:
        raise AuthError
    return match.group(1)


class TokenVerifier:
    def __init__(
        self,
        issuer: str,
        jwks_url: str,
        client_id: str,
        *,
        jwks_lifespan: int = JWKS_LIFESPAN,
        jwks_cooldown: int = JWKS_COOLDOWN,
        timeout: int = JWKS_TIMEOUT,
    ) -> None:
        self._issuer = issuer
        self._client_id = client_id
        # cache_keys stays False: the signing keys are not kept past the
        # key-set lifespan, so a rotated key is picked up at the next refresh.
        self._jwks = PyJWKClient(
            jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=jwks_lifespan,
            cooldown_duration=jwks_cooldown,
            timeout=timeout,
        )

    def verify(self, token: str) -> str:
        """Return the customer's `sub` for a valid access token.

        Raises AuthError (401) or AuthUnavailable (503).
        """
        if not isinstance(token, str) or not 0 < len(token) <= MAX_TOKEN_LENGTH:
            raise AuthError
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError:
            raise AuthError from None
        kid = header.get("kid")
        # Header checks come first so a garbage token never causes a network call.
        if header.get("alg") != ALGORITHM or not isinstance(kid, str) or not _KID_RE.match(kid):
            raise AuthError

        try:
            key = self._jwks.get_signing_key(kid)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                leeway=LEEWAY,
                options={"require": _REQUIRED_CLAIMS, "verify_aud": False},
            )
        except (PyJWKClientConnectionError, PyJWKSetError) as exc:
            logger.error("Signing keys unavailable: %s", type(exc).__name__)
            raise AuthUnavailable from None
        except PyJWKClientError:
            # Unknown kid (or a malformed key set): the token cannot be trusted.
            raise AuthError from None
        except PyJWTError:
            raise AuthError from None

        return self._subject(claims)

    def _subject(self, claims: dict[str, Any]) -> str:
        if claims.get("token_use") != "access":
            raise AuthError
        if claims.get("client_id") != self._client_id:
            raise AuthError
        sub = claims.get("sub")
        if not isinstance(sub, str) or not _SUB_RE.match(sub):
            raise AuthError
        return sub.lower()

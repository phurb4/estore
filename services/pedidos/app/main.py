"""Orders service: POST /orders, plus GET /health for container checks.

Run with:  python -m uvicorn app.main:create_app --factory
Configuration comes only from environment variables (see config.py).

Every order needs a valid Amazon Cognito access token (Authorization: Bearer).
The customer is the verified `sub` of that token and nothing else: it is never
read from the body, the query string or any other header. Error messages are
fixed texts; the token is never logged or echoed.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Protocol

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from .auth import AuthError, AuthUnavailable, TokenVerifier, extract_bearer
from .config import Settings, load_settings
from .db import OrderLimitExceeded, OrderRepository, PostgresOrderRepository
from .pricing import UnknownProductError
from .schemas import (
    HISTORY_DEFAULT_LIMIT,
    HISTORY_MAX_LIMIT,
    OrderIn,
    OrderOut,
    OrderSummaryOut,
)

logger = logging.getLogger("pedidos")


class Verifier(Protocol):
    def verify(self, token: str) -> str: ...


def create_app(
    settings: Settings | None = None,
    repository: OrderRepository | None = None,
    verifier: Verifier | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    repo = repository or PostgresOrderRepository(settings)
    token_verifier = verifier or TokenVerifier(
        settings.cognito_issuer,
        settings.cognito_jwks_url,
        settings.cognito_app_client_id,
    )
    if settings.cognito_allow_insecure_jwks:
        logger.warning("COGNITO_ALLOW_INSECURE_JWKS is true: local emulator use only")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        opener = getattr(repo, "open", None)
        if callable(opener):
            opener()
        try:
            yield
        finally:
            closer = getattr(repo, "close", None)
            if callable(closer):
                closer()

    # No interactive docs or OpenAPI schema: smallest possible surface.
    app = FastAPI(
        title="Orders service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    # One origin from the environment, POST only, no credentials, never "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_allowed_origin],
        allow_methods=["POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # The default 422 body echoes the client's input back. Send a fixed
        # message instead; nothing the client typed is reflected.
        detail = "Invalid order" if request.method == "POST" else "Invalid request"
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Details stay in the server log; the client gets a generic message.
        logger.error(
            "Unhandled error on %s: %s", request.url.path, type(exc).__name__, exc_info=exc
        )
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    @app.get("/health")
    def health():
        # Liveness only: no database access, no data.
        return {"status": "ok"}

    def current_user(authorization: str | None = Header(default=None)) -> str:
        """The customer's verified `sub`, or 401 / 503 with a fixed message."""
        try:
            return token_verifier.verify(extract_bearer(authorization))
        except AuthUnavailable:
            raise HTTPException(503, "Service temporarily unavailable") from None
        except AuthError:
            raise HTTPException(
                401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
            ) from None

    @app.get("/orders", response_model=list[OrderSummaryOut])
    def list_orders(
        user_id: str = Depends(current_user),
        limit: int = Query(default=HISTORY_DEFAULT_LIMIT, ge=1, le=HISTORY_MAX_LIMIT),
    ):
        """The signed-in customer's own orders, newest first. Nobody else's."""
        try:
            return repo.list_orders(user_id, limit)
        except (psycopg.Error, PoolTimeout) as exc:
            logger.error("Database error: %s", type(exc).__name__)
            return JSONResponse(
                {"detail": "Service temporarily unavailable"}, status_code=503
            )

    @app.post("/orders", response_model=OrderOut, status_code=201)
    def create_order(order: OrderIn, user_id: str = Depends(current_user)):
        items = [(item.product_id, item.quantity) for item in order.items]
        try:
            return repo.create_order(user_id, items)
        except UnknownProductError:
            return JSONResponse(
                {"detail": "One or more products are not available"}, status_code=422
            )
        except OrderLimitExceeded:
            return JSONResponse({"detail": "Order limit reached"}, status_code=429)
        except (psycopg.Error, PoolTimeout) as exc:
            logger.error("Database error: %s", type(exc).__name__)
            return JSONResponse(
                {"detail": "Service temporarily unavailable"}, status_code=503
            )

    return app

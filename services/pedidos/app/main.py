"""Orders service: POST /orders, plus GET /health for container checks.

Run with:  python -m uvicorn app.main:create_app --factory
Configuration comes only from environment variables (see config.py).

Orders are anonymous for now. The user_id column exists in the database but
this service never fills it; Cognito will provide it later.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from .config import Settings, load_settings
from .db import OrderRepository, PostgresOrderRepository
from .pricing import UnknownProductError
from .schemas import OrderIn, OrderOut

logger = logging.getLogger("pedidos")


def create_app(
    settings: Settings | None = None,
    repository: OrderRepository | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    repo = repository or PostgresOrderRepository(settings)

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
        return JSONResponse({"detail": "Invalid order"}, status_code=422)

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

    @app.post("/orders", response_model=OrderOut, status_code=201)
    def create_order(order: OrderIn):
        items = [(item.product_id, item.quantity) for item in order.items]
        try:
            return repo.create_order(items)
        except UnknownProductError:
            return JSONResponse(
                {"detail": "One or more products are not available"}, status_code=422
            )
        except (psycopg.Error, PoolTimeout) as exc:
            logger.error("Database error: %s", type(exc).__name__)
            return JSONResponse(
                {"detail": "Service temporarily unavailable"}, status_code=503
            )

    return app

"""Products service: one endpoint, GET /products.

Run with:  python -m uvicorn app.main:create_app --factory
Configuration comes only from environment variables (see config.py).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from .config import Settings, load_settings
from .db import PostgresProductRepository, ProductRepository
from .schemas import IMAGE_PREFIX, ProductOut

logger = logging.getLogger("productos")


def _to_output(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "price": row["price"],
        "image": IMAGE_PREFIX + row["image_file"],
    }


def create_app(
    settings: Settings | None = None,
    repository: ProductRepository | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    repo = repository or PostgresProductRepository(settings)

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
        title="Products service",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    # One origin from the environment, GET only, no credentials, never "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_allowed_origin],
        allow_methods=["GET"],
        allow_headers=[],
        allow_credentials=False,
    )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Details stay in the server log; the client gets a generic message.
        logger.error(
            "Unhandled error on %s: %s", request.url.path, type(exc).__name__, exc_info=exc
        )
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    @app.get("/products", response_model=list[ProductOut])
    def list_products():
        try:
            rows = repo.list_products()
        except (psycopg.Error, PoolTimeout) as exc:
            logger.error("Database error: %s", type(exc).__name__)
            return JSONResponse(
                {"detail": "Service temporarily unavailable"}, status_code=503
            )
        # response_model validates every field before anything leaves the service.
        return [_to_output(row) for row in rows]

    return app

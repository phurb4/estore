"""Read-only access to the catalog in PostgreSQL (parameterized queries only)."""
from __future__ import annotations

from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings

MAX_PRODUCTS = 200  # store.js reads at most 200 products

_QUERY = """
    SELECT p.id, p.name, c.name AS category, p.price, p.image_file
    FROM products AS p
    JOIN categories AS c ON c.id = p.category_id
    ORDER BY p.id
    LIMIT %s
"""


class ProductRepository(Protocol):
    def list_products(self) -> list[dict[str, Any]]: ...


class PostgresProductRepository:
    def __init__(self, settings: Settings) -> None:
        self._pool = ConnectionPool(
            kwargs={
                "host": settings.db_host,
                "port": settings.db_port,
                "user": settings.db_user,
                "password": settings.db_password,
                "dbname": settings.db_name,
                "sslmode": settings.db_sslmode,
                "connect_timeout": 3,
                # Fail slow queries and refuse writes from this service.
                "options": "-c statement_timeout=5000 -c default_transaction_read_only=on",
            },
            min_size=1,
            max_size=5,
            timeout=5.0,
            open=False,
        )

    def open(self) -> None:
        self._pool.open()

    def close(self) -> None:
        self._pool.close()

    def list_products(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_QUERY, (MAX_PRODUCTS,))
                return cur.fetchall()

"""Order storage in PostgreSQL (parameterized queries only).

One transaction per order: read the real prices, compute the total, insert the
order and its lines. If anything fails, nothing is saved.
"""
from __future__ import annotations

import uuid
from typing import Any, Protocol, Sequence

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings
from .pricing import price_order

_CATALOG_QUERY = "SELECT id, name, price FROM products WHERE id = ANY(%s::int[])"
_INSERT_ORDER = "INSERT INTO orders (id, total) VALUES (%s, %s)"
_INSERT_ITEM = (
    "INSERT INTO order_items (order_id, product_id, name, quantity, unit_price) "
    "VALUES (%s, %s, %s, %s, %s)"
)


class OrderRepository(Protocol):
    def create_order(self, items: Sequence[tuple[int, int]]) -> dict[str, Any]: ...


class PostgresOrderRepository:
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
                # Fail slow queries. This role may only INSERT into the order
                # tables and SELECT from products (see db/05-orders-role.sh).
                "options": "-c statement_timeout=5000",
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

    def create_order(self, items: Sequence[tuple[int, int]]) -> dict[str, Any]:
        order_id = uuid.uuid4()
        # The connection context commits on success and rolls back on error.
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_CATALOG_QUERY, ([product_id for product_id, _ in items],))
                catalog = {row["id"]: (row["name"], row["price"]) for row in cur.fetchall()}
                lines, total = price_order(items, catalog)
                cur.execute(_INSERT_ORDER, (order_id, total))
                cur.executemany(
                    _INSERT_ITEM,
                    [
                        (order_id, line["product_id"], line["name"],
                         line["quantity"], line["unit_price"])
                        for line in lines
                    ],
                )
        return {"id": order_id, "total": total, "items": lines}

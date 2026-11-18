"""Order storage in PostgreSQL (parameterized queries only).

One transaction per order, in this order:
  1. set_config('app.user_id', <sub>, true): the customer for this transaction
     only (row-level security reads it; the value disappears at COMMIT/ROLLBACK,
     so it can never stay on a pooled connection);
  2. an advisory lock on that customer: two simultaneous orders of the same
     customer run one after the other, so the limit below cannot be skipped;
  3. the customer's orders in the last hour, against the limit;
  4. the real prices, then the order and its lines.
If anything fails, nothing is saved.

user_id is never read from the request: main.py passes the `sub` that
auth.py validated and normalized, and this module uses that one value in
every step.
"""
from __future__ import annotations

import uuid
from typing import Any, Protocol, Sequence

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings
from .pricing import price_order

_SET_USER = "SELECT set_config('app.user_id', %s, true)"
_LOCK_USER = "SELECT pg_advisory_xact_lock(hashtext(%s::text))"
_COUNT_RECENT = (
    "SELECT count(*) AS n FROM orders "
    "WHERE user_id = %s AND created_at > now() - interval '1 hour'"
)
_CATALOG_QUERY = "SELECT id, name, price FROM products WHERE id = ANY(%s::int[])"
_INSERT_ORDER = "INSERT INTO orders (id, user_id, total) VALUES (%s, %s, %s)"
_INSERT_ITEM = (
    "INSERT INTO order_items (order_id, product_id, name, quantity, unit_price) "
    "VALUES (%s, %s, %s, %s, %s)"
)


class OrderLimitExceeded(Exception):
    """The customer reached the orders-per-hour limit. Carries no data."""


_LIST_ORDERS = (
    "SELECT id, total, created_at FROM orders WHERE user_id = %s "
    "ORDER BY created_at DESC, id DESC LIMIT %s"
)
_LIST_ITEMS = (
    "SELECT order_id, product_id, name, quantity, unit_price FROM order_items "
    "WHERE order_id = ANY(%s::uuid[]) ORDER BY order_id, product_id"
)


class OrderRepository(Protocol):
    def create_order(
        self, user_id: str, items: Sequence[tuple[int, int]]
    ) -> dict[str, Any]: ...

    def list_orders(self, user_id: str, limit: int) -> list[dict[str, Any]]: ...


class PostgresOrderRepository:
    def __init__(self, settings: Settings) -> None:
        self._max_per_hour = settings.max_orders_per_hour
        self._pool = ConnectionPool(
            kwargs={
                "host": settings.db_host,
                "port": settings.db_port,
                "user": settings.db_user,
                "password": settings.db_password,
                "dbname": settings.db_name,
                "sslmode": settings.db_sslmode,
                "connect_timeout": 3,
                # Fail slow queries. This role may SELECT products and its own
                # orders, and INSERT orders (see db/05-orders-role.sh).
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

    def list_orders(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        """The customer's newest orders with their lines.

        Two filters on purpose: the WHERE clause below and the row-level
        security policy (set through app.user_id in this same transaction).
        """
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_SET_USER, (user_id,))
                cur.execute(_LIST_ORDERS, (user_id, limit))
                orders = cur.fetchall()
                if not orders:
                    return []
                cur.execute(_LIST_ITEMS, ([row["id"] for row in orders],))
                lines_by_order: dict[Any, list[dict[str, Any]]] = {}
                for row in cur.fetchall():
                    lines_by_order.setdefault(row["order_id"], []).append(
                        {
                            "product_id": row["product_id"],
                            "name": row["name"],
                            "quantity": row["quantity"],
                            "unit_price": row["unit_price"],
                            "line_total": row["unit_price"] * row["quantity"],
                        }
                    )
        return [
            {
                "id": row["id"],
                "total": row["total"],
                "created_at": row["created_at"],
                "items": lines_by_order.get(row["id"], []),
            }
            for row in orders
        ]

    def create_order(
        self, user_id: str, items: Sequence[tuple[int, int]]
    ) -> dict[str, Any]:
        order_id = uuid.uuid4()
        # The connection context commits on success and rolls back on error.
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_SET_USER, (user_id,))
                cur.execute(_LOCK_USER, (user_id,))
                cur.execute(_COUNT_RECENT, (user_id,))
                if cur.fetchone()["n"] >= self._max_per_hour:
                    raise OrderLimitExceeded

                cur.execute(_CATALOG_QUERY, ([product_id for product_id, _ in items],))
                catalog = {row["id"]: (row["name"], row["price"]) for row in cur.fetchall()}
                lines, total = price_order(items, catalog)
                cur.execute(_INSERT_ORDER, (order_id, user_id, total))
                cur.executemany(
                    _INSERT_ITEM,
                    [
                        (order_id, line["product_id"], line["name"],
                         line["quantity"], line["unit_price"])
                        for line in lines
                    ],
                )
        return {"id": order_id, "total": total, "items": lines}

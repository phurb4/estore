"""Order pricing. Pure function: no database, no network, easy to test.

The catalog (real prices) comes from PostgreSQL, never from the browser.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

CENT = Decimal("0.01")


class UnknownProductError(Exception):
    """An item refers to a product that is not in the catalog."""


def price_order(
    items: Sequence[tuple[int, int]],
    catalog: Mapping[int, tuple[str, Decimal]],
) -> tuple[list[dict[str, Any]], Decimal]:
    """items: (product_id, quantity) in request order.
    catalog: product_id -> (name, unit price).
    Returns the priced lines and the total, all exact to the cent."""
    lines: list[dict[str, Any]] = []
    total = Decimal("0.00")
    for product_id, quantity in items:
        try:
            name, unit_price = catalog[product_id]
        except KeyError:
            raise UnknownProductError from None
        line_total = (unit_price * quantity).quantize(CENT)
        lines.append(
            {
                "product_id": product_id,
                "name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )
        total += line_total
    return lines, total

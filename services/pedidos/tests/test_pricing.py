from decimal import Decimal

import pytest

from app.pricing import UnknownProductError, price_order

CATALOG = {
    1: ("Camera", Decimal("99.99")),
    3: ("Phone", Decimal("299.00")),
    7: ("Cable", Decimal("0.10")),
}


def test_total_is_the_sum_of_lines_in_request_order():
    lines, total = price_order([(3, 1), (1, 2)], CATALOG)
    assert [line["product_id"] for line in lines] == [3, 1]
    assert lines[1]["line_total"] == Decimal("199.98")
    assert total == Decimal("498.98")


def test_amounts_are_exact_to_the_cent():
    # 0.10 * 3 would be 0.30000000000000004 with floats.
    _, total = price_order([(7, 3)], CATALOG)
    assert total == Decimal("0.30")


def test_unknown_product_raises():
    with pytest.raises(UnknownProductError):
        price_order([(1, 1), (999, 1)], CATALOG)

"""Input and output models of the Orders service.

The browser sends only WHICH products and HOW MANY. Prices, names and totals
are never accepted from the client: extra="forbid" rejects any extra field
(for example "price" or "total") instead of silently ignoring it.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_ITEMS = 50
MAX_QUANTITY = 99
HISTORY_DEFAULT_LIMIT = 20
HISTORY_MAX_LIMIT = 50


class OrderItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # strict=True: only real JSON integers (no "2" strings, no true/false).
    product_id: int = Field(ge=1, le=2_147_483_647, strict=True)
    quantity: int = Field(ge=1, le=MAX_QUANTITY, strict=True)


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[OrderItemIn] = Field(min_length=1, max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _no_duplicate_products(self) -> "OrderIn":
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate product")
        return self


class OrderLineOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: int = Field(ge=1, le=2_147_483_647)
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=MAX_QUANTITY)
    # Serialized as JSON strings with two decimals (exact, never a float).
    unit_price: Decimal = Field(ge=0, le=10_000_000, max_digits=10, decimal_places=2)
    line_total: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class OrderOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    total: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    items: list[OrderLineOut]


class OrderSummaryOut(OrderOut):
    """An order in the customer's history. Never carries the user_id."""

    created_at: datetime

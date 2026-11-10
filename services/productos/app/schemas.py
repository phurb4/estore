"""Output model. It mirrors the checks frontend/js/store.js applies to each product."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Same pattern as safeImage() in frontend/js/store.js (relative "img/" path only).
IMAGE_PATTERN = r"^img/[A-Za-z0-9_-]+\.(png|jpe?g|webp|gif)$"
IMAGE_PREFIX = "img/"

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class ProductOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # store.js: String(id) must match ^[A-Za-z0-9_-]{1,64}$ (an integer always does).
    id: int = Field(ge=1, le=2_147_483_647)
    name: Name
    category: Category
    # Serialized as a JSON string with two decimals (exact, never a float).
    price: Decimal = Field(ge=0, le=10_000_000, max_digits=10, decimal_places=2)
    image: str = Field(pattern=IMAGE_PATTERN, max_length=300)

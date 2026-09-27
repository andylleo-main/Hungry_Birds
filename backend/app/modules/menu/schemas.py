import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.core.fields import Description, ImageUrl, Money, Name, SortOrder


class CategoryCreate(BaseModel):
    name: Name
    sort_order: SortOrder = 0


class CategoryUpdate(BaseModel):
    name: Name | None = None
    sort_order: SortOrder | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    name: Name
    description: Description | None = None
    price: Money
    category_id: uuid.UUID | None = None
    image_url: ImageUrl | None = None


class ItemUpdate(BaseModel):
    name: Name | None = None
    description: Description | None = None
    price: Money | None = None
    category_id: uuid.UUID | None = None
    image_url: ImageUrl | None = None
    is_available: bool | None = None


class ItemOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    category_id: uuid.UUID | None
    image_url: str | None
    is_available: bool

    model_config = {"from_attributes": True}


class CategoryWithItems(CategoryOut):
    items: list[ItemOut]

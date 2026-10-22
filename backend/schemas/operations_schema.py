from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Quantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]
Stock = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=3)]


class OperationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InventoryCreate(OperationInput):
    name: str = Field(min_length=2, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    quantity: Stock = Decimal(0)
    reason: str = Field(default="Initial inventory", min_length=2, max_length=1000)


class InventoryUpdate(OperationInput):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    quantity: Stock | None = None
    reason: str = Field(default="Admin stock adjustment", min_length=2, max_length=1000)

    @model_validator(mode="after")
    def requires_change(self):
        if self.name is self.unit is self.quantity is None:
            raise ValueError("Provide a name, unit or quantity to update")
        return self


class ReliefItemInput(OperationInput):
    inventory_item_id: int = Field(gt=0)
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class ReliefCreate(OperationInput):
    incident_id: int = Field(gt=0)
    kind: Literal["SUPPLIES", "RESCUE_SUPPORT"] = "SUPPLIES"
    note: str | None = Field(default=None, max_length=1000)
    items: list[ReliefItemInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def valid_items(self):
        if self.kind == "SUPPLIES" and not self.items:
            raise ValueError("Supply requests need at least one item")
        if self.kind == "RESCUE_SUPPORT" and self.items:
            raise ValueError("Rescue support does not consume inventory")
        if len({item.inventory_item_id for item in self.items}) != len(self.items):
            raise ValueError("Combine duplicate inventory items into one request line")
        return self


class ReliefAssign(OperationInput):
    team_id: int = Field(gt=0)


class DeliveryItemInput(OperationInput):
    request_item_id: int = Field(gt=0)
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class DeliveryCreate(OperationInput):
    idempotency_key: str = Field(min_length=8, max_length=100)
    items: list[DeliveryItemInput] = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({item.request_item_id for item in self.items}) != len(self.items):
            raise ValueError("Combine duplicate request items into one delivery line")
        return self


class TaskNote(OperationInput):
    note: str | None = Field(default=None, max_length=1000)


class TaskProgress(TaskNote):
    status: Literal["EN_ROUTE", "IN_PROGRESS", "RESOLVED"]


class TaskHandoff(OperationInput):
    team_id: int = Field(gt=0)
    note: str = Field(min_length=5, max_length=1000)

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Item = Literal[
    "FOOD",
    "WATER",
    "CLOTHING",
    "MEDICINE",
]

UNITS = {
    "FOOD": "packet",
    "WATER": "litre",
    "CLOTHING": "piece",
    "MEDICINE": "kit",
}


class ServiceInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class ProgressInput(ServiceInput):
    status: Literal[
        "EN_ROUTE",
        "IN_PROGRESS",
        "RESCUE_COMPLETED",
        "RESOLVED",
    ]

    note: str = Field(
        min_length=3,
        max_length=1000,
    )


class HandoffInput(ServiceInput):
    team_id: int = Field(gt=0)

    note: str = Field(
        min_length=3,
        max_length=1000,
    )


class ReliefInput(ServiceInput):
    item: Item

    quantity: int = Field(
        gt=0,
        le=1000000,
        strict=True,
    )


class StockAddition(ServiceInput):
    quantity: int = Field(
        gt=0,
        le=1000000,
        strict=True,
    )


class DeliveryInput(StockAddition):
    idempotency_key: UUID
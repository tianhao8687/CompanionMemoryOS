from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from companion_memoryos.schemas.core import EntityRef, RealityLayer, StrictModel


class EntityProposal(StrictModel):
    """A turn-local reference, not permission to invent or merge stable actor IDs."""

    ref: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=240)
    kind: str = Field(default="person", min_length=1, max_length=64)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    action: Literal["resolve", "new"] = "resolve"
    reality_layer: RealityLayer = RealityLayer.REAL_WORLD

    @field_validator("ref", "name", "kind")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("entity fields cannot be blank")
        return value.strip()

    @field_validator("kind")
    @classmethod
    def normalize_kind(cls, value: str) -> str:
        return value.casefold()

    @field_validator("aliases")
    @classmethod
    def unique_aliases(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))


class EntityResolution(StrictModel):
    ref: str
    status: Literal["matched", "new", "ambiguous", "unanchored"]
    reality_layer: RealityLayer
    entity: EntityRef | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

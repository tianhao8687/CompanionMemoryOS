"""Independent relationship dimensions, shared by persona and history layers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class FamiliarityStage(StrEnum):
    NEW = "new"
    FAMILIAR = "familiar"
    ESTABLISHED = "established"
    CLOSE = "established"  # v0.1/v0.2 Python compatibility alias, not romantic permission.

    @classmethod
    def _missing_(cls, value: Any) -> FamiliarityStage | None:
        if str(value).lower() == "close":
            return cls.ESTABLISHED
        return None


class RelationshipIdentityType(StrEnum):
    UNDEFINED = "undefined"
    FRIEND = "friend"
    CLOSE_FRIEND = "close_friend"
    ROMANTIC_PARTNER = "romantic_partner"
    COMPANION = "companion"
    CUSTOM = "custom"


class RelationshipDistance(StrEnum):
    OPEN = "open"
    CAUTIOUS = "cautious"
    RESERVED = "reserved"

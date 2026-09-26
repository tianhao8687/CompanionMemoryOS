"""Validated, provider-independent persona source and compiled output."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from companion_agent.semantics import (
    FamiliarityStage,
    RelationshipDistance,
    RelationshipIdentityType,
)
from companion_memoryos.schemas import ResponseGoal

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class PersonaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


RelationshipStage = FamiliarityStage


class PersonaIdentity(PersonaModel):
    role: Text
    summary: Text


class CharacterKernel(PersonaModel):
    core_values: list[Text] = Field(min_length=1)
    core_tensions: list[Text] = Field(min_length=1)
    dislikes: list[Text] = Field(min_length=1)
    distinctive_behaviors: list[Text] = Field(min_length=1)


class GoalPersonaStyle(PersonaModel):
    tone: list[Text] = Field(min_length=1)
    tendencies: list[Text] = Field(min_length=1)
    avoid: list[Text] = Field(min_length=1)


class RelationshipStyle(PersonaModel):
    allowed_behaviors: list[Text] = Field(min_length=1)
    interaction_style: list[Text] = Field(min_length=1)


RelationshipStyles = dict[RelationshipStage, RelationshipStyle]


class BehaviorInvariant(PersonaModel):
    id: Text
    description: Text
    severity: Literal["hard", "soft"]


class PersonaExample(PersonaModel):
    situation: Text
    user_message: Text
    character_response: Text
    tags: list[Text] = Field(min_length=1)


class CharacterMemorySeed(PersonaModel):
    id: Text
    title: Text
    content: Text
    occurred_at: datetime | None = None
    topic_keys: list[Text] = Field(min_length=1)
    salience: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("occurred_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class PersonaDefinition(PersonaModel):
    kind: Literal["preset", "custom"] = Field(
        default="preset", exclude_if=lambda value: value == "preset"
    )
    persona_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    display_name: Text
    identity: PersonaIdentity
    kernel: CharacterKernel | None = None
    response_styles: dict[ResponseGoal, GoalPersonaStyle] = Field(default_factory=dict)
    relationship_styles: RelationshipStyles = Field(default_factory=dict)
    identity_styles: dict[RelationshipIdentityType, RelationshipStyle] = Field(default_factory=dict)
    invariants: list[BehaviorInvariant] = Field(default_factory=list)
    examples: list[PersonaExample] = Field(default_factory=list, max_length=100)
    character_memories: list[CharacterMemorySeed] = Field(default_factory=list, max_length=1000)

    @field_validator("response_styles", "relationship_styles", mode="before")
    @classmethod
    def normalize_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = {
            ("established" if str(key).lower() == "close" else str(key).lower()): item
            for key, item in value.items()
        }
        if len(normalized) != len(value):
            raise ValueError("duplicate style keys after case normalization")
        return normalized

    @model_validator(mode="after")
    def complete_definition(self) -> PersonaDefinition:
        if self.kind == "custom":
            if any(
                (
                    self.kernel,
                    self.response_styles,
                    self.relationship_styles,
                    self.identity_styles,
                    self.invariants,
                    self.examples,
                    self.character_memories,
                )
            ):
                raise ValueError("custom characters must not contain preset personality fields")
            return self
        if self.kernel is None or not self.invariants:
            raise ValueError("preset characters require a kernel and invariants")
        if set(self.response_styles) != set(ResponseGoal):
            raise ValueError("response_styles must cover all seven ResponseGoal values")
        if set(self.relationship_styles) != set(RelationshipStage):
            raise ValueError("relationship_styles must cover all three stages")
        for items in (self.invariants, self.character_memories):
            if len({item.id for item in items}) != len(items):
                raise ValueError("duplicate invariant or character memory id")
        return self


class CompiledPersonaContext(PersonaModel):
    persona_id: str
    persona_version: str
    text: str
    estimated_tokens: int = Field(ge=0)
    response_goal: ResponseGoal
    relationship_stage: RelationshipStage
    relationship_identity: RelationshipIdentityType = RelationshipIdentityType.UNDEFINED
    relationship_distance: RelationshipDistance = RelationshipDistance.OPEN
    omitted_items: list[str] = Field(default_factory=list)
    selected_example_indices: list[int] = Field(default_factory=list)

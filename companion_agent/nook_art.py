"""Data-only pixel artwork. Model output is never markup, code or an asset URL."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from companion_agent.context import ChatMessage
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM
from companion_agent.llm import MainLLMError
from companion_agent.nook_drawing import SUPPORTED_SIDES, render_drawing, validate_grid
from companion_agent.nook_prompts import NOOK_PAINT_PROMPT
from companion_agent.persona.models import PersonaModel

PIXEL_SIDE = 48
PIXEL_ALPHABET = "0123456789ABCDEF"
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
PixelRow = Annotated[str, Field(pattern=r"^[.0-9A-F]{32,48}$")]


class PixelArt(PersonaModel):
    palette: list[Color] = Field(min_length=1, max_length=16)
    rows: list[PixelRow] = Field(min_length=32, max_length=PIXEL_SIDE)

    @model_validator(mode="after")
    def valid_pixels(self) -> PixelArt:
        if len(self.rows) not in SUPPORTED_SIDES or any(
            len(row) != len(self.rows) for row in self.rows
        ):
            raise ValueError("artwork must be a supported square grid")
        pixels = "".join(self.rows)
        if not set(pixels) <= set("." + PIXEL_ALPHABET[: len(self.palette)]):
            raise ValueError("pixel references an absent palette entry")
        if set(pixels) == {"."}:
            raise ValueError("artwork is empty")
        return self


class NookSelection(PersonaModel):
    title: str = Field(min_length=1, max_length=40)
    meaning: str = Field(min_length=1, max_length=280)
    sources: list[str] = Field(min_length=1, max_length=6)
    reality_layer: Literal["real_world", "roleplay"]
    zone: Literal["window", "shelf", "desk", "wall", "floor"]
    slot: int = Field(ge=0, le=2)
    update_id: str | None = Field(default=None, max_length=64)


class NookDesign(NookSelection):
    art: PixelArt


class NookBrief(PersonaModel):
    subject: str = Field(min_length=1, max_length=100)
    form: str = Field(min_length=1, max_length=240)
    materials: str = Field(min_length=1, max_length=200)
    story_detail: str = Field(min_length=1, max_length=120)


class NookBlueprint(NookSelection):
    brief: NookBrief


class NookPlan(PersonaModel):
    object: NookBlueprint | None = None


class NookDecision(PersonaModel):
    object: NookDesign | None = None


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate artwork field")
        result[key] = value
    return result


def _parse_payload(text: str, key: str | None, limit: int = 48_000) -> dict[str, Any]:
    """Accept a complete design; recover only a missing outermost closing brace.

    The model adapter rejects incomplete streams before this parser is called.
    Missing values, array endings and inner braces are never filled in.
    """
    text = text.strip()
    if len(text) > limit:
        raise ValueError("artwork response too large")
    try:
        data = json.loads(text, object_pairs_hook=_unique_fields)
    except json.JSONDecodeError as error:
        if error.pos != len(text) or not text.startswith("{"):
            raise
        data = json.loads(text + "}", object_pairs_hook=_unique_fields)
    if not isinstance(data, dict) or (key is not None and set(data) != {key}):
        raise ValueError("unexpected artwork response fields")
    return data


def parse_nook_plan(text: str) -> NookPlan:
    data = _parse_payload(text, None, 12_000)
    if "object" not in data:
        # Some JSON-mode providers omit the decision envelope. Accept only a
        # complete, strictly validated blueprint; never fill in its contents.
        return NookPlan(object=NookBlueprint.model_validate(data))
    return NookPlan.model_validate(data)


def parse_nook_painting(text: str) -> PixelArt:
    art = _parse_payload(text, "art")["art"]
    if isinstance(art, dict) and "layers" in art:
        art = render_drawing(art)
    return PixelArt.model_validate(art)


def parse_nook_patch(text: str, base: PixelArt) -> PixelArt:
    """Apply a bounded pixel edit atomically, preserving palette and other cells.

    A dot explicitly clears one cell; missing cells at the right of a short row
    are untouched. Overlaps are rejected so edit order cannot hide a conflict.
    """
    patches = _parse_payload(text, "patches", 12_000)["patches"]
    if not isinstance(patches, list) or len(patches) > 4:
        raise ValueError("invalid pixel patches")
    side = len(base.rows)
    rows = [list(row) for row in base.rows]
    edited: set[tuple[int, int]] = set()
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) != {"x", "y", "rows"}:
            raise ValueError("unexpected pixel patch fields")
        x, y, grid = validate_grid(
            patch["x"],
            patch["y"],
            patch["rows"],
            side=side,
            palette_size=len(base.palette),
        )
        for dy, row in enumerate(grid):
            for dx, symbol in enumerate(row):
                point = (x + dx, y + dy)
                if point in edited:
                    raise ValueError("overlapping pixel patches")
                edited.add(point)
                if len(edited) > side * side // 2:
                    raise ValueError("pixel patch area exceeds half the canvas")
                rows[y + dy][x + dx] = symbol
    return PixelArt(palette=list(base.palette), rows=["".join(row) for row in rows])


def parse_nook_decision(text: str) -> NookDecision:
    """Read earlier single-step artwork decisions, including saved experiments."""
    data = _parse_payload(text, "object")
    obj = data["object"]
    if isinstance(obj, dict) and isinstance(obj.get("art"), dict) and "layers" in obj["art"]:
        obj["art"] = render_drawing(obj["art"])
    return NookDecision.model_validate(data)


def painting_messages(
    blueprint: NookBlueprint, previous_art: dict[str, Any] | None = None
) -> list[ChatMessage]:
    """Pass only the validated visual brief; the painter cannot revise provenance."""
    data: dict[str, Any] = {
        "brief": blueprint.brief.model_dump(),
        "zone": blueprint.zone,
    }
    if previous_art is not None:
        data["previous_art"] = previous_art
    return [
        ChatMessage(role="system", content=NOOK_PAINT_PROMPT),
        ChatMessage(role="user", content=json.dumps(data, ensure_ascii=False)),
    ]


class NookArtist(DeepSeekLLM):
    """Reuse the user's model; only known DeepSeek endpoints get provider hints."""

    def __init__(
        self,
        config: DeepSeekConfig | None = None,
        *,
        api_key: str | None = None,
        use_environment: bool = True,
    ) -> None:
        config = config or DeepSeekConfig()
        thinking = config.model == "deepseek-reasoner" or (
            config.model != "deepseek-chat" and config.thinking == "enabled"
        )
        # Thinking tokens share the output allowance. Never exceed the user's cap.
        cap = config.max_tokens if thinking else 4096
        super().__init__(
            config.model_copy(update={"max_tokens": min(config.max_tokens, cap)}),
            api_key=api_key,
            use_environment=use_environment,
        )

    def payload(self, messages: list[ChatMessage]) -> dict[str, Any]:
        payload = super().payload(messages)
        if urlsplit(self.deepseek.base_url).hostname == "api.deepseek.com":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def request(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        response = super().request(payload, timeout)
        choices = response.get("choices")
        if (
            isinstance(choices, list)
            and len(choices) == 1
            and isinstance(choices[0], dict)
            and choices[0].get("finish_reason") == "length"
        ):
            raise MainLLMError("nook_output_limit")
        return response

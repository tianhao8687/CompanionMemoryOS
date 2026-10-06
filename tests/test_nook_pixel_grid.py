from __future__ import annotations

import json
from typing import Any

import pytest

from companion_agent.nook_art import PixelArt, parse_nook_painting, parse_nook_patch
from companion_agent.nook_drawing import render_drawing
from companion_agent.nook_prompts import NOOK_GRID_PAINT_PROMPT, NOOK_PIXEL_PATCH_PROMPT


def drawing(ops: list[list[Any]]) -> dict[str, Any]:
    return {
        "size": 48,
        "outline": -1,
        "palette": ["#263641", "#F8ECCF", "#86B2AE"],
        "layers": [{"name": "synthetic", "outline": -1, "ops": ops}],
    }


def test_local_grid_preserves_transparent_and_unspecified_cells() -> None:
    art = parse_nook_painting(
        json.dumps(
            {
                "art": drawing(
                    [
                        ["rect", 0, 10, 9, 12, 11],
                        ["grid", 10, 9, ["12.", "2", ".01"]],
                    ]
                )
            }
        )
    )
    assert art.rows[9][10:13] == "120"
    assert art.rows[10][10:13] == "200"
    assert art.rows[11][10:13] == "001"
    assert art.rows[8] == "." * 48
    assert PixelArt.model_validate_json(art.model_dump_json()) == art


def test_local_grid_obeys_the_existing_clip_mask() -> None:
    base = drawing([["rect", 0, 10, 10, 14, 14], ["pixel", -1, 12, 12]])
    art = render_drawing(
        drawing(
            [
                *base["layers"][0]["ops"],
                ["clip"],
                ["grid", 8, 8, ["1" * 9] * 9],
            ]
        )
    )
    before = render_drawing(base)
    assert [[p != "." for p in row] for row in art["rows"]] == [
        [p != "." for p in row] for row in before["rows"]
    ]
    assert art["rows"][12][12] == "."
    assert art["rows"][10][10] == "1"


@pytest.mark.parametrize(
    "op",
    [
        ["grid", True, 0, ["1"]],
        ["grid", -1, 0, ["1"]],
        ["grid", 47, 0, ["11"]],
        ["grid", 0, 47, ["1", "1"]],
        ["grid", 0, 0, ["F"]],
        ["grid", 0, 0, [" 1"]],
        ["grid", 0, 0, [123]],
        ["grid", 0, 0, []],
        ["grid", 0, 0, [""]],
        ["grid", 0, 0, ["1"], "extra"],
    ],
)
def test_grid_rejects_unbounded_or_ambiguous_data(op: list[Any]) -> None:
    with pytest.raises(ValueError):
        render_drawing(drawing([op]))


def base_art() -> PixelArt:
    return PixelArt(palette=["#263641", "#F8ECCF", "#86B2AE"], rows=["0" * 48] * 48)


def test_grid_prompts_satisfy_provider_json_mode_contract() -> None:
    # DeepSeek JSON mode requires "json" in a system/user message. Both stages
    # are separate requests, so the refinement cannot inherit the draft wording.
    for prompt in (NOOK_GRID_PAINT_PROMPT, NOOK_PIXEL_PATCH_PROMPT):
        assert "json" in prompt.casefold()


def test_patch_is_local_and_can_erase_without_mutating_base() -> None:
    base = base_art()
    before = base.model_dump_json()
    result = parse_nook_patch(
        json.dumps(
            {
                "patches": [
                    {"x": 9, "y": 10, "rows": [".12", "", "2"]},
                    {"x": 30, "y": 20, "rows": ["1"]},
                ]
            }
        ),
        base,
    )
    expected = {(9, 10): ".", (10, 10): "1", (11, 10): "2", (9, 12): "2", (30, 20): "1"}
    for y, row in enumerate(result.rows):
        for x, value in enumerate(row):
            assert value == expected.get((x, y), base.rows[y][x])
    assert result.palette == base.palette
    assert base.model_dump_json() == before
    assert parse_nook_patch('{"patches":[]}', base) == base


@pytest.mark.parametrize(
    "patches",
    [
        [{"x": 47, "y": 0, "rows": ["11"]}],
        [{"x": 0, "y": 0, "rows": ["F"]}],
        [{"x": 0, "y": 0, "rows": ["1"], "palette": ["#FFFFFF"]}],
        [{"x": 0, "y": 0, "rows": ["1"]}] * 2,
        [{"x": 0, "y": 0, "rows": ["1" * 48] * 25}],
        [{"x": 0, "y": 0, "rows": ["1"]}] * 5,
    ],
)
def test_invalid_patch_is_atomic(patches: list[dict[str, Any]]) -> None:
    base = base_art()
    before = base.model_dump_json()
    with pytest.raises(ValueError):
        parse_nook_patch(json.dumps({"patches": patches}), base)
    assert base.model_dump_json() == before


def test_patch_cannot_replace_palette_or_remove_the_entire_artwork() -> None:
    base = PixelArt(palette=["#263641"], rows=["0" + "." * 47] + ["." * 48] * 47)
    for raw in (
        '{"patches":[],"palette":["#ffffff"]}',
        '{"patches":[{"x":0,"y":0,"rows":["."]}]}',
    ):
        with pytest.raises(ValueError):
            parse_nook_patch(raw, base)

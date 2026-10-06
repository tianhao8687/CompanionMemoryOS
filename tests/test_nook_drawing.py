"""Drawing boundaries and failure recovery, independent of model aesthetics."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from companion_agent.deepseek import DeepSeekConfig
from companion_agent.llm import MainLLMError
from companion_agent.nook_art import NookArtist, PixelArt, parse_nook_decision
from companion_agent.nook_drawing import render_drawing


def drawing() -> dict[str, Any]:
    return {
        "palette": ["#58483F", "#FCF5DF", "#78907C"],
        "layers": [
            {"name": "back", "ops": [["rect", 1, 8, 8, 23, 23]]},
            {
                "name": "front",
                "ops": [["ellipse", 2, 10, 10, 21, 21], ["rect", -1, 13, 13, 18, 18]],
            },
        ],
    }


@pytest.mark.parametrize("shape", ["rect", "ellipse", "ell"])
def test_grouped_bounds_match_flat_coordinates_without_mutating_input(shape: str) -> None:
    art = drawing()
    art["layers"][0]["ops"] = [[shape, 1, [8, 8, 23, 23]]]
    original = deepcopy(art)
    flat = deepcopy(art)
    flat["layers"][0]["ops"] = [[shape, 1, 8, 8, 23, 23]]
    assert render_drawing(art) == render_drawing(flat)
    assert art == original


@pytest.mark.parametrize(
    "bounds", [[-1, 8, 23, 23], [8, 8, 32, 23], [True, 8, 23, 23], [23, 8, 8, 23]]
)
def test_grouped_bounds_keep_the_same_validation(bounds: list[Any]) -> None:
    art = drawing()
    art["layers"][0]["ops"] = [["ellipse", 1, bounds]]
    with pytest.raises(ValueError):
        render_drawing(art)


def decision() -> dict[str, Any]:
    return {
        "object": {
            "title": "留念",
            "meaning": "由一个小故事想到的摆件。",
            "sources": ["turn:synthetic"],
            "reality_layer": "real_world",
            "zone": "desk",
            "slot": 0,
            "art": drawing(),
        }
    }


def material_drawing() -> dict[str, Any]:
    """Synthetic 48px art with paint beyond the old canvas and a transparent hole."""
    return {
        "size": 48,
        "outline": -1,
        "palette": ["#785B45", "#F7E7CC", "#E2CAA6", "#B39273"],
        "layers": [
            {
                "name": "body",
                "outline": [2, 0],
                "ops": [
                    ["ellipse", 1, 9, 7, 37, 40],
                    ["ellipse", -1, 19, 13, 27, 21],
                    ["clip"],
                    ["shade", "x", [[9, 2], [14, 1], [26, 2], [33, 3]]],
                    ["line", 1, 1, [[13, 4], [13, 45]]],
                ],
            },
            {"name": "spark", "outline": -1, "ops": [["pixel", 1, 40, 43]]},
        ],
    }


def test_selective_edges_do_not_enlarge_unoutlined_sparks() -> None:
    art = {
        "size": 48,
        "outline": -1,
        "palette": ["#785B45", "#F7E7CC", "#E2CAA6"],
        "layers": [
            {"name": "body", "outline": [2, 0], "ops": [["rect", 1, 10, 10, 20, 20]]},
            {"name": "light", "outline": -1, "ops": [["pixel", 1, 40, 43]]},
        ],
    }
    rows = render_drawing(art)["rows"]
    assert rows[9][15] == rows[15][9] == "2"
    assert rows[21][15] == rows[15][21] == "0"
    assert rows[43][40] == "1"
    assert all(rows[y][x] == "." for x, y in ((39, 43), (41, 43), (40, 42), (40, 44)))
    art["outline"] = 0
    assert render_drawing(art)["rows"][43][39] == "0"  # Reproduce the old forced edge.


def test_clipped_highlights_and_shading_preserve_holes_and_silhouette() -> None:
    art = material_drawing()
    body = art["layers"][0]
    body["outline"] = -1
    base = {**art, "layers": [{**body, "ops": body["ops"][:2]}]}
    expected = render_drawing(base)["rows"]
    rows = render_drawing({**art, "layers": [body]})["rows"]
    assert [[p != "." for p in row] for row in rows] == [
        [p != "." for p in row] for row in expected
    ]
    assert rows[17][23] == "."  # The hole remains open through all paint operations.
    assert rows[28][11] == "2" and rows[28][17] == "1" and rows[28][34] == "3"
    assert rows[30][13] == "1"  # A highlight was applied inside the locked shape.
    assert rows[4][13] == rows[45][13] == "."  # It did not leak outside the silhouette.


def test_ellipse_abbreviation_preserves_pixels_clipping_and_input() -> None:
    canonical = material_drawing()
    canonical["layers"][0]["ops"].append(["ellipse", 2, 0, 0, 47, 47])
    abbreviated = deepcopy(canonical)
    for op in abbreviated["layers"][0]["ops"]:
        if op[0] == "ellipse":
            op[0] = "ell"
    before = deepcopy(abbreviated)
    assert render_drawing(abbreviated) == render_drawing(canonical)
    assert abbreviated == before


@pytest.mark.parametrize(
    "operation",
    [
        ["ell", 1, 0, 0, 48, 10],
        ["ell", 1, 20, 0, 10, 10],
        ["ell", 1, True, 0, 10, 10],
        ["ell", 4, 0, 0, 10, 10],
        ["ell", 1, 0, 0, 10],
        ["elipse", 1, 0, 0, 10, 10],
    ],
)
def test_ellipse_abbreviation_does_not_relax_drawing_validation(operation: list) -> None:
    art = material_drawing()
    art["layers"][0]["ops"] = [operation]
    with pytest.raises(ValueError):
        render_drawing(art)


def test_new_and_legacy_grids_both_round_trip_without_resizing() -> None:
    for art, side in ((drawing(), 32), (material_drawing(), 48)):
        data = decision()
        data["object"]["art"] = art
        obj = parse_nook_decision(json.dumps(data)).object
        assert obj is not None and len(obj.art.rows) == side
        assert PixelArt.model_validate_json(obj.art.model_dump_json()) == obj.art
    for rows in (["0" * 48] * 32, ["0" * 40] * 40, ["0" * 49] * 49):
        with pytest.raises(ValueError):
            PixelArt.model_validate({"palette": ["#000000"], "rows": rows})


@pytest.mark.parametrize(
    "change",
    [
        {"size": True},
        {"size": 64},
        {"outline": [0, 9]},
        {"outline": [0, 1, 2]},
        {"outline": True},
        {"layers": [{"name": "bad", "outline": -2, "ops": [["pixel", 1, 1, 1]]}]},
        {"layers": [{"name": "bad", "ops": [["shade", "z", [[0, 1], [4, 2]]]]}]},
        {"layers": [{"name": "bad", "ops": [["shade", "x", [[8, 1], [4, 2]]]]}]},
        {"layers": [{"name": "bad", "ops": [["shade", "x", [[0, 1], [4, -1]]]]}]},
        {"layers": [{"name": "bad", "ops": [["clip", "unbounded"]]}]},
    ],
)
def test_new_brushes_reject_invalid_values(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        render_drawing({**material_drawing(), **change})


def test_layers_erase_only_their_own_paint_and_outline_is_one_pixel() -> None:
    obj = parse_nook_decision(json.dumps(decision())).object
    assert obj is not None
    rows = obj.art.rows
    assert rows[12][15] == "2"  # Front ellipse.
    assert rows[15][15] == "1"  # Erasing reveals the back layer, not transparency.
    assert rows[8][8] == "1" and rows[7][8] == "0" and rows[6][8] == "."
    assert rows[0] == "." * 32


def test_only_one_missing_outer_brace_is_recoverable() -> None:
    text = json.dumps(decision())
    assert parse_nook_decision(text[:-1]) == parse_nook_decision(text)
    assert parse_nook_decision('{"object":null').object is None
    for bad in (text[:-2], text[:-30], text + " ignored", '{"object":', "{}", "```json\n" + text):
        with pytest.raises(ValueError):
            parse_nook_decision(bad)
    with pytest.raises(ValueError, match="duplicate"):
        parse_nook_decision('{"object":null,"object":null}')


@pytest.mark.parametrize(
    "op",
    [
        ["pixel", 1, True, 10],
        ["rect", 1, 0, 0, 32, 32],
        ["ellipse", 1, 20, 20, 5, 5],
        ["poly", 1, [[1, 1], [2, 2]]],
        ["line", 1, 100, [[1, 1], [2, 2]]],
        ["pixel", 7, 15, 15],
        ["image", "https://example.com/image.png"],
    ],
)
def test_rejects_invalid_or_unbounded_drawing_operations(op: list[Any]) -> None:
    art = drawing()
    art["layers"][0]["ops"] = [op]
    with pytest.raises(ValueError):
        render_drawing(art)


def test_rejects_excess_operations_and_empty_artwork() -> None:
    obj = decision()
    obj["object"]["art"]["layers"] = [{"name": "a", "ops": [["pixel", 1, 1, 1]] * 65}]
    with pytest.raises(ValueError, match="too many"):
        parse_nook_decision(json.dumps(obj))
    obj["object"]["art"]["layers"] = [{"name": "a", "ops": [["pixel", -1, 1, 1]]}]
    with pytest.raises(ValueError, match="empty"):
        parse_nook_decision(json.dumps(obj))


def test_provider_hints_preserve_thinking_choice_and_custom_endpoints() -> None:
    def payload(**options: Any) -> dict[str, Any]:
        return NookArtist(DeepSeekConfig(**options), use_environment=False).payload([])

    off = payload(thinking="disabled")
    assert off["thinking"] == {"type": "disabled"} and "reasoning_effort" not in off
    on = payload(thinking="enabled")
    assert on["thinking"] == {"type": "enabled"} and "reasoning_effort" not in on
    assert on["response_format"] == {"type": "json_object"}
    custom = payload(base_url="https://example.com/v1", thinking="enabled")
    assert "response_format" not in custom and "reasoning_effort" not in custom


def test_thinking_can_use_configured_budget_without_overriding_user_cap() -> None:
    def limit(**options: Any) -> int:
        artist = NookArtist(DeepSeekConfig(**options), use_environment=False)
        return artist.payload([])["max_tokens"]

    assert limit(thinking="enabled", max_tokens=32768) == 32768
    assert limit(thinking="enabled", max_tokens=65536) == 65536
    assert limit(thinking="enabled", max_tokens=2048) == 2048
    assert limit(thinking="disabled", max_tokens=32768) == 4096
    assert limit(model="deepseek-reasoner", max_tokens=16384) == 16384


def test_truncated_response_never_reaches_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    artist = NookArtist(use_environment=False)
    monkeypatch.setattr(
        artist,
        "_request",
        lambda *args, **kwargs: {
            "choices": [
                {"finish_reason": "length", "message": {"content": json.dumps(decision())[:-1]}}
            ]
        },
    )
    with pytest.raises(MainLLMError, match="nook_output_limit"):
        artist.generate([])

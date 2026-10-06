from __future__ import annotations

import json
from copy import deepcopy

import pytest

from companion_agent.nook_art import NookBrief, PixelArt
from companion_agent.nook_drawing import render_drawing
from companion_agent.nook_layer_retouch import apply_layer_retouch, layer_retouch_messages


def source() -> dict:
    return {
        "size": 48,
        "outline": -1,
        "palette": ["#BCA386", "#EBCBC0", "#65584A"],
        "layers": [
            {"name": "surface", "ops": [["rect", 0, 8, 8, 39, 39]]},
            {"name": "accent", "ops": [["rect", 1, 18, 18, 27, 27]]},
            {"name": "front", "ops": [["pixel", 2, 23, 23]]},
        ],
    }


def pixels(drawing: dict) -> PixelArt:
    return PixelArt.model_validate(render_drawing(drawing))


def test_smaller_layer_reveals_original_surface_and_preserves_other_layers() -> None:
    drawing = source()
    original = deepcopy(drawing)
    base = pixels(drawing)
    result = apply_layer_retouch(
        '{"edits":[{"layer":1,"ops":[["rect",1,21,21,24,24]]}]}', drawing, base
    )
    assert result.art.rows[18][18] == "0"  # Original underlying surface is revealed.
    assert result.art.rows[21][21] == "1"
    assert result.art.rows[23][23] == "2"  # Original foreground still occludes the edited layer.
    assert result.art.palette == base.palette
    assert result.changed_layers == (1,)
    assert result.drawing["layers"][0] == drawing["layers"][0]
    assert result.drawing["layers"][2] == drawing["layers"][2]
    assert drawing == original and base == pixels(original)


@pytest.mark.parametrize(
    "edits",
    [
        [{"layer": True, "ops": [["pixel", 1, 22, 22]]}],
        [{"layer": 99, "ops": [["pixel", 1, 22, 22]]}],
        [{"layer": 1, "ops": []}],
        [{"layer": 1, "ops": [["pixel", 5, 22, 22]]}],
        [{"layer": 1, "ops": [["rect", 1, 0, 0, 47, 47]]}],
        [{"layer": 1, "ops": [["pixel", 1, 22, 22]], "name": "renamed"}],
        [{"layer": 1, "ops": [["pixel", 1, 22, 22]]}] * 2,
        [{"layer": 1, "ops": [["pixel", 1, 22, 22]]}] * 3,
        [{"layer": 0, "ops": [["pixel", 1, 22, 22]]}],
    ],
)
def test_invalid_layer_edit_is_atomic(edits: list) -> None:
    drawing = source()
    original = deepcopy(drawing)
    base = pixels(drawing)
    with pytest.raises(ValueError):
        apply_layer_retouch(json.dumps({"edits": edits}), drawing, base)
    assert drawing == original and base == pixels(original)


def test_stale_drawing_source_is_rejected_before_request_and_application() -> None:
    drawing = source()
    base = pixels(drawing)
    drawing["layers"][1]["ops"] = [["pixel", 1, 18, 18]]
    brief = NookBrief(
        subject="Synthetic object",
        form="Stacked parts",
        materials="Matte colors",
        story_detail="One accent",
    )
    with pytest.raises(ValueError, match="does not match"):
        layer_retouch_messages(brief, drawing, base)
    with pytest.raises(ValueError, match="does not match"):
        apply_layer_retouch('{"edits":[]}', drawing, base)


def test_no_edits_preserves_source_and_rejects_global_palette_replacement() -> None:
    drawing = source()
    base = pixels(drawing)
    result = apply_layer_retouch('{"edits":[]}', drawing, base)
    assert result.art == base and result.drawing == drawing and result.changed_layers == ()
    with pytest.raises(ValueError):
        apply_layer_retouch('{"edits":[],"palette":["#FFFFFF"]}', drawing, base)

from __future__ import annotations

from typing import Any

import pytest

from companion_agent.nook_drawing import render_drawing


def artwork(shade: list[Any]) -> dict[str, Any]:
    return {
        "size": 48,
        "outline": -1,
        "palette": ["#12253A", "#214E78", "#4087B7", "#80BCD5", "#D4EDF1"],
        "layers": [
            {
                "name": "shape",
                "outline": -1,
                "ops": [
                    ["ellipse", 2, 10, 10, 38, 38],
                    ["ellipse", -1, 22, 22, 26, 26],
                    shade,
                ],
            }
        ],
    }


def test_round_shade_preserves_mask_holes_and_model_palette() -> None:
    data = artwork(["shade", "round", 24, 24, 14, 14, [0, 1, 2, 3, 4]])
    before = artwork(["pixel", 2, 10, 24])
    actual, base = render_drawing(data), render_drawing(before)
    assert [[p != "." for p in row] for row in actual["rows"]] == [
        [p != "." for p in row] for row in base["rows"]
    ]
    assert actual["palette"] == data["palette"]
    assert actual["rows"][24][24] == "."
    assert int(actual["rows"][18][18], 16) > int(actual["rows"][30][30], 16)
    assert len(set("".join(actual["rows"])) - {"."}) >= 4


@pytest.mark.parametrize(
    "shade",
    [
        ["shade", "round", True, 24, 14, 14, [0, 1]],
        ["shade", "round", 24, 24, 0, 14, [0, 1]],
        ["shade", "round", 24, 24, 14, 14, [0, 99]],
        ["shade", "round", 24, 24, 14, 14, [0]],
        ["shade", "round", 24, 24, 14, 14, [0, 1], "extra"],
    ],
)
def test_round_shade_rejects_invalid_model_parameters(shade: list[Any]) -> None:
    with pytest.raises(ValueError):
        render_drawing(artwork(shade))

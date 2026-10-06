"""Bounded drawing data to pixels; no model-authored code or external assets."""

from __future__ import annotations

import re
from math import sqrt
from typing import Any, cast

from PIL import Image, ImageChops, ImageDraw

SIDE = 32
SUPPORTED_SIDES = (32, 48)
MAX_LAYERS = 12
MAX_OPERATIONS = 64
PIXEL_ALPHABET = "0123456789ABCDEF"
RGBA = tuple[int, int, int, int]


def _integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid drawing integer")
    return value


def _points(value: Any, minimum: int, side: int) -> list[tuple[int, int]]:
    if not isinstance(value, list) or not minimum <= len(value) <= 32:
        raise ValueError("invalid drawing points")
    points = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError("invalid drawing point")
        points.append((_integer(point[0], 0, side - 1), _integer(point[1], 0, side - 1)))
    return points


def _outline(image: Image.Image, value: Any, colors: list[RGBA]) -> Image.Image:
    """Optional one-pixel edge; the model chooses lit and shaded edge colors."""
    if isinstance(value, list):
        if len(value) != 2:
            raise ValueError("invalid outline colors")
        light, dark = [_integer(c, 0, len(colors) - 1) for c in value]
    else:
        light = dark = _integer(value, -1, len(colors) - 1)
    if light == -1:
        return image
    side = image.width
    source = cast(list[RGBA], list(image.get_flattened_data()))
    result = image.copy()

    def filled(x: int, y: int) -> bool:
        return 0 <= x < side and 0 <= y < side and source[y * side + x][3] != 0

    for y in range(side):
        for x in range(side):
            if source[y * side + x][3]:
                continue
            if filled(x - 1, y) or filled(x, y - 1):
                result.putpixel((x, y), colors[dark])
            elif filled(x + 1, y) or filled(x, y + 1):
                result.putpixel((x, y), colors[light])
    return result


def _shade(image: Image.Image, op: list[Any], colors: list[RGBA]) -> None:
    """Discrete color bands clipped to existing paint, with no added pixels/colors."""
    if len(op) >= 2 and op[1] == "round":
        _round_shade(image, op, colors)
        return
    if len(op) != 3 or op[1] not in ("x", "y"):
        raise ValueError("invalid shade axis")
    stops = op[2]
    if not isinstance(stops, list) or not 2 <= len(stops) <= 8:
        raise ValueError("invalid shade stops")
    positions: list[tuple[int, int]] = []
    for stop in stops:
        if not isinstance(stop, list) or len(stop) != 2:
            raise ValueError("invalid shade stop")
        at, color = _integer(stop[0], 0, image.width - 1), _integer(stop[1], 0, len(colors) - 1)
        if positions and at <= positions[-1][0]:
            raise ValueError("shade stops must increase")
        positions.append((at, color))
    bands = []
    for coordinate in range(image.width):
        color = positions[0][1]
        for at, index in positions:
            if at > coordinate:
                break
            color = index
        bands.append(colors[color])
    source = cast(list[RGBA], list(image.get_flattened_data()))
    for y in range(image.height):
        for x in range(image.width):
            if source[y * image.width + x][3]:
                image.putpixel((x, y), bands[x if op[1] == "x" else y])


def _round_shade(image: Image.Image, op: list[Any], colors: list[RGBA]) -> None:
    """Quantized round-surface lighting; the model owns the mask and color ramp."""
    if len(op) != 7:
        raise ValueError("invalid round shade operation")
    cx, cy = [_integer(value, 0, image.width - 1) for value in op[2:4]]
    rx, ry = [_integer(value, 1, image.width) for value in op[4:6]]
    ramp = op[6]
    if not isinstance(ramp, list) or not 2 <= len(ramp) <= 8:
        raise ValueError("invalid round shade ramp")
    shades = [colors[_integer(value, 0, len(colors) - 1)] for value in ramp]
    # A fixed upper-left light matches the room's existing art direction. No
    # generated colors, blur, alpha changes or object-specific geometry.
    light_length = sqrt(0.55**2 + 0.65**2 + 1.0)
    lx, ly, lz = -0.55 / light_length, -0.65 / light_length, 1 / light_length
    half_length = sqrt(lx * lx + ly * ly + (lz + 1) ** 2)
    hx, hy, hz = lx / half_length, ly / half_length, (lz + 1) / half_length
    pixels = cast(list[RGBA], list(image.get_flattened_data()))
    for y in range(image.height):
        for x in range(image.width):
            if not pixels[y * image.width + x][3]:
                continue
            nx, ny = (x - cx) / rx, (y - cy) / ry
            radius = nx * nx + ny * ny
            if radius > 1:
                length = sqrt(radius)
                nx, ny = nx / length, ny / length
            nz = sqrt(max(0.0, 1 - radius))
            diffuse = max(0.0, nx * lx + ny * ly + nz * lz)
            highlight = max(0.0, nx * hx + ny * hy + nz * hz) ** 24
            brightness = min(1.0, 0.12 + 0.7 * diffuse + 0.25 * highlight)
            index = min(len(shades) - 1, int(brightness * len(shades)))
            image.putpixel((x, y), shades[index])


def validate_grid(
    x: Any, y: Any, rows: Any, *, side: int, palette_size: int
) -> tuple[int, int, list[str]]:
    """Bound local text grids; shorter rows simply have no cells to their right."""
    x, y = _integer(x, 0, side - 1), _integer(y, 0, side - 1)
    if not isinstance(rows, list) or not 1 <= len(rows) <= side - y:
        raise ValueError("invalid grid height")
    alphabet = set("." + PIXEL_ALPHABET[:palette_size])
    if any(
        not isinstance(row, str) or len(row) > side - x or not set(row) <= alphabet for row in rows
    ):
        raise ValueError("invalid grid row")
    if not any(rows):
        raise ValueError("empty grid cells")
    return x, y, rows


def _grid(image: Image.Image, op: list[Any], colors: list[RGBA]) -> None:
    if len(op) != 4:
        raise ValueError("invalid grid operation")
    x, y, rows = validate_grid(*op[1:], side=image.width, palette_size=len(colors))
    for dy, row in enumerate(rows):
        for dx, symbol in enumerate(row):
            if symbol != ".":
                image.putpixel((x + dx, y + dy), colors[int(symbol, 16)])


def render_drawing(art: dict[str, Any]) -> dict[str, Any]:
    """Render bounded integer artwork; old drawings retain their original defaults."""
    if not {"palette", "layers"} <= set(art) or set(art) - {"palette", "layers", "size", "outline"}:
        raise ValueError("unexpected drawing fields")
    side = art.get("size", SIDE)
    if type(side) is not int or side not in SUPPORTED_SIDES:
        raise ValueError("unsupported drawing size")
    palette, layers = art["palette"], art["layers"]
    if (
        not isinstance(palette, list)
        or not 1 <= len(palette) <= 16
        or any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in palette)
    ):
        raise ValueError("invalid drawing palette")
    if not isinstance(layers, list) or not 1 <= len(layers) <= MAX_LAYERS:
        raise ValueError("invalid drawing layers")
    count = 0
    for layer in layers:
        if (
            not isinstance(layer, dict)
            or not {"name", "ops"} <= set(layer)
            or set(layer) - {"name", "ops", "outline"}
            or not isinstance(layer["name"], str)
            or not 1 <= len(layer["name"]) <= 40
            or not isinstance(layer["ops"], list)
            or not layer["ops"]
        ):
            raise ValueError("invalid drawing layer")
        count += len(layer["ops"])
    if count > MAX_OPERATIONS:
        raise ValueError("too many drawing operations")

    colors: list[RGBA] = [cast(RGBA, (*bytes.fromhex(c[1:]), 255)) for c in palette]
    image = Image.new("RGBA", (side, side))
    for layer in layers:
        part = Image.new("RGBA", (side, side))
        pen = ImageDraw.Draw(part)
        clip: Image.Image | None = None
        for op in layer["ops"]:
            if not isinstance(op, list) or not op or not isinstance(op[0], str):
                raise ValueError("invalid drawing operation")
            if op == ["clip"]:
                clip = part.getchannel("A")
                continue
            before = part.copy() if clip is not None else None
            if op[0] == "shade":
                _shade(part, op, colors)
                continue  # Shade never expands the current alpha mask.
            if op[0] == "grid":
                _grid(part, op, colors)
                if clip is not None and before is not None:
                    part.paste(before, (0, 0), ImageChops.invert(clip))
                continue
            if len(op) < 2:
                raise ValueError("invalid drawing operation")
            # Accept the unambiguous ellipse abbreviation seen in model output.
            # It shares the exact same arity/bounds checks; do not guess other
            # spellings or modify the model's geometry, colors or operation list.
            name = "ellipse" if op[0] == "ell" else op[0]
            index = _integer(op[1], -1, len(colors) - 1)
            color = (0, 0, 0, 0) if index == -1 else colors[index]
            if name in {"rect", "ellipse"} and (
                len(op) == 6 or (len(op) == 3 and isinstance(op[2], list) and len(op[2]) == 4)
            ):
                # Grouped bounds are the same four coordinates, not an inferred
                # shape repair. Keep the original drawing and all strict limits.
                bounds = op[2] if len(op) == 3 else op[2:]
                x1, y1, x2, y2 = [_integer(v, 0, side - 1) for v in bounds]
                if x1 > x2 or y1 > y2:
                    raise ValueError("reversed drawing rectangle")
                draw = pen.rectangle if name == "rect" else pen.ellipse
                draw((x1, y1, x2, y2), fill=color)
            elif name == "poly" and len(op) == 3:
                pen.polygon(_points(op[2], 3, side), fill=color)
            elif name == "line" and len(op) == 4:
                pen.line(_points(op[3], 2, side), fill=color, width=_integer(op[2], 1, side))
            elif name == "pixel" and len(op) == 4:
                pen.point((_integer(op[2], 0, side - 1), _integer(op[3], 0, side - 1)), fill=color)
            else:
                raise ValueError("unsupported drawing operation")
            if clip is not None and before is not None:
                part.paste(before, (0, 0), ImageChops.invert(clip))
        image = Image.alpha_composite(image, _outline(part, layer.get("outline", -1), colors))

    image = _outline(image, art.get("outline", 0), colors)
    pixels = cast(list[RGBA], list(image.get_flattened_data()))
    lookup = {color: "0123456789ABCDEF"[i] for i, color in enumerate(colors)}
    rows = []
    for y in range(side):
        row = ""
        for x in range(side):
            pixel = pixels[y * side + x]
            if pixel[3]:
                row += lookup[pixel]
            else:
                row += "."
        rows.append(row)
    return {"palette": palette, "rows": rows}

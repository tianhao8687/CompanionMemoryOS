"""Lossless receipt storage, with smaller projections for model input."""

from __future__ import annotations

import json
from typing import Any


def model_result(result: dict[str, Any], *, music: bool = False) -> dict[str, Any]:
    projected = dict(result)
    data, text = projected.get("data"), projected.get("text")
    if data is not None and isinstance(text, str):
        try:
            duplicate = json.loads(text) == data
        except (ValueError, TypeError):
            duplicate = False
        if duplicate:
            projected.pop("text")
    if music:
        # Images/links belong to song cards. Keep every candidate's ID, title,
        # artist, album, duration and lyric-match evidence for version selection.
        def without_images(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    k: without_images(v)
                    for k, v in value.items()
                    if k not in {"artwork", "artwork_base64", "cover_url", "thumbnail", "url"}
                }
            if isinstance(value, list):
                return [without_images(v) for v in value]
            return value

        projected = without_images(projected)
    return projected


def model_receipt(action: dict[str, Any], *, music: bool = False) -> dict[str, Any]:
    return {
        "id": action["id"],
        "tool_name": action["tool_name"],
        "arguments": action["arguments"],
        "status": action["status"],
        "result": model_result(action["result"], music=music),
    }

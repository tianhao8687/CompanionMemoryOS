"""Interpret bounded native observations, never infer a person's emotion from light."""

from __future__ import annotations

import math
from statistics import median
from typing import Any


def screen_environment(light: dict[str, Any], proximity: dict[str, Any]) -> dict[str, Any]:
    def skipped(reason: str) -> dict[str, Any]:
        return {"eligible": False, "reason": reason}

    for result in (light, proximity):
        age = result.get("age_ms")
        if (
            result.get("status") != "succeeded"
            or result.get("foreground") is not True
            or not isinstance(age, (int, float))
            or isinstance(age, bool)
            or not 0 <= age <= 3000
        ):
            return skipped("unavailable")
    if proximity.get("is_near") is not False:
        return skipped("possibly_covered")
    rows = light.get("readings")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        return skipped("unavailable")
    values: list[float] = []
    for row in rows:
        value = row.get("lux") if isinstance(row, dict) else None
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 <= value <= 1e6
        ):
            return skipped("unavailable")
        values.append(float(value))
    lux = float(median(values))
    # Engineering limits for this conservative first release, not a medical or
    # universal display calibration. On-change sensors may report one valid value.
    if max(values) - min(values) > max(5.0, lux * 0.5):
        return skipped("changing_light")
    return {
        "eligible": max(values) <= 50,
        "reason": "dim_environment" if max(values) <= 50 else "environment_bright",
        "lux": round(lux, 1),
    }

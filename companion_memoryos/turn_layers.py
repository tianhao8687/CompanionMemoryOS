"""A partial quote must not reclassify the entire original conversation turn."""

from __future__ import annotations

import json

from companion_memoryos.schemas.core import RealityLayer


def turn_reality_layer(content: str, metadata_json: str, spans_json: str) -> str:
    metadata = json.loads(metadata_json)
    declared = metadata.get("process_reality_layer")
    if declared in {layer.value for layer in RealityLayer}:
        return str(declared)
    spans = json.loads(spans_json)
    if not spans:
        return RealityLayer.REAL_WORLD.value
    layers = {span.get("reality_layer", RealityLayer.REAL_WORLD.value) for span in spans}
    if len(layers) != 1:
        return RealityLayer.REAL_WORLD.value
    # Older hosts might annotate only a quotation inside an otherwise direct utterance.
    # A non-real layer applies to the whole legacy turn only when the spans cover it fully.
    covered_until = 0
    for span in sorted(spans, key=lambda item: item["start_offset"]):
        if span["start_offset"] > covered_until:
            return RealityLayer.REAL_WORLD.value
        covered_until = max(covered_until, span["end_offset"])
    return (
        str(next(iter(layers))) if covered_until >= len(content) else RealityLayer.REAL_WORLD.value
    )

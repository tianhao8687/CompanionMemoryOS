from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from companion_agent.persona.models import PersonaDefinition


class _UniqueLoader(yaml.SafeLoader):
    """Reject accidental shadowing instead of silently changing a persona."""


def _mapping(loader: _UniqueLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def loads_persona(text: str) -> PersonaDefinition:
    if len(text.encode("utf-8")) > 1_000_000:
        raise ValueError("persona YAML exceeds 1 MB")
    # Aliases are unnecessary here and can create cyclic or exponentially expanded trees.
    if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(text)):
        raise ValueError("YAML aliases are not supported")
    return PersonaDefinition.model_validate(yaml.load(text, Loader=_UniqueLoader))


def load_persona(path: str | Path | None = None) -> PersonaDefinition:
    source = (
        Path(path)
        if path is not None
        else files("companion_agent").joinpath("defaults/persona.example.yaml")
    )
    return loads_persona(source.read_text(encoding="utf-8"))

"""Output validation against the kit's schema.json.

The exact layout of schema.json is not assumed: the loader looks for the four
keys and the eight intents in the common shapes (plain lists, or a JSON-Schema
"properties"/"enum" layout) and falls back to the values from the assignment
specification if it cannot find them. Every model output is checked here.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_KEYS = ["intent", "date", "time", "place"]
DEFAULT_INTENTS = [
    "alarm_set", "alarm_query", "calendar_set", "calendar_query",
    "calendar_remove", "weather_query", "datetime_query", "recommendation_events",
]


def _find(obj: Any, names: tuple[str, ...]) -> Any:
    """Depth-first search for the first key in `names` whose value is a list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in names and isinstance(v, list):
                return v
        for v in obj.values():
            found = _find(v, names)
            if found is not None:
                return found
    return None


class Schema:
    def __init__(self, keys: list[str], intents: list[str]):
        self.keys = list(keys)
        self.intents = set(intents)

    @classmethod
    def load(cls, path: str | Path | None) -> "Schema":
        if path and Path(path).exists():
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            keys = _find(data, ("keys", "required", "fields"))
            intents = _find(data, ("intents", "enum", "intent_labels"))
            if isinstance(data, dict) and isinstance(data.get("properties"), dict):
                keys = keys or list(data["properties"].keys())
            if keys and intents and all(isinstance(x, str) for x in keys + intents):
                return cls(keys, intents)
            log.warning("schema.json at %s not understood; using built-in schema", path)
        return cls(DEFAULT_KEYS, DEFAULT_INTENTS)

    def validate(self, raw: str) -> dict | None:
        """Return the parsed frame (keys in schema order) or None if invalid."""
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(obj, dict) or set(obj.keys()) != set(self.keys):
            return None
        if obj["intent"] not in self.intents:
            return None
        for k in self.keys:
            if k != "intent" and obj[k] is not None and not isinstance(obj[k], str):
                return None
        return {k: obj[k] for k in self.keys}

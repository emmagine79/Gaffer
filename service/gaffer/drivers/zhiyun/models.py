"""Zhiyun model files: one JSON per model under gaffer/models/zhiyun/, matched by name prefix.

A real MOLUS G200 advertises as "PL109_C75E" with mesh service 0x1828 and no
0xFEE9 (Gaffer scan, 18 Oct 2026), so the match is on the local name only.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .protocol import VALID_OPS

MODELS_DIR = Path(__file__).resolve().parents[2] / "models" / "zhiyun"


@lru_cache(maxsize=1)
def load_models() -> dict[str, dict[str, Any]]:
    """Every model file by id. A malformed file raises: they ship with the app."""
    models: dict[str, dict[str, Any]] = {}
    for path in sorted(MODELS_DIR.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row["id"] != path.stem or row["driver"] != "zhiyun":
            raise ValueError(f"model file {path.name} does not match its id or driver")
        if row["driver_data"]["control_mode"] not in VALID_OPS:
            raise ValueError(f"model file {path.name} has an unknown control_mode")
        models[row["id"]] = row
    return models


def resolve_model(name: str | None) -> dict[str, Any] | None:
    """The model file whose name prefix starts ``name``; the longest prefix wins."""
    if not isinstance(name, str) or not name:
        return None
    best: dict[str, Any] | None = None
    for row in load_models().values():
        prefix = row["match"]["name_prefix"]
        if name.startswith(prefix) and (best is None or len(prefix) > len(best["match"]["name_prefix"])):
            best = row
    return best

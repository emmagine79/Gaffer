"""JSON persistence for everything the user creates. Atomic writes, no database."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

COLLECTIONS: tuple[str, ...] = ("scenes", "presets", "timelines", "schedules", "swatches", "looks", "cues")

DEFAULT_SETTINGS: dict[str, Any] = {
    "max_rate": 40.0,          # commands/s ceiling, shared by every light; an ML100R kept up with 80 paced
    "relay_ttl": 5,            # hops for commands relayed to lights other than the connected one
    "sync_interval": 0.7,      # seconds between record polls while a browser is watching; 0 = off
    "default_fade": 0.6,       # seconds for scene recall fades
    "favorites": [],           # gel labels
    "light_states": {},        # last look of each light, by light id
    "groups": [],              # sync groups: lights that follow each other
    "theme_accent": "auto",
}


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


#: What each setting may hold. A value outside these never reaches the disk,
#: because a bad one (a rate of 0, a string) would break the next start.
SETTING_RULES: dict[str, tuple[type, float | None, float | None]] = {
    "max_rate": (float, 2.0, 80.0),
    "relay_ttl": (int, 2, 127),
    "sync_interval": (float, 0.0, 30.0),
    "default_fade": (float, 0.0, 60.0),
}


def check_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """``patch`` with numbers coerced, or ValueError naming what is wrong."""
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        if key in SETTING_RULES:
            kind, low, high = SETTING_RULES[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            number = kind(value)
            if (low is not None and number < low) or (high is not None and number > high):
                raise ValueError(f"{key} must be between {low} and {high}")
            clean[key] = number
        elif key == "favorites":
            if not isinstance(value, list) or len(value) > 1000 or not all(isinstance(v, str) and len(v) < 80 for v in value):
                raise ValueError("favorites must be a list of gel names")
            clean[key] = value
        elif key == "theme_accent":
            if not isinstance(value, str) or len(value) > 32:
                raise ValueError("theme_accent must be a short string")
            clean[key] = value
        else:
            clean[key] = value
    return clean


def _id_of(item: Any) -> Any:
    """An item's id, or None for an entry a hand-edit left without one (it is kept, not fatal)."""
    return item.get("id") if isinstance(item, dict) else None


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        stored = self._read("settings", {})
        # Settings from older versions that no longer mean anything are dropped,
        # and one that fails its rule falls back to the default rather than
        # stopping the studio from starting.
        kept: dict[str, Any] = {}
        for key, value in (stored.items() if isinstance(stored, dict) else ()):
            if key not in DEFAULT_SETTINGS:
                continue
            try:
                kept.update(check_settings({key: value}))
            except ValueError:
                continue
        self.settings: dict[str, Any] = {**DEFAULT_SETTINGS, **kept}
        self.collections: dict[str, list[dict[str, Any]]] = {
            name: self._read(name, []) for name in COLLECTIONS
        }

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def _read(self, name: str, default: Any) -> Any:
        try:
            return json.loads(self._path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    # -- settings ------------------------------------------------------------------

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        unknown = set(patch) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"unknown setting(s): {sorted(unknown)}")
        self.settings = {**self.settings, **check_settings(patch)}
        _atomic_write(self._path("settings"), self.settings)
        return self.settings

    # -- collections ----------------------------------------------------------------

    def items(self, collection: str) -> list[dict[str, Any]]:
        if collection not in self.collections:
            raise KeyError(collection)
        return self.collections[collection]

    def upsert(self, collection: str, item: dict[str, Any]) -> dict[str, Any]:
        items = self.items(collection)
        now = time.time()
        stored = {**item, "id": item.get("id") or uuid.uuid4().hex[:10], "updated": now}
        stored.setdefault("created", now)
        replaced = [stored if _id_of(i) == stored["id"] else i for i in items]
        if not any(_id_of(i) == stored["id"] for i in items):
            replaced.append(stored)
        self.collections[collection] = replaced
        _atomic_write(self._path(collection), replaced)
        return stored

    def delete(self, collection: str, item_id: str) -> None:
        kept = [i for i in self.items(collection) if _id_of(i) != item_id]
        self.collections[collection] = kept
        _atomic_write(self._path(collection), kept)

    def reorder(self, collection: str, ids: list[str]) -> None:
        by_id = {i["id"]: i for i in self.items(collection)}
        ordered = [by_id[i] for i in ids if i in by_id] + [i for i in by_id.values() if i["id"] not in ids]
        self.collections[collection] = ordered
        _atomic_write(self._path(collection), ordered)

    def snapshot(self) -> dict[str, Any]:
        return {"settings": self.settings, **self.collections}

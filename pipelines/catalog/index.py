"""rebuild_index(), the only writer of catalog/index.json, and promote() from staging to prod."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .publish import entry_key
from .storage import NO_CACHE, PreconditionFailed, Storage
from .validate import dump_json, validate_entry, validate_index

INDEX_KEY = "catalog/index.json"
ENTRIES_PREFIX = "catalog/entries/"


def _read_entry(storage: Storage, key: str) -> tuple[dict[str, Any], bytes] | None:
    blob = storage.read(key)
    if blob is None:
        return None
    entry: dict[str, Any] = json.loads(blob.data)
    validate_entry(entry)
    if key != entry_key(entry["layer"], entry["date"]):
        raise ValueError(f"{key} holds the entry of {entry['layer']} {entry['date']}")
    return entry, blob.data


def _entry_keys(storage: Storage) -> list[str]:
    return [key for key in storage.list(ENTRIES_PREFIX) if key.endswith(".json")]


def rebuild_index(storage: Storage, attempts: int = 8) -> dict[str, Any]:
    """Rebuild catalog/index.json from every entry object and write it if it changed.

    The write is conditional on the generation read before listing the entries, so two rebuilds that race
    never lose an entry: the one that loses the race lists again and retries.
    """
    for attempt in range(attempts):
        current = storage.read(INDEX_KEY)
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda key: _read_entry(storage, key), _entry_keys(storage)))
        layers: dict[str, dict[str, list[Any]]] = {}
        for entry, _ in sorted((r for r in results if r is not None), key=lambda r: (r[0]["layer"], r[0]["date"])):
            layer = layers.setdefault(entry["layer"], {"dates": [], "entries": []})
            layer["dates"].append(entry["date"])
            layer["entries"].append(entry)
        digest = hashlib.sha256(json.dumps(layers, sort_keys=True).encode()).hexdigest()
        if current is not None:
            published: dict[str, Any] = json.loads(current.data)
            if published.get("entries_digest") == digest:
                return published
        index = {
            "schema_version": 1,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "entries_digest": digest,
            "layers": layers,
        }
        validate_index(index)
        try:
            storage.write(
                INDEX_KEY,
                dump_json(index, separators=(",", ":")),
                "application/json",
                NO_CACHE,
                if_generation_match=current.generation if current is not None else 0,
            )
            return index
        except PreconditionFailed:
            time.sleep(min(2**attempt * 0.1, 5) * random.uniform(0.5, 1.5))
    raise RuntimeError(f"{INDEX_KEY} changed under every one of {attempts} rebuild attempts")


def _write_entry_unless_newer(target: Storage, key: str, entry: dict[str, Any], data: bytes) -> None:
    """Write a promoted entry unless prod already holds a newer publication of that date.

    Promotes run side by side, so a slow one could otherwise overwrite the version a later promote copied
    after staging republished the date. The write is conditional on the prod generation it compared against.
    """
    for _ in range(8):
        current = target.read(key)
        if current is not None:
            if current.data == data:
                return
            published = dt.datetime.fromisoformat(json.loads(current.data)["created_at"])
            if published > dt.datetime.fromisoformat(entry["created_at"]):
                return
        try:
            target.write(
                key,
                data,
                "application/json",
                NO_CACHE,
                if_generation_match=current.generation if current is not None else 0,
            )
            return
        except PreconditionFailed:
            continue
    raise RuntimeError(f"{key} kept changing in the target while being promoted")


def promote(
    source: Storage, target: Storage, start: str, end: str, layers: list[str] | None = None
) -> list[dict[str, Any]]:
    """Copy the entries dated start..end (inclusive) and their files from staging to prod, then rebuild prod.

    Files go first and entries after, as in publish(), so prod never lists a file it does not hold. A prod
    entry newer than the staging one (a later promote of a republished date) is kept.
    """
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    promoted = []
    for key in _entry_keys(source):
        layer, name = key[len(ENTRIES_PREFIX) :].split("/", 1)
        if layers is not None and layer not in layers:
            continue
        if not first <= dt.date.fromisoformat(name.removesuffix(".json")) <= last:
            continue
        read = _read_entry(source, key)
        if read is None:
            continue
        entry, data = read
        for file_key in (entry["cog"], entry["pmtiles"]):
            if not target.exists(file_key):
                try:
                    target.copy_from(source, file_key, if_generation_match=0)
                except PreconditionFailed:
                    pass
        _write_entry_unless_newer(target, key, entry, data)
        promoted.append(entry)
    if not promoted:
        raise ValueError(f"No staging entries between {start} and {end} for layers {layers or 'all'}")
    rebuild_index(target)
    return promoted

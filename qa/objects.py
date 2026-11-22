"""Reading catalogue objects for the checks: COGs as local files, PMTiles by byte range."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pipelines.catalog import GcsStorage, LocalStorage, Storage, storage_from_env

ByteReader = Callable[[int, int], bytes]


def catalogue(target: str, root: str = "") -> Storage:
    """The staging or prod catalogue, or a catalogue under `root` inside it (for example a `_scratch/` trial)."""
    base = storage_from_env(target)
    root = root.strip("/")
    if not root:
        return base
    if isinstance(base, LocalStorage):
        return LocalStorage(base.root / root)
    if isinstance(base, GcsStorage):
        return GcsStorage(base.bucket_name, base.prefix + root)
    raise TypeError(f"Unsupported storage {base!r}")


def local_file(storage: Storage, key: str, folder: Path) -> Path | None:
    """A local path holding the object, downloaded into `folder` unless the catalogue is a local folder."""
    if isinstance(storage, LocalStorage):
        path = storage.root / key
        return path if path.is_file() else None
    blob = storage.read(key)
    if blob is None:
        return None
    path = folder / key.replace("/", "__")
    path.write_bytes(blob.data)
    return path


def byte_reader(storage: Storage, key: str) -> tuple[ByteReader, int] | None:
    """A reader of (offset, length) ranges and the object size, so large PMTiles are never downloaded whole."""
    if isinstance(storage, LocalStorage):
        path = storage.root / key
        if not path.is_file():
            return None

        def read_local(offset: int, length: int) -> bytes:
            with open(path, "rb") as handle:
                handle.seek(offset)
                return handle.read(length)

        return read_local, os.path.getsize(path)
    if isinstance(storage, GcsStorage):
        from google.cloud import storage as gcs

        blob = gcs.Client().bucket(storage.bucket_name).get_blob(storage.prefix + key)
        if blob is None:
            return None
        generation = blob.generation

        def read_gcs(offset: int, length: int) -> bytes:
            if length <= 0:
                return b""
            data: bytes = blob.download_as_bytes(
                start=offset, end=offset + length - 1, if_generation_match=generation, checksum=None
            )
            return data

        return read_gcs, int(blob.size)
    raise TypeError(f"Unsupported storage {storage!r}")


def index_entries(storage: Storage) -> dict[str, list[dict[str, Any]]]:
    """The entries of catalog/index.json by layer; empty when there is no index yet."""
    blob = storage.read("catalog/index.json")
    if blob is None:
        return {}
    return {layer: item["entries"] for layer, item in json.loads(blob.data)["layers"].items()}

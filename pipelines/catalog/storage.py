"""Where a catalogue lives: a local folder (tests, trial runs) or a bucket prefix in Google Cloud Storage."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"
LOCK_TIMEOUT_S = 30.0
STALE_LOCK_S = 10.0


class PreconditionFailed(Exception):
    """The object's generation did not match; for generation 0, the object already exists."""


@dataclass(frozen=True)
class Blob:
    data: bytes
    generation: int
    content_type: str
    cache_control: str
    content_encoding: str | None


class Storage(Protocol):
    """Keys are relative to the catalogue root, for example `catalog/index.json`.

    `if_generation_match=0` means "only if the object does not exist", as in Google Cloud Storage.
    """

    def read(self, key: str) -> Blob | None: ...

    def exists(self, key: str) -> bool: ...

    def write(
        self,
        key: str,
        source: Path | bytes,
        content_type: str,
        cache_control: str,
        if_generation_match: int | None = None,
    ) -> int: ...

    def list(self, prefix: str) -> list[str]: ...

    def copy_from(self, source: Storage, key: str, if_generation_match: int | None = None) -> None: ...


class LocalStorage:
    """A catalogue in a folder. Object metadata (generation, headers) lives under `.meta/`."""

    _thread_lock = threading.Lock()

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return f"LocalStorage({self.root})"

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/") or key.startswith(".meta"):
            raise ValueError(f"Bad key {key!r}")
        return self.root / key

    def _meta_path(self, key: str) -> Path:
        return self.root / ".meta" / f"{key}.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        # A lock file makes compare-and-swap safe across processes too, not only threads.
        lock = self.root / ".lock"
        with self._thread_lock:
            deadline = time.monotonic() + LOCK_TIMEOUT_S
            while True:
                try:
                    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                # On Windows a lock file another process is deleting is "delete pending" for a moment: opening
                # or inspecting it raises PermissionError, which means busy here, like FileExistsError.
                except (FileExistsError, PermissionError):
                    try:
                        age = time.time() - lock.stat().st_mtime
                    except OSError:
                        age = 0.0
                    # The lock covers a metadata write and a rename (milliseconds); an old one was left by a
                    # killed process.
                    if age > STALE_LOCK_S:
                        lock.unlink(missing_ok=True)
                        continue
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Lock {lock} held for more than {LOCK_TIMEOUT_S} s") from None
                    time.sleep(0.005)
            try:
                yield
            finally:
                os.close(fd)
                os.remove(lock)

    def _meta(self, key: str) -> dict | None:
        path = self._meta_path(key)
        if not path.exists() or not self._path(key).exists():
            return None
        meta: dict = json.loads(path.read_text(encoding="utf-8"))
        return meta

    def read(self, key: str) -> Blob | None:
        with self._locked():
            meta = self._meta(key)
            if meta is None:
                return None
            return Blob(
                self._path(key).read_bytes(),
                meta["generation"],
                meta["content_type"],
                meta["cache_control"],
                None,
            )

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def write(
        self,
        key: str,
        source: Path | bytes,
        content_type: str,
        cache_control: str,
        if_generation_match: int | None = None,
    ) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stage next to the target and rename, so a crash never leaves a half-written object.
        fd, staged = tempfile.mkstemp(dir=path.parent, prefix=".staged-")
        os.close(fd)
        try:
            if isinstance(source, bytes):
                Path(staged).write_bytes(source)
            else:
                shutil.copyfile(source, staged)
            with self._locked():
                meta = self._meta(key)
                current = meta["generation"] if meta else 0
                if if_generation_match is not None and if_generation_match != current:
                    raise PreconditionFailed(f"{key}: generation {current}, expected {if_generation_match}")
                generation = current + 1
                os.replace(staged, path)
                meta_path = self._meta_path(key)
                meta_path.parent.mkdir(parents=True, exist_ok=True)
                meta_path.write_text(
                    json.dumps(
                        {"generation": generation, "content_type": content_type, "cache_control": cache_control}
                    ),
                    encoding="utf-8",
                )
                return generation
        finally:
            if os.path.exists(staged):
                os.remove(staged)

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix.rstrip("/")) if prefix else self.root
        if not base.exists():
            return []
        keys = []
        for path in base.rglob("*"):
            if path.is_file() and not path.name.startswith(".staged-"):
                key = path.relative_to(self.root).as_posix()
                if not key.startswith(".meta/") and key != ".lock":
                    keys.append(key)
        return sorted(keys)

    def copy_from(self, source: Storage, key: str, if_generation_match: int | None = None) -> None:
        blob = source.read(key)
        if blob is None:
            raise FileNotFoundError(f"{key} not in {source!r}")
        self.write(key, blob.data, blob.content_type, blob.cache_control, if_generation_match)


class GcsStorage:
    """A catalogue under a prefix of a Google Cloud Storage bucket, through google-cloud-storage.

    Credentials come from Application Default Credentials (Workload Identity Federation in Actions).
    """

    def __init__(self, bucket: str, prefix: str = "") -> None:
        from google.cloud import storage

        self.bucket_name = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    def __repr__(self) -> str:
        return f"GcsStorage(gs://{self.bucket_name}/{self.prefix})"

    def _name(self, key: str) -> str:
        return self.prefix + key

    def read(self, key: str) -> Blob | None:
        from google.api_core.exceptions import NotFound
        from google.api_core.exceptions import PreconditionFailed as GcsPreconditionFailed

        for _ in range(5):
            blob = self._bucket.get_blob(self._name(key))
            if blob is None:
                return None
            # The download overwrites these with its response headers (authenticated reads answer no-cache).
            stored = Blob(b"", int(blob.generation), blob.content_type, blob.cache_control, blob.content_encoding)
            try:
                # Pinning the generation returns the bytes and the generation of the same version.
                data = blob.download_as_bytes(if_generation_match=stored.generation)
            except (NotFound, GcsPreconditionFailed):
                continue
            return Blob(data, stored.generation, stored.content_type, stored.cache_control, stored.content_encoding)
        raise RuntimeError(f"{key} kept changing while being read")

    def exists(self, key: str) -> bool:
        return bool(self._bucket.blob(self._name(key)).exists())

    def write(
        self,
        key: str,
        source: Path | bytes,
        content_type: str,
        cache_control: str,
        if_generation_match: int | None = None,
    ) -> int:
        from google.api_core.exceptions import PreconditionFailed as GcsPreconditionFailed
        from google.cloud.storage.retry import DEFAULT_RETRY, DEFAULT_RETRY_IF_GENERATION_SPECIFIED

        blob = self._bucket.blob(self._name(key))
        blob.cache_control = cache_control
        # Never set content_encoding: gzip-encoded objects break HTTP range requests on PMTiles and COGs.
        # google-cloud-storage retries only conditional writes by default. The unconditional writes here are
        # entry overwrites, which end the same however many times they land, so retrying them is safe too.
        retry = DEFAULT_RETRY if if_generation_match is None else DEFAULT_RETRY_IF_GENERATION_SPECIFIED
        try:
            if isinstance(source, bytes):
                blob.upload_from_string(
                    source, content_type=content_type, if_generation_match=if_generation_match, retry=retry
                )
            else:
                blob.upload_from_filename(
                    str(source), content_type=content_type, if_generation_match=if_generation_match, retry=retry
                )
        except GcsPreconditionFailed as error:
            raise PreconditionFailed(str(error)) from error
        return int(blob.generation)

    def list(self, prefix: str) -> list[str]:
        start = len(self.prefix)
        return sorted(
            blob.name[start:] for blob in self._client.list_blobs(self.bucket_name, prefix=self._name(prefix))
        )

    def copy_from(self, source: Storage, key: str, if_generation_match: int | None = None) -> None:
        from google.api_core.exceptions import PreconditionFailed as GcsPreconditionFailed

        if isinstance(source, GcsStorage):
            # Server-side copy; it keeps the source's metadata (content type, cache control).
            try:
                source._bucket.copy_blob(
                    source._bucket.blob(source._name(key)),
                    self._bucket,
                    self._name(key),
                    if_generation_match=if_generation_match,
                )
            except GcsPreconditionFailed as error:
                raise PreconditionFailed(str(error)) from error
            return
        blob = source.read(key)
        if blob is None:
            raise FileNotFoundError(f"{key} not in {source!r}")
        self.write(key, blob.data, blob.content_type, blob.cache_control, if_generation_match)


def storage_from_env(target: str) -> Storage:
    """The catalogue of `staging` or `prod`, from the repository variables the workflows export.

    STAGING_BUCKET / STAGING_PREFIX and DATA_BUCKET / DATA_PREFIX name the place, so moving to other
    buckets is a variable change. CATALOG_LOCAL_ROOT points both at a local folder instead (trial runs).
    """
    if target not in ("staging", "prod"):
        raise ValueError(f"target must be staging or prod, not {target!r}")
    local_root = os.environ.get("CATALOG_LOCAL_ROOT")
    if local_root:
        return LocalStorage(Path(local_root) / target)
    bucket_var, prefix_var = (
        ("STAGING_BUCKET", "STAGING_PREFIX") if target == "staging" else ("DATA_BUCKET", "DATA_PREFIX")
    )
    bucket = os.environ.get(bucket_var)
    if not bucket:
        raise RuntimeError(f"{bucket_var} is not set")
    return GcsStorage(bucket, os.environ.get(prefix_var, ""))

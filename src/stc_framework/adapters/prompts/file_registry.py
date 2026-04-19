"""File-backed JSON prompt registry with version history.

Default implementation that persists to a local JSON file so a single
process restart does not lose prompt rotations performed by the Trainer.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import RLock
from typing import Any

from stc_framework.adapters.prompts.base import PromptRecord, PromptRegistry
from stc_framework.errors import PromptRegistryError


class FilePromptRegistry(PromptRegistry):
    """Simple append-on-register, flip-active file store."""

    def __init__(self, path: str | Path = ".stc/prompts.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._cache: dict[str, list[PromptRecord]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._cache = {}
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise PromptRegistryError(
                message=f"Corrupt prompt registry file {self._path}: {exc}"
            ) from exc
        self._cache = {
            name: [PromptRecord(**r) for r in records] for name, records in data.items()
        }

    def _persist(self) -> None:
        serial: dict[str, list[dict[str, Any]]] = {}
        for name, records in self._cache.items():
            serial[name] = [r.__dict__ for r in records]
        self._path.write_text(json.dumps(serial, indent=2), encoding="utf-8")

    def seed(self, records: list[PromptRecord]) -> None:
        """Seed initial prompts. Used for zero-install bootstrap."""
        with self._lock:
            for rec in records:
                bucket = self._cache.setdefault(rec.name, [])
                if not any(r.version == rec.version for r in bucket):
                    bucket.append(rec)
                    if rec.active:
                        for other in bucket:
                            other.active = other.version == rec.version
            self._persist()

    async def get(self, name: str, version: str | None = None) -> PromptRecord:
        def _do() -> PromptRecord:
            with self._lock:
                bucket = self._cache.get(name)
                if not bucket:
                    raise PromptRegistryError(message=f"Prompt not found: {name}")
                if version is None:
                    for rec in bucket:
                        if rec.active:
                            return rec
                    return bucket[-1]
                for rec in bucket:
                    if rec.version == version:
                        return rec
                raise PromptRegistryError(
                    message=f"Prompt {name} has no version {version!r}"
                )

        return await asyncio.to_thread(_do)

    async def register(self, record: PromptRecord) -> None:
        def _do() -> None:
            with self._lock:
                bucket = self._cache.setdefault(record.name, [])
                if any(r.version == record.version for r in bucket):
                    raise PromptRegistryError(
                        message=f"Prompt {record.name} v{record.version} already registered"
                    )
                bucket.append(record)
                if record.active:
                    for other in bucket:
                        other.active = other.version == record.version
                self._persist()

        await asyncio.to_thread(_do)

    async def set_active(self, name: str, version: str) -> None:
        def _do() -> None:
            with self._lock:
                bucket = self._cache.get(name)
                if not bucket:
                    raise PromptRegistryError(message=f"Prompt not found: {name}")
                if not any(r.version == version for r in bucket):
                    raise PromptRegistryError(
                        message=f"Prompt {name} has no version {version!r}"
                    )
                for rec in bucket:
                    rec.active = rec.version == version
                self._persist()

        await asyncio.to_thread(_do)

    async def list_versions(self, name: str) -> list[PromptRecord]:
        def _do() -> list[PromptRecord]:
            with self._lock:
                return list(self._cache.get(name, []))

        return await asyncio.to_thread(_do)

    async def healthcheck(self) -> bool:
        return self._path.parent.exists()

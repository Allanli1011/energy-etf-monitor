import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class Connector(Protocol):
    """Common shape for source connectors."""

    source: str


class RawPayloadStore:
    """Persist raw source payloads before parsing for provenance and replay."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def save_json(
        self,
        *,
        source: str,
        payload: Any,
        fetched_at: datetime,
        label: str,
    ) -> Path:
        fetched_at_utc = fetched_at.astimezone(UTC) if fetched_at.tzinfo else fetched_at
        source_dir = self.root_dir / self._slug(source) / fetched_at_utc.date().isoformat()
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / f"{fetched_at_utc:%H%M%S}_{self._slug(label)}.json"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return path

    def save_text(
        self,
        *,
        source: str,
        text: str,
        fetched_at: datetime,
        label: str,
        extension: str = "txt",
    ) -> Path:
        fetched_at_utc = fetched_at.astimezone(UTC) if fetched_at.tzinfo else fetched_at
        source_dir = self.root_dir / self._slug(source) / fetched_at_utc.date().isoformat()
        source_dir.mkdir(parents=True, exist_ok=True)
        path = source_dir / f"{fetched_at_utc:%H%M%S}_{self._slug(label)}.{extension}"
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip().lower())
        return slug.strip("_") or "payload"

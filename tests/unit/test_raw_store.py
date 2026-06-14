import json
from datetime import UTC, datetime
from pathlib import Path

from energy_etf_monitor.ingestion.base import RawPayloadStore


def test_raw_payload_store_writes_dated_json_with_stable_label(tmp_path: Path) -> None:
    store = RawPayloadStore(root_dir=tmp_path)
    fetched_at = datetime(2026, 6, 13, 12, 30, tzinfo=UTC)

    path = store.save_json(
        source="eia",
        payload={"response": {"data": [{"period": "2026-06-12", "value": 42}]}},
        fetched_at=fetched_at,
        label="wti_inventory",
    )

    assert path == tmp_path / "eia" / "2026-06-13" / "123000_wti_inventory.json"
    assert json.loads(path.read_text())["response"]["data"][0]["value"] == 42


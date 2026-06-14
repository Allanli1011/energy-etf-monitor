from datetime import UTC, datetime
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import TimeSeriesObservation


class EiaSeriesConnector:
    source = "eia"
    base_url = "https://api.eia.gov/v2/seriesid"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.raw_store = raw_store
        self.client = client

    def fetch_series(self, series_id: str) -> list[TimeSeriesObservation]:
        fetched_at = datetime.now(UTC)
        params = {"api_key": self.api_key} if self.api_key else {}
        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            response = client.get(f"{self.base_url}/{series_id}", params=params)
            response.raise_for_status()
            payload = response.json()
        finally:
            if close_client:
                client.close()

        if self.raw_store:
            self.raw_store.save_json(
                source=self.source,
                payload=payload,
                fetched_at=fetched_at,
                label=series_id,
            )
        return self.normalize_series(payload=payload, series_id=series_id, fetched_at=fetched_at)

    @staticmethod
    def normalize_series(
        *,
        payload: dict[str, Any],
        series_id: str,
        fetched_at: datetime,
    ) -> list[TimeSeriesObservation]:
        rows = payload.get("response", {}).get("data", [])
        normalized: list[TimeSeriesObservation] = []
        for row in rows:
            value = row.get("value")
            if value in (None, "", "."):
                continue
            normalized.append(
                TimeSeriesObservation(
                    source=EiaSeriesConnector.source,
                    series_id=str(row.get("series") or series_id),
                    report_date=datetime.fromisoformat(str(row["period"])).date(),
                    knowledge_date=fetched_at,
                    value=float(value),
                    unit=row.get("units"),
                    metadata={"raw_period": row.get("period")},
                )
            )
        return normalized


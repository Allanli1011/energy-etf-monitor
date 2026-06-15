from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import TimeSeriesObservation


class FredSeriesConnector:
    source = "fred"
    base_url = "https://api.stlouisfed.org/fred/series/observations"

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

    def fetch_observations(
        self,
        series_id: str,
        *,
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> list[TimeSeriesObservation]:
        fetched_at = datetime.now(UTC)
        params = {
            "series_id": series_id,
            "file_type": "json",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end

        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            response = client.get(self.base_url, params=params)
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
        return self.normalize_observations(
            payload=payload,
            series_id=series_id,
            fetched_at=fetched_at,
        )

    @staticmethod
    def normalize_observations(
        *,
        payload: dict[str, Any],
        series_id: str,
        fetched_at: datetime,
    ) -> list[TimeSeriesObservation]:
        normalized: list[TimeSeriesObservation] = []
        for row in payload.get("observations", []):
            value = row.get("value")
            if value in (None, "", "."):
                continue
            normalized.append(
                TimeSeriesObservation(
                    source=FredSeriesConnector.source,
                    series_id=series_id,
                    report_date=datetime.fromisoformat(str(row["date"])).date(),
                    knowledge_date=_publication_datetime(
                        datetime.fromisoformat(str(row["date"])).date()
                    ),
                    value=float(value),
                )
            )
        return normalized


# Daily macro series post the next business day; a +1-day publication lag keeps the point-in-time
# gate honest without overstating availability.
FRED_PUBLICATION_LAG_DAYS = 1


def _publication_datetime(report_date: date) -> datetime:
    return datetime.combine(
        report_date + timedelta(days=FRED_PUBLICATION_LAG_DAYS), time(13, 0), tzinfo=UTC
    )


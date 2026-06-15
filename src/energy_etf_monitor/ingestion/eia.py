from datetime import UTC, date, datetime
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import TimeSeriesObservation

# The EIA v2 "seriesid" compatibility route addresses legacy weekly petroleum series by their full
# v1-style id (category prefix + ".W" frequency suffix), e.g. WCESTUS1 -> PET.WCESTUS1.W. A bare id
# returns HTTP 404. We keep the bare code as the canonical storage/feature key and only translate it
# for the HTTP request; already-qualified ids (e.g. the NatGas NG.* series) pass through unchanged.
SERIESID_ROUTE_ALIASES = {
    "WCESTUS1": "PET.WCESTUS1.W",
    "WCRSTUS1": "PET.WCRSTUS1.W",
    "WCSSTUS1": "PET.WCSSTUS1.W",
    "W_EPC0_SAX_YCUOK_MBBL": "PET.W_EPC0_SAX_YCUOK_MBBL.W",
    "WGTSTUS1": "PET.WGTSTUS1.W",
}


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
        route_id = SERIESID_ROUTE_ALIASES.get(series_id, series_id)
        params = {"api_key": self.api_key} if self.api_key else {}
        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            response = client.get(f"{self.base_url}/{route_id}", params=params)
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
            # Skip a single malformed row (bad value or unparseable period) rather than
            # discarding the whole series; EIA periods vary by frequency (daily/weekly,
            # monthly "YYYY-MM", annual "YYYY").
            try:
                report_date = _parse_period(str(row["period"]))
                numeric_value = float(value)
            except (KeyError, TypeError, ValueError):
                continue
            normalized.append(
                TimeSeriesObservation(
                    source=EiaSeriesConnector.source,
                    series_id=series_id,
                    report_date=report_date,
                    knowledge_date=fetched_at,
                    value=numeric_value,
                    unit=row.get("units"),
                    metadata={"raw_period": row.get("period"), "eia_series": row.get("series")},
                )
            )
        return normalized


def _parse_period(period: str) -> date:
    """Parse an EIA period string into a date across all reporting frequencies.

    Daily/weekly series use a full ISO date ("YYYY-MM-DD"); monthly series report "YYYY-MM"
    and annual series "YYYY". Partial periods anchor to the first day of the month/year.
    """

    text = period.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y-%m").date()
    except ValueError:
        pass
    return datetime.strptime(text, "%Y").date()


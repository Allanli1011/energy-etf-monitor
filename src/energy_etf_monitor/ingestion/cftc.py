from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import CotPosition

DISAGGREGATED_FUTURES_ONLY_DATASET = "72hh-3qpy"
CFTC_BASE_URL = "https://publicreporting.cftc.gov/resource"
NY_TZ = ZoneInfo("America/New_York")


def cot_knowledge_datetime(report_date: date) -> datetime:
    """COT positions (Tuesday close) are first public on Friday at 15:30 ET.

    Uses 3 business days rather than 3 calendar days so the release date is computed correctly when
    the report date lands near a weekend. Federal holidays can still slip the real release by an
    extra day; a holiday-aware calendar is a future refinement.
    """

    return datetime.combine(
        _add_business_days(report_date, 3), time(15, 30), tzinfo=NY_TZ
    )


def _add_business_days(start: date, business_days: int) -> date:
    current = start
    remaining = business_days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


class CftcCotConnector:
    source = "cftc"

    def __init__(
        self,
        *,
        app_token: str | None = None,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
        dataset_id: str = DISAGGREGATED_FUTURES_ONLY_DATASET,
    ) -> None:
        self.app_token = app_token
        self.raw_store = raw_store
        self.client = client
        self.dataset_id = dataset_id

    def fetch_positions(
        self,
        *,
        commodity: str,
        contract_market_code: str,
        limit: int = 5000,
    ) -> list[CotPosition]:
        fetched_at = datetime.now(tz=NY_TZ)
        params = {
            "$limit": str(limit),
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$where": f"cftc_contract_market_code='{contract_market_code}'",
        }
        headers = {"X-App-Token": self.app_token} if self.app_token else {}

        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            response = client.get(
                f"{CFTC_BASE_URL}/{self.dataset_id}.json",
                params=params,
                headers=headers,
            )
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
                label=f"{commodity.lower()}_cot",
            )
        return self.normalize_positions(payload=payload, commodity=commodity)

    def fetch_wti_positions(self, limit: int = 5000) -> list[CotPosition]:
        return self.fetch_positions(
            commodity="WTI",
            contract_market_code="067651",
            limit=limit,
        )

    @staticmethod
    def normalize_positions(
        *,
        payload: list[dict[str, Any]],
        commodity: str,
    ) -> list[CotPosition]:
        normalized: list[CotPosition] = []
        for row in payload:
            report_date = datetime.fromisoformat(
                str(row["report_date_as_yyyy_mm_dd"]).replace("Z", "+00:00")
            ).date()
            normalized.append(
                CotPosition(
                    source=CftcCotConnector.source,
                    commodity=commodity,
                    market_name=str(row.get("market_and_exchange_names", "")),
                    contract_market_code=str(row.get("cftc_contract_market_code", "")),
                    report_date=report_date,
                    knowledge_date=cot_knowledge_datetime(report_date),
                    open_interest=_to_int(row.get("open_interest_all")),
                    swap_dealer_long=_to_optional_int(row.get("swap_positions_long_all")),
                    swap_dealer_short=_to_optional_int(row.get("swap_positions_short_all")),
                    swap_dealer_spread=_to_optional_int(row.get("swap_positions_spread_all")),
                )
            )
        return normalized


def _to_int(value: Any) -> int:
    if value is None:
        raise ValueError("required integer value is missing")
    return int(float(str(value).replace(",", "")))


def _to_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return _to_int(value)


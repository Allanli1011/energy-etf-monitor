"""ICE Futures Europe Commitments of Traders connector."""

import csv
import io
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import CotPosition

ICE_COT_HISTORY_URL_TEMPLATE = "https://www.ice.com/publicdocs/futures/COTHist{year}.csv"
LONDON_TZ = ZoneInfo("Europe/London")
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def ice_cot_knowledge_datetime(report_date: date) -> datetime:
    """ICE COT positions are published on Friday at 18:30 London time."""

    return datetime.combine(
        _add_business_days(report_date, 3), time(18, 30), tzinfo=LONDON_TZ
    )


def _add_business_days(start: date, business_days: int) -> date:
    current = start
    remaining = business_days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


class IceCotConnector:
    """Fetch public ICE Futures Europe COT history CSV rows."""

    source = "ice_cot"

    def __init__(
        self,
        *,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
        history_url_template: str = ICE_COT_HISTORY_URL_TEMPLATE,
        history_years: int = 4,
    ) -> None:
        self.raw_store = raw_store
        self.client = client
        self.history_url_template = history_url_template
        self.history_years = history_years

    def fetch_positions(
        self,
        *,
        commodity: str,
        contract_market_code: str,
        limit: int = 5000,
    ) -> list[CotPosition]:
        fetched_at = datetime.now(tz=LONDON_TZ)
        current_year = fetched_at.year
        years = range(current_year, current_year - self.history_years, -1)
        rows: list[dict[str, str]] = []
        for year in years:
            rows.extend(self._fetch_year(year))
        if self.raw_store:
            self.raw_store.save_json(
                source=self.source,
                payload=rows,
                fetched_at=fetched_at,
                label=f"{commodity.lower()}_cot",
            )
        positions = self.normalize_positions(
            payload=rows,
            commodity=commodity,
            contract_market_code=contract_market_code,
        )
        return positions[:limit]

    def _fetch_year(self, year: int) -> list[dict[str, str]]:
        client = self.client or httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA, "Accept": "text/csv,*/*"},
        )
        close_client = self.client is None
        try:
            response = client.get(
                self.history_url_template.format(year=year),
                headers={"User-Agent": _BROWSER_UA, "Accept": "text/csv,*/*"},
            )
            response.raise_for_status()
            text = response.content.decode("utf-8-sig")
        finally:
            if close_client:
                client.close()
        return list(csv.DictReader(io.StringIO(text)))

    @staticmethod
    def normalize_positions(
        *,
        payload: list[dict[str, Any]],
        commodity: str,
        contract_market_code: str,
    ) -> list[CotPosition]:
        normalized: list[CotPosition] = []
        for row in payload:
            if str(row.get("CFTC_Commodity_Code", "")).upper() != contract_market_code.upper():
                continue
            if str(row.get("FutOnly_or_Combined", "")) != "FutOnly":
                continue
            report_date = datetime.strptime(
                str(row["As_of_Date_Form_MM/DD/YYYY"]), "%m/%d/%Y"
            ).date()
            normalized.append(
                CotPosition(
                    source=IceCotConnector.source,
                    commodity=commodity,
                    market_name=str(row.get("Market_and_Exchange_Names", "")),
                    contract_market_code=contract_market_code,
                    report_date=report_date,
                    knowledge_date=ice_cot_knowledge_datetime(report_date),
                    open_interest=_to_int(row.get("Open_Interest_All")),
                    swap_dealer_long=_to_optional_int(row.get("Swap_Positions_Long_All")),
                    swap_dealer_short=_to_optional_int(row.get("Swap_Positions_Short_All")),
                    swap_dealer_spread=_to_optional_int(row.get("Swap_Positions_Spread_All")),
                    producer_merchant_long=_to_optional_int(
                        row.get("Prod_Merc_Positions_Long_All")
                    ),
                    producer_merchant_short=_to_optional_int(
                        row.get("Prod_Merc_Positions_Short_All")
                    ),
                    managed_money_long=_to_optional_int(row.get("M_Money_Positions_Long_All")),
                    managed_money_short=_to_optional_int(row.get("M_Money_Positions_Short_All")),
                    other_reportable_long=_to_optional_int(
                        row.get("Other_Rept_Positions_Long_All")
                    ),
                    other_reportable_short=_to_optional_int(
                        row.get("Other_Rept_Positions_Short_All")
                    ),
                )
            )
        normalized.sort(key=lambda row: row.report_date, reverse=True)
        return normalized


def _to_int(value: Any) -> int:
    if value in (None, ""):
        raise ValueError("required integer value is missing")
    return int(float(str(value).replace(",", "")))


def _to_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return _to_int(value)

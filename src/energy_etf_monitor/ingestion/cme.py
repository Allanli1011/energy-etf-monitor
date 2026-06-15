import re
from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FuturesSettlement

# CME energy settlements publish after the trading session closes (WTI settles ~14:30 ET).
# Stamping knowledge_date at the settlement publication time — not trade-day midnight — keeps
# the point-in-time gate honest: an intraday feature build before the close must not see today's
# settle. 16:00 ET is a conservative cutoff after the official settle is disseminated.
CME_SETTLEMENT_TZ = ZoneInfo("America/New_York")
CME_SETTLEMENT_PUBLISH_TIME = time(16, 0)

# cmegroup.com fronts an aggressive bot filter; a default httpx client (no browser headers) is
# routinely dropped. These headers improve the odds from a normal host. From blocked datacenter
# IPs (e.g. CI runners) the request may still time out — the ingestion runner treats that as a
# skippable per-source failure rather than aborting the batch.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


class CurveProvider(Protocol):
    def fetch_curve(
        self,
        *,
        product_code: str,
        trade_date: date,
        max_months: int = 6,
    ) -> list[FuturesSettlement]:
        """Fetch futures settlements for a product."""


class CmeSettlementPageParser:
    def parse(
        self,
        html: str,
        *,
        product_code: str,
        trade_date: date,
        max_months: int = 6,
    ) -> list[FuturesSettlement]:
        soup = BeautifulSoup(html, "html.parser")
        settlements: list[FuturesSettlement] = []
        for table in soup.find_all("table"):
            headers = [_clean_cell(cell.get_text(" ")) for cell in table.find_all("th")]
            if not headers:
                continue
            month_idx = _find_header(headers, {"month", "contract month"})
            settle_idx = _find_header(headers, {"settle", "settlement"})
            oi_idx = _find_header(headers, {"open interest", "open int"})
            if month_idx is None or settle_idx is None:
                continue
            for tr in table.find_all("tr"):
                cells = [_clean_cell(cell.get_text(" ")) for cell in tr.find_all("td")]
                if len(cells) <= max(month_idx, settle_idx):
                    continue
                try:
                    contract_month = parse_contract_month(cells[month_idx])
                    settlement = _to_float(cells[settle_idx])
                except ValueError:
                    continue
                open_interest = None
                if oi_idx is not None and len(cells) > oi_idx:
                    open_interest = _to_optional_int(cells[oi_idx])
                settlements.append(
                    FuturesSettlement(
                        source="cme",
                        product_code=product_code,
                        report_date=trade_date,
                        knowledge_date=datetime.combine(
                            trade_date,
                            CME_SETTLEMENT_PUBLISH_TIME,
                            tzinfo=CME_SETTLEMENT_TZ,
                        ),
                        contract_month=contract_month,
                        settlement_price=settlement,
                        open_interest=open_interest,
                    )
                )
                if len(settlements) == max_months:
                    return settlements
        return settlements


class CmeSettlementCurveProvider:
    """CME HTML settlement provider kept behind a swappable interface."""

    urls = {
        "CL": "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.settlements.html",
        "NG": "https://www.cmegroup.com/markets/energy/natural-gas/natural-gas.settlements.html",
        "RB": "https://www.cmegroup.com/markets/energy/refined-products/rbob-gasoline.settlements.html",
        "HO": "https://www.cmegroup.com/markets/energy/refined-products/heating-oil.settlements.html",
    }

    def __init__(
        self,
        *,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
        parser: CmeSettlementPageParser | None = None,
    ) -> None:
        self.raw_store = raw_store
        self.client = client
        self.parser = parser or CmeSettlementPageParser()

    def fetch_curve(
        self,
        *,
        product_code: str,
        trade_date: date,
        max_months: int = 6,
    ) -> list[FuturesSettlement]:
        product = product_code.upper()
        try:
            url = self.urls[product]
        except KeyError as exc:
            raise ValueError(f"Unsupported CME product code: {product_code}") from exc

        fetched_at = datetime.now(UTC)
        client = self.client or httpx.Client(
            timeout=30, headers=_BROWSER_HEADERS, follow_redirects=True
        )
        close_client = self.client is None
        try:
            response = client.get(url)
            response.raise_for_status()
            html = response.text
        finally:
            if close_client:
                client.close()

        if self.raw_store:
            self.raw_store.save_json(
                source="cme",
                payload={"url": url, "html": html},
                fetched_at=fetched_at,
                label=f"{product}_settlements",
            )
        return self.parser.parse(
            html,
            product_code=product,
            trade_date=trade_date,
            max_months=max_months,
        )


def parse_contract_month(value: str) -> date:
    match = re.search(r"\b([A-Za-z]{3})\s+(\d{2,4})\b", value.strip())
    if not match:
        raise ValueError(f"Cannot parse contract month: {value}")
    month = MONTHS[match.group(1).upper()]
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return date(year, month, 1)


def _find_header(headers: list[str], candidates: set[str]) -> int | None:
    for index, header in enumerate(headers):
        if header in candidates:
            return index
    return None


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def _to_float(value: str) -> float:
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    if not cleaned:
        raise ValueError(f"Cannot parse float: {value}")
    return float(cleaned)


def _to_optional_int(value: str) -> int | None:
    cleaned = re.sub(r"[^0-9\-]", "", value)
    return int(cleaned) if cleaned else None

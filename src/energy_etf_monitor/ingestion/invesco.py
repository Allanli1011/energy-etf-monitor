import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FundDailyMetric, FundHolding

_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
INVESCO_PRODUCTS = {
    "DBO": {
        "cusip": "46140H403",
        "locale": "en_US",
        "product_type": "ETF",
        "page_url": "https://www.invesco.com/us/en/financial-products/etfs/invesco-db-oil-fund.html",
    },
}
INVESCO_API_BASE_URL = "https://dng-api.invesco.com/cache/v1/accounts"
_FUTURES_MONTH_CODES = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}
_MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


@dataclass(frozen=True)
class InvescoHoldingsSnapshot:
    metric: FundDailyMetric
    holdings: list[FundHolding]


class InvescoHoldingsParser:
    """Parse Invesco DNG API payloads for commodity ETF prices and holdings."""

    def parse(
        self,
        *,
        price: dict[str, Any],
        holdings: dict[str, Any],
        fund_ticker: str,
        fetched_at: datetime,
    ) -> InvescoHoldingsSnapshot:
        ticker = fund_ticker.upper()
        report_date = _parse_date(
            price.get("effectiveBusinessDate") or price.get("effectiveDate"),
            label="price effective date",
        )
        nav_per_share = _required_number(price, "nav")
        shares_outstanding = _required_number(price, "sharesOutstanding")
        total_net_assets = _optional_number(price.get("marketValue"))
        if total_net_assets is None:
            total_net_assets = nav_per_share * shares_outstanding
        metric = FundDailyMetric(
            source="invesco",
            fund_ticker=ticker,
            report_date=report_date,
            knowledge_date=fetched_at,
            nav_per_share=nav_per_share,
            shares_outstanding=shares_outstanding,
            total_net_assets=total_net_assets,
        )

        holding_date = _parse_date(
            holdings.get("effectiveBusinessDate") or holdings.get("effectiveDate"),
            label="holdings effective date",
        )
        rows = holdings.get("holdings")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Invesco {ticker} holdings response returned no holdings")
        parsed_holdings = [
            _parse_holding_row(
                row,
                fund_ticker=ticker,
                report_date=holding_date,
                fetched_at=fetched_at,
            )
            for row in rows
        ]
        return InvescoHoldingsSnapshot(metric=metric, holdings=parsed_holdings)


class InvescoHoldingsConnector:
    source = "invesco_api"

    def __init__(
        self,
        *,
        raw_root_dir,
        client: httpx.Client | None = None,
        parser: InvescoHoldingsParser | None = None,
        products: dict[str, dict[str, str]] | None = None,
        api_base_url: str = INVESCO_API_BASE_URL,
    ) -> None:
        self.raw_store = RawPayloadStore(raw_root_dir)
        self.client = client
        self.parser = parser or InvescoHoldingsParser()
        self.products = products or INVESCO_PRODUCTS
        self.api_base_url = api_base_url.rstrip("/")

    def fetch_latest(self, *, fund_ticker: str) -> InvescoHoldingsSnapshot:
        ticker = fund_ticker.upper()
        try:
            product = self.products[ticker]
        except KeyError as exc:
            raise ValueError(f"Unsupported Invesco fund ticker: {ticker}") from exc

        fetched_at = datetime.now(UTC)
        price_url = self._price_url(product)
        holdings_url = self._holdings_url(product)
        if self.client is None:
            price = _get_json_with_curl(price_url, referer=product["page_url"])
            holdings = _get_json_with_curl(holdings_url, referer=product["page_url"])
        else:
            price = self._get_json(self.client, price_url, referer=product["page_url"])
            holdings = self._get_json(self.client, holdings_url, referer=product["page_url"])

        self.raw_store.save_json(
            source=self.source,
            payload={"price": price, "holdings": holdings},
            fetched_at=fetched_at,
            label=f"{ticker}_holdings",
        )
        return self.parser.parse(
            price=price,
            holdings=holdings,
            fund_ticker=ticker,
            fetched_at=fetched_at,
        )

    def _price_url(self, product: dict[str, str]) -> str:
        return (
            f"{self.api_base_url}/{product['locale']}/shareclasses/{product['cusip']}/prices"
            f"?idType=cusip&variationType=priceListing&productType={product['product_type']}"
        )

    def _holdings_url(self, product: dict[str, str]) -> str:
        return (
            f"{self.api_base_url}/{product['locale']}/shareclasses/{product['cusip']}"
            f"/holdings/fund?idType=cusip&variationType=currencyHoldings"
            f"&productType={product['product_type']}"
        )

    @staticmethod
    def _get_json(client: httpx.Client, url: str, *, referer: str) -> dict[str, Any]:
        response = client.get(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Origin": "https://www.invesco.com",
                "Referer": referer,
                "User-Agent": _BROWSER_USER_AGENT,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            if response.status_code == 406:
                return _get_json_with_curl(url, referer=referer)
            raise
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Invesco DNG API returned a non-object response")
        return payload


def _get_json_with_curl(url: str, *, referer: str) -> dict[str, Any]:
    curl = shutil.which("curl")
    if curl is None:
        raise ValueError("Invesco DNG API returned 406 and curl is not available")
    result = subprocess.run(
        [
            curl,
            "-L",
            "-sS",
            "-f",
            "-A",
            _BROWSER_USER_AGENT,
            "-H",
            "Accept: application/json,text/plain,*/*",
            "-H",
            "Origin: https://www.invesco.com",
            "-H",
            f"Referer: {referer}",
            url,
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"Invesco DNG API curl fallback failed: {detail}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Invesco DNG API curl fallback returned a non-object response")
    return payload


def _parse_holding_row(
    row: Any,
    *,
    fund_ticker: str,
    report_date: date,
    fetched_at: datetime,
) -> FundHolding:
    if not isinstance(row, dict):
        raise ValueError("Invesco holding row is not an object")
    name = _clean_name(row.get("localCurrencyName"))
    if not name:
        raise ValueError("Invesco holding row is missing localCurrencyName")
    ticker = _find_futures_code(name, report_date=report_date)
    contract_month = _find_contract_month(name, report_date=report_date)
    return FundHolding(
        source="invesco",
        fund_ticker=fund_ticker,
        holding_key=_holding_key(ticker=ticker, contract_month=contract_month, name=name),
        holding_name=name,
        instrument_type=_instrument_type(name),
        ticker=ticker,
        report_date=report_date,
        knowledge_date=fetched_at,
        contract_month=contract_month,
        percent_nav=_optional_number(row.get("percentageOfTotalNetAssets")),
    )


def _parse_date(value: Any, *, label: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Invesco response is missing {label}")
    return date.fromisoformat(text[:10])


def _required_number(row: dict[str, Any], key: str) -> float:
    parsed = _optional_number(row.get(key))
    if parsed is None:
        raise ValueError(f"Invesco response is missing {key}")
    return parsed


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if text in {"", "--", "-"}:
        return None
    cleaned = re.sub(r"[$,%\s]", "", text).replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return float(cleaned)


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _find_futures_code(value: str, *, report_date: date) -> str | None:
    text = value.upper()
    match = re.search(r"([A-Z]{1,3})([FGHJKMNQUVXZ])(\d{1,2})(?=\b|[^A-Z0-9])", text)
    if match is None:
        return None
    year = _expand_year(match.group(3), report_date=report_date)
    return f"{match.group(1)}{match.group(2)}{year % 100:02d}"


def _find_contract_month(value: str, *, report_date: date) -> date | None:
    futures_code = re.search(
        r"([A-Z]{1,3})([FGHJKMNQUVXZ])(\d{1,2})(?=\b|[^A-Z0-9])",
        value.upper(),
    )
    if futures_code is not None:
        return date(
            _expand_year(futures_code.group(3), report_date=report_date),
            _FUTURES_MONTH_CODES[futures_code.group(2)],
            1,
        )
    month_name = re.search(r"\b([A-Za-z]{3,9})\s*(\d{1,4})\b", value)
    if month_name is None:
        return None
    month = _MONTH_NAMES.get(month_name.group(1).lower()[:3])
    if month is None:
        return None
    return date(_expand_year(month_name.group(2), report_date=report_date), month, 1)


def _expand_year(value: str, *, report_date: date) -> int:
    if len(value) >= 4:
        return int(value)
    if len(value) == 2:
        return 2000 + int(value)
    decade = report_date.year // 10 * 10
    year = decade + int(value)
    if year < report_date.year - 2:
        year += 10
    return year


def _instrument_type(value: str) -> str:
    text = value.upper()
    if "CONTRA FUTURE" in text:
        return "Contra Future"
    if "FUTR" in text or "FUTURE" in text:
        return "Futures"
    if "COLLATERAL" in text or "CASH" in text:
        return "Cash"
    if "TREASURY" in text or "GOVERNMENT" in text:
        return "Collateral"
    return "Unknown"


def _holding_key(*, ticker: str | None, contract_month: date | None, name: str) -> str:
    ticker_part = (ticker or "na").lower()
    contract_part = contract_month.isoformat() if contract_month else "na"
    name_part = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"{ticker_part}|{contract_part}|{name_part}"

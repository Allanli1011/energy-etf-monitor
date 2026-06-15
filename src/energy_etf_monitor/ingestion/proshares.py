import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx
from bs4 import BeautifulSoup

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FundDailyMetric, FundHolding

PROSHARES_PRODUCT_URLS = {
    "UCO": "https://www.proshares.com/our-etfs/leveraged-and-inverse/uco",
    "SCO": "https://www.proshares.com/our-etfs/leveraged-and-inverse/sco",
    "BOIL": "https://www.proshares.com/our-etfs/leveraged-and-inverse/boil",
    "KOLD": "https://www.proshares.com/our-etfs/leveraged-and-inverse/kold",
}
PROSHARES_PRODUCT_CODES = {
    "UCO": "CL",
    "SCO": "CL",
    "BOIL": "NG",
    "KOLD": "NG",
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
_MONTH_CODES_BY_NUMBER = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}


@dataclass(frozen=True)
class ProSharesHoldingsSnapshot:
    metric: FundDailyMetric
    holdings: list[FundHolding]


class ProSharesHoldingsParser:
    """Parse ProShares fund pages that render NAV, net assets, and holdings in HTML."""

    def parse(
        self,
        html: str,
        *,
        fund_ticker: str,
        fetched_at: datetime,
    ) -> ProSharesHoldingsSnapshot:
        ticker = fund_ticker.upper()
        soup = BeautifulSoup(html, "html.parser")
        report_date = _parse_as_of(_required_text(soup, "#price-asOfDate", "price as-of date"))
        nav_per_share = _parse_number(_required_text(soup, "#price-nav", "NAV"))
        total_net_assets = _parse_number(
            _required_text(soup, "#snapshot-netAssets", "net assets")
        )
        shares_outstanding = total_net_assets / nav_per_share
        metric = FundDailyMetric(
            source="proshares",
            fund_ticker=ticker,
            report_date=report_date,
            knowledge_date=fetched_at,
            nav_per_share=nav_per_share,
            shares_outstanding=shares_outstanding,
            total_net_assets=total_net_assets,
        )

        table = soup.find("table", id="holdings")
        if table is None:
            raise ValueError(f"ProShares {ticker} page does not contain a holdings table")

        holdings = [
            _parse_holding_row(
                row,
                fund_ticker=ticker,
                report_date=report_date,
                fetched_at=fetched_at,
            )
            for row in table.find_all("tr")
            if row.find_all("td")
        ]
        if not holdings:
            raise ValueError(f"ProShares {ticker} page returned no holdings")
        return ProSharesHoldingsSnapshot(metric=metric, holdings=holdings)


class ProSharesHoldingsConnector:
    source = "proshares_html"

    def __init__(
        self,
        *,
        raw_root_dir,
        client: httpx.Client | None = None,
        parser: ProSharesHoldingsParser | None = None,
        product_urls: dict[str, str] | None = None,
    ) -> None:
        self.raw_store = RawPayloadStore(raw_root_dir)
        self.client = client
        self.parser = parser or ProSharesHoldingsParser()
        self.product_urls = product_urls or PROSHARES_PRODUCT_URLS

    def fetch_latest(self, *, fund_ticker: str) -> ProSharesHoldingsSnapshot:
        ticker = fund_ticker.upper()
        try:
            url = self.product_urls[ticker]
        except KeyError as exc:
            raise ValueError(f"Unsupported ProShares fund ticker: {ticker}") from exc

        fetched_at = datetime.now(UTC)
        client = self.client or httpx.Client(timeout=30, follow_redirects=True)
        close_client = self.client is None
        try:
            response = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36"
                    )
                },
            )
            response.raise_for_status()
            html = response.text
        finally:
            if close_client:
                client.close()

        self.raw_store.save_text(
            source=self.source,
            text=html,
            fetched_at=fetched_at,
            label=f"{ticker}_holdings",
            extension="html",
        )
        return self.parser.parse(html, fund_ticker=ticker, fetched_at=fetched_at)


def _parse_holding_row(
    row,
    *,
    fund_ticker: str,
    report_date: date,
    fetched_at: datetime,
) -> FundHolding:
    cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
    if len(cells) < 7:
        raise ValueError(f"ProShares holding row has {len(cells)} cells; expected 7")
    exposure_weight, ticker_cell, name, exposure_value, market_value, quantity, _sedol = cells[:7]
    contract_month = _find_contract_month(name, report_date=report_date)
    product_code = PROSHARES_PRODUCT_CODES.get(fund_ticker)
    holding_ticker = _normalize_ticker(ticker_cell)
    if holding_ticker is None and contract_month is not None and product_code is not None:
        holding_ticker = _futures_code(product_code, contract_month)
    parsed_market_value = _optional_number(market_value)
    if parsed_market_value is None:
        parsed_market_value = _optional_number(exposure_value)
    return FundHolding(
        source="proshares",
        fund_ticker=fund_ticker,
        holding_key=_holding_key(ticker=holding_ticker, contract_month=contract_month, name=name),
        holding_name=name,
        instrument_type=_instrument_type(name),
        ticker=holding_ticker,
        report_date=report_date,
        knowledge_date=fetched_at,
        contract_month=contract_month,
        quantity=_optional_number(quantity),
        market_value=parsed_market_value,
        percent_nav=_optional_number(exposure_weight),
    )


def _required_text(soup: BeautifulSoup, selector: str, label: str) -> str:
    node = soup.select_one(selector)
    if node is None:
        raise ValueError(f"ProShares page is missing {label}")
    text = _clean_text(node.get_text(" ", strip=True))
    if not text:
        raise ValueError(f"ProShares page has blank {label}")
    return text


def _parse_as_of(value: str) -> date:
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if match is None:
        raise ValueError(f"ProShares as-of date is unsupported: {value}")
    return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))


def _parse_number(value: str) -> float:
    cleaned = re.sub(r"[$,%\s]", "", value).replace(",", "")
    if cleaned in {"", "--", "-"}:
        raise ValueError(f"ProShares numeric field is blank: {value}")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return float(cleaned)


def _optional_number(value: str) -> float | None:
    cleaned = value.strip()
    if cleaned in {"", "--", "-"}:
        return None
    return _parse_number(cleaned)


def _normalize_ticker(value: str) -> str | None:
    text = value.strip().upper()
    return None if text in {"", "--", "-"} else text


def _find_contract_month(value: str, *, report_date: date) -> date | None:
    match = re.search(r"\b([A-Za-z]{3,9})\s*(\d{1,4})\b", value)
    if match is None:
        return None
    month = _MONTH_NAMES.get(match.group(1).lower()[:3])
    if month is None:
        return None
    year = _expand_year(match.group(2), report_date=report_date)
    return date(year, month, 1)


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


def _futures_code(product_code: str, contract_month: date) -> str:
    return f"{product_code}{_MONTH_CODES_BY_NUMBER[contract_month.month]}{contract_month:%y}"


def _instrument_type(value: str) -> str:
    text = value.upper()
    if "CASH" in text:
        return "Cash"
    if "SWAP" in text:
        return "Swap"
    if "FUTR" in text or "FUTURE" in text:
        return "Futures"
    return "Unknown"


def _holding_key(*, ticker: str | None, contract_month: date | None, name: str) -> str:
    ticker_part = (ticker or "na").lower()
    contract_part = contract_month.isoformat() if contract_month else "na"
    name_part = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"{ticker_part}|{contract_part}|{name_part}"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()

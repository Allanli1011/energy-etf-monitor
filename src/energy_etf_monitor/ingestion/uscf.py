import csv
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FundDailyMetric, FundHolding

USCF_API_KEY_URL = "https://www.uscfinvestments.com/site-template/assets/javascript/api_key.php"
USCF_API_BASE_URL = "https://secure.alpsinc.com/MarketingAPI/api/v1/"
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
class UscfPcfSnapshot:
    metric: FundDailyMetric
    holdings: list[FundHolding]


class UscfPcfParser:
    def parse(
        self,
        text: str,
        *,
        fund_ticker: str,
        fetched_at: datetime,
    ) -> UscfPcfSnapshot:
        preamble, holding_rows = _split_preamble_and_holdings(text)
        metadata = _parse_metadata(preamble)
        report_date = _parse_report_date(metadata)
        fund = (metadata.get("fund") or fund_ticker).upper()
        metric = FundDailyMetric(
            source="uscf",
            fund_ticker=fund,
            report_date=report_date,
            knowledge_date=fetched_at,
            nav_per_share=_required_number(metadata, "nav"),
            shares_outstanding=_required_number(metadata, "shares_outstanding"),
            total_net_assets=_required_number(metadata, "total_net_assets"),
        )
        holdings = [
            _parse_holding(row, fund_ticker=fund, report_date=report_date, fetched_at=fetched_at)
            for row in holding_rows
        ]
        return UscfPcfSnapshot(metric=metric, holdings=holdings)


class UscfHoldingsParser:
    """Parse the official USCF holdings/dailyprice JSON used by the public holdings pages."""

    def parse(
        self,
        *,
        daily_price: Any,
        holdings: Any,
        fund_ticker: str,
        fetched_at: datetime,
    ) -> UscfPcfSnapshot:
        daily_row = _first_api_row(daily_price, endpoint="dailyprice")
        holding_rows = _api_rows(holdings, endpoint="holding")
        fund = str(daily_row.get("symbol") or fund_ticker).upper()
        report_date = _parse_api_date(
            daily_row.get("displaydate")
            or daily_row.get("asofdate")
            or (holding_rows[0].get("asofdate") if holding_rows else None),
            label="dailyprice displaydate",
        )
        nav_per_share = _required_api_number(daily_row, "navextended", "nav")
        shares_outstanding = _required_api_number(daily_row, "so")
        total_net_assets = _optional_api_number(daily_row.get("navtotal"))
        if total_net_assets is None:
            total_net_assets = nav_per_share * shares_outstanding
        created_redeemed = _optional_api_number(daily_row.get("cr"))
        metric = FundDailyMetric(
            source="uscf",
            fund_ticker=fund,
            report_date=report_date,
            knowledge_date=fetched_at,
            nav_per_share=nav_per_share,
            shares_outstanding=shares_outstanding,
            total_net_assets=total_net_assets,
            implied_flow_usd=(
                None if created_redeemed is None else created_redeemed * nav_per_share
            ),
        )
        parsed_holdings = [
            _parse_api_holding(row, fund_ticker=fund, fetched_at=fetched_at)
            for row in holding_rows
            if str(row.get("possessionname") or "Hold").lower() == "hold"
        ]
        return UscfPcfSnapshot(metric=metric, holdings=parsed_holdings)


class UscfHoldingsConnector:
    source = "uscf_api"

    def __init__(
        self,
        *,
        raw_root_dir: Path,
        client: httpx.Client | None = None,
        parser: UscfHoldingsParser | None = None,
        api_key_url: str = USCF_API_KEY_URL,
    ) -> None:
        self.raw_store = RawPayloadStore(raw_root_dir)
        self.client = client
        self.parser = parser or UscfHoldingsParser()
        self.api_key_url = api_key_url

    def fetch_latest(self, *, fund_ticker: str) -> UscfPcfSnapshot:
        ticker = fund_ticker.upper()
        fetched_at = datetime.now(UTC)
        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            token, api_base_url = self._fetch_api_credentials(client)
            headers = {"Authorization": f"Bearer {token}"}
            daily_price = self._get_json(
                client, f"{api_base_url.rstrip('/')}/dailyprice/{ticker}", headers=headers
            )
            holdings = self._get_json(
                client,
                f"{api_base_url.rstrip('/')}/holding/{ticker}/full",
                headers=headers,
            )
        finally:
            if close_client:
                client.close()

        self.raw_store.save_json(
            source=self.source,
            payload={"dailyprice": daily_price, "holdings": holdings},
            fetched_at=fetched_at,
            label=f"{ticker}_holdings",
        )
        return self.parser.parse(
            daily_price=daily_price,
            holdings=holdings,
            fund_ticker=ticker,
            fetched_at=fetched_at,
        )

    def _fetch_api_credentials(self, client: httpx.Client) -> tuple[str, str]:
        response = client.get(self.api_key_url)
        response.raise_for_status()
        return _parse_api_credentials(response.text)

    @staticmethod
    def _get_json(client: httpx.Client, url: str, *, headers: dict[str, str]) -> Any:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


class UscfPcfConnector:
    source = "uscf_pcf"

    def __init__(
        self,
        *,
        fund_ticker: str,
        pcf_url: str,
        raw_root_dir: Path,
        client: httpx.Client | None = None,
        parser: UscfPcfParser | None = None,
    ) -> None:
        self.fund_ticker = fund_ticker.upper()
        self.pcf_url = pcf_url
        self.raw_store = RawPayloadStore(raw_root_dir)
        self.client = client
        self.parser = parser or UscfPcfParser()

    def fetch_latest(self) -> UscfPcfSnapshot:
        fetched_at = datetime.now(UTC)
        client = self.client or httpx.Client(timeout=30)
        close_client = self.client is None
        try:
            response = client.get(self.pcf_url)
            response.raise_for_status()
            text = response.text
        finally:
            if close_client:
                client.close()

        self.raw_store.save_text(
            source=self.source,
            text=text,
            fetched_at=fetched_at,
            label=f"{self.fund_ticker}_pcf",
            extension="csv",
        )
        return self.parser.parse(text, fund_ticker=self.fund_ticker, fetched_at=fetched_at)


def derive_implied_flow(
    *,
    current: FundDailyMetric,
    previous: FundDailyMetric | None,
) -> FundDailyMetric:
    if previous is None:
        return current
    share_delta = current.shares_outstanding - previous.shares_outstanding
    return current.model_copy(update={"implied_flow_usd": share_delta * current.nav_per_share})


def _parse_api_credentials(script_text: str) -> tuple[str, str]:
    token_match = re.search(r"var\s+token\s*=\s*'([^']+)'", script_text)
    base_match = re.search(r"var\s+api_url_v2\s*=\s*'([^']+)'", script_text)
    if token_match is None:
        raise ValueError("USCF api_key.php did not include a bearer token")
    return token_match.group(1), base_match.group(1) if base_match else USCF_API_BASE_URL


def _first_api_row(payload: Any, *, endpoint: str) -> dict[str, Any]:
    rows = _api_rows(payload, endpoint=endpoint)
    if not rows:
        raise ValueError(f"USCF {endpoint} endpoint returned no rows")
    return rows[0]


def _api_rows(payload: Any, *, endpoint: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        raise ValueError(f"USCF {endpoint} endpoint returned unsupported payload")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"USCF {endpoint} endpoint returned non-object rows")
    return rows


def _parse_api_holding(
    row: dict[str, Any],
    *,
    fund_ticker: str,
    fetched_at: datetime,
) -> FundHolding:
    report_date = _parse_api_date(row.get("asofdate"), label="holding asofdate")
    name = str(row.get("name") or "").strip()
    if not name:
        raise ValueError("USCF holding row is missing name")
    ticker = _optional_api_text(
        row.get("identifiertodisplay")
        or row.get("primaryidentifier")
        or row.get("holdingsymbol")
    )
    contract_month = _parse_api_contract_month(row, report_date=report_date)
    weight = _optional_api_number(row.get("weight"))
    return FundHolding(
        source="uscf",
        fund_ticker=fund_ticker,
        holding_key=_holding_key(ticker=ticker, contract_month=contract_month, name=name),
        holding_name=name,
        instrument_type=str(row.get("holdingtype") or row.get("holdingtypeabbrev") or "Unknown"),
        ticker=ticker,
        report_date=report_date,
        knowledge_date=fetched_at,
        contract_month=contract_month,
        quantity=_optional_api_number(row.get("shares")),
        market_value=_optional_api_number(row.get("marketvalue")),
        percent_nav=None if weight is None else weight * 100.0,
    )


def _parse_api_contract_month(row: dict[str, Any], *, report_date: date) -> date | None:
    for value in (row.get("futuredate"), row.get("maturity")):
        parsed = _parse_contract_month(str(value or ""))
        if parsed is not None:
            return parsed
    for value in (
        row.get("primaryidentifier"),
        row.get("identifiertodisplay"),
        row.get("holdingsymbol"),
    ):
        parsed = _parse_futures_code(str(value or ""), report_date=report_date)
        if parsed is not None:
            return parsed
    return _find_contract_month_in_text(str(row.get("name") or ""), report_date=report_date)


def _parse_futures_code(value: str, *, report_date: date) -> date | None:
    text = value.strip().upper()
    match = re.search(r"([A-Z]{1,3})([FGHJKMNQUVXZ])(\d{1,2})\b", text)
    if match is None:
        return None
    year = _expand_contract_year(match.group(3), report_date=report_date)
    return date(year, _FUTURES_MONTH_CODES[match.group(2)], 1)


def _find_contract_month_in_text(value: str, *, report_date: date) -> date | None:
    match = re.search(r"\b([A-Za-z]{3,9})\s*(\d{1,4})\b", value)
    if match is None:
        return None
    month = _MONTH_NAMES.get(match.group(1).lower()[:3])
    if month is None:
        return None
    year = _expand_contract_year(match.group(2), report_date=report_date)
    return date(year, month, 1)


def _expand_contract_year(value: str, *, report_date: date) -> int:
    if len(value) >= 4:
        return int(value)
    if len(value) == 2:
        return 2000 + int(value)
    decade = report_date.year // 10 * 10
    year = decade + int(value)
    if year < report_date.year - 2:
        year += 10
    return year


def _parse_api_date(value: Any, *, label: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"USCF API row is missing {label}")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def _required_api_number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        parsed = _optional_api_number(row.get(key))
        if parsed is not None:
            return parsed
    raise ValueError(f"USCF API row is missing one of: {', '.join(keys)}")


def _optional_api_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    return None if not text else _parse_number(text)


def _optional_api_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _split_preamble_and_holdings(text: str) -> tuple[list[list[str]], list[dict[str, str]]]:
    rows = [row for row in csv.reader(StringIO(text)) if any(cell.strip() for cell in row)]
    holdings_idx = None
    for index, row in enumerate(rows):
        if _normalize_key(row[0]) in {"holdings", "portfolio_holdings"}:
            holdings_idx = index
            break
    if holdings_idx is None:
        raise ValueError("USCF PCF text does not contain a Holdings section")

    preamble = rows[:holdings_idx]
    header = [_normalize_key(cell) for cell in rows[holdings_idx + 1]]
    holdings: list[dict[str, str]] = []
    for row in rows[holdings_idx + 2 :]:
        padded = row + [""] * (len(header) - len(row))
        holdings.append(dict(zip(header, padded, strict=False)))
    return preamble, holdings


def _parse_metadata(rows: list[list[str]]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        key = _normalize_key(row[0])
        value = row[1].strip()
        if key:
            metadata[key] = value
    return metadata


def _parse_report_date(metadata: dict[str, str]) -> date:
    value = metadata.get("as_of") or metadata.get("date") or metadata.get("report_date")
    if not value:
        raise ValueError("USCF PCF metadata is missing As Of date")
    return date.fromisoformat(value)


def _parse_holding(
    row: dict[str, str],
    *,
    fund_ticker: str,
    report_date: date,
    fetched_at: datetime,
) -> FundHolding:
    name = _pick(row, "name", "holding_name", "description")
    ticker = _optional_text(_pick(row, "ticker", "symbol", "contract", default=""))
    contract_month = _parse_contract_month(_pick(row, "contract_month", "maturity", default=""))
    instrument_type = _pick(row, "asset_type", "type", "instrument_type", default="Unknown")
    return FundHolding(
        source="uscf",
        fund_ticker=fund_ticker,
        holding_key=_holding_key(ticker=ticker, contract_month=contract_month, name=name),
        holding_name=name,
        instrument_type=instrument_type,
        ticker=ticker,
        report_date=report_date,
        knowledge_date=fetched_at,
        contract_month=contract_month,
        quantity=_optional_number(_pick(row, "quantity", "shares", "contracts", default="")),
        market_value=_optional_number(_pick(row, "market_value", "value", default="")),
        percent_nav=_optional_number(
            _pick(row, "percent_of_nav", "weight", "percent_nav", default="")
        ),
    )


def _required_number(metadata: dict[str, str], key: str) -> float:
    try:
        return _parse_number(metadata[key])
    except KeyError as exc:
        raise ValueError(f"USCF PCF metadata is missing {key}") from exc


def _optional_number(value: str) -> float | None:
    if not value.strip():
        return None
    return _parse_number(value)


def _parse_number(value: str) -> float:
    cleaned = re.sub(r"[$,%\s]", "", value).replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return float(cleaned)


def _parse_contract_month(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    iso_match = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", text)
    if iso_match:
        return date(int(iso_match.group(1)), int(iso_match.group(2)), 1)
    match = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{2,4})", text)
    if not match:
        return None
    month_name = match.group(1).lower()[:3]
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return date(year, _MONTH_NAMES[month_name], 1)


def _holding_key(*, ticker: str | None, contract_month: date | None, name: str) -> str:
    ticker_part = (ticker or "na").lower()
    contract_part = contract_month.isoformat() if contract_month else "na"
    name_part = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"{ticker_part}|{contract_part}|{name_part}"


def _pick(row: dict[str, str], *keys: str, default: str | None = None) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and value.strip():
            return value.strip()
    if default is not None:
        return default
    raise ValueError(f"USCF PCF holding row is missing one of: {', '.join(keys)}")


def _optional_text(value: str) -> str | None:
    text = value.strip()
    return text if text else None


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

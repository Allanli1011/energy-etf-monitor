import csv
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FundDailyMetric, FundHolding


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
    months = {
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
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return date(year, months[month_name], 1)


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

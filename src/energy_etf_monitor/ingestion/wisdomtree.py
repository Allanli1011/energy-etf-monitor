"""WisdomTree Europe fund-list metrics connector."""

import re
import xml.etree.ElementTree as ET
from contextlib import suppress
from datetime import UTC, date, datetime
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FundDailyMetric

WISDOMTREE_PRODUCTS_URL = (
    "https://www.wisdomtree.eu/products?assetClass=Commodities&structure=ETPs"
    "&productType=Short%20and%20Leveraged"
)
WISDOMTREE_FUNDLIST_URL = "https://dataspanapi.wisdomtree.com/fundlist/data/"
WISDOMTREE_FUNDLIST_EXCEL_URL = "https://dataspanapi.wisdomtree.com/fundlist/excel"
WISDOMTREE_FUNDLIST_PARAMS = {
    "divisionId": 2,
    "wtRegion": "GB",
    "isoCode": "en-GB",
    "isLeveraged": -1,
    "isFP": 0,
}
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_BROWSER_TLS_IMPERSONATIONS = (
    "chrome146",
    "chrome145",
    "chrome142",
    "chrome136",
    "chrome133a",
    "chrome131",
    "chrome124",
    "chrome120",
)
_XLSX_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class WisdomTreeFundListConnector:
    """Fetch WisdomTree product-list NAV/AUM rows for USD-listed ETPs.

    The product list is the source behind WisdomTree Europe's downloadable fund table. It contains
    one row per listing currency, so the parser only accepts rows where the exchange ticker matches
    the configured dashboard ticker and the fund/base/listing currencies are all USD.
    """

    source = "wisdomtree_fundlist"

    def __init__(
        self,
        *,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
        fundlist_url: str = WISDOMTREE_FUNDLIST_URL,
    ) -> None:
        self.raw_store = raw_store
        self.client = client
        self.fundlist_url = fundlist_url

    def fetch_metrics(self, *, fund_tickers: list[str]) -> list[FundDailyMetric]:
        fetched_at = datetime.now(UTC)
        payload = self._fetch_payload()
        if self.raw_store:
            self.raw_store.save_json(
                source=self.source,
                payload=payload,
                fetched_at=fetched_at,
                label="fundlist_metrics",
            )
        return parse_wisdomtree_fundlist_metrics(
            payload,
            fund_tickers=fund_tickers,
            fetched_at=fetched_at,
        )

    def _fetch_payload(self) -> list[dict[str, Any]]:
        if self.client is None:
            payload = _fetch_official_payload_with_browser_tls(self.fundlist_url)
        else:
            try:
                payload = self._fetch_payload_with_httpx()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {403, 429}:
                    raise
                payload = _fetch_official_payload_with_browser_tls(self.fundlist_url)
        if not isinstance(payload, list):
            raise ValueError("WisdomTree fundlist returned a non-list payload")
        return payload

    def _fetch_payload_with_httpx(self) -> Any:
        client = self.client or httpx.Client(
            timeout=40,
            follow_redirects=True,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.wisdomtree.eu/products",
                "Origin": "https://www.wisdomtree.eu",
            },
        )
        close_client = self.client is None
        try:
            response = client.get(
                self.fundlist_url,
                params=WISDOMTREE_FUNDLIST_PARAMS,
                headers={
                    "User-Agent": _BROWSER_UA,
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.wisdomtree.eu/products",
                    "Origin": "https://www.wisdomtree.eu",
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if close_client:
                client.close()
        return payload


def parse_wisdomtree_fundlist_metrics(
    rows: list[dict[str, Any]],
    *,
    fund_tickers: list[str],
    fetched_at: datetime,
) -> list[FundDailyMetric]:
    metrics: list[FundDailyMetric] = []
    for ticker in [item.upper() for item in fund_tickers]:
        row = _find_usd_listing(rows, ticker)
        if row is None:
            continue
        nav = _number(row.get("NAVusd") or row.get("NAV"))
        aum = _number(row.get("AUMusd") or row.get("AUM"))
        shares = _optional_number(row.get("SharesOutstanding"))
        if shares is None:
            shares = aum / nav
        metrics.append(
            FundDailyMetric(
                source=WisdomTreeFundListConnector.source,
                fund_ticker=ticker,
                report_date=_report_date(row),
                knowledge_date=fetched_at,
                nav_per_share=nav,
                shares_outstanding=shares,
                total_net_assets=aum,
            )
        )
    return metrics


def parse_wisdomtree_fundlist_excel(content: bytes) -> list[dict[str, Any]]:
    try:
        with ZipFile(BytesIO(content)) as workbook:
            shared_strings = _xlsx_shared_strings(workbook)
            rows = _xlsx_sheet_rows(workbook, shared_strings)
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("WisdomTree fundlist Excel payload is not a readable XLSX") from exc

    report_date = _xlsx_report_date(rows)
    header_index, header = _xlsx_header(rows)
    out: list[dict[str, Any]] = []
    for _row_number, values in rows[header_index + 1 :]:
        product = values.get(header["product"])
        raw_ticker = values.get(header["ticker"])
        nav = values.get(header["nav"])
        aum = values.get(header["aum"])
        base_currency = values.get(header["base ccy"])
        listing_currency = values.get(header["trading ccy"])
        if not product or not raw_ticker or not nav or not aum:
            continue
        ticker = str(raw_ticker).split()[0].upper()
        out.append(
            {
                "exchangeTicker": ticker,
                "name": str(product),
                "fundCurrency": str(base_currency or "").strip().upper(),
                "baseCCY": str(base_currency or "").strip().upper(),
                "listingCCY": str(listing_currency or "").strip().upper(),
                "AUM": aum,
                "AUMusd": aum,
                "NAV": nav,
                "NAVusd": nav,
                "NAV_Date": report_date.isoformat(),
            }
        )
    return out


def _find_usd_listing(rows: list[dict[str, Any]], ticker: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("exchangeTicker") or "").upper() != ticker:
            continue
        if str(row.get("fundCurrency") or "").upper() != "USD":
            continue
        if str(row.get("baseCCY") or "").upper() != "USD":
            continue
        if str(row.get("listingCCY") or "").upper() != "USD":
            continue
        try:
            nav = _number(row.get("NAVusd") or row.get("NAV"))
            aum = _number(row.get("AUMusd") or row.get("AUM"))
        except ValueError:
            continue
        if nav <= 0 or aum <= 0:
            continue
        return row
    return None


def _report_date(row: dict[str, Any]) -> date:
    raw = row.get("NAV_Date") or row.get("AUM_DateTime")
    if not raw:
        raise ValueError("WisdomTree fundlist row has no NAV/AUM date")
    value = str(raw).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed.date()


def _number(value: Any) -> float:
    if value is None or value == "":
        raise ValueError("WisdomTree fundlist row has a missing numeric field")
    return float(str(value).replace(",", ""))


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return _number(value)


def _fetch_official_payload_with_browser_tls(url: str) -> Any:
    try:
        return _fetch_with_browser_tls(url, WISDOMTREE_FUNDLIST_PARAMS)
    except Exception as json_exc:
        try:
            excel_content = _fetch_excel_with_browser_tls(
                WISDOMTREE_FUNDLIST_EXCEL_URL,
                WISDOMTREE_FUNDLIST_PARAMS,
            )
        except Exception as excel_exc:
            raise RuntimeError(
                f"WisdomTree official JSON failed ({json_exc}); official Excel failed "
                f"({excel_exc})"
            ) from excel_exc
        return parse_wisdomtree_fundlist_excel(excel_content)


def _fetch_with_browser_tls(url: str, params: dict[str, Any]) -> Any:
    from curl_cffi import requests as curl_requests

    errors: list[str] = []
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-GB,en;q=0.9,en-US;q=0.8",
        "origin": "https://www.wisdomtree.eu",
        "referer": WISDOMTREE_PRODUCTS_URL,
    }
    for impersonate in _BROWSER_TLS_IMPERSONATIONS:
        session = curl_requests.Session(impersonate=impersonate, timeout=40)
        session.headers.update(headers)
        try:
            with suppress(Exception):
                session.get(WISDOMTREE_PRODUCTS_URL)
            response = session.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            errors.append(f"{impersonate}: {exc}")
        finally:
            session.close()
    raise RuntimeError("WisdomTree browser-TLS fetch failed: " + "; ".join(errors))


def _fetch_excel_with_browser_tls(url: str, params: dict[str, Any]) -> bytes:
    from curl_cffi import requests as curl_requests

    errors: list[str] = []
    headers = {
        "accept": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "application/octet-stream,*/*"
        ),
        "accept-language": "en-GB,en;q=0.9,en-US;q=0.8",
        "origin": "https://www.wisdomtree.eu",
        "referer": WISDOMTREE_PRODUCTS_URL,
    }
    for impersonate in _BROWSER_TLS_IMPERSONATIONS:
        session = curl_requests.Session(impersonate=impersonate, timeout=40)
        session.headers.update(headers)
        try:
            with suppress(Exception):
                session.get(WISDOMTREE_PRODUCTS_URL)
            response = session.get(url, params=params, headers=headers)
            response.raise_for_status()
            return bytes(response.content)
        except Exception as exc:
            errors.append(f"{impersonate}: {exc}")
        finally:
            session.close()
    raise RuntimeError("WisdomTree Excel browser-TLS fetch failed: " + "; ".join(errors))


def _xlsx_shared_strings(workbook: ZipFile) -> list[str]:
    try:
        root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(text.text or "" for text in item.findall(".//m:t", _XLSX_NS))
        for item in root.findall("m:si", _XLSX_NS)
    ]


def _xlsx_sheet_rows(
    workbook: ZipFile,
    shared_strings: list[str],
) -> list[tuple[int, dict[int, Any]]]:
    root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    rows: list[tuple[int, dict[int, Any]]] = []
    for row in root.findall(".//m:row", _XLSX_NS):
        values: dict[int, Any] = {}
        for cell in row.findall("m:c", _XLSX_NS):
            value = _xlsx_cell_value(cell, shared_strings)
            if value is not None:
                values[_xlsx_column_index(cell.attrib["r"])] = value
        rows.append((int(row.attrib["r"]), values))
    return rows


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    if cell.attrib.get("t") == "inlineStr":
        texts = cell.findall(".//m:t", _XLSX_NS)
        return "".join(text.text or "" for text in texts)
    value = cell.find("m:v", _XLSX_NS)
    if value is None:
        return None
    raw = value.text or ""
    if cell.attrib.get("t") == "s":
        return shared_strings[int(raw)]
    return raw


def _xlsx_column_index(cell_ref: str) -> int:
    column = 0
    for char in re.sub(r"[^A-Z]", "", cell_ref.upper()):
        column = column * 26 + ord(char) - ord("A") + 1
    return column - 1


def _xlsx_report_date(rows: list[tuple[int, dict[int, Any]]]) -> date:
    for _row_number, values in rows:
        for value in values.values():
            match = re.search(r"As Of (\d{4}-\d{2}-\d{2})", str(value))
            if match:
                return date.fromisoformat(match.group(1))
    raise ValueError("WisdomTree fundlist Excel payload has no as-of date")


def _xlsx_header(rows: list[tuple[int, dict[int, Any]]]) -> tuple[int, dict[str, int]]:
    for index, (_row_number, values) in enumerate(rows):
        normalized = {str(value).strip().lower(): column for column, value in values.items()}
        required = {"product", "ticker", "base ccy", "trading ccy", "nav", "aum"}
        if required <= set(normalized):
            return index, normalized
    raise ValueError("WisdomTree fundlist Excel payload has no product header row")

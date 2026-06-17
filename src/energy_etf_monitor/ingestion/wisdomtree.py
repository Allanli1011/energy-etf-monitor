"""WisdomTree Europe fund-list metrics connector."""

from datetime import UTC, date, datetime
from typing import Any

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FundDailyMetric

WISDOMTREE_FUNDLIST_URL = "https://dataspanapi.wisdomtree.com/fundlist/data/"
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
            payload = _fetch_with_browser_tls(self.fundlist_url, WISDOMTREE_FUNDLIST_PARAMS)
        else:
            try:
                payload = self._fetch_payload_with_httpx()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {403, 429}:
                    raise
                payload = _fetch_with_browser_tls(self.fundlist_url, WISDOMTREE_FUNDLIST_PARAMS)
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


def _fetch_with_browser_tls(url: str, params: dict[str, Any]) -> Any:
    from curl_cffi import requests as curl_requests

    response = curl_requests.get(
        url,
        params=params,
        headers={
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-GB,en;q=0.9,en-US;q=0.8",
            "origin": "https://www.wisdomtree.eu",
            "referer": (
                "https://www.wisdomtree.eu/products?assetClass=Commodities"
                "&structure=ETPs&productType=Short%20and%20Leveraged"
            ),
        },
        impersonate="chrome120",
        timeout=40,
    )
    response.raise_for_status()
    return response.json()

from datetime import UTC, date, datetime
from io import BytesIO
from zipfile import ZipFile

import httpx

import energy_etf_monitor.ingestion.wisdomtree as wisdomtree
from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.wisdomtree import (
    WISDOMTREE_FUNDLIST_PARAMS,
    WISDOMTREE_PRODUCTS_URL,
    WisdomTreeFundListConnector,
    parse_wisdomtree_fundlist_excel,
    parse_wisdomtree_fundlist_metrics,
)

SAMPLE_FUNDLIST = [
    {
        "exchangeTicker": "BRNG",
        "name": "WisdomTree Brent Crude Oil",
        "fundCurrency": "USD",
        "baseCCY": "USD",
        "listingCCY": "GBP",
        "AUM": 695_517_504,
        "AUMusd": 695_517_504,
        "NAV": 56.33905,
        "NAVusd": 56.33905,
        "SharesOutstanding": 12_345_212,
        "NAV_Date": "2026-06-15",
    },
    {
        "exchangeTicker": "BRNT",
        "name": "WisdomTree Brent Crude Oil",
        "fundCurrency": "USD",
        "baseCCY": "USD",
        "listingCCY": "USD",
        "AUM": 934_914_624,
        "AUMusd": 934_914_646.29,
        "NAV": 75.73095,
        "NAVusd": 75.73095,
        "SharesOutstanding": 12_345_212,
        "NAV_Date": "2026-06-15",
    },
    {
        "exchangeTicker": "SBRT",
        "name": "WisdomTree Brent Crude Oil 1x Daily Short",
        "fundCurrency": "USD",
        "baseCCY": "USD",
        "listingCCY": "USD",
        "AUM": 52_609_684,
        "NAV": 9.37389,
        "SharesOutstanding": 5_612_366,
        "AUM_DateTime": "2026-06-15T00:00:00Z",
    },
]


def test_wisdomtree_parser_selects_same_ticker_usd_listing() -> None:
    metrics = parse_wisdomtree_fundlist_metrics(
        SAMPLE_FUNDLIST,
        fund_tickers=["BRNT", "SBRT", "MISSING"],
        fetched_at=datetime(2026, 6, 16, 8, tzinfo=UTC),
    )

    assert [metric.fund_ticker for metric in metrics] == ["BRNT", "SBRT"]
    brnt = metrics[0]
    assert brnt.source == "wisdomtree_fundlist"
    assert brnt.report_date == date(2026, 6, 15)
    assert brnt.nav_per_share == 75.73095
    assert brnt.total_net_assets == 934_914_646.29
    assert brnt.shares_outstanding == 12_345_212

    sbrt = metrics[1]
    assert sbrt.report_date == date(2026, 6, 15)
    assert sbrt.total_net_assets == 52_609_684


def test_wisdomtree_connector_fetches_fundlist_and_saves_raw(tmp_path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["user_agent"] = request.headers["User-Agent"]
        expected_params = {k: str(v) for k, v in WISDOMTREE_FUNDLIST_PARAMS.items()}
        assert dict(request.url.params) == expected_params
        return httpx.Response(200, json=SAMPLE_FUNDLIST)

    connector = WisdomTreeFundListConnector(
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        fundlist_url="https://example.test/fundlist/data/",
    )

    metrics = connector.fetch_metrics(fund_tickers=["BRNT"])

    assert metrics[0].fund_ticker == "BRNT"
    assert "Mozilla" in seen["user_agent"]
    assert list((tmp_path / "wisdomtree_fundlist").glob("*/*.json"))


def test_wisdomtree_connector_uses_browser_tls_fallback_for_403(monkeypatch) -> None:
    browser_tls_calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    def fake_browser_tls(url: str, params: dict[str, object]) -> list[dict[str, object]]:
        browser_tls_calls.append((url, params))
        return SAMPLE_FUNDLIST

    monkeypatch.setattr(wisdomtree, "_fetch_with_browser_tls", fake_browser_tls)
    connector = WisdomTreeFundListConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        fundlist_url="https://example.test/fundlist/data/",
    )

    metrics = connector.fetch_metrics(fund_tickers=["BRNT"])

    assert [metric.fund_ticker for metric in metrics] == ["BRNT"]
    assert browser_tls_calls == [
        ("https://example.test/fundlist/data/", WISDOMTREE_FUNDLIST_PARAMS)
    ]


def test_wisdomtree_connector_falls_back_to_official_excel(monkeypatch) -> None:
    calls: list[str] = []

    def fake_browser_tls(url: str, params: dict[str, object]) -> list[dict[str, object]]:
        _ = params
        calls.append(f"json:{url}")
        raise RuntimeError("json blocked")

    def fake_excel_tls(url: str, params: dict[str, object]) -> bytes:
        _ = params
        calls.append(f"excel:{url}")
        return _fundlist_xlsx()

    monkeypatch.setattr(wisdomtree, "_fetch_with_browser_tls", fake_browser_tls)
    monkeypatch.setattr(wisdomtree, "_fetch_excel_with_browser_tls", fake_excel_tls)
    connector = WisdomTreeFundListConnector()

    metrics = connector.fetch_metrics(fund_tickers=["BRNT"])

    assert calls == [
        "json:https://dataspanapi.wisdomtree.com/fundlist/data/",
        "excel:https://dataspanapi.wisdomtree.com/fundlist/excel",
    ]
    assert [metric.fund_ticker for metric in metrics] == ["BRNT"]
    assert metrics[0].source == "wisdomtree_fundlist"
    assert metrics[0].report_date == date(2026, 6, 16)
    assert metrics[0].total_net_assets == 879_291_520
    assert metrics[0].shares_outstanding == 879_291_520 / 72.44856262207031


def test_wisdomtree_excel_parser_projects_json_like_rows() -> None:
    rows = parse_wisdomtree_fundlist_excel(_fundlist_xlsx())

    assert rows == [
        {
            "exchangeTicker": "BRNT",
            "name": "WisdomTree Brent Crude Oil",
            "fundCurrency": "USD",
            "baseCCY": "USD",
            "listingCCY": "USD",
            "AUM": "879291520",
            "AUMusd": "879291520",
            "NAV": "72.44856262207031",
            "NAVusd": "72.44856262207031",
            "NAV_Date": "2026-06-16",
        }
    ]


def test_browser_tls_fetch_warms_products_page_and_retries_impersonations(
    monkeypatch,
) -> None:
    from curl_cffi import requests as curl_requests

    calls: list[tuple[str, str, object | None]] = []

    class FakeResponse:
        def __init__(self, *, status_code: int = 200, payload: object | None = None) -> None:
            self.status_code = status_code
            self.payload = payload or []

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self) -> object:
            return self.payload

    class FakeSession:
        def __init__(self, *, impersonate: str, timeout: int) -> None:
            self.impersonate = impersonate
            self.timeout = timeout
            self.headers: dict[str, str] = {}
            self.closed = False

        def get(self, url: str, *, params: object | None = None, **kwargs) -> FakeResponse:
            _ = kwargs
            calls.append((self.impersonate, url, params))
            if url == WISDOMTREE_PRODUCTS_URL:
                return FakeResponse()
            if self.impersonate == "chrome146":
                return FakeResponse(status_code=403)
            return FakeResponse(payload=SAMPLE_FUNDLIST)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(wisdomtree, "_BROWSER_TLS_IMPERSONATIONS", ("chrome146", "chrome120"))
    monkeypatch.setattr(curl_requests, "Session", FakeSession)

    payload = wisdomtree._fetch_with_browser_tls(
        "https://example.test/fundlist/data/",
        WISDOMTREE_FUNDLIST_PARAMS,
    )

    assert payload == SAMPLE_FUNDLIST
    assert calls == [
        ("chrome146", WISDOMTREE_PRODUCTS_URL, None),
        ("chrome146", "https://example.test/fundlist/data/", WISDOMTREE_FUNDLIST_PARAMS),
        ("chrome120", WISDOMTREE_PRODUCTS_URL, None),
        ("chrome120", "https://example.test/fundlist/data/", WISDOMTREE_FUNDLIST_PARAMS),
    ]


def _fundlist_xlsx() -> bytes:
    shared_strings = [
        "WisdomTree",
        "As Of 2026-06-16",
        "Product",
        "Ticker",
        "Leverage Factor",
        "MER",
        "Base Ccy",
        "Trading Ccy ",
        "Use Of Income",
        "NAV",
        "Daily Change",
        "AUM",
        "WisdomTree Brent Crude Oil",
        "BRNT LN",
        "1.0x",
        "USD",
        "N/A",
    ]
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c></row>
    <row r="2"><c r="A2" t="s"><v>1</v></c></row>
    <row r="4">
      <c r="A4" t="s"><v>2</v></c><c r="B4" t="s"><v>3</v></c>
      <c r="C4" t="s"><v>4</v></c><c r="D4" t="s"><v>5</v></c>
      <c r="E4" t="s"><v>6</v></c><c r="F4" t="s"><v>7</v></c>
      <c r="G4" t="s"><v>8</v></c><c r="H4" t="s"><v>9</v></c>
      <c r="I4" t="s"><v>10</v></c><c r="J4" t="s"><v>11</v></c>
    </row>
    <row r="5">
      <c r="A5" t="s"><v>12</v></c><c r="B5" t="s"><v>13</v></c>
      <c r="C5" t="s"><v>14</v></c><c r="D5"><v>0.0049</v></c>
      <c r="E5" t="s"><v>15</v></c><c r="F5" t="s"><v>15</v></c>
      <c r="G5" t="s"><v>16</v></c><c r="H5"><v>72.44856262207031</v></c>
      <c r="I5"><v>-0.04334278032183647</v></c><c r="J5"><v>879291520</v></c>
    </row>
  </sheetData>
</worksheet>"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as workbook:
        workbook.writestr("xl/sharedStrings.xml", shared_xml)
        workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()

from datetime import date
from zoneinfo import ZoneInfo

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.ingestion.ice import IceCotConnector, ice_cot_knowledge_datetime

SAMPLE_ICE_COT_CSV = "\n".join(
    [
        ",".join(
            [
                "Market_and_Exchange_Names",
                "As_of_Date_In_Form_YYMMDD",
                "As_of_Date_Form_MM/DD/YYYY",
                "CFTC_Commodity_Code",
                "Open_Interest_All",
                "Prod_Merc_Positions_Long_All",
                "Prod_Merc_Positions_Short_All",
                "Swap_Positions_Long_All",
                "Swap_Positions_Short_All",
                "Swap_Positions_Spread_All",
                "M_Money_Positions_Long_All",
                "M_Money_Positions_Short_All",
                "Other_Rept_Positions_Long_All",
                "Other_Rept_Positions_Short_All",
                "Contract_Units",
                "FutOnly_or_Combined",
            ]
        ),
        ",".join(
            [
                "ICE Brent Crude Futures - ICE Futures Europe",
                "260609",
                "06/09/2026",
                "B",
                "2656533",
                "869502",
                "1329816",
                "370888",
                "99463",
                "115290",
                "338224",
                "120134",
                "195079",
                "378473",
                '"(CONTRACTS OF 1,000 BARRELS)"',
                "FutOnly",
            ]
        ),
        ",".join(
            [
                "ICE Brent Crude Futures and Options - ICE Futures Europe",
                "260609",
                "06/09/2026",
                "B",
                "3621255",
                "965226",
                "1446566",
                "397336",
                "104506",
                "279106",
                "365528",
                "156637",
                "211092",
                "375601",
                '"(CONTRACTS OF 1,000 BARRELS)"',
                "Combined",
            ]
        ),
        ",".join(
            [
                "ICE Gasoil Futures - ICE Futures Europe",
                "260609",
                "06/09/2026",
                "G",
                "960000",
                "1",
                "2",
                "3",
                "4",
                "5",
                "6",
                "7",
                "8",
                "9",
                '"(CONTRACTS OF 100 METRIC TONNES)"',
                "FutOnly",
            ]
        ),
        ",".join(
            [
                "ICE Brent Crude Futures - ICE Futures Europe",
                "260602",
                "06/02/2026",
                "B",
                "2500000",
                "800000",
                "1200000",
                "300000",
                "90000",
                "100000",
                "300000",
                "110000",
                "190000",
                "370000",
                '"(CONTRACTS OF 1,000 BARRELS)"',
                "FutOnly",
            ]
        ),
    ]
)


def test_ice_cot_knowledge_datetime_applies_london_release_lag() -> None:
    knowledge_date = ice_cot_knowledge_datetime(date(2026, 6, 9))

    assert knowledge_date.isoformat() == "2026-06-12T18:30:00+01:00"
    assert knowledge_date.tzinfo == ZoneInfo("Europe/London")


def test_ice_cot_connector_normalizes_brent_futures_only_rows(tmp_path) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        assert "Mozilla" in request.headers["User-Agent"]
        return httpx.Response(200, text=SAMPLE_ICE_COT_CSV)

    connector = IceCotConnector(
        raw_store=RawPayloadStore(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        history_url_template="https://example.test/COTHist{year}.csv",
        history_years=1,
    )

    rows = connector.fetch_positions(commodity="BRENT", contract_market_code="B", limit=10)

    assert seen_urls
    assert [row.report_date.isoformat() for row in rows] == ["2026-06-09", "2026-06-02"]
    latest = rows[0]
    assert latest.source == "ice_cot"
    assert latest.market_name == "ICE Brent Crude Futures - ICE Futures Europe"
    assert latest.contract_market_code == "B"
    assert latest.open_interest == 2_656_533
    assert latest.swap_dealer_long == 370_888
    assert latest.swap_dealer_short == 99_463
    assert latest.swap_dealer_spread == 115_290
    assert latest.producer_merchant_long == 869_502
    assert latest.producer_merchant_short == 1_329_816
    assert latest.managed_money_long == 338_224
    assert latest.managed_money_short == 120_134
    assert list((tmp_path / "ice_cot").glob("*/*.json"))

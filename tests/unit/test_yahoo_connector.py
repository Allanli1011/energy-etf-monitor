from datetime import UTC, date, datetime

import httpx

from energy_etf_monitor.ingestion.yahoo import YahooEtfMetricsConnector, YahooFuturesConnector


def _chart(points: list[tuple[datetime, float]]) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [int(moment.timestamp()) for moment, _ in points],
                    "indicators": {"quote": [{"close": [price for _, price in points]}]},
                    "meta": {},
                }
            ]
        }
    }


def test_yahoo_front_history_parses_closes() -> None:
    payload = _chart(
        [
            (datetime(2026, 6, 12, tzinfo=UTC), 73.5),
            (datetime(2026, 6, 15, tzinfo=UTC), 80.29),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/CL=F")
        return httpx.Response(200, json=payload)

    connector = YahooFuturesConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    rows = connector.fetch_front_history(product_code="CL")

    assert [row.settlement_price for row in rows] == [73.5, 80.29]
    assert rows[0].product_code == "CL"
    assert rows[0].report_date == date(2026, 6, 12)
    # Continuous front: tagged as the following month so front-month logic resolves it.
    assert rows[0].contract_month == date(2026, 7, 1)


def test_yahoo_curve_assembles_front_months_with_spreads() -> None:
    prices = {"M": 81.0, "N": 80.3, "Q": 78.8, "U": 77.6, "V": 76.4}

    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.path.rsplit("/", 1)[-1]
        month_code = symbol[2]  # CL<code><yy>.NYM
        price = prices.get(month_code)
        if price is None:
            return httpx.Response(404, json={"chart": {"result": None}})
        return httpx.Response(200, json=_chart([(datetime(2026, 6, 15, tzinfo=UTC), price)]))

    connector = YahooFuturesConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    curve = connector.fetch_curve(product_code="CL", trade_date=date(2026, 6, 16), max_months=4)

    assert len(curve) == 4
    # Ordered by contract month starting at the trade month (June 2026).
    assert [s.contract_month.month for s in curve] == [6, 7, 8, 9]
    assert round(curve[0].settlement_price - curve[1].settlement_price, 2) == 0.70


def test_yahoo_supports_brent_continuous_and_monthly_contracts() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.path.rsplit("/", 1)[-1]
        seen.append(symbol)
        if symbol == "BZ=F":
            return httpx.Response(
                200,
                json=_chart([(datetime(2026, 6, 15, tzinfo=UTC), 80.0)]),
            )
        if symbol.startswith("BZ") and symbol.endswith(".NYM"):
            return httpx.Response(
                200,
                json=_chart([(datetime(2026, 6, 15, tzinfo=UTC), 79.0)]),
            )
        return httpx.Response(404, json={"chart": {"result": None}})

    connector = YahooFuturesConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    front = connector.fetch_front_history(product_code="BZ")
    curve = connector.fetch_curve(product_code="BZ", trade_date=date(2026, 6, 16), max_months=2)

    assert front[0].product_code == "BZ"
    assert curve
    assert all(row.product_code == "BZ" for row in curve)
    assert "BZ=F" in seen
    assert "BZM26.NYM" in seen


def test_yahoo_curve_history_emits_per_contract_settlements_in_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.path.rsplit("/", 1)[-1]
        if not symbol.endswith(".NYM"):
            return httpx.Response(404, json={"chart": {"result": None}})
        return httpx.Response(
            200,
            json=_chart(
                [
                    (datetime(2026, 1, 5, tzinfo=UTC), 75.0),
                    (datetime(2026, 1, 6, tzinfo=UTC), 76.0),
                    (datetime(2026, 3, 1, tzinfo=UTC), 70.0),  # outside the requested range
                ]
            ),
        )

    connector = YahooFuturesConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    rows = connector.fetch_curve_history(
        product_code="CL",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        months_ahead=2,
    )

    # Only in-range observation dates, spread across multiple contract months.
    assert rows
    assert all(date(2026, 1, 1) <= row.report_date <= date(2026, 1, 31) for row in rows)
    assert len({row.contract_month for row in rows}) >= 2


def test_yahoo_etf_metrics_approximates_shares_from_aum_and_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getcrumb"):
            return httpx.Response(200, text="testcrumb")
        if "quoteSummary" in path:
            return httpx.Response(200, json={"quoteSummary": {"result": [{
                "price": {"regularMarketPrice": {"raw": 80.0}},
                "defaultKeyStatistics": {"totalAssets": {"raw": 1_600_000_000.0}}}]}})
        return httpx.Response(200, text="")  # cookie-priming fetch

    connector = YahooEtfMetricsConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    metric = connector.fetch_metric(fund_ticker="USO")

    assert metric.fund_ticker == "USO"
    assert metric.total_net_assets == 1_600_000_000.0
    assert metric.nav_per_share == 80.0
    assert metric.shares_outstanding == 20_000_000.0  # AUM / price

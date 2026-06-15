"""Yahoo Finance futures connector (free, no key, reachable from CI).

Two roles, both returning ``FuturesSettlement`` records so they flow through the existing curve
feature pipeline:

* ``fetch_front_history`` — the continuous front-month series (e.g. ``CL=F``) as a long daily
  price history. Used to backfill the price line and price-momentum features. Only the front
  contract is known historically, so curve spreads stay unavailable for backfilled dates.
* ``fetch_curve`` — the nearest ``max_months`` monthly contracts as of a trade date (e.g.
  ``CLN26.NYM``), giving the live term structure (spreads, carry) that CME would otherwise provide.

CME's settlement pages block CI runner IPs (HTTP 403) and EIA discontinued its futures series in
2024, so Yahoo is the practical free source for WTI/NatGas futures prices.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import httpx

from energy_etf_monitor.ingestion.base import RawPayloadStore
from energy_etf_monitor.records import FuturesSettlement

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
SETTLEMENT_TZ = ZoneInfo("America/New_York")
SETTLEMENT_PUBLISH_TIME = time(16, 0)
_MONTH_CODES = "FGHJKMNQUVXZ"  # Jan..Dec CME month codes
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# product code -> (continuous front symbol, monthly contract root)
PRODUCT_SYMBOLS = {
    "CL": ("CL=F", "CL"),
    "NG": ("NG=F", "NG"),
    "RB": ("RB=F", "RB"),
}


class YahooFuturesConnector:
    source = "yahoo"

    def __init__(
        self,
        *,
        raw_store: RawPayloadStore | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.raw_store = raw_store
        self.client = client

    def _get_chart(self, symbol: str, *, range_: str, interval: str = "1d") -> dict:
        client = self.client or httpx.Client(timeout=30, headers={"User-Agent": _BROWSER_UA})
        close_client = self.client is None
        try:
            response = client.get(
                f"{YAHOO_CHART_URL}/{symbol}",
                params={"interval": interval, "range": range_},
            )
            response.raise_for_status()
            return response.json()
        finally:
            if close_client:
                client.close()

    def fetch_front_history(
        self,
        *,
        product_code: str,
        range_: str = "10y",
    ) -> list[FuturesSettlement]:
        """Continuous front-month daily history as front-contract settlements."""

        symbol, _ = _resolve_symbols(product_code)
        fetched_at = datetime.now(UTC)
        payload = self._get_chart(symbol, range_=range_)
        if self.raw_store:
            self.raw_store.save_json(
                source=self.source, payload=payload, fetched_at=fetched_at, label=f"{symbol}_front"
            )
        return [
            FuturesSettlement(
                source=self.source,
                product_code=product_code.upper(),
                report_date=observation_date,
                knowledge_date=datetime.combine(
                    observation_date, SETTLEMENT_PUBLISH_TIME, tzinfo=SETTLEMENT_TZ
                ),
                # Continuous front: tag the contract month as the month after the observation so
                # downstream front-month logic resolves it; back months are unavailable here.
                contract_month=_first_of_next_month(observation_date),
                settlement_price=close,
            )
            for observation_date, close in _iter_closes(payload)
        ]

    def fetch_curve(
        self,
        *,
        product_code: str,
        trade_date: date,
        max_months: int = 6,
    ) -> list[FuturesSettlement]:
        """The nearest ``max_months`` monthly contracts as of ``trade_date``.

        Provides the live term structure (spreads, carry) that CME would otherwise supply."""

        _, root = _resolve_symbols(product_code)
        fetched_at = datetime.now(UTC)
        settlements: list[FuturesSettlement] = []
        saved_payloads: list[dict] = []
        for offset in range(max_months + 3):
            contract_month = _add_months(date(trade_date.year, trade_date.month, 1), offset)
            symbol = _contract_symbol(root, contract_month)
            try:
                payload = self._get_chart(symbol, range_="1mo")
            except httpx.HTTPError:
                continue
            saved_payloads.append({"symbol": symbol, "payload": payload})
            settle = _close_on_or_before(payload, trade_date)
            if settle is None:
                continue
            observation_date, price = settle
            settlements.append(
                FuturesSettlement(
                    source=self.source,
                    product_code=product_code.upper(),
                    report_date=trade_date,
                    knowledge_date=datetime.combine(
                        observation_date, SETTLEMENT_PUBLISH_TIME, tzinfo=SETTLEMENT_TZ
                    ),
                    contract_month=contract_month,
                    settlement_price=price,
                )
            )
            if len(settlements) == max_months:
                break
        if self.raw_store and saved_payloads:
            self.raw_store.save_json(
                source=self.source,
                payload={"contracts": saved_payloads},
                fetched_at=fetched_at,
                label=f"{root}_curve",
            )
        return settlements


    def fetch_curve_history(
        self,
        *,
        product_code: str,
        start_date: date,
        end_date: date,
        months_ahead: int = 7,
    ) -> list[FuturesSettlement]:
        """Per-(date, contract) settlements for every monthly contract spanning the range.

        Each monthly contract carries years of its own daily history, so assembling them gives a
        real M1..M6 term structure on each historical date — feature derivation picks the nearest
        contracts by delivery month, so far-dated contracts are simply ignored per date.
        """

        _, root = _resolve_symbols(product_code)
        fetched_at = datetime.now(UTC)
        first = date(start_date.year, start_date.month, 1)
        last = _add_months(date(end_date.year, end_date.month, 1), months_ahead)
        settlements: list[FuturesSettlement] = []
        manifest: list[dict] = []
        contract = first
        while contract <= last:
            symbol = _contract_symbol(root, contract)
            try:
                payload = self._get_chart(symbol, range_="10y")
            except httpx.HTTPError:
                contract = _add_months(contract, 1)
                continue
            in_range = 0
            for observation_date, price in _iter_closes(payload):
                if start_date <= observation_date <= end_date:
                    settlements.append(
                        FuturesSettlement(
                            source=self.source,
                            product_code=product_code.upper(),
                            report_date=observation_date,
                            knowledge_date=datetime.combine(
                                observation_date, SETTLEMENT_PUBLISH_TIME, tzinfo=SETTLEMENT_TZ
                            ),
                            contract_month=contract,
                            settlement_price=price,
                        )
                    )
                    in_range += 1
            manifest.append({"symbol": symbol, "in_range": in_range})
            contract = _add_months(contract, 1)
        if self.raw_store and manifest:
            self.raw_store.save_json(
                source=self.source,
                payload={"contracts": manifest},
                fetched_at=fetched_at,
                label=f"{root}_curve_history",
            )
        return settlements


def _resolve_symbols(product_code: str) -> tuple[str, str]:
    try:
        return PRODUCT_SYMBOLS[product_code.upper()]
    except KeyError as exc:
        raise ValueError(f"Unsupported Yahoo product code: {product_code}") from exc


def _contract_symbol(root: str, contract_month: date) -> str:
    return f"{root}{_MONTH_CODES[contract_month.month - 1]}{contract_month.year % 100:02d}.NYM"


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _first_of_next_month(value: date) -> date:
    return _add_months(date(value.year, value.month, 1), 1)


def _iter_closes(payload: dict) -> list[tuple[date, float]]:
    result = _first_result(payload)
    if result is None:
        return []
    timestamps = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    out: list[tuple[date, float]] = []
    for ts, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        out.append((datetime.fromtimestamp(ts, tz=UTC).date(), float(close)))
    return out


def _close_on_or_before(payload: dict, trade_date: date) -> tuple[date, float] | None:
    eligible = [pair for pair in _iter_closes(payload) if pair[0] <= trade_date]
    return max(eligible, key=lambda pair: pair[0]) if eligible else None


def _first_result(payload: dict) -> dict | None:
    results = (payload.get("chart") or {}).get("result")
    if not results:
        return None
    return results[0]

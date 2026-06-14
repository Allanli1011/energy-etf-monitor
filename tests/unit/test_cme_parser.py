from datetime import date

from energy_etf_monitor.ingestion.cme import CmeSettlementPageParser


def test_cme_parser_extracts_first_six_contract_months() -> None:
    html = """
    <table>
      <tr><th>Month</th><th>Open</th><th>Settle</th><th>Volume</th><th>Open Interest</th></tr>
      <tr><td>JUL 2026</td><td>73.10</td><td>73.25</td><td>100</td><td>250000</td></tr>
      <tr><td>AUG 2026</td><td>72.88</td><td>72.95</td><td>90</td><td>180000</td></tr>
      <tr><td>SEP 2026</td><td>72.50</td><td>72.61</td><td>80</td><td>120000</td></tr>
      <tr><td>OCT 2026</td><td>72.10</td><td>72.22</td><td>70</td><td>90000</td></tr>
      <tr><td>NOV 2026</td><td>71.75</td><td>71.83</td><td>60</td><td>80000</td></tr>
      <tr><td>DEC 2026</td><td>71.20</td><td>71.34</td><td>50</td><td>76000</td></tr>
      <tr><td>JAN 2027</td><td>70.80</td><td>70.91</td><td>40</td><td>50000</td></tr>
    </table>
    """

    rows = CmeSettlementPageParser().parse(html, product_code="CL", trade_date=date(2026, 6, 12))

    assert len(rows) == 6
    assert rows[0].source == "cme"
    assert rows[0].product_code == "CL"
    assert rows[0].contract_month.isoformat() == "2026-07-01"
    assert rows[0].settlement_price == 73.25
    assert rows[0].open_interest == 250_000
    assert rows[-1].contract_month.isoformat() == "2026-12-01"


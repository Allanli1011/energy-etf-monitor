"""Self-contained static HTML dashboard — a serverless alternative to the Streamlit app.

Reuses the tested ``dashboard/data.py`` shaping layer, so training/inference logic and display
projections stay identical. The output is a single HTML file per commodity with inline CSS and
inline SVG charts: no JavaScript, no external assets, no server — it works offline and on a static
host such as GitHub Pages.
"""

import html
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from energy_etf_monitor.commodities import COMMODITIES
from energy_etf_monitor.config import Settings
from energy_etf_monitor.dashboard.data import (
    INVENTORY_COLUMNS,
    POSITIONING_COLUMNS,
    PRICE_AND_CURVE_COLUMNS,
    feature_time_series,
    latest_call,
    news_panel_rows,
)
from energy_etf_monitor.modeling.monitoring import ModelHealthReport, build_model_health_report
from energy_etf_monitor.records import DailyFeatureRow, DailyPrediction, NewsArticle
from energy_etf_monitor.storage.repository import IngestionRepository

_COLORS = ("#4fc3f7", "#ff8a65", "#81c784", "#ba68c8", "#ffd54f")


def _svg_multiline(series_map: dict[str, list[float | None]], *, width: int = 780,
                   height: int = 230) -> str:
    pad_l, pad_r, pad_t, pad_b = 52, 14, 14, 30
    numeric = [value for values in series_map.values() for value in values if value is not None]
    if not numeric:
        return '<div class="empty">no data yet</div>'
    low, high = min(numeric), max(numeric)
    if low == high:
        low, high = low - 1, high + 1
    count = max((len(values) for values in series_map.values()), default=2)
    count = max(count, 2)
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    def fx(index: int) -> float:
        return pad_l + plot_w * index / (count - 1)

    def fy(value: float) -> float:
        return pad_t + plot_h * (1 - (value - low) / (high - low))

    polylines, legend = [], []
    for order, (name, values) in enumerate(series_map.items()):
        color = _COLORS[order % len(_COLORS)]
        points = " ".join(
            f"{fx(i):.1f},{fy(v):.1f}" for i, v in enumerate(values) if v is not None
        )
        if points:
            polylines.append(
                f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{points}"/>'
            )
        legend.append(
            f'<span class="lg"><i style="background:{color}"></i>{html.escape(name)}</span>'
        )
    axes = (
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" class="axis"/>'
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" '
        f'y2="{pad_t + plot_h}" class="axis"/>'
    )
    labels = (
        f'<text x="8" y="{pad_t + 9}" class="ax">{high:.2f}</text>'
        f'<text x="8" y="{pad_t + plot_h}" class="ax">{low:.2f}</text>'
    )
    svg = (
        f'<svg viewBox="0 0 {width} {height}" class="chart" '
        f'preserveAspectRatio="xMidYMid meet">{axes}{labels}{"".join(polylines)}</svg>'
    )
    return svg + '<div class="legend">' + "".join(legend) + "</div>"


def _call_card(label: str, probability: float, naive: float | None) -> str:
    delta = ""
    if naive is not None:
        difference = probability - naive
        css = "up" if difference >= 0 else "down"
        delta = f'<div class="delta {css}">{difference:+.2f} vs naive</div>'
    return (
        f'<div class="card"><div class="lbl">{html.escape(label)}</div>'
        f'<div class="big">{probability:.2f}</div>{delta}</div>'
    )


def _drivers_table(title: str, drivers) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(driver.feature)}</td>"
        f"<td class='num'>{driver.contribution:+.4f}</td></tr>"
        for driver in drivers
    )
    return f'<div class="drivers"><h4>{html.escape(title)}</h4><table>{rows}</table></div>'


def _chart_section(title: str, feature_rows: Sequence[DailyFeatureRow],
                  columns: Sequence[str]) -> str:
    series = feature_time_series(feature_rows, columns).series
    return f"<h3>{html.escape(title)}</h3>{_svg_multiline(series)}"


def render_dashboard_html(
    *,
    commodity: str,
    predictions: Sequence[DailyPrediction],
    feature_rows: Sequence[DailyFeatureRow],
    news: Sequence[NewsArticle],
    health: ModelHealthReport,
    as_of: datetime,
    commodities: Sequence[str] = tuple(COMMODITIES),
) -> str:
    """Render one commodity's dashboard into a self-contained HTML document (pure, no I/O)."""

    news_rows = news_panel_rows(news, limit=12)
    news_html = "".join(
        f"<tr><td>{html.escape(row['published'])}</td>"
        f"<td>{html.escape(str(row['headline']))}</td>"
        f"<td>{html.escape(str(row['commodity']))}</td>"
        f"<td>{html.escape(str(row['catalyst']))}</td>"
        f"<td class='num'>{row['importance']}</td>"
        f"<td>{html.escape(str(row['direction']))}</td>"
        f"<td class='num'>{row['confidence']}</td></tr>"
        for row in news_rows
    ) or "<tr><td colspan='7' class='muted'>No classified news yet.</td></tr>"

    call = latest_call(list(predictions))
    if call is None:
        call_html = '<p class="muted">No predictions yet.</p>'
    else:
        price_card = _call_card(
            "P(price up)", call.price_up_probability, call.price_naive_probability
        )
        spread_card = _call_card(
            "P(spread widens)", call.spread_up_probability, call.spread_naive_probability
        )
        call_html = (
            f'<p class="muted">{html.escape(call.commodity)} — decision date '
            f"{call.report_date}, horizon {call.horizon_days}d</p>"
            f'<div class="cards">{price_card}{spread_card}</div>'
            f'<div class="dgrid">{_drivers_table("Price drivers", call.price_top_drivers)}'
            f'{_drivers_table("Spread drivers", call.spread_top_drivers)}</div>'
        )

    if health.metrics:
        metric_rows = "".join(
            f"<tr><td>{html.escape(key)}</td><td class='num'>{value:.4f}</td></tr>"
            for key, value in health.metrics.items()
        )
        health_html = (
            f"<table>{metric_rows}</table>"
            f'<p class="muted">Scored {len(health.outcomes)} predictions '
            f"with realized outcomes.</p>"
        )
    else:
        health_html = '<p class="muted">No realized outcomes yet.</p>'

    nav = " ".join(
        f'<a href="{name.lower()}.html" class="{"on" if name == commodity else ""}">'
        f"{html.escape(name)}</a>"
        for name in commodities
    )
    return _PAGE.format(
        commodity=html.escape(commodity),
        as_of=as_of.strftime("%Y-%m-%d %H:%M"),
        nav=nav,
        call_html=call_html,
        news_html=news_html,
        price_chart=_chart_section("Price & curve", feature_rows, PRICE_AND_CURVE_COLUMNS),
        positioning_chart=_chart_section(
            "Positioning (COT swap dealers)", feature_rows, POSITIONING_COLUMNS
        ),
        inventory_chart=_chart_section("Inventory", feature_rows, INVENTORY_COLUMNS),
        health_html=health_html,
    )


def build_commodity_html(commodity: str, settings: Settings, as_of: datetime) -> str:
    """Load a commodity's point-in-time data from the repository and render its page."""

    with IngestionRepository.from_settings(settings) as repository:
        predictions = repository.list_daily_predictions(commodity=commodity)
        feature_rows = repository.list_daily_feature_rows(commodity=commodity)
        news = repository.list_news_articles(as_of=as_of, limit=25)
    health = build_model_health_report(
        predictions, feature_rows, as_of=as_of, commodity=commodity
    )
    return render_dashboard_html(
        commodity=commodity,
        predictions=predictions,
        feature_rows=feature_rows,
        news=news,
        health=health,
        as_of=as_of,
    )


def write_static_site(output_dir: Path, *, settings: Settings, as_of: datetime) -> list[Path]:
    """Write one HTML page per commodity plus an index page; return the paths written."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    default = next(iter(COMMODITIES))
    for commodity in COMMODITIES:
        page = build_commodity_html(commodity, settings, as_of)
        path = output_dir / f"{commodity.lower()}.html"
        path.write_text(page, encoding="utf-8")
        written.append(path)
        if commodity == default:
            index = output_dir / "index.html"
            index.write_text(page, encoding="utf-8")
            written.append(index)
    return written


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Energy ETF monitor — {commodity}</title>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:#0e1117;color:#e6edf3;
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.wrap{{max-width:1000px;margin:0 auto;padding:24px}}
h1{{font-size:26px;margin:0 0 2px}}
h3{{margin:26px 0 6px;border-bottom:1px solid #222a35;padding-bottom:4px}}
h4{{margin:0 0 6px;font-size:14px;color:#9aa7b4}}
.muted{{color:#8b97a4}}
.caption{{color:#8b97a4;margin:0 0 14px}}
nav{{margin:10px 0 18px}}
nav a{{display:inline-block;padding:6px 14px;margin-right:6px;border-radius:8px;
background:#161b22;color:#c9d4df;text-decoration:none;border:1px solid #222a35}}
nav a.on{{background:#1f6feb;color:#fff;border-color:#1f6feb}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #1c232d}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
.cards{{display:flex;gap:16px;margin:8px 0;flex-wrap:wrap}}
.card{{background:#161b22;border:1px solid #222a35;border-radius:12px;
padding:14px 20px;min-width:200px}}
.card .lbl{{color:#9aa7b4;font-size:13px}}
.card .big{{font-size:34px;font-weight:700}}
.delta{{font-size:12px;margin-top:2px}}
.delta.up{{color:#3fb950}}.delta.down{{color:#f85149}}
.dgrid{{display:flex;gap:24px;flex-wrap:wrap;margin-top:8px}}
.drivers{{flex:1;min-width:300px}}
.chart{{width:100%;height:auto;background:#10151c;border:1px solid #1c232d;border-radius:10px}}
.axis{{stroke:#39424d;stroke-width:1}}.ax{{fill:#7d8a97;font-size:10px}}
.legend{{margin:6px 0 2px;color:#9aa7b4;font-size:12px}}
.legend .lg{{margin-right:14px;white-space:nowrap}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;
margin-right:5px;vertical-align:middle}}
.empty{{color:#6b7682;padding:18px 0}}
footer{{margin-top:30px;color:#6b7682;font-size:12px;border-top:1px solid #1c232d;padding-top:12px}}
</style></head><body><div class="wrap">
<h1>Energy ETF monitor</h1>
<p class="caption">Probabilistic directional tilts, not a price oracle. \
Static snapshot generated {as_of} UTC.</p>
<nav>{nav}</nav>
<h3>Today's call</h3>{call_html}
<h3>Latest market-moving news</h3>
<table><thead><tr><th>published</th><th>headline</th><th>commodity</th><th>catalyst</th>\
<th>importance</th><th>direction</th><th>confidence</th></tr></thead>\
<tbody>{news_html}</tbody></table>
{price_chart}
{positioning_chart}
{inventory_chart}
<h3>Model health (decay monitor)</h3>{health_html}
<footer>Energy ETF monitor · self-contained static report · no JavaScript, no external assets.\
</footer>
</div></body></html>"""

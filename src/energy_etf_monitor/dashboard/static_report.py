"""Self-contained interactive dashboard of energy-price *factors* (not a price predictor).

One HTML file per commodity: embedded JSON time series + vanilla JS (no external assets, no
network) renders the charts and a single global time-range selector that drives every chart. Built
on the same tested ``dashboard/data.py`` shaping layer; works offline and on a static host.
"""

import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta

from energy_etf_monitor.commodities import COMMODITIES
from energy_etf_monitor.config import Settings
from energy_etf_monitor.dashboard.data import (
    etf_exposure_flow_chart,
    etf_exposure_rows,
    etf_flow_chart,
    etf_flow_rows,
    etf_source_health_rows,
    etf_strategy_summary_rows,
    feature_time_series,
    news_panel_rows,
)
from energy_etf_monitor.etfs import dashboard_commodities, etf_funds_for_commodity
from energy_etf_monitor.records import (
    CotPosition,
    DailyFeatureRow,
    FundDailyMetric,
    FundHolding,
    NewsArticle,
)
from energy_etf_monitor.storage.repository import IngestionRepository

# USCF single-commodity roll window: front-month funds roll early each month (business days ~5–9).
ROLL_WINDOW_START_BD = 5
ROLL_WINDOW_END_BD = 9

# (chart key, feature column(s), human label, y-axis label, explanation shown under the chart)
PRICE_CHART = {
    "key": "price", "column": "cl_front_month_settlement",
    "title": "Front-month futures price",
    "yLabel": "Price",
    "explain": "The nearest-to-expiry futures settlement (from Yahoo Finance). This is the single "
               "most direct read on the commodity itself; everything else on this page is a factor "
               "that pushes it around.",
}
INVENTORY_VALUE = {"key": "inventory", "column": "inventory_value"}
INVENTORY_SURPRISE = {"key": "surprise", "column": "inventory_seasonal_surprise"}


def _series(feature_rows: Sequence[DailyFeatureRow], column: str) -> dict:
    ts = feature_time_series(feature_rows, (column,))
    return {
        "dates": [d.isoformat() for d in ts.dates],
        "values": [None if v is None else round(float(v), 4) for v in ts.series[column]],
    }


def _cot_series(cot_positions: Sequence[CotPosition]) -> dict:
    ordered = sorted(cot_positions, key=lambda c: c.report_date)

    def net(long_value, short_value):
        if long_value is None or short_value is None:
            return None
        return int(long_value) - int(short_value)

    categories = [
        ("Producer / merchant (hedgers)", "producer_merchant_long", "producer_merchant_short"),
        ("Swap dealers", "swap_dealer_long", "swap_dealer_short"),
        ("Managed money (speculators)", "managed_money_long", "managed_money_short"),
        ("Other reportables", "other_reportable_long", "other_reportable_short"),
    ]
    return {
        "dates": [c.report_date.isoformat() for c in ordered],
        "series": [
            {"name": name,
             "values": [net(getattr(c, lo), getattr(c, sh)) for c in ordered]}
            for name, lo, sh in categories
        ],
        "title": "Positioning by trader type — net (CFTC disaggregated COT)",
        "yLabel": "Net contracts (long − short)",
        "explain": "Net position (long − short) for each CFTC disaggregated trader category. "
                   "Producer / merchant / processor / user are the physical hedgers (producers "
                   "tend net short, consumers net long) — this is the producer-hedger flow. Swap "
                   "dealers mostly offset index/ETF exposure; managed money is speculative (CTAs, "
                   "funds); other reportables are the remaining large traders. Weekly: reported "
                   "Tuesday, released Friday (lagged here accordingly).",
    }


def _nth_business_day(year: int, month: int, n: int) -> date:
    day, count = date(year, month, 1), 0
    while True:
        if day.weekday() < 5:
            count += 1
            if count == n:
                return day
        day += timedelta(days=1)


def _roll_status(as_of: date) -> dict:
    """Next early-month roll window for front-month funds, and a heads-up when it is near."""

    def window(year: int, month: int) -> tuple[date, date]:
        return (_nth_business_day(year, month, ROLL_WINDOW_START_BD),
                _nth_business_day(year, month, ROLL_WINDOW_END_BD))

    start, end = window(as_of.year, as_of.month)
    if as_of > end:  # this month's window has passed — look to next month
        ny, nm = (as_of.year + 1, 1) if as_of.month == 12 else (as_of.year, as_of.month + 1)
        start, end = window(ny, nm)
    in_window = start <= as_of <= end
    days_until = (start - as_of).days
    if in_window:
        level, message = "now", "Roll window is active now — front-month funds are rolling."
    elif days_until <= 5:
        level, message = "soon", f"Roll window starts in {days_until} day(s) ({start.isoformat()})."
    else:
        level, message = "ok", f"Next roll window: {start.isoformat()} → {end.isoformat()} " \
                               f"({days_until} days away)."
    return {"window_start": start.isoformat(), "window_end": end.isoformat(),
            "days_until": days_until, "in_window": in_window, "level": level, "message": message}


def _legacy_flow_section(commodity: str, fund_metrics: Sequence[FundDailyMetric]) -> dict:
    config = COMMODITIES.get(commodity)
    fund = config.crowding_fund_ticker if config else None
    ordered = sorted(fund_metrics, key=lambda m: m.report_date)
    return {
        "fund": fund,
        "dates": [m.report_date.isoformat() for m in ordered],
        "values": [None if m.implied_flow_usd is None else round(m.implied_flow_usd / 1e6, 3)
                   for m in ordered],
        "title": f"ETF creation / redemption — {fund}" if fund else "ETF creation / redemption",
        "yLabel": "Daily flow ($M)",
        "explain": "Estimated daily creation (positive) and redemption (negative) for the "
                   f"futures-based ETF tracking this commodity ({fund or 'n/a'}). Derived from the "
                   "day-over-day change in shares outstanding (approximated as Yahoo AUM ÷ price) "
                   "× NAV. Sustained creation means new money flowing in — those dollars must buy "
                   "futures, and around the monthly roll that flow can move the front-of-curve "
                   "spread. Going-forward only: it begins accumulating once collection starts, so "
                   "early on this chart is sparse.",
    }


def _flow_section(commodity: str, fund_metrics: Sequence[FundDailyMetric]) -> dict:
    config = COMMODITIES.get(commodity)
    fund = config.crowding_fund_ticker if config else None
    ordered = sorted(fund_metrics, key=lambda metric: metric.report_date)
    return {
        "fund": fund,
        "dates": [metric.report_date.isoformat() for metric in ordered],
        "values": [
            None
            if metric.implied_flow_usd is None
            else round(metric.implied_flow_usd / 1e6, 3)
            for metric in ordered
        ],
        "title": (
            f"ETF creation / redemption - {fund}" if fund else "ETF creation / redemption"
        ),
        "yLabel": "Daily flow ($M)",
        "explain": (
            "Official issuer creation/redemption flow is used when available; otherwise the "
            "fallback is day-over-day shares outstanding times NAV. Sustained creation means new "
            "money flowing in, and around monthly roll windows that pressure can matter for "
            "front-of-curve spreads."
        ),
    }


def _coverage_note(commodity: str) -> str:
    if commodity.upper() in COMMODITIES:
        return ""
    return (
        "ETF/ETP analysis only: core futures curve, inventory, and COT factor rows are not "
        "enabled for this commodity yet. Brent ICE curve source coverage is pending, so "
        "issuer/fallback ETF rows are separated from unavailable futures-market factor data."
    )


def render_dashboard_html(
    *,
    commodity: str,
    feature_rows: Sequence[DailyFeatureRow],
    news: Sequence[NewsArticle],
    as_of: datetime,
    fund_metrics: Sequence[FundDailyMetric] = (),
    fund_holdings: Sequence[FundHolding] = (),
    cot_positions: Sequence[CotPosition] = (),
    commodities: Sequence[str] | None = None,
) -> str:
    """Render one commodity's factor dashboard into a self-contained interactive HTML document."""

    commodity = commodity.upper()
    etf_funds = etf_funds_for_commodity(commodity)
    news_rows = [
        {
            "published": r["published"], "title": str(r["headline"]), "url": str(r["url"]),
            "source": str(r["source"]), "commodity": str(r["commodity"]),
            "catalyst": str(r["catalyst"]), "importance": r["importance"],
            "direction": str(r["direction"]), "confidence": r["confidence"],
        }
        for r in news_panel_rows(news, limit=25)
    ]
    data = {
        "commodity": commodity,
        "commodities": list(commodities or dashboard_commodities(tuple(COMMODITIES))),
        "coverage_note": _coverage_note(commodity),
        "as_of": as_of.strftime("%Y-%m-%d %H:%M"),
        "funds": [
            {
                "ticker": fund.ticker,
                "issuer": fund.issuer,
                "front": fund.front_month_roll,
                "strategy": fund.strategy_description,
                "badge": fund.strategy_badge,
                "leverage": fund.leverage,
            }
            for fund in etf_funds
        ],
        "roll": _roll_status(as_of.date()),
        "price": {**PRICE_CHART, **_series(feature_rows, PRICE_CHART["column"])},
        "cot": _cot_series(cot_positions),
        "inventory": _series(feature_rows, INVENTORY_VALUE["column"]),
        "surprise": _series(feature_rows, INVENTORY_SURPRISE["column"]),
        "flow": _flow_section(commodity, fund_metrics),
        "etf": {
            "flow": etf_flow_chart(fund_metrics, funds=etf_funds),
            "exposure_flow": etf_exposure_flow_chart(fund_metrics, funds=etf_funds),
            "rows": etf_flow_rows(fund_metrics, funds=etf_funds),
            "summary": etf_strategy_summary_rows(fund_metrics, funds=etf_funds),
            "health": etf_source_health_rows(
                fund_metrics,
                holdings=fund_holdings,
                funds=etf_funds,
                as_of=as_of.date(),
            ),
            "exposure": etf_exposure_rows(
                fund_holdings,
                metrics=fund_metrics,
                funds=etf_funds,
            ),
        },
        "news": news_rows,
    }
    return _PAGE.replace("/*__DASH__*/", _script_safe_json(data))


def build_commodity_html(
    commodity: str,
    settings: Settings,
    as_of: datetime,
    *,
    commodities: Sequence[str] | None = None,
) -> str:
    etf_funds = etf_funds_for_commodity(commodity)
    tickers = [fund.ticker for fund in etf_funds]
    with IngestionRepository.from_settings(settings) as repository:
        feature_rows = repository.list_daily_feature_rows(commodity=commodity)
        news = repository.list_news_articles(as_of=as_of, limit=25)
        fund_metrics = [
            metric
            for ticker in tickers
            for metric in repository.list_fund_daily_metrics(fund_ticker=ticker)
        ]
        fund_holdings = [
            holding
            for ticker in tickers
            for holding in repository.list_fund_holdings(fund_ticker=ticker)
        ]
        cot_positions = repository.list_cot_positions(commodity=commodity)
    return render_dashboard_html(
        commodity=commodity, feature_rows=feature_rows, news=news,
        as_of=as_of, fund_metrics=fund_metrics, fund_holdings=fund_holdings,
        cot_positions=cot_positions, commodities=commodities,
    )


def write_static_site(output_dir, *, settings: Settings, as_of: datetime) -> list:
    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list = []
    commodities = dashboard_commodities(tuple(COMMODITIES))
    default = commodities[0]
    for commodity in commodities:
        page = build_commodity_html(commodity, settings, as_of, commodities=commodities)
        path = output_dir / f"{commodity.lower()}.html"
        path.write_text(page, encoding="utf-8")
        written.append(path)
        if commodity == default:
            index = output_dir / "index.html"
            index.write_text(page, encoding="utf-8")
            written.append(index)
    return written


def _script_safe_json(data: dict) -> str:
    return (
        json.dumps(data)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Energy ETF monitor</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0e1117;color:#e6edf3;
font:14px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:24px}
h1{font-size:26px;margin:0 0 2px}
h2{font-size:19px;margin:30px 0 4px}
.caption,.explain{color:#8b97a4}
.explain{font-size:12.5px;margin:8px 0 0;max-width:880px}
nav{margin:12px 0 16px}
nav a{display:inline-block;padding:6px 14px;margin-right:6px;border-radius:8px;
background:#161b22;color:#c9d4df;text-decoration:none;border:1px solid #222a35}
nav a.on{background:#1f6feb;color:#fff;border-color:#1f6feb}
a{color:#6cb6ff}
.panel{background:#10151c;border:1px solid #1c232d;border-radius:12px;padding:14px 16px;margin-top:10px}
.rollgrid{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px}
.fund{flex:1;min-width:280px;background:#161b22;border:1px solid #222a35;border-radius:10px;padding:12px 14px}
.fund .tk{font-weight:700;font-size:15px}
.fund .tag{font-size:11px;color:#9aa7b4;border:1px solid #2b3340;border-radius:999px;padding:1px 8px;margin-left:6px}
.metricgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:10px}
.metric{background:#10151c;border:1px solid #1c232d;border-radius:10px;padding:10px 12px}
.metric .k{color:#9aa7b4;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.metric .v{font-size:18px;font-weight:700;margin-top:2px}
.alert{border-radius:10px;padding:10px 14px;margin-top:8px;font-size:13px;border:1px solid}
.alert.now{background:#3a1d20;border-color:#7d2b32;color:#ffb4b4}
.alert.soon{background:#3a311a;border-color:#7d6a2b;color:#ffe08a}
.alert.ok{background:#161b22;border-color:#222a35;color:#9aa7b4}
.ranges{margin:18px 0 4px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.ranges b{color:#9aa7b4;font-weight:600;margin-right:4px}
.ranges button{background:#161b22;color:#c9d4df;border:1px solid #222a35;border-radius:8px;
padding:5px 12px;cursor:pointer;font:inherit;font-size:13px}
.ranges button.on{background:#1f6feb;color:#fff;border-color:#1f6feb}
.chartcard{margin-top:14px}
.chart{position:relative}
.chart svg{width:100%;height:auto;background:#10151c;border:1px solid #1c232d;border-radius:10px;display:block}
.tip{position:absolute;pointer-events:none;background:#1b2430;border:1px solid #2b3340;border-radius:8px;
padding:6px 9px;font-size:12px;color:#e6edf3;box-shadow:0 4px 14px rgba(0,0,0,.45);z-index:5;white-space:nowrap}
.tip b{display:block;margin-bottom:3px;color:#9aa7b4;font-weight:600}
.tip i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:middle}
.axis{stroke:#39424d;stroke-width:1}.grid{stroke:#1a212b;stroke-width:1}
.axlbl{fill:#7d8a97;font-size:10px}
.legend{margin:6px 2px 0;color:#9aa7b4;font-size:12px}
.legend .lg{margin-right:16px;white-space:nowrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}
.empty{color:#6b7682;padding:22px 0;text-align:center}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #1c232d;vertical-align:top}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.status{font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:.04em}
.status-ok{color:#3fb950}.status-partial{color:#ffd54f}.status-stale{color:#ff8a65}.status-missing{color:#f85149}
.dir-Bullish{color:#3fb950}.dir-Bearish{color:#f85149}.dir-Mixed,.dir-Neutral,.dir-Unknown{color:#9aa7b4}
footer{margin-top:34px;color:#6b7682;font-size:12px;border-top:1px solid #1c232d;padding-top:12px}
</style></head><body><div class="wrap" id="root"></div>
<script>
const DASH = /*__DASH__*/;
const PALETTE = ["#4fc3f7","#ff8a65","#81c784","#ba68c8","#ffd54f"];
let RANGE = 12; // months; null = all

function esc(s){const d=document.createElement("div");d.textContent=s==null?"":String(s);return d.innerHTML;}

function clip(series, months){
  if(!months || !series.dates.length) return series;
  const last = new Date(series.dates[series.dates.length-1]+"T00:00:00Z");
  const cut = new Date(last); cut.setUTCMonth(cut.getUTCMonth()-months);
  const dates=[], values=[];
  for(let i=0;i<series.dates.length;i++){
    if(new Date(series.dates[i]+"T00:00:00Z") >= cut){ dates.push(series.dates[i]); values.push(series.values[i]); }
  }
  return {dates, values};
}

function extent(arr){let lo=Infinity,hi=-Infinity;for(const v of arr){if(v==null)continue;if(v<lo)lo=v;if(v>hi)hi=v;}
  if(lo===Infinity)return null; if(lo===hi){lo-=1;hi+=1;} return [lo,hi];}

// series: [{name,color,values,axis(0|1)}]; shared `dates`. Dual axis when any axis===1.
function chartSVG(dates, series){
  const W=980,H=260,padL=58,padR=58,padT=14,padB=30;
  const left = extent([].concat(...series.filter(s=>s.axis!==1).map(s=>s.values)));
  const right = extent([].concat(...series.filter(s=>s.axis===1).map(s=>s.values)));
  if(!left && !right) return '<div class="empty">no data in this range</div>';
  const n=Math.max(dates.length,2), plotW=W-padL-padR, plotH=H-padT-padB;
  const x=i=>padL+plotW*(n<2?0:i/(n-1));
  const yOf=(v,ext)=>{const[a,b]=ext;return padT+plotH*(1-(v-a)/(b-a));};
  let svg=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">`;
  // gridlines + y labels (left axis primary)
  const pe = left||right;
  for(let g=0; g<=3; g++){const yy=padT+plotH*g/3; const val=pe[1]-(pe[1]-pe[0])*g/3;
    svg+=`<line class="grid" x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}"/>`;
    svg+=`<text class="axlbl" x="${padL-6}" y="${yy+3}" text-anchor="end">${fmt(val)}</text>`;}
  if(right){for(let g=0; g<=3; g++){const yy=padT+plotH*g/3; const val=right[1]-(right[1]-right[0])*g/3;
    svg+=`<text class="axlbl" x="${W-padR+6}" y="${yy+3}" text-anchor="start">${fmt(val)}</text>`;}}
  // x date labels (~5)
  const ticks=Math.min(5,n);
  for(let t=0;t<ticks;t++){const i=Math.round(t*(n-1)/(ticks-1||1)); const dt=dates[i]||"";
    svg+=`<text class="axlbl" x="${x(i)}" y="${H-padB+16}" text-anchor="middle">${dt.slice(0,7)}</text>`;}
  svg+=`<line class="axis" x1="${padL}" y1="${padT+plotH}" x2="${W-padR}" y2="${padT+plotH}"/>`;
  for(const s of series){const ext = s.axis===1?right:left; if(!ext)continue;
    let pts=""; for(let i=0;i<dates.length;i++){const v=s.values[i]; if(v==null)continue; pts+=`${x(i).toFixed(1)},${yOf(v,ext).toFixed(1)} `;}
    if(pts.trim()) svg+=`<polyline fill="none" stroke="${s.color}" stroke-width="1.8" points="${pts.trim()}"/>`;}
  svg+="</svg>";
  const legend='<div class="legend">'+series.map(s=>`<span class="lg"><i style="background:${s.color}"></i>${esc(s.name)}${s.axis===1?" (right)":""}</span>`).join("")+"</div>";
  return svg+legend;
}
function stackedBarLineSVG(dates, series, net){
  const W=980,H=260,padL=58,padR=58,padT=14,padB=30;
  const n=Math.max(dates.length,1), plotW=W-padL-padR, plotH=H-padT-padB;
  const posTotals=[], negTotals=[];
  for(let i=0;i<dates.length;i++){
    let pos=0, neg=0;
    for(const s of series){const v=s.values[i]; if(v==null)continue; if(v>=0)pos+=v; else neg+=v;}
    posTotals.push(pos); negTotals.push(neg);
  }
  const leftRaw=extent(posTotals.concat(negTotals));
  if(!leftRaw) return '<div class="empty">no data in this range</div>';
  const left=[Math.min(0,leftRaw[0]), Math.max(0,leftRaw[1])];
  if(left[0]===left[1]){left[0]-=1;left[1]+=1;}
  const right=extent(net && net.values ? net.values : []);
  const x=i=>dates.length<2?padL+plotW/2:padL+plotW*(i/(dates.length-1));
  const yOf=(v,ext)=>{const[a,b]=ext;return padT+plotH*(1-(v-a)/(b-a));};
  const barW=Math.max(4,Math.min(30,plotW/(dates.length||1)*0.55));
  let svg=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">`;
  for(let g=0; g<=3; g++){const yy=padT+plotH*g/3; const val=left[1]-(left[1]-left[0])*g/3;
    svg+=`<line class="grid" x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}"/>`;
    svg+=`<text class="axlbl" x="${padL-6}" y="${yy+3}" text-anchor="end">${fmt(val)}</text>`;}
  if(right){for(let g=0; g<=3; g++){const yy=padT+plotH*g/3; const val=right[1]-(right[1]-right[0])*g/3;
    svg+=`<text class="axlbl" x="${W-padR+6}" y="${yy+3}" text-anchor="start">${fmt(val)}</text>`;}}
  const ticks=Math.min(5,dates.length||1);
  for(let t=0;t<ticks;t++){const i=Math.round(t*((dates.length||1)-1)/(ticks-1||1)); const dt=dates[i]||"";
    svg+=`<text class="axlbl" x="${x(i)}" y="${H-padB+16}" text-anchor="middle">${dt.slice(0,7)}</text>`;}
  const zeroY=yOf(0,left);
  svg+=`<line class="axis" x1="${padL}" y1="${zeroY}" x2="${W-padR}" y2="${zeroY}"/>`;
  for(let i=0;i<dates.length;i++){
    let posBase=0, negBase=0;
    for(const s of series){const v=s.values[i]; if(v==null || v===0)continue;
      let y0,y1;
      if(v>0){y0=yOf(posBase,left); posBase+=v; y1=yOf(posBase,left);}
      else {y0=yOf(negBase,left); negBase+=v; y1=yOf(negBase,left);}
      const y=Math.min(y0,y1), h=Math.max(1,Math.abs(y1-y0));
      svg+=`<rect x="${(x(i)-barW/2).toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" fill="${s.color}" opacity=".88"/>`;
    }
  }
  if(right && net && net.values){
    let pts="";
    for(let i=0;i<dates.length;i++){const v=net.values[i]; if(v==null)continue; pts+=`${x(i).toFixed(1)},${yOf(v,right).toFixed(1)} `;}
    if(pts.trim()) svg+=`<polyline fill="none" stroke="${net.color}" stroke-width="2.2" points="${pts.trim()}"/>`;
    for(let i=0;i<dates.length;i++){const v=net.values[i]; if(v==null)continue;
      svg+=`<circle cx="${x(i).toFixed(1)}" cy="${yOf(v,right).toFixed(1)}" r="2.5" fill="${net.color}"/>`;}
  }
  svg+="</svg>";
  const legendItems=series.concat(net?[net]:[]);
  const legend='<div class="legend">'+legendItems.map(s=>`<span class="lg"><i style="background:${s.color}"></i>${esc(s.name)}${s.axis===1?" (right)":""}</span>`).join("")+"</div>";
  return svg+legend;
}
function fmt(v){const a=Math.abs(v); if(a>=1e9)return (v/1e9).toFixed(2)+"B"; if(a>=1e6)return (v/1e6).toFixed(2)+"M"; if(a>=1e3)return (v/1e3).toFixed(1)+"k"; return (Math.round(v*100)/100).toString();}

function chartCard(title, explain){
  return `<div class="chartcard"><h2>${esc(title)}</h2><div class="chart" data-chart="${esc(title)}"></div>`
       + `<p class="explain">${esc(explain)}</p></div>`;
}

const VBW=980, PADL=58, PLOTW=864, XH_Y1=14, XH_Y2=230;

function renderCharts(){
  // ETF cash flow and commodity-equivalent exposure flow use different sign conventions.
  renderEtfChart(DASH.etf && DASH.etf.flow);
  renderEtfChart(DASH.etf && DASH.etf.exposure_flow);
  // Front-month price
  const price=clip(DASH.price,RANGE);
  setChart(DASH.price.title, price.dates, [{name:DASH.price.yLabel,color:PALETTE[0],values:price.values,axis:0}]);
  // Positioning by trader type (multi-series net)
  const cot=clipMulti(DASH.cot.dates,DASH.cot.series,RANGE);
  setChart(DASH.cot.title, cot.dates,
    cot.series.map((s,i)=>({name:s.name,color:PALETTE[i%PALETTE.length],values:s.values,axis:0})));
  // Inventory dual axis (value left, surprise right) — align on inventory dates
  const inv=clip(DASH.inventory,RANGE), sur=clip(DASH.surprise,RANGE);
  setChart("Inventory & seasonal surprise", inv.dates, [
    {name:"Inventory level",color:PALETTE[1],values:inv.values,axis:0},
    {name:"Seasonal surprise (z)",color:PALETTE[3],values:alignTo(inv.dates,sur),axis:1}]);
}
function renderEtfChart(flow){
  if(!flow || !flow.dates || !flow.dates.length) return;
  const fl=clipFlow(flow,RANGE);
  const series=fl.series.map((s,i)=>({name:s.name,color:PALETTE[i%PALETTE.length],values:s.values,axis:0}));
  const net=fl.net?{name:fl.net.name,color:"#f0f6fc",values:fl.net.values,axis:1}:null;
  setStackedFlowChart(flow.title, fl.dates, series, net);
}
function clipFlow(flow, months){
  if(!months || !flow.dates.length) return flow;
  const last=new Date(flow.dates[flow.dates.length-1]+"T00:00:00Z"); const cut=new Date(last); cut.setUTCMonth(cut.getUTCMonth()-months);
  const keep=[]; for(let i=0;i<flow.dates.length;i++) if(new Date(flow.dates[i]+"T00:00:00Z")>=cut) keep.push(i);
  return {
    ...flow,
    dates:keep.map(i=>flow.dates[i]),
    series:flow.series.map(s=>({...s,values:keep.map(i=>s.values[i])})),
    net:flow.net?{...flow.net,values:keep.map(i=>flow.net.values[i])}:null
  };
}
function clipMulti(dates, series, months){
  if(!months || !dates.length) return {dates, series};
  const last=new Date(dates[dates.length-1]+"T00:00:00Z"); const cut=new Date(last); cut.setUTCMonth(cut.getUTCMonth()-months);
  const keep=[]; for(let i=0;i<dates.length;i++) if(new Date(dates[i]+"T00:00:00Z")>=cut) keep.push(i);
  return {dates:keep.map(i=>dates[i]), series:series.map(s=>({...s,values:keep.map(i=>s.values[i])}))};
}
function alignTo(dates, series){const m=new Map(); for(let i=0;i<series.dates.length;i++)m.set(series.dates[i],series.values[i]); return dates.map(d=>m.has(d)?m.get(d):null);}
function setChart(title, dates, series){
  const el=document.querySelector(`.chart[data-chart="${cssEsc(title)}"]`); if(!el) return;
  if(!dates || !dates.length){ el.innerHTML='<div class="empty">no data in this range</div>'; el._meta=null; return; }
  el.innerHTML = chartSVG(dates, series) + '<div class="tip" style="display:none"></div>';
  el._meta = {dates, series};
  attachHover(el);
}
function setStackedFlowChart(title, dates, series, net){
  const el=document.querySelector(`.chart[data-chart="${cssEsc(title)}"]`); if(!el) return;
  if(!dates || !dates.length){ el.innerHTML='<div class="empty">no data in this range</div>'; el._meta=null; return; }
  el.innerHTML = stackedBarLineSVG(dates, series, net) + '<div class="tip" style="display:none"></div>';
  el._meta = {dates, series: net ? series.concat([net]) : series};
  attachHover(el);
}
function attachHover(el){
  const svg=el.querySelector("svg"); const tip=el.querySelector(".tip"); const meta=el._meta;
  if(!svg || !tip || !meta) return;
  svg.addEventListener("mousemove", ev=>{
    const rect=svg.getBoundingClientRect(); if(!rect.width) return;
    const n=meta.dates.length;
    const xvb=(ev.clientX-rect.left)/rect.width*VBW;
    let idx=Math.round((xvb-PADL)/PLOTW*(n<2?0:(n-1))); idx=Math.max(0,Math.min(n-1,idx));
    let rows="", any=false;
    for(const s of meta.series){ const v=s.values[idx]; if(v==null)continue; any=true;
      rows+=`<div><i style="background:${s.color}"></i>${esc(s.name)}: ${fmtFull(v)}</div>`; }
    if(!any){ tip.style.display="none"; return; }
    tip.innerHTML=`<b>${esc(meta.dates[idx])}</b>${rows}`; tip.style.display="block";
    const crect=el.getBoundingClientRect();
    let left=ev.clientX-crect.left+14; if(left>crect.width-180) left=ev.clientX-crect.left-170;
    tip.style.left=left+"px"; tip.style.top=Math.max(4,ev.clientY-crect.top+12)+"px";
    crosshair(svg, PADL+PLOTW*(n<2?0:idx/(n-1)));
  });
  svg.addEventListener("mouseleave", ()=>{ tip.style.display="none"; const l=svg.querySelector("#xhair"); if(l)l.remove(); });
}
function crosshair(svg, xvb){
  let line=svg.querySelector("#xhair");
  if(!line){ line=document.createElementNS("http://www.w3.org/2000/svg","line"); line.id="xhair";
    line.setAttribute("stroke","#56708a"); line.setAttribute("stroke-width","1"); line.setAttribute("stroke-dasharray","3 3"); svg.appendChild(line); }
  line.setAttribute("x1",xvb); line.setAttribute("x2",xvb); line.setAttribute("y1",XH_Y1); line.setAttribute("y2",XH_Y2);
}
function fmtFull(v){ return (Math.round(v*100)/100).toLocaleString(); }
function cssEsc(s){return s.replace(/"/g,'\\"');}

function render(){
  const d=DASH;
  const nav = d.commodities.map(c=>`<a href="${c.toLowerCase()}.html" class="${c===d.commodity?'on':''}">${esc(c)}</a>`).join(" ");
  const coverage = d.coverage_note ? `<div class="alert soon">${esc(d.coverage_note)}</div>` : "";
  const funds = d.funds.map(f=>`<div class="fund"><span class="tk">${esc(f.ticker)}</span>`
      +`<span class="tag">${esc(f.badge)}</span><div class="explain" style="margin-top:6px">${esc(f.strategy)}</div></div>`).join("");
  const roll = d.roll;
  const alert = `<div class="alert ${roll.level}">⏱ <b>Roll watch:</b> ${esc(roll.message)} `
      + `<span style="opacity:.8">Front-month funds (e.g. ${esc((d.funds.find(f=>f.front)||{}).ticker||'')}) sell the expiring contract and buy the next during this window; large fund AUM vs. open interest can move the front-of-curve spread.</span></div>`;
  const etf = d.etf || {rows:[],summary:[],exposure:[],flow:{series:[]},exposure_flow:{series:[]}};
  const totalAum = (etf.rows||[]).reduce((s,r)=>s+(r.latest_aum_usd||0),0);
  const totalFlow = (etf.rows||[]).reduce((s,r)=>s+(r.daily_flow_usd||0),0);
  const totalExposureFlow = (etf.rows||[]).reduce((s,r)=>s+(r.exposure_flow_usd||0),0);
  const leveragedExposureFlow = (etf.rows||[]).filter(r=>Math.abs(r.leverage||1)>1).reduce((s,r)=>s+(r.exposure_flow_usd||0),0);
  const metricCards = `<div class="metricgrid">
    <div class="metric"><div class="k">covered AUM</div><div class="v">${fmt(totalAum)}</div></div>
    <div class="metric"><div class="k">ETF cash flow</div><div class="v">${fmt(totalFlow)}</div></div>
    <div class="metric"><div class="k">${esc(d.commodity)} exposure flow</div><div class="v">${fmt(totalExposureFlow)}</div></div>
    <div class="metric"><div class="k">leveraged exposure flow</div><div class="v">${fmt(leveragedExposureFlow)}</div></div>
  </div>`;
  const healthRows = (etf.health||[]).length ? etf.health.map(r=>`<tr>`
      +`<td>${esc(r.ticker)}</td><td>${esc(r.issuer)}</td>`
      +`<td class="status status-${esc(r.status)}">${esc(r.status)}</td>`
      +`<td>${esc(r.metric_source||"")}</td><td>${esc(r.latest_metric_date||"")}</td>`
      +`<td>${esc(r.latest_holding_date||"")}</td>`
      +`<td class="num">${esc(r.holding_rows||0)}</td><td class="num">${esc(r.contract_rows||0)}</td>`
      +`<td>${esc(r.note||"")}</td></tr>`).join("")
      : `<tr><td colspan="9" class="empty">No ETF source health rows yet.</td></tr>`;
  const etfRows = (etf.rows||[]).length ? etf.rows.map(r=>`<tr>`
      +`<td>${esc(r.ticker)}</td><td>${esc(r.issuer)}</td><td>${esc(r.strategy)}</td>`
      +`<td class="num">${esc(r.leverage)}</td><td>${esc(r.latest_date||"")}</td>`
      +`<td class="num">${fmtMaybe(r.latest_aum_usd)}</td><td class="num">${fmtMaybe(r.daily_flow_usd)}</td>`
      +`<td class="num">${fmtMaybe(r.exposure_flow_usd)}</td><td class="num">${pctMaybe(r.flow_pct_aum)}</td><td class="num">${fmtMaybe(r.flow_5d_usd)}</td>`
      +`<td>${r.model_input?"yes":"no"}</td></tr>`).join("")
      : `<tr><td colspan="11" class="empty">No ETF metric snapshots yet.</td></tr>`;
  const summaryRows = (etf.summary||[]).length ? etf.summary.map(r=>`<tr>`
      +`<td>${esc(r.strategy)}</td><td>${esc(r.funds)}</td><td class="num">${esc(r.fund_count)}</td>`
      +`<td class="num">${fmtMaybe(r.aum_usd)}</td><td class="num">${fmtMaybe(r.daily_flow_usd)}</td>`
      +`<td class="num">${fmtMaybe(r.exposure_flow_usd)}</td><td class="num">${fmtMaybe(r.flow_5d_usd)}</td></tr>`).join("")
      : `<tr><td colspan="7" class="empty">No strategy summary yet.</td></tr>`;
  const exposureRows = (etf.exposure||[]).length ? etf.exposure.map(r=>`<tr>`
      +`<td>${esc(r.ticker)}</td><td>${esc(r.contract_month)}</td><td>${esc(r.holding_name)}</td>`
      +`<td class="num">${fmtMaybe(r.quantity)}</td><td class="num">${fmtMaybe(r.market_value_usd)}</td>`
      +`<td class="num">${pctMaybe((r.percent_nav||0)/100)}</td></tr>`).join("")
      : `<tr><td colspan="6" class="empty">No issuer holdings/PCF rows loaded yet.</td></tr>`;
  const newsRows = d.news.length ? d.news.map(a=>`<tr>`
      +`<td>${esc(a.published)}</td>`
      +`<td><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a></td>`
      +`<td>${esc(a.commodity)}</td><td>${esc(a.catalyst)}</td>`
      +`<td class="num">${esc(a.importance)}</td>`
      +`<td class="dir-${esc(a.direction)}">${esc(a.direction)}</td>`
      +`<td class="num">${esc(a.confidence)}</td></tr>`).join("")
      : `<tr><td colspan="7" class="empty">No classified news yet.</td></tr>`;
  const rangeBtns = [[1,"1M"],[3,"3M"],[6,"6M"],[12,"1Y"],[24,"2Y"],[null,"All"]]
      .map(([m,l])=>`<button data-m="${m}" class="${m===RANGE?'on':''}">${l}</button>`).join("");

  document.getElementById("root").innerHTML = `
    <h1>Energy price factors — ${esc(d.commodity)}</h1>
    <p class="caption">A monitoring dashboard for the drivers of energy prices (futures, ETF roll mechanics, positioning, inventories, news). Not a price forecast. Snapshot ${esc(d.as_of)} UTC.</p>
    ${coverage}
    <nav>${nav}</nav>
    <h2>ETF roll watch</h2>
    ${alert}
    <div class="rollgrid">${funds}</div>
    <p class="explain">USCF single-commodity funds publish their roll methodology; this is the standard early-month window. The alert is a heads-up that fund roll flows are imminent — it is informational, not a trade signal.</p>
    <h2>ETF flow & roll pressure</h2>
    ${metricCards}
    <h2>ETF source health</h2>
    <table><thead><tr><th>fund</th><th>issuer</th><th>status</th><th>metric source</th><th>metric date</th><th>holdings date</th><th>holding rows</th><th>contract rows</th><th>note</th></tr></thead><tbody>${healthRows}</tbody></table>
    <table><thead><tr><th>fund</th><th>issuer</th><th>strategy</th><th>lev</th><th>date</th><th>AUM</th><th>ETF cash flow</th><th>${esc(d.commodity)} exposure flow</th><th>flow/AUM</th><th>5d flow</th><th>model</th></tr></thead><tbody>${etfRows}</tbody></table>
    <table><thead><tr><th>strategy</th><th>funds</th><th>count</th><th>AUM</th><th>ETF cash flow</th><th>${esc(d.commodity)} exposure flow</th><th>5d flow</th></tr></thead><tbody>${summaryRows}</tbody></table>
    <h2>ETF exposure by contract month</h2>
    <table><thead><tr><th>fund</th><th>contract month</th><th>holding</th><th>quantity</th><th>market value</th><th>% NAV</th></tr></thead><tbody>${exposureRows}</tbody></table>
    <div class="ranges"><b>Time range (applies to all charts):</b> ${rangeBtns}</div>
    <div id="charts">
      ${etf.flow && etf.flow.series && etf.flow.series.length ? chartCard(etf.flow.title, etf.flow.explain) : ""}
      ${etf.exposure_flow && etf.exposure_flow.series && etf.exposure_flow.series.length ? chartCard(etf.exposure_flow.title, etf.exposure_flow.explain) : ""}
      ${chartCard(d.price.title, d.price.explain)}
      ${chartCard(d.cot.title, d.cot.explain)}
      ${chartCard("Inventory & seasonal surprise", "EIA inventory level (left axis) vs. its seasonal surprise — how far the latest level sits from the typical level for this time of year, in standard deviations (right axis). The two are on separate axes because their scales differ by orders of magnitude. A large positive surprise (more inventory than seasonal norm) is generally bearish for price; a negative surprise is bullish.")}
    </div>
    <h2>Latest market-moving news</h2>
    <table><thead><tr><th>published</th><th>headline (click to open)</th><th>commodity</th><th>catalyst</th><th>importance</th><th>direction</th><th>confidence</th></tr></thead><tbody>${newsRows}</tbody></table>
    <p class="explain">Headlines are pulled from free news feeds (GDELT / RSS) and classified by catalyst, directional lean and confidence. Click a headline to open the source article.</p>
    <footer>Energy ETF monitor · self-contained factor dashboard · data: issuer ETF holdings (USCF/ProShares), Yahoo Finance (futures/fallback), EIA (inventory), FRED (macro), CFTC (positioning), GDELT/RSS (news). No price forecast, no JavaScript trackers, no external assets.</footer>`;

  document.querySelectorAll(".ranges button").forEach(b=>b.addEventListener("click",()=>{
    const m=b.getAttribute("data-m"); RANGE = (m==="null"||m===null)?null:parseInt(m,10);
    document.querySelectorAll(".ranges button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
    renderCharts();
  }));
  renderCharts();
}
render();
function fmtMaybe(v){return v==null?"":fmt(Number(v));}
function pctMaybe(v){return v==null?"":(Number(v)*100).toFixed(2)+"%";}
</script></body></html>"""

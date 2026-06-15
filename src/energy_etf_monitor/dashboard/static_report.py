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
from energy_etf_monitor.dashboard.data import feature_time_series, news_panel_rows
from energy_etf_monitor.records import DailyFeatureRow, FundDailyMetric, NewsArticle
from energy_etf_monitor.storage.repository import IngestionRepository

# USCF single-commodity roll window: front-month funds roll early each month (business days ~5–9).
ROLL_WINDOW_START_BD = 5
ROLL_WINDOW_END_BD = 9

# Documented per-fund roll methodology (docs/02-etf-universe.md). `front` funds drive the roll alert.
FUNDS_BY_COMMODITY: dict[str, list[dict]] = {
    "WTI": [
        {"ticker": "USO", "front": True,
         "strategy": "Front-month CL, rolled over a multi-day window early each month "
                     "(≈ business days 5–9)."},
        {"ticker": "USL", "front": False,
         "strategy": "Laddered equally across 12 consecutive monthly CL contracts — far lower "
                     "roll concentration than USO."},
    ],
    "NATGAS": [
        {"ticker": "UNG", "front": True,
         "strategy": "Front-month NG, rolled ≈ 2 weeks before contract expiry."},
        {"ticker": "UNL", "front": False,
         "strategy": "Laddered across 12 consecutive monthly NG contracts."},
    ],
    "RBOB": [
        {"ticker": "UGA", "front": True,
         "strategy": "Front-month RB, simple monthly roll."},
    ],
}

# (chart key, feature column(s), human label, y-axis label, explanation shown under the chart)
PRICE_CHART = {
    "key": "price", "column": "cl_front_month_settlement",
    "title": "Front-month futures price",
    "yLabel": "Price",
    "explain": "The nearest-to-expiry futures settlement (from Yahoo Finance). This is the single "
               "most direct read on the commodity itself; everything else on this page is a factor "
               "that pushes it around.",
}
COT_CHART = {
    "key": "cot", "column": "cot_swap_dealer_net",
    "title": "Positioning — swap-dealer net (CFTC COT)",
    "yLabel": "Net contracts",
    "explain": "Swap dealers' net long−short position from the weekly CFTC Commitments of Traders "
               "report. Swap dealers largely intermediate index/ETF and producer-hedger flow, so a "
               "large or fast-changing net position is a proxy for crowded positioning and hedging "
               "pressure. Reported Tuesday, released Friday (lagged here accordingly).",
}
INVENTORY_VALUE = {"key": "inventory", "column": "inventory_value"}
INVENTORY_SURPRISE = {"key": "surprise", "column": "inventory_seasonal_surprise"}


def _series(feature_rows: Sequence[DailyFeatureRow], column: str) -> dict:
    ts = feature_time_series(feature_rows, (column,))
    return {
        "dates": [d.isoformat() for d in ts.dates],
        "values": [None if v is None else round(float(v), 4) for v in ts.series[column]],
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


def _flow_section(commodity: str, fund_metrics: Sequence[FundDailyMetric]) -> dict:
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


def render_dashboard_html(
    *,
    commodity: str,
    feature_rows: Sequence[DailyFeatureRow],
    news: Sequence[NewsArticle],
    as_of: datetime,
    fund_metrics: Sequence[FundDailyMetric] = (),
    commodities: Sequence[str] = tuple(COMMODITIES),
) -> str:
    """Render one commodity's factor dashboard into a self-contained interactive HTML document."""

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
        "commodities": list(commodities),
        "as_of": as_of.strftime("%Y-%m-%d %H:%M"),
        "funds": FUNDS_BY_COMMODITY.get(commodity, []),
        "roll": _roll_status(as_of.date()),
        "price": {**PRICE_CHART, **_series(feature_rows, PRICE_CHART["column"])},
        "cot": {**COT_CHART, **_series(feature_rows, COT_CHART["column"])},
        "inventory": _series(feature_rows, INVENTORY_VALUE["column"]),
        "surprise": _series(feature_rows, INVENTORY_SURPRISE["column"]),
        "flow": _flow_section(commodity, fund_metrics),
        "news": news_rows,
    }
    return _PAGE.replace("/*__DASH__*/", json.dumps(data))


def build_commodity_html(commodity: str, settings: Settings, as_of: datetime) -> str:
    config = COMMODITIES.get(commodity)
    fund = config.crowding_fund_ticker if config else None
    with IngestionRepository.from_settings(settings) as repository:
        feature_rows = repository.list_daily_feature_rows(commodity=commodity)
        news = repository.list_news_articles(as_of=as_of, limit=25)
        fund_metrics = repository.list_fund_daily_metrics(fund_ticker=fund) if fund else []
    return render_dashboard_html(
        commodity=commodity, feature_rows=feature_rows, news=news,
        as_of=as_of, fund_metrics=fund_metrics,
    )


def write_static_site(output_dir, *, settings: Settings, as_of: datetime) -> list:
    from pathlib import Path

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list = []
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
.chart svg{width:100%;height:auto;background:#10151c;border:1px solid #1c232d;border-radius:10px;display:block}
.axis{stroke:#39424d;stroke-width:1}.grid{stroke:#1a212b;stroke-width:1}
.axlbl{fill:#7d8a97;font-size:10px}
.legend{margin:6px 2px 0;color:#9aa7b4;font-size:12px}
.legend .lg{margin-right:16px;white-space:nowrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}
.empty{color:#6b7682;padding:22px 0;text-align:center}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #1c232d;vertical-align:top}
td.num{text-align:right;font-variant-numeric:tabular-nums}
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
function fmt(v){const a=Math.abs(v); if(a>=1e9)return (v/1e9).toFixed(2)+"B"; if(a>=1e6)return (v/1e6).toFixed(2)+"M"; if(a>=1e3)return (v/1e3).toFixed(1)+"k"; return (Math.round(v*100)/100).toString();}

function chartCard(title, explain){
  return `<div class="chartcard"><h2>${esc(title)}</h2><div class="chart" data-chart="${esc(title)}"></div>`
       + `<p class="explain">${esc(explain)}</p></div>`;
}

function renderCharts(){
  // ETF creation/redemption flow (going-forward; may be empty early on)
  if(DASH.flow && DASH.flow.dates && DASH.flow.dates.length){
    const fl=clip(DASH.flow,RANGE);
    setChart(DASH.flow.title, chartSVG(fl.dates,[{name:DASH.flow.yLabel,color:PALETTE[4],values:fl.values,axis:0}]));
  }
  // Price
  const price=clip(DASH.price,RANGE);
  setChart(DASH.price.title, chartSVG(price.dates,[{name:DASH.price.yLabel,color:PALETTE[0],values:price.values,axis:0}]));
  // Positioning
  const cot=clip(DASH.cot,RANGE);
  setChart(DASH.cot.title, chartSVG(cot.dates,[{name:DASH.cot.yLabel,color:PALETTE[2],values:cot.values,axis:0}]));
  // Inventory dual axis (value left, surprise right) — align on inventory dates
  const inv=clip(DASH.inventory,RANGE), sur=clip(DASH.surprise,RANGE);
  setChart("Inventory & seasonal surprise", chartSVG(inv.dates,[
    {name:"Inventory level",color:PALETTE[1],values:inv.values,axis:0},
    {name:"Seasonal surprise (z)",color:PALETTE[3],values:alignTo(inv.dates,sur),axis:1}]));
}
function alignTo(dates, series){const m=new Map(); for(let i=0;i<series.dates.length;i++)m.set(series.dates[i],series.values[i]); return dates.map(d=>m.has(d)?m.get(d):null);}
function setChart(title, svg){const el=document.querySelector(`.chart[data-chart="${cssEsc(title)}"]`); if(el)el.innerHTML=svg;}
function cssEsc(s){return s.replace(/"/g,'\\"');}

function render(){
  const d=DASH;
  const nav = d.commodities.map(c=>`<a href="${c.toLowerCase()}.html" class="${c===d.commodity?'on':''}">${esc(c)}</a>`).join(" ");
  const funds = d.funds.map(f=>`<div class="fund"><span class="tk">${esc(f.ticker)}</span>`
      +`<span class="tag">${f.front?"front-month roll":"laddered"}</span><div class="explain" style="margin-top:6px">${esc(f.strategy)}</div></div>`).join("");
  const roll = d.roll;
  const alert = `<div class="alert ${roll.level}">⏱ <b>Roll watch:</b> ${esc(roll.message)} `
      + `<span style="opacity:.8">Front-month funds (e.g. ${esc((d.funds.find(f=>f.front)||{}).ticker||'')}) sell the expiring contract and buy the next during this window; large fund AUM vs. open interest can move the front-of-curve spread.</span></div>`;
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
    <nav>${nav}</nav>
    <h2>ETF roll watch</h2>
    ${alert}
    <div class="rollgrid">${funds}</div>
    <p class="explain">USCF single-commodity funds publish their roll methodology; this is the standard early-month window. The alert is a heads-up that fund roll flows are imminent — it is informational, not a trade signal.</p>
    <div class="ranges"><b>Time range (applies to all charts):</b> ${rangeBtns}</div>
    <div id="charts">
      ${d.flow && d.flow.fund ? chartCard(d.flow.title, d.flow.explain) : ""}
      ${chartCard(d.price.title, d.price.explain)}
      ${chartCard(d.cot.title, d.cot.explain)}
      ${chartCard("Inventory & seasonal surprise", "EIA inventory level (left axis) vs. its seasonal surprise — how far the latest level sits from the typical level for this time of year, in standard deviations (right axis). The two are on separate axes because their scales differ by orders of magnitude. A large positive surprise (more inventory than seasonal norm) is generally bearish for price; a negative surprise is bullish.")}
    </div>
    <h2>Latest market-moving news</h2>
    <table><thead><tr><th>published</th><th>headline (click to open)</th><th>commodity</th><th>catalyst</th><th>importance</th><th>direction</th><th>confidence</th></tr></thead><tbody>${newsRows}</tbody></table>
    <p class="explain">Headlines are pulled from free news feeds (GDELT / RSS) and classified by catalyst, directional lean and confidence. Click a headline to open the source article.</p>
    <footer>Energy ETF monitor · self-contained factor dashboard · data: Yahoo Finance (futures), EIA (inventory), FRED (macro), CFTC (positioning), GDELT/RSS (news). No price forecast, no JavaScript trackers, no external assets.</footer>`;

  document.querySelectorAll(".ranges button").forEach(b=>b.addEventListener("click",()=>{
    const m=b.getAttribute("data-m"); RANGE = (m==="null"||m===null)?null:parseInt(m,10);
    document.querySelectorAll(".ranges button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
    renderCharts();
  }));
  renderCharts();
}
render();
</script></body></html>"""

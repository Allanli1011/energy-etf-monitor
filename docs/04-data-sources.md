# 04 - Data Sources

A free backbone is enough for the non-model monitoring MVP. Paid sources remain upgrade slots.

## Free Backbone

| Data | Source | Access | Cadence |
|---|---|---|---|
| Crude / product / Cushing inventory | EIA Open Data API v2 | `https://api.eia.gov/v2/...`; key series include `WCESTUS1`, `WCRSTUS1`, `WCSSTUS1`, `W_EPC0_SAX_YCUOK_MBBL` | Weekly |
| Natural gas storage | EIA Weekly NatGas Storage | `NG.NW2_EPG0_SWO_R48_BCF.W` and regional series | Weekly |
| Macro | FRED API | `DTWEXBGS`, `DFII10`, `DCOILWTICO`, `GASREGW` | Daily / weekly |
| Positioning | CFTC Socrata API | Disaggregated Futures-Only `72hh-3qpy` plus commodity filters, including Brent Last Day `06765T` | Weekly, T+3 |
| Futures curve | Yahoo Finance futures feed | CL, NG, RB, and BZ listed month snapshots where available | Daily |
| USCF ETF NAV, shares, creation/redemption, holdings | USCF public holdings stack via ALPS MarketingAPI | Fetch `api_key.php` from USCF, then call `dailyprice/{ticker}` and `holding/{ticker}/full` with the bearer token | Daily, T+1 |
| ProShares ETF NAV, shares, holdings | ProShares official fund pages | `UCO`, `SCO`, `BOIL`, `KOLD` HTML pages with price/snapshot blocks and holdings tables | Daily, T+1 |
| WisdomTree ETP NAV, shares, AUM | WisdomTree Europe fund-list download API | `fundlist/data` JSON behind the Products page/download; select same-name USD listings for Brent, WTI, and NatGas ETPs | Daily |
| ETF fallback AUM/price context | Yahoo Finance quote summary | Explicit fallback/cross-check for products without issuer/fund-list metrics | Daily |
| News / sentiment | GDELT 2.0 DOC API, RSS, optional Marketaux | Free headline/event ingestion and rule-based classification | Intraday |
| Sector flow context | ICI weekly ETF net issuance | Commodity ETFs as one aggregate bucket | Weekly |

## ETF Flow

For USCF funds, use the official `dailyprice` `cr` field when available:

```text
flow_usd = created_or_redeemed_shares * nav_per_share
```

For sources that do not expose creation/redemption shares, use the fallback:

```text
flow_usd = (shares_outstanding[t] - shares_outstanding[t-1]) * nav_per_share[t]
```

Both are net flow proxies. Intraday authorized-participant activity and gross creates/redeems are
not public.

## USCF API Notes

The public USCF holdings pages load data client-side:

- token/base URL: `https://www.uscfinvestments.com/site-template/assets/javascript/api_key.php`
- daily metrics: `https://secure.alpsinc.com/MarketingAPI/api/v1/dailyprice/{ticker}`
- holdings: `https://secure.alpsinc.com/MarketingAPI/api/v1/holding/{ticker}/full`

Do not hardcode the bearer token; fetch `api_key.php` on each run. Save raw JSON before parsing so
format changes can be replayed.

## ProShares Page Notes

The ProShares leveraged/inverse energy pages render the relevant data directly in HTML:

- `https://www.proshares.com/our-etfs/leveraged-and-inverse/uco`
- `https://www.proshares.com/our-etfs/leveraged-and-inverse/sco`
- `https://www.proshares.com/our-etfs/leveraged-and-inverse/boil`
- `https://www.proshares.com/our-etfs/leveraged-and-inverse/kold`

The connector saves the raw HTML and parses the price as-of date, NAV, net assets, and holdings
table. ProShares does not expose daily gross creation/redemption units on these pages, so flow is
derived from same-source shares outstanding deltas.

## WisdomTree Notes

WisdomTree Europe product lists load a DataSpan-backed JSON endpoint:

- product-list page: `https://www.wisdomtree.eu/products?assetClass=Commodities&structure=ETPs&productType=Short%20and%20Leveraged`
- product-list JSON: `https://dataspanapi.wisdomtree.com/fundlist/data/`
- downloadable Excel: `https://dataspanapi.wisdomtree.com/fundlist/excel`

Rows include `AUM`, `AUMusd`, `NAV`, `NAVusd`, `SharesOutstanding`, `NAV_Date`,
`AUM_DateTime`, `exchangeTicker`, `fundCurrency`, `baseCCY`, and `listingCCY`. Because each
product can have multiple listing currencies, the connector only accepts rows where
`exchangeTicker` equals the dashboard ticker and `fundCurrency`, `baseCCY`, and `listingCCY` are
all `USD`.

The current WisdomTree fund-list endpoint is Cloudflare-protected for plain script HTTP clients.
The nightly pipeline attempts it first and then uses Yahoo fallback snapshots where configured.
The separate `funddetails/nav` API shape is known to include `nav`, `sharesOutstanding`, and `aum`,
but it requires an `x-wt-dataspan-key`, so it remains disabled as a keyed connector.

## Paid Upgrade Slots

| Need | Source | Tier |
|---|---|---|
| Brent / gasoil full curve | ICE end-of-day packages | Paid |
| Full multi-year historical curve | CME DataMine, Barchart OnDemand, Refinitiv/Bloomberg | Paid |
| API weekly inventory | American Petroleum Institute | Subscription |
| Consensus inventory surprise | Bloomberg / Reuters surveys | Enterprise |
| Physical flows / tank levels | Vortexa, Kpler, Genscape, ClipperData | Enterprise |
| Enterprise news sentiment | RavenPack / Bloomberg | Enterprise |

## Verified Gotchas

- CFTC `Swap Dealers` is aggregate; it cannot isolate one ETF's position.
- USCF current public endpoints expose latest holdings, not a clean historical holdings archive.
  Going-forward raw JSON capture is therefore important.
- Yahoo ETF metric data is a fallback estimate and should not override official issuer data.
- WisdomTree fund-list rows are official product-list data but may be blocked for non-browser
  clients; keep Yahoo fallback enabled and prefer `wisdomtree_fundlist` when both sources exist.
- Yahoo Brent futures data is useful for free dashboard context, but it is not the exchange-official
  ICE end-of-day settlement package.
- ETF.com and ETFDB fund-flow pages are unreliable for automated free ingestion; prefer issuer
  primaries or paid APIs.
- EIA release timing shifts on federal-holiday weeks; release calendars should become explicit
  source metadata before stricter freshness checks.

## Free API Keys

- EIA: `https://www.eia.gov/opendata/`
- FRED: `https://fred.stlouisfed.org/docs/api/fred`
- CFTC Socrata: optional app token for production reliability
- Marketaux: optional free-tier key

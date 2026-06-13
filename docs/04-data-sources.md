# 04 — Data sources

A free backbone is enough to run the entire MVP. Paid sources are upgrade slots, added only when a
specific need justifies them.

## Free backbone

| Data | Source | Access | Cadence |
|---|---|---|---|
| Crude / product / Cushing inventory | EIA Open Data API v2 (free key) | `https://api.eia.gov/v2/...`; legacy series via `/v2/seriesid/{ID}`. Series e.g. `WCESTUS1` (US crude ex-SPR), `WCRSTUS1` (incl. SPR), `WCSSTUS1` (SPR), `W_EPC0_SAX_YCUOK_MBBL` (Cushing) | Wed 10:30 ET |
| Natural gas storage | EIA Weekly NatGas Storage | `NG.NW2_EPG0_SWO_R48_BCF.W` (Lower-48) + regional; also `ir.eia.gov/ngs/wngsr.json` | Thu 10:30 ET |
| Macro (USD, real yields, WTI spot, retail gasoline) | FRED API (free key) | `https://api.stlouisfed.org/fred/series/data?series_id=ID`. `DTWEXBGS` (broad USD), `DFII10` (10Y real yield), `DCOILWTICO` (WTI spot), `GASREGW` (retail gasoline) | daily / weekly |
| Positioning (COT) | CFTC Socrata API | `https://publicreporting.cftc.gov/resource/{id}.json` with SoQL (`$where`, `$order`, `$limit`). Datasets: Disaggregated Futures-Only `72hh-3qpy` (verified live, returns 2026-06-09), Disaggregated Combined `kh3c-gbw2`, Legacy `6dca-aqww`/`jun7-fc8e`, TFF `gpe5-46if`/`yw9f-hn96`, Supplemental/CIT `4zgm-a668` | Fri 15:30 ET, T+3 |
| Futures curve | CME settlement pages (free web) + EIA Contracts 1–4 | CME per-product `*.settlements.html` for CL/NG/RB/HO across listed months; EIA gives M1–M4 | daily |
| ETF holdings / roll state | USCF daily PCF files | `uscfinvestments.com` per-fund holdings pages (CSV/XLS) — exact contract months held, shares outstanding, NAV | T+1 |
| News / sentiment | GDELT 2.0 DOC API (free); Marketaux free tier (100 req/day) | `api.gdeltproject.org/api/v2/doc/doc?query=...` (15-min, tone + article count); `marketaux.com` (entity-level sentiment) | 15-min / real-time (rate-limited) |
| Sector flow context | ICI weekly ETF net issuance | `ici.org/research/statistics/etfs/weekly-estimated-etf-net-issuance` (Commodity ETFs as one bucket) | weekly |
| Index roll schedules | S&P GSCI methodology PDF (BD 5–9); BCOM methodology PDF (BD 6–10) | `spglobal.com/spdji` and `assets.bbhub.io` | as amended |

### Fund-flow proxy
There is no free single "fund flow" metric. Compute it as
`(shares_outstanding[t] - shares_outstanding[t-1]) x NAV` from the issuer's daily PCF (T+1). This
conflates gross creations and redemptions into one net number — that's the best available.

## Paid upgrade slots (add only when justified)

| Need | Source | Tier |
|---|---|---|
| Brent / Gasoil full curve | ICE End-of-Day report packages | paid |
| Full multi-year historical curve (all months) | CME DataMine, Barchart OnDemand (~$500/mo + exchange fees), Refinitiv/Bloomberg | paid |
| API weekly inventory (Tue, the EIA-vs-API divergence trade) | American Petroleum Institute (subscription; circulates via wires) | paid |
| True Street consensus for inventory "surprise" | Bloomberg / Reuters survey medians | enterprise |
| Physical flows / tanker tracking / Cushing tank levels | Vortexa, Kpler, Genscape (Wood Mackenzie), ClipperData | enterprise |
| Enterprise news sentiment | RavenPack / Bloomberg | enterprise |
| Petrochemical price/inventory | ICIS, Argus, S&P Global (Platts); China: SCI99, Longzhong, CCF | paid |
| Global oil balances | JODI-Oil (free bulk download; API only via paid ICE Connect); OPEC MOMR (free PDF, no API); IEA OMR (paid) | mixed |

## Verified gotchas

- **CFTC `Swap Dealers` is aggregate** — you cannot isolate one ETF's position; T+3 stale at
  release.
- **`CHRIS/CME_*` Nasdaq Data Link continuous futures** (an old free favorite) has ambiguous /
  likely-paywalled status in 2026 — test a live call before relying on it.
- **EIA legacy dnav futures series** (`PET_PRI_FUT_*`) reportedly stopped updating ~April 2024 —
  confirm the EIA API v2 endpoint is the live replacement.
- **etf.com / etfdb.com fund-flow pages return HTTP 403** to automated fetchers — likely
  login-walled; use issuer primaries or a paid API.
- **No free 3-2-1 crack spread or Baltic Dry series in FRED** — derive crack from CME RBOB/ULSD/WTI
  futures; BDI from the Baltic Exchange / aggregators.
- **China manufacturing PMI is not in FRED** under a clean series ID — use NBS / Caixin releases.
- **EIA release timing shifts a day** on weeks with a Monday federal holiday — check the calendar,
  don't hardcode the weekday.
- **CME bulk/programmatic VOI** (open interest by contract) requires a data license; the free web
  CSVs are manual. ICE has no free programmatic VOI equivalent.

## Free API keys to obtain

- EIA: `https://www.eia.gov/opendata/` (register)
- FRED: `https://fred.stlouisfed.org/docs/api/fred` (register)
- CFTC Socrata: no key needed for low volume; register an app token for production reliability.
- Marketaux: free tier key at `marketaux.com`.

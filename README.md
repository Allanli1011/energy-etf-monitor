# energy-etf-monitor

Monitoring system for **futures-based energy commodity ETFs** (US & European markets) — tracking
fund flows, holdings, and roll strategy to produce **probabilistic directional tilt signals** on
the underlying futures price and, primarily, the **calendar (roll) spread**.

> This repository currently holds the **design plan**. No application code yet — see
> [docs/06-roadmap.md](docs/06-roadmap.md) for the build sequence. The WTI vertical slice is the
> first milestone.

## What this is (and is not)

This is a **monitoring dashboard that emits probabilistic directional tilts**, with SHAP-driver
explanations shown alongside a naive-persistence baseline. It is **not a price oracle**. Every
predictive signal in scope (inventory surprise, COT positioning, carry / term structure,
roll front-running) is — per the academic literature surveyed — weak, low-frequency, and
regime-dependent. The honest, load-bearing framing is in
[docs/01-overview-and-constraints.md](docs/01-overview-and-constraints.md).

The single best shot at a real, structural edge is the **roll/calendar-spread model**, not the
outright price model. See [docs/05-prediction-methodology.md](docs/05-prediction-methodology.md).

## Three hard facts that shape the whole design

1. **Energy is viable; "chemicals" is essentially an empty set in Western markets.** PP, PVC,
   methanol, PTA, ethylene futures trade liquidly only on Chinese exchanges (Zhengzhou / Dalian)
   and have **no US- or UCITS-listed ETF/ETC wrapper**. Chemicals are out of scope permanently.
2. **"Fund flows" are a daily proxy, not true creation/redemption.** Intraday create/redeem and
   the identity of Authorized Participants are never public. The usable proxy is daily
   `shares_outstanding` delta x NAV (T+1). COT positioning lumps all index/ETF exposure into an
   aggregate `Swap Dealers` bucket (cannot isolate one ETF) and is published T+3.
3. **Publication lag is a hard correctness constraint.** COT is T+3, ETF holdings T+1, EIA
   inventory same-day-after-release. Every table carries both `report_date` and `knowledge_date`;
   models may only use data whose `knowledge_date` has arrived. Getting this wrong makes the
   backtest lie.

## Architecture at a glance

Nightly batch pipeline (matched to low-frequency data), single machine, mostly-free data:

```
free sources -> idempotent connectors -> PostgreSQL (dual timestamps) -> features ->
  { price-direction model | roll-spread model }  (LightGBM) -> Streamlit dashboard + alerts
```

See [docs/03-architecture.md](docs/03-architecture.md) and
[docs/architecture.svg](docs/architecture.svg).

## Docs

| Doc | Contents |
|---|---|
| [01-overview-and-constraints](docs/01-overview-and-constraints.md) | Mission, the three hard facts, red lines, honest expectations |
| [02-etf-universe](docs/02-etf-universe.md) | Verified universe of futures-based energy ETFs/ETCs (US + EU) |
| [03-architecture](docs/03-architecture.md) | Layers, recommended stack, what is explicitly out of scope |
| [04-data-sources](docs/04-data-sources.md) | Free backbone + paid upgrade slots, with API endpoints / series IDs |
| [05-prediction-methodology](docs/05-prediction-methodology.md) | Two model heads, feature engineering, evidence, caveats |
| [06-roadmap](docs/06-roadmap.md) | Phased build (WTI end-to-end first), then horizontal expansion |

## Status

Design synced. Implementation not started. Target stack: Python 3.12, PostgreSQL 16, LightGBM,
Streamlit — all free / self-hostable.

# 01 — Overview, constraints, and honest expectations

## Mission

Monitor the footprint of futures-based energy commodity ETFs (the "smart money" vehicles) — their
fund flows, holdings, and roll behavior — to anticipate, over a short horizon:

- the direction of the **underlying futures price**, and
- the direction of the **roll / calendar spread** (M1–M2 and beyond).

Augment with physical inventory data, macro fundamentals, and news/sentiment.

## The three hard facts (these reshape the original idea)

### 1. Energy is viable; "chemicals" is an empty set in Western markets

PP, PVC, methanol, PTA, and ethylene futures trade liquidly **only on Chinese exchanges**
(Zhengzhou Commodity Exchange, Dalian Commodity Exchange). CME lists thinly-traded `PCW`
petrochemical swap-futures (PP / PGP / HDPE) and ICE lists cash-settled Asia ethylene futures, but
these are commercial-hedger instruments with open interest often in the single/low-triple digits
and **zero ETF wrappers**. The only "energy & chemicals futures index" fund is a China-onshore
A-share product (CCB Principal) inaccessible to US/EU investors and not UCITS-compliant.

**Conclusion:** there is **no US-listed or UCITS-domiciled ETF/ETC** providing exposure to PP /
PVC / methanol / ethylene / PTA. Designing around a "chemical ETF" is designing around a phantom.
Chemicals are out of scope permanently. (A genuine chemicals project would be a separate effort
built on Chinese onshore futures + Chinese-language paid inventory data — SCI99 / Longzhong / CCF.)

### 2. "Fund flows" are a daily proxy, not true creation/redemption

- True intraday creation/redemption units and the identity of the Authorized Participants are
  **never public**.
- The usable proxy is the daily change in `shares_outstanding` x NAV (T+1), from issuer files.
- Holdings and roll state come from each issuer's daily PCF (Portfolio Composition File).
- In CFTC COT data, all index/ETF/swap exposure is lumped into an aggregate `Swap Dealers` bucket
  — you **cannot isolate a single ETF's position** — and the data is published **T+3** (Tuesday
  positions released the following Friday 15:30 ET).

### 3. Publication lag is a hard correctness constraint

| Data | Lag at decision time |
|---|---|
| CFTC COT | T+3 (Tue close, Fri 15:30 ET release) |
| ETF holdings (PCF) | T+1 |
| EIA inventory | same-day, but only after the 10:30 ET release |

**Every table carries two timestamps:** `report_date` (when the event happened) and
`knowledge_date` (when it could first have been known). Models may only consume rows whose
`knowledge_date` has arrived. This is the single most important correctness rule — violating it
produces a look-ahead-biased backtest that looks great and fails live.

## What this system is

A **monitoring dashboard that emits probabilistic directional tilts**, each accompanied by a
SHAP top-3-driver explanation and shown next to a naive-persistence baseline so the dashboard
always reveals whether the model is adding value. **Not a price oracle.**

The roll/calendar-spread model is the most defensible source of edge (theory of storage + the
mechanical, calendar-scheduled ETF roll). The outright price model is harder and lower-confidence.

## Honest expectations (all from the literature survey)

- **COT → price predictability is contested.** Singleton (2014) found it in 2006–2010 oil;
  Sanders & Irwin (2014) and Hamilton & Wu (2015) could not replicate. Treat COT features as a
  hypothesis to be falsified by the model-health page — drop them if they don't beat baseline.
- **Front-running the roll (Mou 2010, Sharpe up to 4.39) has likely decayed/become crowded.**
  Major indices randomized/staggered roll windows specifically to reduce exploitability. Treat
  the roll-window feature as one input, not guaranteed alpha.
- **Inventory surprise is intraday and short-lived.** A daily batch only captures post-
  announcement drift (small), not the 10:30 ET jump.
- **The USO-2020 episode is an extreme, threshold-dependent tail event** (AUM became a large
  fraction of front-month OI). Handle it as a rule-based crowding alert (AUM/OI > threshold), not
  a smooth daily signal.
- **Sample is thin** (COT disaggregated since 2006, ETF flows since ~2006) — at most ~1,000 weekly
  observations. Cross-commodity pooling + strict walk-forward validation are mandatory to avoid
  overfitting.
- **Any discovered edge decays** (~8% annualized per 1-SD increase in a crowding metric). The
  model-health / decay monitor is the trigger to stop trusting the model — it is required, not
  polish.

## Red lines

1. **No phantom chemical scope.** Do not add an `asset_class='chemical'` placeholder that implies
   a roadmap.
2. **Do not trust third-party aggregator AUM** (e.g. `USCI` reported as both ~$197M and ~$288M on
   the same date). Source AUM from the issuer's own PCF/fact sheet.
3. **The CME curve scraper is the most fragile component** — keep it behind a swappable
   curve-provider interface so it can be replaced by CME DataMine / Barchart later.
4. **Transaction costs are flow-conditional** — costs/bid-ask widen exactly when ETF flows are
   large and the roll signal is strongest. Never use static cost assumptions in a backtest P&L.

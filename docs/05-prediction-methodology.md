# 05 — Prediction methodology

Two related supervised models per commodity, trained on a pooled cross-commodity panel
(commodity-id as a categorical) for sample size, with strict expanding-window walk-forward
(monthly retrain) and point-in-time data (respecting all publication lags).

## Head A — roll / calendar-spread model (the main edge)

**Target:** N-day-forward change in the M1–M2 spread (roll yield), binarized (or magnitude via
quantile regression).

**Why this is the best shot at edge:** it rests on two structural mechanisms rather than weak
statistical correlation.

1. **Theory of storage.** Low inventory at the WTI delivery hub (Cushing) → high convenience
   yield → backwardation; high/rising inventory → contango. So the **Cushing stock-to-capacity
   ratio** is a more direct predictor of the WTI front spread than of flat price. (NatGas: Lower-48
   storage vs 5-year norm.)
2. **Mechanical, calendar-scheduled ETF/index roll.** `USO`-style front-month funds and the major
   indices roll on documented schedules (GSCI business days 5–9; BCOM 6–10; USO's multi-day
   window). Mou (2010), "Front-Running the Goldman Roll," documented exploitable price impact on
   the calendar spread.

**Features:**
- Cushing stock-to-capacity ratio (primary); NatGas storage vs 5y norm.
- `roll_window_flag` — binary/ramping during each fund's documented roll window.
- `AUM_to_OI` — fund contracts held (from PCF) / CME open interest for that month — a
  crowding/impact magnitude. Interaction term `roll_window_flag * AUM_to_OI` lets trees learn a
  threshold effect (the `USO`-2020 nonlinearity).
- Curve curvature (M2–M3, M3–M6) as additional theory-of-storage signal.
- Swap-dealer net position + its COT index.

## Head B — price-direction model (harder, lower confidence)

**Target:** N-day-forward log return of the front-month settle, binarized (or tertile up/flat/down).

**Features:**
- **Carry / term structure:** log(M2/M1), log(M3/M1), log(M12/M1), curve slope, curvature
  (Gorton-Rouwenhorst, Erb-Harvey carry factor).
- **Inventory surprise** = actual − consensus. Consensus proxied by a trailing-seasonal EWMA of
  prior surprises (true Bloomberg consensus is not free). Separate features for total US crude,
  Cushing, and NatGas. Honest framing: a daily model captures post-announcement drift only.
- **COT positioning** as a contrarian risk-overlay: Managed Money / Swap Dealer net positions
  z-scored vs a trailing 156-week window (Williams COT Index), **strictly lagged to
  `report_date + 3 business days`**. Extreme percentiles (>90 / <10) tilt toward mean reversion;
  mid-range lets carry/momentum dominate.
- **Macro:** `DTWEXBGS` (USD) daily change, `DFII10` (real yields) daily change.
- **Sentiment:** GDELT tone / article-count z-score, 2-day lag.

## Output and evaluation

- Each commodity each day: `P(price up over next 5 trading days)`, `P(spread widens over next 5
  days)`, each with a SHAP top-3-driver explanation.
- **Always displayed next to a naive-persistence baseline.** The ML model must beat it
  out-of-sample or the Model-Health page flags it as not adding value.
- A simple carry baseline (sign of M1–M2 spread) is the benchmark for the price head.

## Mandatory correctness discipline

- **Dual timestamps everywhere** (`report_date` + `knowledge_date`); models consume only rows
  whose `knowledge_date` has arrived. COT lagged 3 business days, holdings T+1, EIA after release.
- **Walk-forward**, expanding window, retrain monthly; evaluate across 2008 GFC / 2014–16 crash /
  2020 COVID-negative / 2021–22 inflation regimes.
- **Flow-conditional transaction costs** in any P&L — costs scale with the same crowding the model
  exploits.
- **Decay monitoring** — rolling information coefficient / Brier vs baseline; sustained
  degradation (the literature cites ~8% annualized per 1-SD crowding increase) triggers a
  retrain-and-review, not silent rot.

## Evidence base (key references)

- Mou (2010), *Limits to Arbitrage and Commodity Index Investment: Front-Running the Goldman Roll*
  (SSRN 1716841; CFTC `plstudy_33_yu.pdf`).
- Gorton & Rouwenhorst (2006), *Facts and Fantasies about Commodity Futures* (NBER w10595); 10-yr
  update Bhardwaj/Gorton/Rouwenhorst (2015, NBER w21243).
- Erb & Harvey (2006), *The Tactical and Strategic Value of Commodity Futures* (NBER w11222).
- Ye & Karali (2016) and Karali/Ye/Ramirez (2019) — inventory-surprise event studies.
- Singleton (2014) vs Sanders & Irwin (2014) / Hamilton & Wu (2015) — the positioning-
  predictability debate (treat COT signals as fragile / regime-dependent).

> All of these signals are individually weak (a few percent of annual return at best, often
> economically marginal after costs). They are tilts/overlays on a carry base, not standalone
> alpha. See [01-overview-and-constraints.md](01-overview-and-constraints.md).

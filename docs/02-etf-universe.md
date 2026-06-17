# 02 — ETF / ETC universe (verified)

The monitorable universe of **futures-based** energy commodity products. Equity-based energy
sector funds (e.g. `GUSH` / `DRIP`, which hold E&P company stock/swaps) are explicitly excluded —
they do not hold commodity futures.

> AUM figures below are approximate / directional (correct order of magnitude). They move
> materially with commodity prices and flows, and third-party aggregators are often stale or
> inconsistent. **Always re-pull from the issuer's own fact sheet / PCF for current figures.**

## Key insight: only US commodity pools let you "see the roll"

| Market | Structure | Can you observe the underlying futures roll? |
|---|---|---|
| US single-commodity & broad (commodity pools) | Hold **actual NYMEX/ICE futures** directly | **Yes** — daily PCF discloses exact contract months |
| US leveraged/inverse | **Futures + total-return swaps** mix | Partial — swap leg is opaque |
| European UCITS ETCs/ETFs | **Swap-based synthetic replication** (UCITS rules forbid undiversified direct futures) | **No** — only NAV/AUM visible, not underlying futures |

**Therefore the core monitoring targets are the US commodity pools.** European UCITS products are
a secondary "sentiment layer" (NAV/AUM changes only).

## US — single-commodity, direct futures holders (USCF family)

| Ticker | Underlying | Roll methodology | Notes |
|---|---|---|---|
| `USO` | WTI (CL) | Front-month, rolled over a multi-day window early each month | 1933-Act commodity pool (K-1). Post-2020 prospectus permits laddered multi-month + swaps when futures access is constrained |
| `USL` | WTI (CL) | Laddered across 12 consecutive monthly contracts (equal weight) | Lower roll concentration than USO |
| `UNG` | Henry Hub NatGas (NG) | Front-month, rolled ~2 weeks before expiry | |
| `UNL` | Henry Hub NatGas (NG) | Laddered 12 consecutive monthly contracts | |
| `UGA` | RBOB gasoline (RB) | Front-month monthly roll | |
| `BNO` | ICE Brent | Front-month monthly roll | |

### The USO 2020 episode (a structural lesson, not a daily signal)

On 2020-04-20 (negative WTI), `USO`'s FCMs imposed position limits; USO could no longer hold its
benchmark in the front month. It filed 8-Ks (Apr 24–28, 2020) disclosing a forced shift to a
multi-month ladder (~20% Jun / 40% Jul / 20% Aug / 20% Sep at one point), did a 1-for-8 reverse
split (Apr 28), and the SEC later issued an enforcement order (2021, Release 33-11006). This
demonstrates that **ETF-driven roll flows can sharply move the front-of-curve spread when fund AUM
is large relative to open interest** — a nonlinear, threshold-dependent "size matters" effect.

## US — optimized-roll single-commodity

| Ticker | Underlying | Methodology |
|---|---|---|
| `OILK` | WTI | "Optimized yield" roll; '40-Act fund (1099, no K-1) |

## US — broad commodity (energy-heavy)

| Ticker | Index / methodology | Energy weight |
|---|---|---|
| `GSG` | S&P GSCI Total Return; standard GSCI roll (business days 5–9) | ~70% |
| `DBC` | DBIQ Optimum Yield Diversified (K-1) | ~ |
| `PDBC` | DBIQ Optimum Yield Diversified (no K-1/1099) — largest in category (~$6B) | ~ |
| `BCI` | Bloomberg Commodity Broad Strategy (dynamic roll, no K-1) | ~30% (BCOM) |
| `COMT` | S&P GSCI Dynamic Roll Strategy | ~ |
| `USCI` | SummerHaven Dynamic Commodity Index — monthly reformulated from 27→14 contracts via backwardation screen | ~ |

## US — leveraged / inverse (futures + swaps)

| Ticker | Exposure | Underlying index |
|---|---|---|
| `BOIL` / `KOLD` | +2x / -2x NatGas | Bloomberg Natural Gas Subindex (near-month, rolls every other month) |
| `UCO` / `SCO` | +2x / -2x WTI | Bloomberg Commodity Balanced WTI Crude Oil Index |

Counterparties seen for the swap legs include Goldman Sachs, Societe Generale. K-1 commodity pools.

## Europe — UCITS (all swap-based; holdings opaque)

| Product | Tracks | Structure |
|---|---|---|
| WisdomTree Brent Crude Oil (`BRNT`) | Brent crude futures total-return exposure | Fully-collateralised swap-based ETC |
| WisdomTree Brent Crude Oil 1x Daily Short (`SBRT`) | -1x daily Brent crude futures exposure | Fully-collateralised swap-based ETP |
| WisdomTree Brent Crude Oil 2x Daily Leveraged (`LBRT` / `2BRT`) | +2x daily Brent crude futures exposure | Fully-collateralised swap-based ETP |
| WisdomTree Brent Crude Oil 3x Daily Leveraged (`3BRL`) | +3x daily Brent crude futures exposure | Fully-collateralised swap-based ETP |
| WisdomTree Brent Crude Oil 3x Daily Short (`3BRS`) | -3x daily Brent crude futures exposure | Fully-collateralised swap-based ETP |
| WisdomTree WTI / Natural Gas ETCs (+ leveraged / inverse variants) | Bloomberg single-commodity subindices (e.g. `BCLMT4T` WTI, `BCOMNG4T` NatGas) | Fully-collateralised swap-based ETC |
| iShares Diversified Commodity Swap UCITS ETF (+ Enhanced Roll Yield) | Bloomberg Commodity (Total Return) Index | Synthetic swap |
| L&G All Commodities UCITS ETF | Bloomberg Commodity Index | Synthetic swap |
| Invesco Bloomberg Commodity UCITS ETF | Bloomberg Commodity Index | Synthetic swap |

Roll schedules for these live in the **Bloomberg index methodology** documents, not the ETC itself.
They are visible on the Brent dashboard as ETF/ETP flow and AUM context; unlike USCF commodity
pools, their underlying futures/swap legs are not transparent daily PCF rows.

## Chemicals — confirmed: no Western ETF wrapper exists

CME `PCW` (PP / PGP / HDPE) swap-futures and ICE Asia ethylene futures are illiquid commercial-
hedger contracts with no fund wrapper. Methanol / PTA liquidity is concentrated on Zhengzhou /
Dalian. There is **no US-listed or UCITS-domiciled ETF/ETC** for any of these. Out of scope.

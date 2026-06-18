# 01 - Overview, Constraints, And Expectations

## Mission

Monitor the footprint of futures-based energy commodity ETFs: fund flows, issuer holdings, roll
behavior, contract-month exposure, and related futures-market context. The current system is a
data and dashboard product, not a predictive-model product.

The practical questions are:

- where did ETF creation/redemption pressure appear;
- which contract months are ETF portfolios actually holding;
- whether front-month roll funds are concentrated in a vulnerable part of the curve;
- how COT positioning, inventories, macro data, and news frame the current market state.

## The Three Hard Facts

### 1. Energy Is Viable; Chemicals Are Not

PP, PVC, methanol, PTA, and ethylene futures are concentrated on Chinese exchanges or thin
commercial-hedger venues. There is no useful US-listed or UCITS-domiciled ETF/ETC wrapper for a
Western chemicals ETF monitor.

Conclusion: chemicals remain out of scope.

### 2. ETF Flow Is Still A Proxy

True intraday creation/redemption units and authorized-participant identities are not public.

For USCF funds, the public dailyprice endpoint exposes a daily `cr` field that can be converted to
net flow as:

```text
cr * NAV
```

For sources without `cr`, the fallback proxy is:

```text
(shares_outstanding[t] - shares_outstanding[t-1]) * NAV[t]
```

Both are net proxies, not gross AP activity.

### 3. Publication Lag Is A Hard Correctness Constraint

| Data | Lag at decision time |
|---|---|
| CFTC / ICE COT | T+3 |
| ETF holdings | Usually T+1 |
| EIA inventory | Same day, only after release time |

Every table carries `report_date` and `knowledge_date`. This matters for dashboards too: a
monitoring view should not silently use data that was not public yet at the selected timestamp.

## What This System Is

A data-first monitoring pipeline and dashboard:

- official ETF dailyprice/NAV/share and holdings ingestion from USCF and ProShares;
- Yahoo ETF metric ingestion only for explicit cross-checks;
- futures curves, inventory, macro, COT, and news ingestion;
- point-in-time factor rows;
- Streamlit and static HTML dashboards;
- optional rule-based alerts.

Prediction-model training and inference are out of the primary product path. Legacy modeling code
is retained as research context, but it should not drive current workflows or documentation.

## Expectations

- ETF-driven roll pressure can matter most when fund AUM is large relative to open interest, but it
  is episodic rather than a smooth daily signal.
- COT positioning is useful context, not single-ETF positioning. The `Swap Dealers` bucket is
  aggregate.
- Inventory surprises are timing-sensitive; a daily monitor captures state and post-release
  context, not the initial intraday jump.
- Historical ETF holdings are hard. Current issuer endpoints are mostly latest-snapshot oriented,
  so raw payload capture going forward is part of the data asset.

## Red Lines

1. Do not add phantom chemicals scope.
2. Prefer issuer primary data over third-party ETF aggregators.
3. Keep fragile futures-curve scraping behind a swappable provider interface.
4. Never auto-substitute Yahoo ETF metrics for WisdomTree official fund-list rows.

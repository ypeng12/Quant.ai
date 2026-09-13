# Quant platform audit and experiments — 2026-09-13

The implementation now includes actual-data ingestion, corrected L1 OFI, causal
research comparisons, joint portfolio ablations, reconciled PnL attribution, and
read-only Lab results. **All dollar results below are simulations starting with
$100,000, not money earned in the user's account.** No real account balance was
assumed from broker access. No live strategy was promoted, no orders were placed,
and no commit or push was performed.

Each comparison predeclares 12 candidate configurations and two single-side costs:
20 complete trials and four unavailable L1 trials. Models train on earlier
sessions only, use completed five-minute bars, fill at the next open, and flatten
at 15:55. The periods have already been explored; these are not untouched holdouts.

## Foundation audit and corrections

- Fixed OFI when bid/ask prices worsen: disappearing prior depth now contributes;
  resets occur per New York session. Stable event ordering is retained.
- Trade direction uses strictly earlier same-day quotes with an explicit 30-second
  tolerance. Unknown direction, no quotes, incomplete buckets, or absent L1 remain
  missing rather than becoming an invented feature.
- Historical imports preserve feed, source, original timestamps, size units, raw
  pages and normalized-file checksums. Interrupted pagination remains incomplete.
- Independent XNYS session checks detect an entirely missing trading day instead
  of silently shrinking the evaluated interval. Early closes are explicitly unsupported.
- The 30-symbol SLSQP run failed on a feasible convex allocation problem. Research
  and shadow now use OSQP for the same objective; live defaults are preserved.
  All final experiments were rerun with this solver; the failed run is retained.
- Fixed a prior **5 bps optimizer / 2 bps execution-ledger mismatch** in peer ablation.
  Its old reoptimized figures are withdrawn; see the ERRATA in the old bundle.
  Matching cost rates and symbol/cash PnL identities are now verified on every trial.
- Newly queried Yahoo history covers 30 symbols, each with 2,652 bars over 34 sessions
  (79,560 rows). Original SNDK/TSLA/MSTR/NVDA OHLCV and timestamps match the fresh query
  exactly. This is a same-vendor consistency check, not independent market-data proof.
- Yahoo returned four dividend events and no splits. Dividends are not credited to
  intraday-flat portfolios. Ex-dividend gaps remain unadjusted contextual features.
- Alpaca key/secret were absent in the local credential probe. No historical Alpaca
  entitlement or actual L1 performance is therefore established.

## Four symbols, two weeks: Aug 31–Sep 11 (9 sessions)

| Candidate | Net at 2 bps | Net at 5 bps | Costs at 5 bps | Drawdown at 5 bps |
|---|---:|---:|---:|---:|
| cash | $0.00 | $0.00 | $0.00 | 0.00% |
| equal_weight | $6,211.32 | $5,679.86 | $891.71 | -4.52% |
| price_ridge | $3,877.33 | $3,154.65 | $2,542.98 | -4.58% |
| peer_ridge | $5,679.31 | $4,670.99 | $2,870.85 | -4.50% |
| context_ridge | $7,112.67 | $6,008.57 | $3,103.95 | -5.25% |
| context_tree | $6,101.53 | $11,758.86 | $4,158.57 | -2.53% |
| context_lightgbm | $-3,149.85 | $-411.96 | $2,092.08 | -4.75% |
| context_uncertainty | $3,298.80 | $1,872.34 | $1,229.71 | -1.74% |
| context_common_risk | $5,831.86 | $5,093.86 | $2,709.93 | -4.91% |
| context_robust | $3,230.21 | $2,099.66 | $985.84 | -1.56% |
| l1_ridge | unavailable | unavailable | — | — |
| combined_robust | unavailable | unavailable | — | — |

## Four symbols, recent week: Sep 8–11 (4 sessions), reset to $100,000

| Candidate | Net at 2 bps | Net at 5 bps | Costs at 5 bps | Drawdown at 5 bps |
|---|---:|---:|---:|---:|
| cash | $0.00 | $0.00 | $0.00 | 0.00% |
| equal_weight | $-3,625.46 | $-3,845.83 | $368.15 | -4.56% |
| price_ridge | $1,816.81 | $-1,899.89 | $928.49 | -4.57% |
| peer_ridge | $2,549.84 | $-1,442.14 | $1,093.15 | -4.47% |
| context_ridge | $1,861.39 | $-2,300.01 | $1,083.82 | -5.34% |
| context_tree | $2,132.24 | $3,983.04 | $1,766.57 | -2.51% |
| context_lightgbm | $-1,051.55 | $-1,091.75 | $1,065.46 | -4.23% |
| context_uncertainty | $3,599.45 | $534.46 | $435.92 | -1.44% |
| context_common_risk | $1,632.09 | $-1,687.45 | $912.81 | -4.95% |
| context_robust | $3,786.72 | $1,211.28 | $394.77 | -1.38% |
| l1_ridge | unavailable | unavailable | — | — |
| combined_robust | unavailable | unavailable | — | — |

All three final tables use the same OSQP portfolio solver. The earlier four-symbol
SLSQP tree result (+$11,055.32 over two weeks; +$4,170.78 in the recent week) is
retained in its original source-versioned bundle. The final values in these tables
supersede those interim comparisons. No fixed weekly profit has been established.
Changing the cost parameter also changes orders: fixed-order repricing is reported
separately and must not be confused with reoptimization.

The unified price Ridge uses the new common research fit/risk implementation and
is not an exact rerun of the previously frozen live-policy artifact's $4,102.05.

## Expanded 30-symbol panel, same two-week interval

| Candidate | Net at 2 bps | Net at 5 bps | Costs at 5 bps | Drawdown at 5 bps |
|---|---:|---:|---:|---:|
| cash | $0.00 | $0.00 | $0.00 | 0.00% |
| equal_weight | $2,605.90 | $2,112.57 | $827.66 | -1.66% |
| price_ridge | $1,201.27 | $-928.77 | $4,538.10 | -4.40% |
| peer_ridge | $-4,407.23 | $-4,283.91 | $5,860.34 | -6.94% |
| context_ridge | $-7,022.71 | $-6,995.13 | $6,510.49 | -8.80% |
| context_tree | $-1,963.07 | $-7,649.66 | $13,886.21 | -9.96% |
| context_lightgbm | $4,969.18 | $1,914.64 | $5,251.50 | -4.71% |
| context_uncertainty | $-4,438.78 | $-3,554.16 | $3,570.50 | -6.63% |
| context_common_risk | $-6,747.75 | $-6,659.38 | $6,025.18 | -7.71% |
| context_robust | $-4,016.47 | $-2,004.17 | $3,196.00 | -5.50% |
| l1_ridge | unavailable | unavailable | — | — |
| combined_robust | unavailable | unavailable | — | — |

This broadens cross-sectional evidence, not time-series evidence. The dates are
still reused, the panel was selected today, and there are no delisted constituents.
SPY-based residual features are available here; they were absent in the four-symbol
experiment. Comparing panel totals therefore changes both available features and
portfolio opportunities and is not a pure feature ablation.

## What the portfolio changes actually do

All context Ridge portfolio variants share the same forecasts. Joint allocation
trades off expected return against shrunk covariance risk, turnover cost, and
optional forecast-error / statistical common-risk penalties. No hand-assigned
indicator score or win probability is used. Coefficients are explicit research
specifications rather than alleged universal institutional settings.

Compare the context Ridge row with the uncertainty-only, common-risk-only and
combined variants for allocation effects, holding the forecasts fixed. Lower
costs or drawdown may be accompanied by lower net returns. Ridge uncertainty is
approximate and is not a calibrated profit probability.

### context_tree, four symbols, 5 bps: per-symbol attribution

| Symbol | Gross PnL | Costs | Net PnL |
|---|---:|---:|---:|
| SNDK | $325.91 | $715.77 | $-389.87 |
| TSLA | $3,252.00 | $1,237.18 | $2,014.82 |
| MSTR | $12,407.29 | $1,245.47 | $11,161.82 |
| NVDA | $-67.77 | $960.13 | $-1,027.91 |

### context_robust, four symbols, 5 bps: per-symbol attribution

| Symbol | Gross PnL | Costs | Net PnL |
|---|---:|---:|---:|
| SNDK | $144.08 | $257.80 | $-113.72 |
| TSLA | $223.27 | $225.59 | $-2.33 |
| MSTR | $2,718.15 | $502.44 | $2,215.70 |
| NVDA | $0.00 | $0.00 | $0.00 |

Detailed bundles also contain daily/hour/long/short attribution, decisions,
forecast errors, risk contributions, every fill, marked equity, data/source hashes,
training metadata, frozen sources and library versions. The API verifies these
artifacts before display. Hash consistency does not independently authenticate
vendor data or make exploratory results statistically conclusive.

## Forward work that is ready, and what has not happened

Three four-symbol candidates (context Ridge, shallow tree, combined portfolio)
were frozen on 2026-09-13 for future observations at 5 bps. All have **zero future
observations**. The recorder accepts fresh completed observations after the
registration time, archives inputs, and maintains a checked append-only hash chain.
It records decisions, not fictitious fills or equity. Actual/paper account PnL and
fill TCA have separate import tools. No collector, scheduled recorder, broker API
server or trading process was started by this implementation.

Remaining evidence: genuine quote/trade history and collection with configured
credentials; reconciled account exports; longer and untouched validation; actual
spread/latency/impact/borrow and funding costs; point-in-time corporate/universe data;
industry-factor analysis. Four weeks of future time cannot be generated today.

## Validation and use

99 relevant backend/replay tests and 8 subtests passed. Updated shadow tests
also passed after input archival was added. Frontend TypeScript/Vite build passed.
See `docs/quant_research_platform.md` for the 12-area status, commands, data schemas,
and resume wording supported by the implementation. Warnings include a websockets
deprecation and the existing frontend bundle-size warning.

Alpaca documents free live IEX and historical SIP with an end at least 15 minutes
old: https://docs.alpaca.markets/us/docs/market-data-faq . Account access still needs
verification. The OFI definition is based on Cont, Kukanov and Stoikov:
https://arxiv.org/abs/1011.6402 . Calendar implementation:
https://github.com/gerrymanoim/exchange_calendars . QP solver API:
https://osqp.org/docs/interfaces/python.html .

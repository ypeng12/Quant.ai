# Quant research platform — implementation and operation

This platform separates retained market data, candidate research, portfolio allocation,
execution assumptions, and actual account PnL. A feature or an ML model is a candidate,
not an established Alpha. Nothing in this workflow submits an order or promotes a model.

## What is implemented across the 12 work areas

| Area | Implemented and reviewable | Evidence still needed |
|---|---|---|
| 1. Data foundation | Historical permissions probe; explicit IEX/SIP downloads; pagination; timezone, session calendar, source and file checks | Alpaca credentials; point-in-time dataset audit. The original four-symbol OHLCV was freshly re-queried from Yahoo and matched exactly; this is a same-vendor check |
| 2. Broader universe | Separate 30-symbol research panel; multi-symbol historical downloader and experiment runner | 30 symbols now have 34 retained full sessions (79,560 bars); historical membership and delisted names remain absent. Today's panel is subject to selection/survivorship bias |
| 3. Alpha registry | Candidate definitions, feature names, source snapshots, package versions and all successful/unavailable trials retained | Stable incremental predictive evidence across independent periods |
| 4. Price/volume research | Causal returns, VWAP deviation, relative volume, peer residual returns, time of day, overnight gap, seasonal volume | Longer history and cross-universe tests |
| 5. Factor residual research | Past-only market residual feature when SPY is supplied; shrunk joint covariance and statistical PCA common risk | SPY is present in the expanded 30-symbol experiment; industry classification and factor-neutral validation remain absent |
| 6. Genuine L1 | IEX capture and historical quote/trade import; six measured L1 features; corrected OFI, quote age and direction classification | No actual L1 files present; quote and trade coverage, timestamp/reception-lag and cost effectiveness are untested |
| 7. ML comparison | Same input families compared with Ridge, shallow tree, LightGBM; prior-session fitting and frozen hyperparameters | Calibrated uncertainty and longer forward performance; no reason yet to add deep learning |
| 8. Validation | Independent exchange calendar, completed-bar/next-open ledger, daily training, identical costs, input/output hashes, descriptive paired daily differences | These reused dates are exploratory; no untouched holdout, multiple-testing-adjusted Alpha claim or long-run Sharpe claim |
| 9. Portfolio | Correlation-aware joint allocation; separate uncertainty/common-risk ablations; transaction-cost penalty; integer shares and exposure diagnostics | Future outcomes; actual borrow availability, financing and execution constraints |
| 10. Execution costs | Matching objective and ledger cost; fixed-order repricing kept separate; actual-fill TCA import | Actual fills and reference quotes needed to estimate spread, latency and impact; free IEX midpoint is not consolidated NBBO |
| 11. PnL attribution | Gross/cost/net by symbol, direction, day, hour; cash/equity reconciliation; separate actual account flow adjustment | Broker exports and strategy-tagged fills needed for actual strategy PnL |
| 12. Lab and presentation | Read-only verified comparison API and Lab UI; source archive; frozen future-decision logs; reproducible report and truthful resume text | Future observations and reconciled forward equity curve. The recorder is a command, not a running service |

## Free data workflow

Alpaca's official FAQ distinguishes free live IEX from paid live SIP. It also states
historical SIP requests can be made without a subscription when `end` is at least
15 minutes old. This is an entitlement to verify with the user's account, not proof
that a request has succeeded. No subscription upgrade is performed.

Source: https://docs.alpaca.markets/us/docs/market-data-faq

Configure `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in `backend/.env` locally. Do not
put secrets in reports, commits, command arguments, or chat. The data tools read
credentials directly and do not import the broker application configuration.

From the repository root:

```bash
python3 scripts/probe_research_permissions.py --output reports/history_probe_new.json
python3 scripts/download_yahoo_research_bars.py --universe30 --start 2026-07-27 --end 2026-09-12 --output data/yahoo_bars_new
python3 scripts/download_research_history.py --universe30 --start 2026-07-01T00:00:00Z --end 2026-09-12T00:00:00Z --feed sip --kind bars --output data/research_bars_new
python3 scripts/download_research_history.py --symbols SNDK TSLA MSTR NVDA --start 2026-09-08T13:30:00Z --end 2026-09-11T20:00:00Z --feed sip --kind quotes --output data/research_quotes_new
python3 scripts/download_research_history.py --symbols SNDK TSLA MSTR NVDA --start 2026-09-08T13:30:00Z --end 2026-09-11T20:00:00Z --feed sip --kind trades --output data/research_trades_new
python3 scripts/capture_alpaca_l1.py --universe liquid_us_iex_30 --feed iex
```

Quote/trade history can be large. Test a short interval first. An interrupted download
is labelled incomplete and cannot silently become a complete research interval.
Historical quote and trade directories can be passed together via `--l1-dir`.
Do not mix IEX and SIP events into one feature series. L1 sizes retain their source
units (quote round lots, trades shares); no invented L2/L3 levels are produced.
The six L1 inputs are spread, displayed-size imbalance, microprice displacement,
normalized OFI, classified-trade imbalance, and quote-update count. Unknown trade
direction stays missing. The default prior-quote tolerance is a documented 30 seconds;
it is a research assumption to evaluate, not a discovered market constant.
OFI formula reference: https://arxiv.org/abs/1011.6402

## Reproducible experiment

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_unified_research.py --bars reports/quant_audit_20260912/bars --symbols SNDK TSLA MSTR NVDA --start 2026-08-31 --end 2026-09-11 --costs 2 5 --equity 100000 --output reports/my_new_experiment
```

For the broader panel, pass the corresponding symbols and downloaded bar directory.
For genuine L1, append `--l1-dir data/research_quotes_new data/research_trades_new`
and supply enough prior sessions of both feeds for training. Four evaluation days
alone are not enough to cover prior training dates. Missing required L1 makes the
candidate unavailable, rather than turning missing order flow into a zero prediction.

The universe, 1-bar horizon, Ridge alpha 10, risk aversion 50, gross .95 and
per-symbol .70 are explicit research specifications retained in the registry.
Tree/LightGBM settings are also frozen in the archived source. The research and shadow
portfolio solver is OSQP, solving the same convex objective. Default shared live
solver behavior is retained; these research candidates are not deployed. A 30-stock
SLSQP failure is retained as an incomplete experiment, and all final comparisons
are rerun with OSQP rather than combining solver versions. Source: https://osqp.org/docs/interfaces/python.html . They are not alleged
industry constants or optimized universal answers. Portfolio uncertainty and PCA
risk coefficients are research preferences, not probabilities. All candidates use
the same gross/per-symbol limits, next-open execution and scheduled 15:55 liquidation.
The replay currently supports full 390-minute sessions; early-close requests fail
with an explanation instead of silently dropping those dates.

Compare context Ridge against uncertainty-only, common-risk-only, and combined
portfolio variants to isolate allocation effects while keeping forecasts fixed.
Compare Ridge/tree/LightGBM with the same context features to isolate model choice.
Changes in model and cost settings change trades: higher assumed costs can coincidentally
produce higher retrospective PnL through a different order path. Fixed-order cost
stress is the relevant calculation when asking how an existing path fares at higher costs.

All outputs are simulations using retained Yahoo OHLCV when using the bundled input.
Hashes establish local consistency, not independent proof of vendor accuracy or
point-in-time availability. A fresh same-vendor requery matched all original four-stock OHLCV values. Yahoo reported four dividend events and no splits in the expanded panel. Intraday-flat PnL does not receive overnight dividends; ex-dividend gaps remain raw model inputs, not a corporate-event Alpha. Borrow restrictions, financing, latency, market impact,
intrabar drawdown and actual fills are absent. Do not relabel these as live PnL.
The API `/api/research/platform` serves the final retained bundle read-only; `dataset` selects `four_two_weeks`, `four_recent_week`, or `thirty_two_weeks`. The API
server itself retains existing broker startup behavior, so the offline workflow never
starts it. The UI build is verified separately.

## Future observation

```bash
python3 scripts/shadow_research.py register --directory reports/new_forward_trial --symbols SNDK TSLA MSTR NVDA --candidate context_robust --cost-bps 5
python3 scripts/shadow_research.py record --directory reports/new_forward_trial --bars data/current_bars --account-snapshot data/current_account.json
python3 scripts/shadow_research.py verify --directory reports/new_forward_trial
```

`current_account.json` must contain actual or clearly identified paper-account
`timestamp`, `equity`, and `shares` for every registered symbol. Example schema:

```json
{"timestamp":"<current timezone-aware timestamp>","equity":100000,"shares":{"SNDK":0,"TSLA":0,"MSTR":0,"NVDA":0},"account_kind":"paper"}
```

The timestamp placeholder must be replaced with the time of a real snapshot.
The recorder requires synchronized completed bars after registration and fresh
account/data snapshots; it logs predictions and target weights, archives inputs,
and verifies a hash chain. It does not fill orders or invent paper equity changes.
A stale observation is not a live trading halt: this is validation of research labels
in a separate offline tool. No forced-stop or loss-lockout logic was added to trading.
Registration alone creates zero future observations. Run during market hours with
new data; collect actual paper fills/equity separately. A scheduled daemon and actual
forward execution are not running. Candidate source or package changes require a new
registration so experiments remain distinguishable.

## Actual PnL and transaction-cost analysis

```bash
python3 scripts/reconcile_research_pnl.py account --snapshots data/account_equity.csv --output reports/actual_pnl_new.json
python3 scripts/reconcile_research_pnl.py tca --fills data/actual_fills.csv --quotes data/reference_quotes.csv --output reports/tca_new.csv
```

Account CSV columns: `timestamp,equity,external_flow`. External flow means signed
deposits minus withdrawals since the preceding snapshot. PnL equals equity change
minus external flows and includes unrealized PnL; it is not automatically attributable
to this strategy. Fill CSV: `symbol,fill_time,quantity,fill_price,commission` with signed
quantity. Quote CSV: `symbol,timestamp,bid_price,ask_price,feed`. TCA uses strictly prior
same-feed quotes and reports missing references instead of inventing zero slippage.
Slippage is a price comparison; do not subtract it again from account equity PnL.

## Resume wording supported by the implementation

“Built an auditable multi-asset quantitative research platform with causal feature
construction, prior-session model fitting, covariance-aware allocation, explicit
execution-cost accounting, and reconciled PnL attribution. Compared Ridge, tree and
LightGBM candidates against simple baselines; implemented genuine L1 ingestion and
frozen forward-observation logs with reproducible data and source artifacts.”

Do not claim institutional profitability, a proven Alpha, live L1 advantage, or
weekly $10,000 earnings before the corresponding independent evidence exists.

## Counting features versus established Alpha

The retained selected live-policy artifact has 12 price/volume input features for
SNDK, TSLA, MSTR and NVDA. The new offline registry has 12 candidate configurations
including two baselines; it is not evidence of 12 independent Alphas. Peer features
extend the input set to 16; context features to 19; non-SPY names can have a 20th
market-residual input when SPY exists. Genuine L1 contributes six measured features,
some algebraically related (microprice, spread and imbalance). These counts cannot
be added up as independent predictive edges. No stable net-of-cost Alpha is yet
established from these reused short intervals.

Only Ridge error diagnostics are used by uncertainty-aware allocation. Tree and
LightGBM runs do not use their linear residual diagnostic field for allocation;
that field must not be read as calibrated tree/boosting predictive uncertainty.

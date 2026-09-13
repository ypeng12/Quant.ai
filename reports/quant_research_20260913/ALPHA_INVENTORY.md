# Alpha inventory and deployment status

## Current trading path

`live_runner.py` uses one model artifact: `price_volume_h1_g50`.  It is a separate per-symbol Ridge forecast based on 12 price/volume features. It is the only current model that reaches portfolio targets in the runner.

This is not a confirmed alpha. It was selected on five sessions, then evaluated retrospectively on nine sessions. Its 2 bps assumed-cost result was +$4,102.05 from $100,000, but the equal-weight intraday baseline returned +$6,211.32 over the same dates. Repricing the same fills at 5 bps gave -$1,135.49. It remains a research baseline rather than a proven production edge.

## Legacy components not eligible for trading

| Component | Why it is ineligible | Status |
|---|---|---|
| `InstitutionalAlphaEngine` composite OFI/micro/OU/lead-lag score | Fixed weights and candle-derived order-flow / book proxies | retired from trading path |
| Microstructure wave LightGBM | Its features can manufacture bid/ask values from OHLCV; stored model has no real-L1 walk-forward evidence | public prediction retired |
| LightGBM alpha predictor | Training script generates synthetic features and labels; fallback is a hand-set formula | public prediction retired |
| PEAD event engine | Creates a simulated earnings-growth input when no earnings event dataset is supplied | research stub only |
| Advanced per-ticker ensembles | Artifact metadata reports AUC 0.482--0.505 for three of four tickers, near random; feature construction includes candle-based proxy OFI | not used by live runner |

## Eligible research candidates

1. **Real L1 OFI and microprice.** Requires retained quotes and trade prints. This is the first new candidate because the top-of-book imbalance literature is relevant at short horizons, but it has no captured sample in this project yet.
2. **Peer-relative residual features.** New `price_volume_peer` features compare each closed five-minute return to the leave-one-out mean of the other three symbols. This is a fixed exploratory ablation only; its test artifact is separate and it cannot replace the baseline from retrospective results.
3. **Event features.** Earnings, news, options IV, and borrow need timestamped source data. They cannot be inferred from price/volume spikes. No event candidate will be created until those inputs are recorded.

## Research standards

A candidate may be promoted only after a frozen definition, training on past sessions, a pre-declared validation window, and an untouched out-of-sample period with execution costs. It must report its result against the existing baseline and per-symbol attribution. Dollar-profit targets are not selection criteria.

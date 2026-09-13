# Peer-residual Alpha ablation

> Correction (2026-09-13): the old reoptimized 5 bps runs used 5 bps in the optimizer but **2 bps in the execution ledger**. Those reoptimized numbers are invalid. The original 2 bps and fixed-order repricing are separate calculations. Correctly matched optimizer/ledger comparisons are in `../platform_research_20260913_qp/registry.json`; model fitting also differs, so this is not an exact old-policy reproduction.

## Candidate definition

`price_volume_peer` adds four features to the frozen price-and-volume Ridge model. At each completed five-minute bar it uses the **leave-one-out average** of the other three symbols' one- and three-bar returns, plus the target symbol's return minus that average. A missing peer makes the feature missing. It does not use future bars, a fixed score, or an external market-data proxy.

## Result

The experiment uses the same $100,000 starting capital, 2 bps assumed one-way cost, horizon, regularization, gross limit, and symbol limit as the frozen `price_volume_h1_g50` baseline.

| Candidate | Five-session preperiod | Nine-session retrospective period | Fills | Assumed 2 bps costs |
|---|---:|---:|---:|---:|
| Frozen price/volume baseline | +$993.69 | +$4,102.05 | 1,326 | $3,491.69 |
| Exploratory peer-residual model | +$1,596.81 | +$5,654.16 | 1,361 | $3,748.09 |
| Equal-weight intraday reference | — | +$6,211.32 | 72 | $357.55 |

The peer candidate does **not** beat the simple equal-weight reference in the retrospective window. It also has higher turnover than the frozen baseline.

## Cost sensitivity

Holding the exact recorded orders and reference prices fixed, repricing one-way slippage from 2 to 5 bps changes the baseline to `-$1,135.49` and the peer candidate to `+$32.02`. This makes the apparent peer improvement economically fragile.

The separately reoptimized 5 bps result is withdrawn because execution still charged 2 bps. It must not be cited as a 5 bps result.

## Decision

The candidate stays out of the live policy. The output is post-hoc exploratory because this nine-session period was already inspected before the candidate was added. Its next test must use a frozen definition on future, untouched sessions.

Machine-readable details: `peer_alpha_ablation/summary.json`.

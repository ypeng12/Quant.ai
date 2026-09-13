# Real L1 alpha research plan

## What is available now

The collector stores only source-labelled Alpaca WebSocket best-bid/best-ask quotes and trade prints. It does not manufacture a book from OHLCV bars. The available feature candidates are:

- quoted spread in basis points;
- displayed top-of-book imbalance;
- microprice displacement from the midpoint;
- quote-update order-flow imbalance (OFI), normalized by displayed depth;
- signed trade imbalance, only when a prior real quote exists; and
- quote-update count.

Those features are inputs for a model, not a live trading signal. A missing quote or trade remains missing; it is never converted to zero or estimated from a candle.

## Why last week cannot be replayed with L1

There are no retained real L1 capture files for the previous week. A candle dataset cannot reconstruct historical quotes, displayed sizes, quote revisions, or trade direction. Therefore it is impossible to make a valid L1 replay for that week from the current project data.

The existing OHLCV-only selected-policy replay is separate. It begins with $100,000, has 2 bps assumed one-way slippage, and recorded +$1,727.46 for Sep. 8--11, 2026. This is a historical simulation, not a $10,000 target or a prediction. At 5 bps assumed one-way cost, that same order flow is negative.

## Research procedure after capture

1. Capture all four symbols during regular sessions for at least 20 complete sessions.
2. Freeze the existing price-and-volume policy as the baseline before inspecting the L1 test period.
3. Train candidate models on prior sessions only: baseline features, real-L1 features, and their combined regularized model.
4. Select the model using a pre-declared validation window, then run one untouched out-of-sample window with the same position and execution accounting.
5. Report per-symbol PnL, turnover, measured quote spread/slippage where available, drawdown, feature coverage, and the baseline comparison. Keep the L1 model out of the live runner unless the unseen period improves after costs.

No candidate is tuned to force a particular weekly dollar PnL. That would select noise and cannot establish an alpha.

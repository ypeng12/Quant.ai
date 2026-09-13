# Free IEX L1 quant-research design

## Scope and cost

The first implementation uses Alpaca's free IEX WebSocket feed. It records actual IEX top-of-book quotes and trades, not a national best bid/offer and not L2 depth. The free plan permits 30 simultaneous WebSocket symbols, so `liquid_us_iex_30` is a fixed 30-symbol research panel. It is separate from the broker watchlist and cannot enlarge live trading by itself.

Start the manual collector with:

```bash
python3 scripts/capture_alpaca_l1.py --universe liquid_us_iex_30 --feed iex
```

The command only records market data. It does not place, alter, or cancel orders.

## Data layer

| Dataset | Source | Stored fields | Status |
|---|---|---|---|
| Five-minute OHLCV | IEX bars | timestamp, OHLCV, feed provenance | current baseline |
| L1 quote events | IEX WebSocket | bid/ask price, displayed size, exchange, timestamp | collector ready |
| Trade events | IEX WebSocket | price, size, exchange, conditions, timestamp | collector ready |
| Orders/fills/account | broker API | broker identifiers, status, filled quantity/price, account equity | execution reconciliation |
| Earnings/news/options/borrow | timestamped third-party or public source | raw event and publication time | not yet admitted |

Raw events stay append-only. Feature files include the source, feed, depth level, and the raw-data date range. IEX data is never labelled SIP, NBBO, L2, queue position, or cancellation depth.

## Research layers

1. **Baseline:** current price/volume Ridge model, retained as the comparison only.
2. **Panel candidate:** leave-one-out peer returns from the 30-name panel; it remains exploratory until a new unseen period is complete.
3. **L1 candidate:** spread, top-of-book imbalance, microprice displacement, normalized OFI, signed trade imbalance, and quote-update intensity.
4. **Combined model:** regularized price/volume + L1 model. It must beat both the baseline and a simple reference after the same execution accounting.
5. **Portfolio:** use joint forecast covariance and a turnover-cost objective across eligible symbols. The research universe is not an automatic live universe.

## Validation protocol

- First 20 complete sessions: data coverage, timestamp alignment, feature availability, and cost-distribution study only.
- Initial L1 evidence: 60 earlier sessions for training, 20 later sessions for model selection, then 20 untouched sessions for the reported result.
- Every reported run records candidate definitions before its untouched period, per-symbol PnL, turnover, fill count, drawdown, raw-data hashes, and fixed-order cost sensitivity.
- Real paper fills and retained IEX quotes provide execution calibration. IEX is a single exchange, so its displayed spread is not assumed to be the full-market executable spread.

## Current decision

No new Alpha or symbol is promoted to `live_runner` by this design. The current four-symbol Ridge policy remains the baseline while the 30-symbol panel collects data and research is run offline.

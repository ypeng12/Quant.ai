---
title: Quant AI - Reproducible Trading Research
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: Causal research, portfolios and auditable simulations
tags:
  - quant
  - trading
  - machine-learning
  - finance
---

# Quant.ai

A quantitative research and trading project with a React Lab, causal historical
simulation, portfolio allocation, broker execution reconciliation, and genuine
L1 data ingestion. Research evidence and account performance are kept separate.

[Open the Space](https://huggingface.co/spaces/Ypeng12/quant-ai) ·
[Implementation and reproducible commands](docs/quant_research_platform.md) ·
[Research findings (中文)](reports/platform_audit_20260913/结论.md) ·
[Methodology and results](reports/platform_audit_20260913/REPORT.md)

The [extended Alpha study](reports/extended_report_20260913/REPORT.md) adds
27 predeclared candidates and 54 completed simulations at the same capital and
costs, covering forecast horizons, pooled ML, opening selection, reference risks
and three pairs. At 5 bps, its retrospective best is **$13,512.18**, up **$1,753.32**
from the original four-symbol tree, by excluding SNDK from allocation while
retaining four-symbol features. Removing MSTR instead leaves only **$347.22**.
The first-five-session selection rule picks equal weight, which loses **$4,180.08**
over the subsequent four sessions. This is exploratory evidence, not a validated
strategy promotion. [Implementation and data eligibility](docs/extended_alpha_research.md).

The [large-cap policy](docs/largecap_liquid_policy.md) adds explicit stock
admission, daily walk-forward tree/Ridge calibration, and joint portfolio risk
comparisons. It screens a declared 32-stock panel using price, prior 20-session
dollar volume, reviewed security type and a current $50 billion market-cap floor.
Current membership is not historical membership evidence. The Lab exposes all
seven comparisons and admission reasons; the shared paper adapter records
decisions without assuming fills or automatically changing the live policy.
An additional [active-allocation comparison](reports/active_report_20260913/REPORT.md)
relaxes the market-cap floor while preserving price, liquidity and security-type
requirements, and tests concentrated targets against the same four-stock control.
The [revised direction models](reports/direction_report_20260913/REPORT.md)
keep the four traded stocks, add explicit market/industry inputs, and compare
longer forecast horizons with a fully costed multi-period holding plan. The best
new variant improves SNDK's contribution but underperforms the original overall;
all six results are retained and no new model is automatically promoted live.

## Research snapshot — September 13, 2026

These are retrospective simulations starting with **$100,000**, covering
**August 31–September 11, 2026 (9 trading sessions)**. The table uses
**5 basis points per side** of modeled execution cost and zero commission.
Cost, borrow, financing, impact and latency assumptions still need validation
against actual executions. These are not realized account profits.

| Candidate | Four-symbol net PnL | Thirty-symbol net PnL |
|---|---:|---:|
| Equal weight baseline | $5,679.86 | $2,112.57 |
| Context Ridge | $6,008.57 | -$6,995.13 |
| Context tree | $11,758.86 | -$7,649.66 |
| Context LightGBM | -$411.96 | $1,914.64 |
| Context robust portfolio | $2,099.66 | -$2,004.17 |

MSTR contributes **$11,161.82 (about 95%)** of the four-symbol tree result.
The four-symbol and thirty-symbol studies also differ in available market
reference features, so this is not a controlled universe-size ablation.
The dates have been reused during research; there is no untouched final
holdout and no demonstrated stable Alpha. All completed candidates, including
losses, are retained in the Lab and reports.

The tree candidate has **not** replaced the selected execution policy.
The configured artifact remains `price_volume_h1_g50` (Ridge).
Forward registrations currently contain **zero observations**. Their recorder
stores forecasts and target weights, not a complete forward fill/equity service.
No verified genuine L1 samples are included in this research snapshot.

## Implemented components

The current Lab landing view is the **non-crypto stock comparison**:
SNDK, TSLA and NVDA trade; SPY, QQQ and SOXX supply features. MSTR and IBIT
are excluded from these fresh models and their risk inputs. Over August 31–
September 11, 2026, at $100,000 initial equity and assumed 5 bps per side,
the fixed per-stock market Ridge simulation returned **+$1,169.25**; selecting
each stock's model from the preceding five validation sessions returned
**−$4,909.02**. Distinct models per stock did not improve this experiment.
These are retrospective results, not account profits or validated future Alpha.
See [the full non-crypto report](reports/stock_report_20260913/REPORT.md),
[daily model choices](reports/stock_report_20260913/stock_selections.csv), and
[the shared research/paper implementation](backend/app/research/stock_policy.py).
The live runner and its default model have not been switched.

A subsequent [paper-inspired conditional momentum pilot](reports/conditional_report_20260913/REPORT.md)
adds past-only volume/volatility interactions to Ridge. At the same capital,
dates and 5 bps cost, its five-minute version simulated **+$4,702.13**, versus
**+$4,221.73** for daily equal allocation without ML and **+$1,169.25** for
the unchanged Ridge control. The thirty-minute variant returned **+$3,454.27**.
This is a short retrospective hypothesis adaptation, not replication of the
paper's ETF sample or proof of live Alpha. Lab includes all four comparisons.
Legacy prediction screens no longer fabricate default win rates or random
price trajectories when predictions are unavailable; the unverified trajectory
API now explicitly returns unavailable.

The [next incremental Alpha study](reports/incremental_report_20260913/REPORT.md)
tests same-clock historical returns, overnight/intraday interactions and trailing
range structure separately and together. None beats the frozen conditional
Ridge in either the nine-session comparison or the earlier August 24–28 panel.
Both periods remain retrospective research; all six candidates are retained in
Lab, including losses. More features did not improve this experiment.

- Timestamp, exchange-session, provenance and checksum audits for historical bars.
- Shared price/volume, peer and market-context features; Ridge, tree and LightGBM comparisons.
- Past-session training, next-open simulation, cost stress and complete trial registries.
- Joint portfolio optimization with covariance, turnover cost and research risk preferences.
- Signed position accounting and symbol, day, hour and direction PnL attribution.
- Genuine quote/trade ingestion and L1 OFI, spread, imbalance and microprice features.
- Read-only Lab results with integrity checks and explicit unavailable-data states.
- Broker order/fill reconciliation and separate account-equity reconciliation tools.

Legacy C++/LOB/ML modules remain in the repository for research. Their existence
is not evidence of institutional execution latency, live L2/L3 coverage, validated
win rates or profitable Alpha. Older strategy documents describe project history;
the dated reports above describe the current measured evidence.

## Run and verify

See [the research guide](docs/quant_research_platform.md) for data collection,
experiment, shadow recording and reconciliation commands. Supply credentials
through local environment variables or Space secrets; never commit tokens.
The existing application startup starts the configured broker runner and retains
its paper-account authorization settings. Publishing the Space rebuilds the app.

```bash
python3 -m pip install -r requirements.txt
PYTHONPATH=backend python3 -m pytest -q backend/tests/test_research_catalog.py backend/tests/test_research_audit.py backend/tests/test_research_execution.py
cd frontend
npm install
npm run build
```

Published research registries and source snapshots are immutable evidence.
The loader relocates their report inputs on deployment and verifies the original
file hashes. A mismatch is displayed as unavailable, not replaced by synthetic
performance.

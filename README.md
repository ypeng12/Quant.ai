---
title: Quant AI - Reproducible Trading Research
emoji: 📊
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: Causal research, portfolio optimization and auditable simulations
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

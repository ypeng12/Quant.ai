# Financial Sentiment Analysis Using Prices

MSML610, Group 19: reproducible research infrastructure for testing whether financial text adds predictive value beyond price controls. The project is part of Quant.ai, but these offline research commands do not start the trading service.

## Current research status

As of October 20, 2026, no predictive alpha or model trading return has been verified. Real observations still require independently audited text availability, mature price outcomes, and consistent opening total-return evidence. Unknown evidence remains unknown; it is not filled in to make an experiment run.

The price-supervised text model, Loughran–McDonald comparison, full-text model comparison, and large-move attribution remain pending. Optional pretrained FinBERT scores describe text tone; they are not calibrated probabilities that a stock will rise, and the model was not trained in this project.

The published tests use synthetic fixtures. Passing them demonstrates software behavior, not investment performance. No raw news corpus, assistant review ledger, private research archive, account history, or owner planning document is added by this research publication.

## Reproduce offline checks

Run from the repository root with Python 3.11:

```bash
python3 -m unittest discover -s research/financial_sentiment_using_prices/tests -v
python3 research/financial_sentiment_using_prices/run_course.py --demo --output-dir /tmp/financial-sentiment-demo
```

Choose a new output directory for every run. The demo uses a deterministic synthetic contract and writes labels, chronological split, paired numeric controls, a stage report, and a hash manifest. Its metrics cannot be interpreted as real-market results. A zero exit code does not mean that the pending text-model stages are complete.

Most research modules use the standard library. The independent calendar audit additionally uses `exchange_calendars` and records its installed version and calendar export hash. Its optional tests explicitly skip if that package is unavailable. The renderer requires Matplotlib. Neither optional tone inference nor network collection is needed for the offline demo.

Optional local FinBERT dependencies are isolated in `requirements-nlp.txt`. `sentiment_model.py` pins the model repository, revision and ONNX filename, and hashes the downloaded artifacts. Request offline mode when working with an existing local model cache.

## Publication validation

On October 20, 2026, the isolated publication checkout passed all **329 research tests**, with no skips, using Python 3.11. The offline course demo also completed and produced 45 eligible **synthetic** labels. These checks establish reproducibility of the software contract; `market_predictive_skill_established` remains false.

## Research modules

| Module | Purpose |
| --- | --- |
| `run_course.py` | One offline entry point for archive readiness, prepared datasets and the synthetic demonstration; reports pending stages explicitly. |
| `data_preflight.py` | Audits retained raw/normalized bytes, request receipts, source families and historical availability evidence. |
| `calendar_audit.py` | Exports an independent exchange calendar and checks requested session endpoints against archived bars. |
| `corporate_action_archive.py`, `corporate_actions.py` | Retains corporate-action responses and validates dividend, ex-date, coverage and total-return evidence contracts. |
| `price_labels.py` | Constructs ten-session benchmark-relative labels and a mature chronological split with transitive source/event purging. |
| `price_baselines.py` | Compares existing numeric controls on identical complete-case observations; does not train a text encoder. |
| `prepare_text_candidates.py` | Freezes actually available text into prospective company-day candidates without fabricating predictions or outcomes. |
| `text_event_review.py` | Validates hash-bound relevance evidence and event links while retaining original articles and excluding unavailable samples from the split. |
| `run_research.py`, `event_extraction.py` | Produces descriptive, company-specific text/event summaries and optional pretrained tone analysis. |
| `stock_context.py`, `price_context.py` | Builds descriptive price/text context using only the information available at the selected clock. |
| `issuer_event.py` | Retains issuer-source versions and separates issuer publication claims from actual observation/receipt evidence. |
| `collect_research.py` | Bounded, explicitly invoked data capture using the existing read-only credential helper; importing it performs no acquisition. |

Use each command's `--help` for its input contract. Outputs are private by default and must be kept separate from input archives.

## Evidence boundaries

- Keep publication, update, actual response receipt, extraction, prediction completion, decision and label availability clocks separate. A later download cannot establish earlier text availability.
- Freeze input text by the pre-open cutoff and retain actual calculation completion. A post-open review cannot be backdated into a trading decision.
- Use an independent session calendar. Calendar weekdays, observed bars, and a daily close are not substitutes for an exchange opening timestamp.
- Treat raw or split-adjusted prices as descriptive until their return basis is audited. Provider process-date corporate-action queries alone do not prove complete ex-date coverage. Missing currency or incomplete events remain explicit.
- Observed total-return inputs require per-symbol series identity, dividend/split treatment, independently reviewed coverage, and actual evidence availability. Never add cash dividends again to an index that already embeds them.
- Fit only on mature historical outcomes. Purge linked sources/events transitively across train and test; keep multiple articles about the same reported event from masquerading as independent samples.
- Assistant relevance/event review is an auditable proposal, not independent human ground truth. A roundup may mention several events, so full-article deduplication can discard useful evidence.
- Run controls and text models on the same eligible observations and report missingness, exclusions, gross simulated results and explicitly named cost assumptions. Actual broker fees or account performance require separate evidence.

## Running with real data

Retain licensed inputs outside the public checkout or under the ignored private run directory. Supply your own existing archives to `run_course.py --dry-run`; an archive readiness audit does not automatically create a prepared training dataset. A prepared `--dataset` must satisfy the emitted `required_contract.json`, including source/version provenance, feature availability, exchange sessions, price basis evidence and mature evaluation windows.

Collectors are opt-in and require existing authorized provider access. No credentials, raw source text, model weights or research run outputs are bundled here. Do not commit generated reports or use a successful synthetic run as evidence of alpha.

The original notebook examples and lightweight helper remain available alongside the auditable research entry point.

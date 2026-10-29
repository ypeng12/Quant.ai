# Train_Financial_Sentinment_Analysis_Using_Prices

## Offline profitability follow-up (2026-10-28)

The current research priority is absolute net profitability, signal validity, and holding decisions. The frozen A/C/B comparison remains unchanged. Its text increment was negative; repeated observations of two receipt batches do not establish a sentiment alpha. New work is isolated on `research/signal-profitability-v2`, with no app deployment or trading activation.

The [fixed protocol](profitability_v2_protocol.json) evaluates four active price candidates at 2/5/10 bps per side and five text-decomposition arms. [Candidate code](../../backend/app/research/profit_signal_candidates.py) uses prior-only executable return labels and explicit holding/exit costs. The [semantic gate](semantic_signal_gate.py) requires verified entity, event, direction, horizon, and availability evidence; it is not an implemented NLP extraction model or proof of predictive value.

Full replays run in [the research workflow](../../.github/workflows/signal-research.yml) on a standard GitHub-hosted Linux runner. Numeric inputs and detailed simulated results remain in a private dataset; the public repository contains the protocol, code, and tests. The workflow never imports the trading API or supplies broker credentials to a solver. The 32-session historical interval is already-inspected development data, not a new blind test. All candidates, including losses, must be reported.

For local contract tests only:

```bash
PYTHONPATH=backend:scripts python -m pytest -q \
  backend/tests/test_profit_signal_candidates.py \
  scripts/tests/test_cloud_profit_research.py \
  scripts/tests/test_replay_sentiment_ablations.py \
  research/financial_sentiment_using_prices/tests/test_semantic_signal_gate.py
```

The owner's [Chinese review](README.zh-CN.md) and [primary research plan](../../docs/financial_sentiment_using_prices_plan.md) retain the detailed findings and current results.

This Python research module tests whether text labels derived from subsequent price reactions can add information to Quant.ai. The directory preserves the spelling of the assigned project title. See the [owner's research plan](../../docs/financial_sentiment_using_prices_plan.md) for scope and milestones; this README describes reproduction.

For the owner's Chinese explanation, current progress, original trading-logic audit, and the October 28 old/new strategy comparison, see [Chinese project review](README.zh-CN.md). The new offline comparison is implemented; its text overlay did not improve the price-only control in this development run, and no candidate has been promoted to live trading.

**Status (2026-10-21):** A real historical price-return TF-IDF/linear baseline and manual daily capture/checkpoint path now run locally. The original strict ten-session total-return target still has zero independently eligible prospective labels; trading alpha and A/B remain unverified. See the October 21 section below for exact commands, counts and negative baseline results.

## Course template adaptation

The module follows the API/example notebook structure of the [course starter template](https://github.com/gpsaggese/umd_classes/tree/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/project_template), reviewed at commit `60df5bc966d6da403eb54ee059372edc5cf20099`, including its [project creation tool](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/create_project.py) and [Docker instructions](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/project_template/docker_scripts.README.md).

This is a starter adapted to Quant's layout; the official creation tool was not run. Local utilities remove dependencies on the course repository root and `helpers_root`. Python 3.11 matches the verified research environment. The image name is lowercase, and Jupyter retains token authentication with a localhost-only host port. The assigned issue, final directory, branch naming, and submission must still follow the [course guidelines](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/README.md). No course PR has been submitted.

## Files

| File | Purpose |
|---|---|
| `financial_sentiment.API.ipynb` / `.API.py` | Loading API, field definitions, and small authorized local samples |
| `financial_sentiment.example.ipynb` / `.example.py` | Coverage, exclusions, and independent price-label recomputation |
| `financial_sentiment_utils.py` | Reusable read-only loading and validation |
| `collect_research.py` | Bounded, read-only Alpaca news and daily-price collection |
| `run_research.py` | Independent automated evidence review and safe public-summary export |
| `event_extraction.py` / `price_context.py` | Evidence-backed rule extraction, candidate grouping, and price arithmetic |
| `stock_context.py` | Offline multi-source snapshot, causal price-window checks, community keyword counts and atomic public export |
| `render_stock_context.py` | Exportable PNG derived only from the public stock-context JSON |
| `sentiment_model.py` / `requirements-nlp.txt` | Pinned local FinBERT ONNX inference in a separate environment |
| `price_labels.py` | Explicit session-calendar labels, actual availability checks, maturity filtering and source/event-group time splits |
| `price_baselines.py` | Paired numerical price/tone controls and synthetic contract demonstrations; audited features must be supplied by the caller |
| `data_preflight.py` | Offline month/source-family evidence audit; separates financial reports, calls, news and comments, exact versions/receipts and unknown event identity without constructing labels |
| `issuer_event.py` | Two fixed Microsoft issuer-page captures and offline body/date/version audit using the existing source-eligibility contract |
| `run_course.py` | Single offline entry point: archive dry-run or existing prepared-contract labels, chronological/event isolation, paired numeric controls and staged report |
| `tests/` | Timing, attribution, grouping, missing-data, and pipeline-isolation checks |
| `Dockerfile` / `requirements.txt` | Python 3.11 and notebook dependencies; no trading SDK |
| `docker_build.sh` / `docker_bash.sh` / `docker_jupyter.sh` | Build, container commands, and Jupyter entry point |
| `docker_name.sh` / `utils.sh` / `run_jupyter.sh` | Image configuration, mounts, and startup |

Notebooks and scripts use Jupytext `ipynb,py:percent` pairing. After editing, run `jupytext --sync financial_sentiment.API.ipynb`; do the same for the example notebook.

## Data and reproducibility

The default input is `../../reports/market_impact_data_audit_20261007/`. Set `FINANCIAL_SENTIMENT_DATA_DIR` to another existing audit directory if needed. The module does not fetch replacement data. Missing or incomplete archives raise errors.

The local audit contains 187 news articles, 120 Futu query records representing 118 distinct post IDs, five trading sessions for seven price symbols, and SEC filing metadata. Of 203 article-stock candidate pairs, 90 satisfy the exploratory window requirements and involve 81 articles. The other 113 have recorded exclusion reasons. These counts are calculated from the archive when the notebooks run.

The exploratory entry is the first five-minute boundary after `max(created_at, updated_at) + 60 seconds`; exit is 60 minutes later. Labels compare stock and SPY opening-price returns within one trading session, ending no later than 15:55. Validation also checks candidate pairs, duplicate bars, archived hashes, and saved statistics. This verifies internal consistency; it does not establish historical text availability, independent events, causality, predictive performance, or returns after costs. Missing response-receipt timestamps in the first Futu snapshot remain missing.

Raw articles and posts remain local. A clean clone does not contain that corpus; reproduction requires the same authorized archive or an explicitly agreed replacement dataset. The public Quant.ai interface uses aggregate counts, computed price context and selected short summaries; it does not expose the private corpus.

## Local Python

From the Quant repository root, Python 3.11 or later can recompute the archived labels:

```bash
python3 research/financial_sentiment_using_prices/financial_sentiment_utils.py
```

The utility uses the standard library. Notebook displays require pandas. In this module directory, use a compatible existing environment or create a separate one:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python financial_sentiment.API.py
.venv/bin/python financial_sentiment.example.py
.venv/bin/python -m jupyterlab
```

The verified research environment used pandas 2.3.3 and numpy 2.4.6. Notebook dependencies use version ranges rather than a complete cross-platform lock. The commands above are setup instructions, not evidence that a new environment was installed in the main Quant directory.

## Docker and Jupyter

Run from this module directory:

```bash
./docker_build.sh
./docker_bash.sh -lc 'python financial_sentiment_utils.py'
./docker_bash.sh -lc 'python financial_sentiment.API.py && python financial_sentiment.example.py'
./docker_jupyter.sh -p 8890
```

Use the token URL printed by Jupyter with host port `8890`, for example `http://127.0.0.1:8890/lab?token=...`. The module mounts at `/workspace`; the audit mounts separately and read-only at `/data/audit`. The trading application is not launched.

Both notebooks were previously executed in fresh Python kernels, including all four/five code cells. Recalculation produced 203 candidates and 90 valid exploratory labels with zero maximum return error. Shell syntax checks passed. Committed notebooks retain empty outputs so raw text is not published through notebook results.

**Docker build and container execution have not been verified locally; Docker is not installed on this machine.** Once available, verify image build, Jupyter access, and execution with `jupyter nbconvert --to notebook --execute financial_sentiment.example.ipynb --output /tmp/financial_sentiment.example.executed.ipynb`.

## Automated evidence-review prototype

Create an isolated Python 3.11 environment for the prototype. This does not change the trading backend environment or require an inference API key:

```bash
python3.11 -m venv research/financial_sentiment_using_prices/.venv
research/financial_sentiment_using_prices/.venv/bin/python -m pip install -r research/financial_sentiment_using_prices/requirements-nlp.txt
research/financial_sentiment_using_prices/.venv/bin/python research/financial_sentiment_using_prices/run_research.py \
  --input-dir reports/financial_sentiment_runs/event_review_20261009 \
  --output-dir reports/financial_sentiment_runs/my_evidence_review \
  --symbols PLTR AMZN MSFT --start-date 2026-10-02 --end-date 2026-10-09 \
  --public-output reports/financial_sentiment_prototype_summary.json
```

The output directory must be new. The first run downloads a pinned [ONNX conversion](https://huggingface.co/Xenova/finbert) of [ProsusAI/finbert](https://huggingface.co/ProsusAI/finbert); inference runs on the local CPU. Add `--offline` after the model is cached. `--rules-only` produces an explicitly unscored local review; the public UI schema currently expects completed FinBERT inference. Model revision, file hashes, runtime, input hashes, timestamps and inference truncation are retained. Softmax scores describe text tone and are not calibrated probabilities of future price movement.

To collect a new bounded archive, use the existing Quant Python environment (with `requests`, `pandas` and `python-dotenv`) and locally configured Alpaca market-data credentials:

```bash
python3 research/financial_sentiment_using_prices/collect_research.py \
  --output-dir reports/financial_sentiment_runs/my_new_capture \
  --symbols PLTR AMZN MSFT --start-date 2026-10-08 --end-date 2026-10-09
```

Pass that directory to `run_research.py` with matching price dates and a new output directory. The collector uses only fixed market-data GET endpoints, records actual receipt times, and caps news at 20 pages of 50 records. Page caps, missing symbols and failed requests remain visible; it never switches feeds or submits orders. A real two-session collection on October 9 returned 57 unique news articles and 16 daily bars across eight instruments. The original 385-article archive remains the separate, wider development trial.

The loader verifies raw-response hashes, normalized text and receipt times. It reads only the collection manifest, normalized news and raw bars; it never consumes `case_review.json`, saved outlooks or precomputed return labels. Extraction receives text only. Price calculations are added afterward. Company-bearing clauses reduce cross-company tone transfer, but indirect references and mixed-company clauses still require review. Rules may retain duplicate events or miss details; one primary candidate per article/company is not exhaustive extraction.

Reports are retrospective and use historical final text. An optional `--information-cutoff` filters on publication, revision and actual receipt time and rejects a requested price close later than that cutoff. It does not reconstruct unavailable old text versions. The price window uses exact start/end closes; raw price changes are not dividend-adjusted returns or strategy profit. The current regular-close reference assumes a full session; half-day calendars are not implemented.

This prototype searches the supplied news feed, not the wider web or company IR sites. Group timestamps identify the earliest retained report, not a proven global first publication. Later details in a cluster must not be attributed to its earliest headline time. The report combines extraction templates and price arithmetic; it does not reproduce a generative analyst's full reasoning.

Private `report.json` includes source evidence, model input and scores. Only short generated summaries, public source links, aggregate counts and computed price context reach the exported public JSON. Raw runs and model environments are excluded from the application image. Missing data and inference failures are not replaced by fabricated results.

Run the offline checks from the repository root:

```bash
python3 -m unittest discover -s research/financial_sentiment_using_prices/tests -v
```

The reviewed October archive is development material, not an unseen performance benchmark. No ten-day return predictor, Futu crowding measurement, trading orders or recurring scheduler is implemented by this prototype.

## Multi-source stock-context snapshot

The October 12 snapshot is a separate, reproducible SNDK research view with a **12:00 ET price cutoff**. `stock_context.py` uses only the standard library and reads six documented inputs: `daily.json`, `intraday.json`, `manifest.json`, `futu_current/all_normalized.json`, `news_context.json` and `context_sources.json`. The last four are optional. It does not collect data, run FinBERT, consume human-selected `levels.json` or `case_review.json`, or import the trading runtime. The selected news summaries in this snapshot were **manually reviewed**, not generated by an automatic NLP pipeline.

From the repository root, with the authorized local archive present, choose a
new private run directory. The input archive stays read-only:

```bash
RESEARCH_PYTHON=research/financial_sentiment_using_prices/.venv/bin/python
RUN_DIR="reports/financial_sentiment_runs/stock_context_rebuild_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$RUN_DIR"
printf '*\n' > "$RUN_DIR/.gitignore"

"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/stock_context.py \
  --input-dir reports/financial_sentiment_runs/stock_context_20261012_1200 \
  --output "$RUN_DIR/context.json" \
  --audit-output "$RUN_DIR/generation_audit.json" \
  --cutoff 2026-10-12T16:00:00Z --symbol SNDK

# Use a research interpreter with Matplotlib installed for this optional step.
python3.11 research/financial_sentiment_using_prices/render_stock_context.py \
  --snapshot "$RUN_DIR/context.json" \
  --output "$RUN_DIR/context.png"
```

Both commands are offline. The renderer additionally requires Matplotlib; version 3.10.7 was used locally. Install it in a separate research environment and use that interpreter for the rendering command. This optional dependency is not in the notebook requirements file and was not added to trading-environment requirements. The [public JSON](../../reports/financial_sentiment_stock_context.json) and [PNG](../../reports/financial_sentiment_stock_context.png) contain no raw posts, article bodies, account data or local paths. Public JSON is written through an atomic temporary-file replacement. The required `--audit-output` names a **new private audit outside the input archive**, recording SHA256 hashes of the exact six input byte sequences, generator and public output. Existing audits, input-directory writes and path aliases into the archive are rejected. If publishing the report fails, the old report remains and only the newly created audit is rolled back. Historical audits remain bound to their historical generator; the October 15 local backup preserves that code. Never rewrite old audit hashes to match newer code.

| Input | Observed coverage and limitation |
|---|---|
| Alpaca SIP prices | SNDK, SPY, QQQ, SOXX, MU, WDC and STX; 497 daily bars through October 9 and 651 completed five-minute bars on October 12. Seven bars starting at 12:00 ET are excluded from the 658 returned bars. The connector does not expose the adjustment setting. |
| Alpaca / Benzinga | 21 news records, 19 with bodies; stock tags do not establish direct Sandisk relevance. |
| SEC | 37 filing metadata records; the selected filing body returned HTTP 403. No filing body was analyzed. |
| Sandisk IR | One calendar item manually reviewed using the web tool; direct archival capture returned HTTP 403. |
| Industry evidence | Two captured reports, including competing industry evidence; combined news coverage is 24 records, with seven manually reviewed public evidence items. These are not 24 independent events. |
| Futu | 30 unique post IDs: 2 bullish, 1 bearish, 0 mixed, 27 unknown. No author or engagement fields. |
| X | Not connected; no captured records. |

At the cutoff, SNDK's observed price was $1,491.80, down 5.69% from the previous close and 3.01% from the regular-session open. Its change was 5.72 percentage points below SPY and 3.54 points below SOXX. Provider bar VWAP weighted by regular-session volume was $1,486.58. These are realized observations, not executable quotes or forecast results.

Five-minute timestamps denote **bar ends**, and unfinished intervals are excluded. Daily charts start at zero on the first common archived close; 5- and 20-session comparisons use matching endpoints. Previous-session high/low/close, 20-session high/low and SMA20/50 are computed only from prior completed daily bars. The 14-session simple mean true range describes past variability, not a confidence interval. VWAP uses provider bar VWAP when complete; otherwise the whole observed session uses an explicitly labeled typical-price proxy.

Reference `known_at` denotes the underlying market-period close, **not proven pipeline availability**. Prices were received at 12:20:21 ET; the reused daily archive retains its separate 11:09:32 ET receipt in the private manifest. All news and Futu observations were received after 12:00 ET, so **both have zero usable records at the replay cutoff**. Futu posts themselves were published between 12:08:08 and 12:19:41 ET. Publication before a cutoff does not replace evidence of actual receipt.

The Futu baseline removes instrument-name cashtags, avoids counting identical title/excerpt text twice, preserves unknowns and uses actual receipt of the retained post version. Rule coverage is 3/30, or **10%**. Directional balance is `100 * (bullish - bearish) / (bullish + bearish)`, here **33.33 on a -100 to +100 scale**, not confidence or an upward-return probability. Traditional Chinese, Cantonese, conditional statements, sarcasm and subject attribution remain limitations. Unknown does not mean neutral; these counts describe sampled posts, not all investors or unique users.

The read-only `GET /api/research/financial-sentiment/context` endpoint validates and projects the saved report through [financial_sentiment_context.py](../../backend/app/financial_sentiment_context.py). Missing reports return 404 and invalid reports return 503. [StockContextPanel.tsx](../../frontend/src/components/StockContextPanel.tsx) adds an explorer to the existing Financial Sentiment panel: selectable series, intraday/daily charts, regular-session filtering, prior-price references, session/5/20-session comparisons, an evidence timeline and source/stance diagnostics. Its SNDK research snapshot is independent of the global watchlist. Refreshing reads saved data only.

Validation for this iteration: **79 research tests and 111 research API tests passed (190 total)**; the frontend production build passed. The actual React component was checked in a local preview harness, including daily/intraday, regular-session, 5-session, company-statement and source controls. The harness is a safe preview of the component integrated into the existing app, not a separate product. See the [browser preview](../../reports/financial_sentiment_stock_context_preview.jpg); private `delivery_verification.json` in the run directory records artifact hashes, test and browser checks. The exportable PNG was also visually checked. Timing, incomplete bars, matching comparison endpoints, public-field boundaries, duplicate text, the ETF-name false positive, atomic replacement and archive hashes were checked. These checks do not measure NLP accuracy, prediction skill or trading returns. The new explorer and PNG have not been deployed to Hugging Face, and no trading strategy was changed.

## Quant.ai display and next steps

The display belongs in the existing [Quant.ai Hugging Face app](https://huggingface.co/spaces/Ypeng12/quant-ai), under **Financial Sentiment**, immediately after Live Alpha. The updated local React panel reads the saved stock-context snapshot and the separate automated evidence report from dedicated read-only APIs; the original audit is under **Data diagnostics**, and the community database remains separate. Reloading the page does not collect data or run inference. Local changes do not imply that the hosted Space has been deployed.

Next, establish ongoing collection with real receipt timestamps, implement sentiment baselines and price-label models, validate on time-separated data, and then compare equal-capital Quant.ai variants. Data-audit success alone does not establish predictive or trading value.

## Price-label and baseline contract (October 15)

The course question is whether price-response labels let text provide information
beyond traditional tone and past prices. `price_labels.py` now implements an
offline **company–decision-day** contract: raw inputs through **08:45 New York
time**, extraction/prediction completed by **09:15**, and the supplied regular
session open to the open **10 supplied trading sessions later**. Five and twenty
sessions are separate robustness runs. The target is the stock total return minus
SPY total return, in decimal units; an optional sector difference is separate.
The old 90 labels remain the original 60-minute raw-price exploration.

No exchange calendar or corporate-action series is downloaded or inferred.
Callers must supply and independently audit the following JSON fields:

| Field | Required content |
|---|---|
| `data_kind` | Explicitly `synthetic` or `observed`. |
| `as_of` | Timezone-aware evaluation timestamp; immature or late-received outcomes remain pending. |
| `calendar` | `calendar_id`, `calendar_version`, `complete: true`, and ordered, unique `sessions` with `date`, `open_at`, `close_at`. Completeness is a caller assertion, not independently established by this module. |
| `prices` | Rows with `symbol`, `session_date`, positive `open_value`, `return_basis`, actual `available_at`, and `provenance_id`. `total_return_index` requires independently verified split/dividend treatment; `raw_price` is retrospective diagnostics only. |
| `observations` | One row per company and decision day: `sample_id`, `symbol`, `decision_session`, `source_ids`, `event_cluster_ids`, `published_at`, `updated_at`, actual `response_received_at`, `extraction_completed_at`, `prediction_completed_at`, and an explicit `historical_availability_verified` declaration. |
| Feature evidence | Numeric `feature_values` and `feature_provenance[name] = {available_at, provenance_id}`. These times describe the latest raw input used by each feature, not its later inference completion. Future outcome fields cannot be features. |
| `evaluation` | `training_cutoff`, `test_start`, `test_end`, all timezone-aware. No random split or automatically chosen favorable period. |

Labels distinguish `Eligible`, `Pending`, `Unavailable`, and `Retrospective`, and
record missing/late-input reasons. The temporal split admits only eligible,
available outcomes. Training labels must actually be available **before** the
training cutoff; test entries fall in `[test_start, test_end)`. Shared source IDs
and event clusters are purged from training, including articles naming multiple
companies and transitive connections through excluded or out-of-window records.
A sample-count gap is not a substitute for these checks. A training cutoff later
than an actual test prediction, inconsistent horizon/calendar/return bases, or an
opening price allegedly received before the session open is rejected.

`price_baselines.py` compares five fixed controls on exactly the same complete-case
train/test intersection: training mean, calibrated five-session momentum,
calibrated tone, price-only ridge, and price-plus-tone ridge. Price features are
`momentum_5d` and `momentum_20d`; tone is `tone_score`. Ridge strength is fixed at
1.0 in the CLI, and all scaling and fitting use training rows only. Outputs include
sample IDs, fitted coefficients, MAE/MSE, directional accuracy and paired loss
differences. Missing tone is not imputed as neutral, and overlapping outcomes are
not treated as independent statistical evidence. There is no tuning, trading
simulation, cost-adjusted performance or confidence-interval claim.

Run the synthetic software contract using a new directory:

```bash
research/financial_sentiment_using_prices/.venv/bin/python \
  research/financial_sentiment_using_prices/price_baselines.py --demo \
  --output-dir "reports/financial_sentiment_runs/label_demo_$(date -u +%Y%m%dT%H%M%SZ)"
```

The new directory contains `synthetic_input.json`, `labels.json`, `split.json`,
`comparison.json`, a module/input/output hash manifest, and a private `.gitignore`.
The artificial consecutive-day calendar intentionally includes weekends; it is
**not an exchange calendar or market dataset**. The report says `Synthetic contract
check`. For an audited dataset, replace `--demo` with `--input <dataset.json>`;
the same eligibility checks remain in force. Existing output directories are
rejected. Add `--horizon-sessions 5` or `20` for separately identified runs.

The current SNDK archive was received after its analysis cutoff and does not
provide an audited total-return series, so it cannot substantiate a forward
ten-session comparison. The October 15 rerun reproduced its historical numbers
in a fresh private directory without changing the original inputs or audit.
This framework does not train a price-label text encoder, fetch an LM dictionary,
create a human review set, or complete the course's large-move attribution task.
Real data collection, text baselines, supervised text training and later-period
evaluation remain required course work. No new market-performance result is
claimed by the synthetic comparison.

October 15 verification: **140 research tests and 111 independent research API
tests passed (251 total)** in an isolated copy. The unchanged frontend also
passed TypeScript and Vite production build in the pre-change isolation run.
The input archives and historical public JSON/PNG were preserved. These are
engineering checks, not predictive-performance evidence.

## Local month preflight (October 16)

Audit the selected existing archives before constructing a company-day dataset:

```bash
python3 research/financial_sentiment_using_prices/data_preflight.py \
  --input-dir reports/financial_sentiment_runs/event_review_20261009 \
  --legacy-alpaca-dir reports/market_impact_data_audit_20261007/alpaca \
  --symbols PLTR AMZN MSFT --month 2026-09 \
  --as-of 2026-10-16T14:26:20Z \
  --output-dir reports/financial_sentiment_runs/my_september_preflight
```

The output must be new and outside both input archives. This standard-library
audit checks original response hashes and normalized text/version fields, saves
a private `preflight.json` and input/generator/output hash manifest, and performs
no network request, inference or training. It reads the wider prototype archive
and only the original audit's four `news_recent_*` pages, normalized news, request
log and hash index. Older access probes, saved answers, labels and outlooks are
excluded. It inventories publication dates in New York; it does not assign texts
to decision sessions or treat vendor tags as verified relevance.

September was chosen as the latest complete calendar month, without comparing
monthly returns. The three companies inherit a previously price-inspected
development prototype; this is not an unseen test set. The existing inputs have
11 distinct September article IDs (all September 30), 15 company/article pairs
and 10 pairs with bodies. PLTR/AMZN/MSFT have 2/6/7 tagged articles. AMZN and MSFT
were incidental tags in the old query, not a complete company-specific query.
All 11 selected captures lack an exact receipt; the old `observed_at` is request
start and must not become receipt. Repeated captures do not prove historical
text availability.

Each company and SPY has 24 raw daily records, September 8 through October 9:
17 observed September dates and seven October dates. These dates do not establish
the exchange calendar. Daily timestamps are date markers, not regular open or
receipt times. The selected archives supply no independently established session
calendar or consistent opening total-return series. The decision-day denominator,
ten-session matchable fraction and whole-month maturity remain `null`; zero
formal labels were constructed and real-model evaluation remains `Not evaluated`.
This is a reproducible readiness finding, not a predictive-performance result.

## Single course entry point

`run_course.py` connects the existing modules without duplicating their label,
split or fitting algorithms. It always produces an English JSON stage report
in a **new private directory**. It performs no network request or collection.

Run the available real archives through a dry-run:

```bash
python3 research/financial_sentiment_using_prices/run_course.py --dry-run \
  --input-dir reports/financial_sentiment_runs/event_review_20261009 \
  --legacy-alpaca-dir reports/market_impact_data_audit_20261007/alpaca \
  --symbols PLTR AMZN MSFT --month 2026-09 \
  --as-of 2026-10-16T14:43:14Z \
  --output-dir reports/financial_sentiment_runs/my_course_dry_run
```

This invokes `data_preflight.audit_archives`, writes `preflight.json`,
`source_family_audit.json`, `required_contract.json`, `report.json` and `run_manifest.json`, and **does not
invoke label construction or fitting**. The report retains the exact missing
evidence and required prepared fields. For the current inputs, labels remain
zero and evaluation is `Not evaluated`. Exit **0** means the requested audit
executed successfully; it does not mean the research dataset is ready.

Once an independently audited prepared dataset exists, the same entry point
can execute the existing numerical label/control chain:

```bash
python3 research/financial_sentiment_using_prices/run_course.py \
  --dataset /path/to/audited_company_day.json \
  --output-dir reports/financial_sentiment_runs/my_prepared_course_run
```

The file must follow the [price-label contract](#price-label-and-baseline-contract-october-15).
Prepared mode reads and hashes those exact input bytes, lists missing field paths,
and delegates to `price_baselines.evaluate_dataset`: ten-session labels, strict
maturity/availability filtering, chronological source/event-group purging and
five controls on the identical complete-case sample intersection. It writes
`labels.json`, `split.json` and `comparison.json` only after that contract returns.
These prepared inputs are caller supplied; this command does **not** establish
that they came from the raw archive or independently certify their provenance.
`labels_created` counts diagnostic rows; `eligible_labels` and `label_coverage`
distinguish usable, pending, unavailable and retrospective records.

Missing schema fields, invalid data or too few eligible paired samples produce
a blocked report, `Not evaluated` and exit **2**. Per-row missing receipts,
feature evidence and raw prices retain the core contract's conservative statuses
and exclusions; they are never filled with invented timestamps, zero or neutral
tone. Output-path protection and invalid command combinations fail before a run
is published. Existing output directories and writes inside either input archive
are rejected. Every published run includes input, all seven orchestration/core
source and output fingerprints, plus `.gitignore` and directory mode 0700.

The existing synthetic fixture can check this entry point without any market
dataset:

```bash
python3 research/financial_sentiment_using_prices/run_course.py --demo \
  --output-dir reports/financial_sentiment_runs/my_course_contract_demo
```

Demo mode reuses `price_baselines.synthetic_dataset`; it saves the exact fixture
and says `Synthetic contract check`. It is software verification, not a real
prediction experiment. A synthetic prepared input retains that label, and the
existing guard rejects synthetic fixtures relabeled as observed.

| Stage | Implemented behavior | Still required |
|---|---|---|
| Raw news/prices → evidence audit | Existing local archives and exact hash/availability checks | Complete permitted corpus, versions, calendar and corporate-action evidence |
| Raw archive → company-day dataset | Explicitly reported as pending | Actual text/feature adapter and audited time evidence |
| Prepared dataset → ten-session labels and split | Existing calendar/availability/maturity/event-isolation contracts | Independent evidence supporting caller declarations |
| Prepared split → paired numerical controls | Five fixed existing mean/momentum/tone/price controls | Real eligible samples; `tone_score` origin is not certified as FinBERT |
| Price-supervised text and full text baselines | Explicitly reported as pending | TF-IDF/text model, LM and fair text-budget comparison |
| Large-move news attribution | Explicitly reported as pending | Frozen detection, ranking and independent evaluation |

Successful controls still report incomplete research stages. No profitability,
statistical independence, full end-to-end text research or trading result is
claimed by this integration.

## Source-family provenance and eligibility

The research must investigate **financial reports, earnings calls, news and
investor comments**. Its eventual alpha criterion is incremental out-of-sample,
after-cost profit beyond price controls. Source counts, software tests and
prediction-loss improvement alone do not establish that result.

`data_preflight.audit_source_records()` extends the existing preflight. It keeps
`source_id`, explicitly supplied `event_ids`, original publication evidence,
`text_version_sha256`, version/republication times and retrieval evidence separate.
An event ID is not generated from each article/post ID, URL or fiscal label.
Reviewed event mapping is still required; syndicated copies sharing an event ID
remain associated and do not become independent evidence.

`first_actual_receipt_at` is the earliest retained successful response bound to
that exact text version. `first_response_received_at` may describe metadata or a
failed response; it is not proof of receiving the text. An older version's first
receipt is shown separately as `source_first_retained_text_receipt_at` and cannot
backdate revised or republished text. Request starts and `first_seen` do not
supply receipt. Contradictory request/response chronology, failed responses,
unbound hashes, future captures and after-cutoff content remain ineligible.
Unknown receipt stays `null`, including material retrieved historically later.
`Eligible under supplied evidence` is a source-contract check, not independent
authentication, a price label, a model result or a trading signal.

Include the existing SNDK multi-source snapshot in the same offline runner:

```bash
python3 research/financial_sentiment_using_prices/run_course.py --dry-run \
  --input-dir reports/financial_sentiment_runs/event_review_20261009 \
  --legacy-alpaca-dir reports/market_impact_data_audit_20261007/alpaca \
  --symbols PLTR AMZN MSFT --month 2026-09 \
  --as-of 2026-10-16T16:27:59Z \
  --source-snapshot-dir reports/financial_sentiment_runs/stock_context_20261012_1200 \
  --output-dir reports/financial_sentiment_runs/my_source_eligibility_run
```

The optional snapshot keeps its original **2026-10-12 16:00Z** cutoff. The
September news audit is a separate inventory at the audit clock, not an 08:45
decision replay; the two scopes are not pooled as training samples. Output must
be outside every input archive. Prepared/demo modes reject the snapshot argument
instead of silently ignoring it.

The snapshot adapter verifies the old six-input generation audit, all six source
responses, news normalization and the Futu response/text/Unix-publication/receipt
binding. It reads no saved analyst outlook, computes no price context or labels,
and does not reuse manual summaries as original documents. The current outcome
is **21 news records, 30 comments and one metadata-only 10-K; zero eligible text
records at the original cutoff**. All 51 news/comment captures arrived later;
all 52 event identities remain unknown. The 37 SEC filing-index records include
only one 10-K; insider filings are not financial-report bodies. Two failed body
requests and two unparsed industry HTML captures stay explicit coverage gaps.
No earnings-call original or financial-report body was retained in this snapshot.

Financial dates are explicit: `fiscal_period` and the report-period end remain
separate from `event_calendar_date` and exact publication time. For example,
[Microsoft's official FY2026 Q1 call](https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q1)
is dated **October 29, 2025**; the fiscal year in its title/URL does not make it a
calendar-2026 event. This public date check supplies no historical pipeline
receipt or original text-version capture. Similarly, the
[official Nasdaq 2026 holiday page](https://www.nasdaqtrader.com/trader.aspx?id=Calendar)
is a calendar reference, not a generated and verified full session-calendar input.
The existing missing-calendar and total-return findings remain unchanged.

## Microsoft FY2026 Q1 document preflight (October 17)

The official [release](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q1/press-release-webcast)
and [call transcript](https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q1)
have now been retained locally for the same **October 29, 2025** event. FY2026 Q1
is a fiscal label. This is one event with two documents, not two independent
prediction samples. The release is an earnings press release, not a retained 10-Q.

Reproduce the saved body/date/source audit **offline** using a fresh output:

```bash
python3 research/financial_sentiment_using_prices/issuer_event.py \
  --input-dir reports/financial_sentiment_runs/msft_fy2026q1_20261017T141455Z/capture_network_retry \
  --output-dir reports/financial_sentiment_runs/my_msft_document_replay \
  --cutoff 2025-10-30T12:45:00Z
```

The reference cutoff is 08:45 New York on October 30, 2025; it does not certify
an exchange calendar or construct a trading label. The adapter validates the
fixed URLs, methods, raw byte lengths and hashes; extracts only the release body
and transcript through `END`; stores exact text hashes and date offsets; then
reuses `data_preflight.audit_source_records`. It never loads a model or the app.
Navigation, scripts, annual-report links and footer text are excluded. The
original HTML remains authoritative for financial table layout; plain text is
not parsed financial data.

Outputs include private `bodies/*.txt`, `publication_evidence.json`,
`event_mapping.json`, `source_records.json`, `report.json` and a manifest binding
raw inputs, all five generation modules and outputs. The conservative shared
earnings group is supported by issuer headings and explicit dates; it is not
independent human gold or a claim that every discussed fact originated that day.
For example, prior-day agreements must retain their own fact dates.

Observed capture receipts are **October 17, 2026**, after each complete response
body was read. The release supplies a **publication date** of October 29, 2025,
without an exact time. The transcript's date identifies the **call event** and
does not establish when the transcript was first posted. Its original publication
date therefore remains `null`; exact publication times and historical pipeline
receipts remain `null` for both documents. HTTP Date, Last-Modified and the call's
scheduled start are not publication or historical receipt evidence.

Both current versions are correctly **After cutoff**, with zero eligible sources,
zero formal labels and `Not evaluated` for the real model. No same-event news or
comments were requested; their coverage remains unknown, not a measured zero.
The existing October 2026 news/comment corpus is not paired to this 2025 event.
Full session-calendar, total-return, historical-availability and paired text-model
requirements remain pending.

Only if a new capture is needed, the following command requests the two fixed
public URLs once each, with no credentials, cookies, redirects or wider crawl:

```bash
python3 research/financial_sentiment_using_prices/issuer_event.py --capture \
  --output-dir reports/financial_sentiment_runs/my_new_msft_issuer_capture
```

Public network access is needed only for capture. A blocked, failed or truncated
response leaves an explicit partial manifest and exit 2; it is not silently
retried or substituted. Offline audit exits 0 when both bodies are verified,
even though historical source eligibility remains zero. Failed body extraction
returns exit 2 with explicit coverage gaps. Existing outputs, raw-file symlinks
and audit writes inside the input capture are rejected. Raw bodies stay local.

October 17 verification: **28 focused tests and all 255 research tests passed**.
These test capture integrity, extraction/date boundaries and conservative source
eligibility. They are not predictive or profit evidence. The owner plan records
an untested hypothesis about call facts beyond the release and generic tone,
requiring same-sample, time/event-isolated ten-session validation and a separate
after-cost strategy comparison before any alpha claim.


## Independent calendar and raw-open endpoint coverage (October 17)

`calendar_audit.py` exports the installed `exchange_calendars` XNYS rules and
checks company/SPY opening-price endpoints in one retained raw daily archive.
It does not infer sessions from returned bar dates. The optional package is
already installed as **4.13.2** in the local Python 3.11 environment used for this
run; the NLP virtual environment may not contain it. Use that version for
reproduction (no package installation or dependency upgrade was performed).

```bash
python3 research/financial_sentiment_using_prices/calendar_audit.py \
  --archive reports/financial_sentiment_runs/event_review_20261009 \
  --month 2026-09 --as-of 2026-10-17T15:47:37Z \
  --calendar-end 2026-10-30 --symbols PLTR AMZN MSFT \
  --output-dir reports/financial_sentiment_runs/calendar_endpoint_NEW
```

The input archive must include a manifest-bound, successful, fully paginated
`1Day` response with explicit `adjustment=raw` and an actual response receipt.
Choose a new output directory outside the input archive. `calendar.json` retains
rule/package/dependency versions, source hashes, and UTC session opens/closes.
`report.json` records every decision-date/horizon pair, missing endpoints,
calendar maturity, and price receipt separately. `run_manifest.json` binds input
and output hashes and retains the actual generator as `generation_source.py`.

For the existing September development archive there are **21 rule decision
sessions**. Each of PLTR, AMZN, and MSFT has **17/21, 14/21, and 4/21** paired raw
open endpoints for horizons 5, 10, and 20, respectively. Four September entry
sessions (September 1–4) are absent for all companies and SPY. The last September
10-session exit is October 14; the 20-session exit is October 28, so only 13 of
21 twenty-session windows have reached exit open as of October 17.

These are raw-price coverage diagnostics, not eligible text observations,
total-return labels, or model results. No returns are calculated. Formal labels
remain zero and model/trading evaluation remains `Not evaluated`. The installed
calendar is a rule reference, not exchange certification of extraordinary
closures, historical announcements, or symbol-specific auction execution.
See [NYSE](https://www.nyse.com/trade/hours-calendars),
[Nasdaq](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule), and
the [package source](https://github.com/gerrymanoim/exchange_calendars) for review.
The standalone audit is not yet a raw-archive-to-prepared-dataset adapter for
`run_course.py`; total returns, text versions/receipts, event grouping and feature
clock evidence remain separate requirements.

Fourteen focused offline regressions cover holidays, DST, early closes,
endpoint counting and missing SPY, invalid prices, receipt timing, raw basis,
hashes/pagination, duplicate dates and output preservation. These are software
checks; they provide no predictive or profit evidence.


## Corporate-action dates and observed total-return evidence (October 18)

There is currently no corporate-action downloader or total-return reconstruction
adapter in this course pipeline. `corporate_actions.py` adds offline contracts;
it does not fetch data, add cash, or calculate market performance.

`audit_cash_dividends` accepts explicitly normalized ordinary cash-dividend
records: `event_id`, `symbol`, `ex_date`, `cash_per_share`, `currency`, and
`treatment="standard_cash_dividend"`. Keep `record_date`, `payment_date` and
`process_date` separately; never substitute these for missing `ex_date`.
For an open-to-open holding interval, the ordinary entitlement convention is
`entry_session < ex_date <= exit_session`. Special due-bill distributions and
non-cash actions need separately reviewed treatment. Identical captures of one
stable event ID count once; conflicting versions and ambiguous duplicate
identities raise errors. Payment is not a second return event.

The supplied Alpaca query contract must explicitly use `date_basis="process_date"`.
A complete or empty response over process dates does not establish complete
ex-date coverage. No fixed extension of the query window is treated as proof.
See the [Alpaca endpoint documentation](https://docs.alpaca.markets/us/v1.1/reference/corporateactions-1)
and [SSGA distribution schedule](https://www.ssga.com/library-content/products/fund-data/etfs/us/distribution/SPDR_Dividend_Distribution_Schedule.pdf).

For `data_kind="observed"` (also the conservative default in `build_labels`),
`total_return_index` prices now require matching per-endpoint `return_series_id`
and a `return_series_evidence[symbol]` object with:

| Field | Required meaning |
| --- | --- |
| `method` | `vendor_total_return_index`; price adjustment names alone are insufficient |
| `series_id`, `provenance_id` | Same retained index scale at both endpoints and source evidence |
| `cash_dividends_embedded`, `splits_embedded` | Both explicitly true, supported by source review |
| `additional_cash_dividends_added` | Explicitly false: cash must not be added again |
| `available_at` | Actual aware time that the supporting evidence was available |
| `ex_date_coverage` | `date_basis="ex_date"`, inclusive `start`/`end` covering the label interval, `reviewed_complete=true` and an `evidence_id` |

These are checked evidence declarations, not independent authentication. Missing
proof keeps arithmetic diagnostics `Retrospective` and excludes them from the
formal split. Later evidence delays `label_available_at`; future evidence keeps
labels `Pending`, and a later review cannot enter an earlier training cutoff.
Optional sector returns without their own evidence are omitted. `raw_price`
remains retrospective; explicit synthetic fixtures test arithmetic only and
provide no observed predictive evidence. Do not relabel real archives synthetic.

`run_course.py` reports missing evidence/series fields. Its source manifest and
the baseline CLI provenance include the new module hash. Existing archived runs
are preserved. Twenty-six new regressions exercise the date, duplication,
evidence and temporal boundaries; market/text datasets, real trained models,
strategy profits and alpha remain unvalidated.


## Real corporate-action archive (October 19)

`corporate_action_archive.py` captures only the fixed read-only Alpaca
`/v1/corporate-actions` endpoint, using the existing local credential helper.
No credentials are printed or persisted in request logs. Successful HTTP response
bytes, hashes, query parameters, actual receipt after reading the body, and page
chain are retained. Choose a new private output directory. No feed switching,
orders, purchases or index reconstruction occurs.

```bash
python3 research/financial_sentiment_using_prices/corporate_action_archive.py \
  --capture --symbols PLTR AMZN MSFT SPY \
  --start 2026-09-01 --end 2026-10-16 --data-quality complete \
  --max-pages 3 --limit 1000 --output-dir /private/new_capture
python3 research/financial_sentiment_using_prices/corporate_action_archive.py \
  --archive /private/new_capture \
  --entry-session 2026-09-01 --exit-session 2026-09-30 \
  --output-dir /private/new_audit
```

Dates describe a **process-date query**. Reaching a null `next_page_token` means
only completion under that query. Page-budget truncation or HTTP/transport errors
are explicit and return exit 2. Offline audit checks raw hashes, receipts,
parameters, pagination continuity, provider IDs and conflicting versions. It also
accepts the first saved instrumented probe so successful data need not be fetched
again. Query completion never promotes ex-date coverage or total-return evidence.

Actual October 19 captures over August 1–November 30 and September 1–October 16
returned two and one unique events, respectively, on one completed page each.
Both include the same MSFT event (ex August 20, pay/process September 10).
Only the broad query includes SPY (ex September 18, pay/process October 30,
rate 1.888834). Three captured rows represent two provider events, not three
independent distributions. This directly demonstrates a narrow process-window
omission, not full coverage of the broader ex-date interval. The retained SSGA
schedule supports SPY's ex/pay date pair; it does not verify the rate, currency,
process date or total-return treatment.

The current endpoint documentation notes that default `data_quality=complete`
can omit unprocessed incomplete records and that availability can be delayed.
`--data-quality all` preserves missing ex-dates/rates as unknown rather than
inventing them; it also does not certify universal coverage. Currency absent from
the retained response stays null. No normalized record is silently certified for
ordinary entitlement or fed into a total-return index. Actual historical text
and index evidence remain missing: formal eligible labels stay zero and model
results remain `Not evaluated`. Thirteen new offline integrity regressions and
all 308 research tests passed in the actual repository on October 19.


## Real text candidate snapshot (October 19, next NLP step)

`prepare_text_candidates.py` reads a retained collector archive through the
existing raw-response binding checks and freezes company-tagged headlines and
bodies for an explicit decision session. Publication, revision, actual receipt,
input snapshot creation and prediction completion are separate fields. Shared
articles retain shared IDs. Event identities are not invented, missing bodies
stay empty, and neither prices nor outcomes are supplied to a text model.

```bash
python3 research/financial_sentiment_using_prices/prepare_text_candidates.py \
  --input-dir /private/news_capture --calendar /private/calendar.json \
  --symbols PLTR AMZN MSFT --decision-session 2026-10-20 \
  --as-of 2026-10-19T23:00:00Z --output-dir /private/new_text_candidates
```

Use the actual preparation clock when running. Outputs must be new and separate
from inputs. The candidate schema deliberately differs from the prepared model
dataset: it has no verified return label, reviewed event identity or prediction
completion time. It must not be passed off as an eligible training set.

The actual October 19 00:00–16:00 New York query returned 25 unique articles
(16 bodies), covering 27 company/article pairs: PLTR 3, AMZN 14, MSFT 10. The
October 20 input snapshot has three company-day candidates and zero eligible
training samples. Its ten-session calendar exit is November 3 at 14:30 UTC;
actual labels also require usable opening total returns and evidence available
at the applicable clock. No TF-IDF/linear model was fitted or evaluated.

Retained primary-source evidence establishes USD bar-price defaults, SPY's USD
fund/trading currency and NAV-reinvestment performance convention, and the
scope of Microsoft's split-adjusted closing lookup and investment calculator.
These facts do not certify corporate-action rate currency, full ex-date
coverage or an opening total-return index. Eight new timing/source regressions
and all 316 research tests passed in the actual checkout. Software success is
not predictive or trading evidence.


## Version-bound text/event review (October 20)

`text_event_review.py` validates an explicit assistant-review ledger against an
existing candidate snapshot and the retained raw archive. Every company/article
pair needs a disposition, exact text-version hash, rationale and supporting
character offsets/hash. Group definitions and each group link require evidence.
Reported events, historical/external events, and conservative context associations
are labeled separately; none is independently certified by this adapter.

```bash
python3 research/financial_sentiment_using_prices/text_event_review.py \
  --candidates /private/prepared_candidates/candidates.json \
  --review /private/review_ledger.json --input-dir /private/news_capture \
  --as-of 2026-10-20T14:30:00Z --training-cutoff 2026-10-19T12:00:00Z \
  --test-start 2026-10-20T13:30:00Z --test-end 2026-10-21T13:30:00Z \
  --output-dir /private/new_reviewed_readiness
```

Use the actual review/readiness clock; never backdate it. The original snapshot's
clocks, texts and all source IDs are retained. A proposed direct subset is a
separate field. Shared event/context IDs reach `event_cluster_ids`, including
multi-event links and retained context sources, for the existing transitive split
purger. A review created after the cutoff/deadline is explicitly flagged and
cannot count as a previously frozen selection or prediction.

Actual source review of the existing 27 pairs found 13 direct, 9 contextual,
1 unrelated and 4 uncertain pairs. Thirteen direct pairs include 6 headline-only
items. Five reported-event groups have support in multiple article IDs; one
Amazon article bridges a rating change and a nuclear project. These are assistant
annotations, not independent human evaluation or verified issuer-event truth.

The real readiness run delegates explicitly non-label `Unavailable` stubs to the
unchanged split gate: zero train/test, three excluded. No return label or model is
constructed, and eligible training samples remain zero. Opening total-return,
action coverage, independent confirmation and prediction/maturity requirements
remain unresolved. Thirteen new contract regressions and all 329 actual-checkout
research tests passed. This is engineering evidence, not alpha.


## Working daily collection and retrospective price model — October 21, 2026

This local slice completes capture → observed price-return labels → company-day features → chronological/source-proxy purging → four fixed baselines → explicit cost scenarios. The original ten-session **total-return** contract in `price_labels.py` remains unchanged and has zero independently eligible prospective examples. The new historical target excludes cash dividends and is explicitly retrospective. No alpha or actual account profit is established.

### Run the daily command

From the Quant project root (the launcher also resolves its own repository root):

```bash
./research/financial_sentiment_using_prices/run_daily.sh --overlap-minutes 1440
```

The launcher reuses an installed Python 3.11, including the verified macOS framework path; it installs nothing. `FIN_SENTIMENT_PYTHON` may select an existing compatible interpreter. Existing Alpaca credentials are read through the existing helper and are never printed or changed. The command executes once; it does not install a scheduled task.

On the first run, the default window looks back three calendar days. Later runs resume the saved cursor, with the explicit one-day overlap above. The default endpoint is **actual invocation time minus 20 minutes**, respecting delayed historical SIP access described in [Alpaca's FAQ](https://docs.alpaca.markets/us/docs/market-data-faq). `--end-at` supplies an explicit past timezone-aware endpoint; `--lag-minutes 0` is available for existing real-time access. No feed/subscription fallback occurs.

News uses the exact requested interval, including post-16:00, overnight and weekend publications. Daily bar queries independently begin at the corresponding New York date boundary, so an intraday rerun refreshes the retained session bars. An unfinished current daily bar remains a raw input, not a mature future outcome. The cursor advances only after complete news/bar query pagination; failure or a page cap retains the old cursor and the attempted archive. Every rerun gets a new capture directory. All old text versions and receipts remain intact; overlaps are not independent new events. Changes to articles whose publication falls outside the overlap are not guaranteed to be rediscovered.

Actual verification on October 21: four successful captures/reruns; the first acquired 31 unique news articles (22 with bodies). Repeats returned the same retained IDs, rather than another independent 31 examples. The final one-day-overlap run refreshed 16 daily bars across eight symbols. The original capture's bytes remained unchanged. Limits remain 50 symbols, 93 calendar days, 20 news pages × 50 rows, and one daily-bar page; caps are not market-coverage guarantees. Choose a new `--output-root` when changing the company pool.

### Reproduce the historical development slice

Use Python 3.11 with `requirements-experiments.txt`. The following directories must not already exist. On the verified Mac, the interpreter is `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11`.

```bash
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 research/financial_sentiment_using_prices/historical_backfill.py \
  --protocol research/financial_sentiment_using_prices/historical_protocol_a.json \
  --output-dir reports/financial_sentiment_runs/historical_reproduction/capture
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 research/financial_sentiment_using_prices/run_historical.py \
  --input-dir reports/financial_sentiment_runs/historical_reproduction/capture \
  --output-dir reports/financial_sentiment_runs/historical_reproduction/evaluation
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -m unittest discover -s research/financial_sentiment_using_prices/tests -v
```

`historical_protocol_a.json` freezes the configuration before fitting. It links the original registration hash and documents ticker mapping. `A` is Agilent Technologies on NYSE, checked against [its investor overview](https://www.investor.agilent.com/overview/default.aspx) and an indexed 2020 issuer release. A direct issuer-page snapshot returned 403 and was not bypassed; historical asset-master completeness is not claimed.

The collector pins the [original FNSPID](https://huggingface.co/datasets/Zihan1004/FNSPID) revision `bf9189c41527198897d1af3e17b1a0095279fc45` and retains only a 2 MiB prefix of `Stock_news/All_external.csv`, not the multi-gigabyte dataset. The first retained ticker was selected before price/model inspection. The prefix yielded 8,922 complete CSV records; `A` has 1,433 retained rows across 2009–2020, of which 356 fall in the registered 2016–2020 window. Bodies and supplied summaries/sentiment are not used. This is bounded, incomplete source coverage. Publisher rights and historical text versions are not independently certified; raw source material remains local. FNSPID's Viewer returned HTTP 500; the alternative mirror filter timed out, so neither is presented as a functioning retrieval route.

### Input and label dictionary

| Field or step | Definition |
| --- | --- |
| `source_date` | Vendor-reported calendar date; original timestamp string and actual current receipt are retained separately. |
| Input text | Original headline only, vendor ticker tags; 188/356 titles explicitly mention Agilent. This is not independent relevance gold. |
| Source/group identity | Canonical URL (identity query parameters retained), plus conservative near-headline links within seven days; not independently confirmed economic events. |
| Company-day | One company per delayed entry date, distinct headlines once, all source/group links retained, including excluded bridges. |
| Entry | Second XNYS session strictly after the reported source date; a conservative historical assumption, not a claimed historical receipt or prediction. |
| Target `excess_return` | `(A split-adjusted open at t+10 / open at t − 1) − (SPY split-adjusted open at t+10 / open at t − 1)`. Cash dividends excluded. |
| `price_class` | Rise above +0.5%, fall below −0.5%, otherwise neutral. These are relative-price classes, distinct from FinBERT prose tone. |
| Price features | Five-/twenty-session momentum ending at the **prior** session open; no entry open, current close or future outcomes in features. |
| TF-IDF | Up to 2,000 unigrams/bigrams, `min_df=2`, vocabulary/IDF fitted only on training text. |
| Models | Fixed ridge alpha 10; training mean, price-only, headline-only, price+headline; identical complete-case samples. |
| Availability | `observed_retrospective`, `historical_availability_verified=false`; actual predictions are generated now, not backdated. |

### Actual results and limits

The price archive contains 1,144 daily bars for each of A/SPY; all required symbols and the complete page-token chain were audited. No duplicate URL/headline rows were found. The 356 headlines on 181 reported dates map to 180 distinct company-days. All 180 have observed retrospective price outcomes; two lack prior momentum history, leaving **91 train / 87 test** rows. The fixed boundary is January 1, 2019. Training entries span February 18, 2016–November 26, 2018, with the last outcome December 11, 2018. Test entries span January 7, 2019–June 9, 2020; the last outcome is June 23, 2020. Shared URL/event proxies are purged transitively using the existing graph helper, without marking the rows prospectively Eligible.

| Model | Test MAE (percentage points) | RMSE (percentage points) |
| --- | --- | --- |
| train_mean | 2.5764 | 3.4473 |
| price_ridge | 2.6543 | 3.5217 |
| text_tfidf_ridge | 2.6013 | 3.4584 |
| price_text_ridge | 2.6850 | 3.5377 |

The combined text+price model did not improve on the training mean or price-only baseline. These are first historical development results, not a final untouched holdout or a supported alpha claim. Train/test price-class counts and per-sample predictions are saved, as are fitted vocabulary, IDF, scaling, coefficients, package versions and input/source/output hashes.

Only **25 non-overlapping ten-session intervals** are compounded; the other 62 overlapping test observations are not treated as sequential capital growth. Models take long/cash company positions from predicted relative-return sign, with always-company/SPY controls on exactly the same intervals. Each interval is closed/reopened conservatively. Results below exclude cash dividends and idle-cash interest, are not annualized, and do not represent an account or fill-verified strategy.

| Model/control | Round trips | Assumed 0 bp gross | Assumed 10 bp round trip | Assumed 20 bp round trip |
| --- | --- | --- | --- | --- |
| train_mean | 25 | 37.13% | 33.75% | 30.44% |
| price_ridge | 19 | 0.05% | -1.84% | -3.69% |
| text_tfidf_ridge | 24 | 37.28% | 34.03% | 30.84% |
| price_text_ridge | 18 | 20.00% | 17.86% | 15.76% |
| always_company | 25 | 37.13% | 33.75% | 30.44% |
| always_spy | 25 | 19.18% | 16.24% | 13.36% |

These are illustrative execution-cost scenarios, not confirmed Alpaca commissions or account deductions. Actual broker charges remain unknown. The always-company control outperformed the combined model; the nearly always-long text model did not establish incremental alpha.

The full **361-test research suite passed** after integration. Repeated offline runs reproduced `predictions.json`, `fitted_models.json`, `company_days.json` and `split.json` byte-for-byte, including a final run with integrity guards. This establishes current-environment reproducibility; a fresh environment/container run is still pending.

Local outputs are under `reports/financial_sentiment_runs/historical_development_20261021/` and `daily_610/`. Daily collection does not automatically train or predict for PLTR/AMZN/MSFT with this A-only model. Next work is a pre-registered broader company/time pool, independent relevance/event review, equal-budget tone/LM controls and course notebooks/report. The strict original total-return experiment still requires its own audited return-series and source-availability evidence.

## October 21: executed research notebook and fixed FinBERT comparison

[Research report](financial_sentiment.research_report.md) contains the real results,
source limitations and course requirement gaps. The new
[`financial_sentiment.research.ipynb`](financial_sentiment.research.ipynb) and paired
Python file execute the retained historical archive offline. All eight code cells
were executed successfully, including independent raw-price label recomputation,
split/event checks, six-model refitting and two saved figures. The existing API and
example notebooks remain unchanged.

Current verification: **373 research tests pass**. There are 180 observed
retrospective outcomes; two early days lack the prior momentum features, so every
model uses 91 training and 87 test days. The original strict total-return track
still has zero eligible labels. FinBERT's 338 distinct headlines / 352 headline
uses match TF-IDF inputs exactly and are all untruncated. Tone-only MAE is 2.7058
percentage points, price-plus-tone 2.8376, compared with 2.5764 for training mean.
The inspected development comparison does not establish alpha. See the report for
all controls, 25 non-overlapping cost intervals and the predeclared expansion's
coverage failures.

Local outputs are under `reports/financial_sentiment_runs/course_delivery_20261021/`.
`notebook_delivery/` contains the executed notebook and HTML. Raw archives and model
weights are private and are not automatically downloaded by the notebook. The
notebook needs the retained A archive, tone request/receipts and fixed registration;
each run creates a new private output directory. Its replay environment is
`requirements-course.txt`; FinBERT inference uses the existing separate NLP venv.

To create another same-budget comparison from the retained archive, use new output
directories (existing outputs are protected):

```bash
RESEARCH_PYTHON=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/finbert_comparison.py prepare \
  --capture reports/financial_sentiment_runs/historical_development_20261021/capture \
  --base reports/financial_sentiment_runs/historical_development_20261021/evaluation_verified \
  --registration research/financial_sentiment_using_prices/comparison_protocol_20261021.json \
  --output-dir reports/financial_sentiment_runs/my_tone_request

HF_HUB_OFFLINE=1 research/financial_sentiment_using_prices/.venv/bin/python \
  research/financial_sentiment_using_prices/finbert_comparison.py infer \
  --cached-snapshot "$HOME/.cache/huggingface/hub/models--Xenova--finbert/snapshots/8f269abebfdd9009d7d9b5e96af7e5c6bfe50b20" \
  --packet reports/financial_sentiment_runs/my_tone_request/tone_request.json \
  --output-dir reports/financial_sentiment_runs/my_tone_inference

"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/finbert_comparison.py evaluate \
  --base reports/financial_sentiment_runs/historical_development_20261021/evaluation_verified \
  --packet reports/financial_sentiment_runs/my_tone_request/tone_request.json \
  --features reports/financial_sentiment_runs/my_tone_inference/tone_features.json \
  --registration research/financial_sentiment_using_prices/comparison_protocol_20261021.json \
  --output-dir reports/financial_sentiment_runs/my_tone_comparison
```

The explicit snapshot path is optional, must name the pinned revision, and was
actually tested against the original offline loader: per-headline probabilities,
aggregates and model metadata were exactly equal. It requires all three existing
cached files and never downloads them. No price or target field is included in the
inference request. Evaluation checks input hashes and recomputes every aggregate
from its headline receipts. The cached FinBERT transformer is frozen; this is
training-only return calibration, not project-specific transformer fine-tuning.

To replay the notebook with the already installed research environment:

```bash
"$RESEARCH_PYTHON" -m nbconvert --to notebook --execute \
  --ExecutePreprocessor.timeout=120 \
  --output-dir reports/financial_sentiment_runs/my_notebook_export \
  research/financial_sentiment_using_prices/financial_sentiment.research.ipynb
```

Use a Python 3.11 kernel containing the listed research dependencies. The verified
execution used a task-local kernelspec pointing to the research Python; it did not
modify the user's registered kernel. The notebook makes no network requests.

`Dockerfile.research` and its narrow build-context ignore file prepare an additional
offline-replay image using `requirements-course.txt`. The old Dockerfile/scripts
are preserved. **Docker is unavailable on this Mac; this new image has not been
built or run.** When Docker is available, the intended local commands are:

```bash
docker build -f research/financial_sentiment_using_prices/Dockerfile.research \
  -t financial-sentiment-research research/financial_sentiment_using_prices
docker run --rm -v "$PWD:/workspace" -w /workspace financial-sentiment-research \
  python -m nbconvert --to notebook --execute --ExecutePreprocessor.timeout=120 \
  --output-dir reports/financial_sentiment_runs/my_docker_export \
  research/financial_sentiment_using_prices/financial_sentiment.research.ipynb
```

These container commands are prepared, not verified. The mounted private archive
is required; the model weights are unnecessary for replaying verified tone
receipts. No clean-environment or final-submission claim is made.

## October 21 continuation: bounded source search, three-company replay and PDF

The full research suite now passes **389 tests**. A separate, explicitly registered
2023 development study supplies 9,419 headline-company records (8,294 distinct
canonical URLs), 451 observed outcomes, and 272 training / 154 test rows after 25
cross-cutoff training outcomes are purged. See the updated
[research report](financial_sentiment.research_report.md) for per-company metrics,
costs, source failures and limitations. The original A 2016–2020 experiment,
FinBERT comparison and strict total-return contract remain separate.

`historical_ranges.py` retrieves exact, finite byte ranges from the pinned FNSPID
files, preserving actual offsets, original receipt timestamps, response hashes
and local ticker/date boundaries. The original 2016–2020 expanded window was
unavailable in both attempted files. The common 2023 source window and September 1
split were registered **before new price queries/outcomes**, based on source-date
coverage, not performance. No date or company was changed after inspecting these
new model results. Global corpus ordering and historical text availability remain
uncertified. Reused responses are verified and counted once in the transfer ledger.

The final registered aggregate ceiling was 256 MiB / 200 responses; actual transfer
was **107,723,488 bytes / 139 responses**. No full 23 GB corpus was downloaded.
Raw bodies remain private and are not model features. The separate study protocol
is `coverage_study_2023_protocol.json`; earlier registrations and failed attempts
remain available. All four original control settings were retained. Expanded
FinBERT/LM and transformer fine-tuning were not performed in this step.

The new `financial_sentiment.expansion.ipynb` and paired `.py` completed all **six**
code cells offline. They independently recompute all 451 labels and prior-price
features, check maturity and proxy-group separation, refit into new directories,
and assert byte-identical core outputs against the first CLI run. The executed
notebook, HTML, figures and receipts are in
`reports/financial_sentiment_runs/expanded_ranges_20261021/`.

To collect a new archive using this fixed development protocol, use new output
directories. These commands require the existing research dependencies and the
already-configured Alpaca read-only access for the company-price step:

```bash
RESEARCH_PYTHON=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/historical_ranges.py source \
  --registration research/financial_sentiment_using_prices/coverage_study_2023_protocol.json \
  --output-dir reports/financial_sentiment_runs/my_2023_source

"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/historical_ranges.py company \
  --source reports/financial_sentiment_runs/my_2023_source --symbol MSFT \
  --output-dir reports/financial_sentiment_runs/my_msft_2023_capture

"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/run_historical.py \
  --input-dir reports/financial_sentiment_runs/my_msft_2023_capture \
  --output-dir reports/financial_sentiment_runs/my_msft_2023_evaluation
```

The first source command is a bounded network retrieval. Replaying the notebooks
uses only the retained archive and makes no network calls. The manual daily
collector remains `./research/financial_sentiment_using_prices/run_daily.sh
--overlap-minutes 1440`; it is not an installed scheduler or validated current-day
predictor automatically using these historical models.

Docker was checked on PATH, common executable locations and sockets. The actual
`./research/financial_sentiment_using_prices/run_course_container.sh --check`
returned **127**, because no Docker executable is available. The helper passes
Bash syntax checking. When an approved local runtime exists, invoking the helper
without `--check` will build a unique image and execute the frozen A research
notebook with runtime network disabled and narrow archive/research mounts. It
does not mount backend credentials, install/start Docker, or change permissions.
The existing Docker files/scripts remain preserved. Container build/run is still
**unverified**; no installation was attempted.

The user-readable 8-page PDF is saved as
`reports/financial_sentiment_runs/expanded_ranges_20261021/delivery/MSML610_Research_Report_20261021.pdf`.
Its text, metrics, sample counts and SHA256 were checked. `export_report_pdf.py`
can export the Markdown report using the already installed optional packages
recorded in `requirements-report.txt`; no installation was performed:

```bash
"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/export_report_pdf.py \
  --source research/financial_sentiment_using_prices/financial_sentiment.research_report.md \
  --output reports/financial_sentiment_runs/my_research_report.pdf
```

Course completion still requires original total-return/availability evidence,
fair expanded controls and horizons, feasible transformer fine-tuning,
independently annotated attribution, Docker execution, formal course issue/PR and
the owner presentation/video. No alpha, final-submission or live-predictor claim
is made by these development results.

## October 21: registered expanded FinBERT comparison completed

The fixed 2023 rows now have six-control comparisons: the four existing controls
plus training-calibrated FinBERT tone and price-plus-FinBERT. All **426 paired rows**
(272 train / 154 test) are unchanged. The additional comparator was registered
after earlier development results had been inspected; it is not a fresh blind test.

Cached offline CPU inference completed in **128.94 seconds** within the registered
900-second shared budget / 930-second outer process cap. All three companies were
covered, with 8,710 same-budget headline uses, 6,948 actual distinct inferences,
maximum 55 tokens and no truncation or new row removal. Per-company scalers/Ridge
alpha10 were fitted on training only. A required headline failure makes the whole
company comparator unavailable, preserving original baselines and denominators.

**396 research tests pass.** The existing `financial_sentiment.expansion.ipynb`
and paired Python file now have **nine executable cells**, all actually executed
offline. They use retained tone receipts rather than repeating tensor inference,
check training-only means/IDs, and require identical six-model predictions,
calibration parameters and cost intervals. Older executed versions remain saved.
Current artifacts are under `reports/financial_sentiment_runs/finbert_2023_20261021/`.

Price-plus-FinBERT MAE is A 5.4223pp, AMZN 3.7507pp and MSFT 2.4564pp. A/AMZN
worsen against price-only; MSFT improves slightly. Both added controls stay in
cash on A cost intervals and equal always-company exposure/returns on AMZN/MSFT.
These development results do not establish incremental timing returns or alpha.
The frozen transformer itself was not fine-tuned. See the updated
[separate comparison report](financial_sentiment.finbert_2023_report.md)
for all metrics, costs and the exact official multi-horizon/attribution scope.

Preparation uses the installed research Python:

```bash
RESEARCH_PYTHON=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/expanded_finbert.py prepare \
  --repo "$PWD" --registration research/financial_sentiment_using_prices/finbert_2023_protocol.json \
  --output-dir reports/financial_sentiment_runs/my_finbert_2023/prepare
```

The `infer` subcommand uses the existing NLP venv with `HF_HUB_OFFLINE=1`, the
registered cached snapshot, that prepared packet root and a **new** output directory.
The actual run additionally used a Python subprocess timeout of 930 seconds; its
result and complete progress are retained in `outer_budget_result.json` and
`inference.log`. No model download or installation was performed. Evaluation uses
the existing `finbert_comparison.py evaluate` interface for each company and checks
all bindings. Existing outputs are protected from overwrite.

The existing Library eight-page report is the earlier source-expansion snapshot.
This step's latest results are the separate comparison report and nine-cell executed
notebook/HTML. LM, multiple horizons, transformer fine-tuning, independently
evaluated attribution, original strict evidence, Docker and final submission/video
remain unfinished. This step did not start those extra experiments.


## October 21: registered multi-horizon development comparison completed

The fixed 2023 A / AMZN / MSFT source pool and September 1 split now have separate
5/10/20-session **raw and SPY-excess price-return** comparisons. These horizons are
project choices, not a course-prescribed list. Both targets exclude dividends;
the original strict ten-session total-return track remains separate and has zero
eligible labels. This is development sensitivity, not blind confirmation or alpha.

The 36 registered combinations completed offline in 19.23 seconds. Horizon-specific
used counts are 440 / 426 / 400 (train 286 / 272 / 246; test 154 each), from the same
451 observed company-days. Maturity exclusions are 14 / 25 / 51, with no missing
observed endpoints. Common-ID sensitivity uses exactly 246 training and 154 test
rows at every horizon, without return- or cache-dependent row selection. Original
full-pool ten-session excess results are retained after exact split/hash checks.

Full-pool five-session added FinBERT controls are explicitly unavailable for all
three companies because some newly mature training titles lack cached inference.
All four baselines keep every row. Ten/twenty-session and all common-ID tone
comparisons have complete coverage; no tensor inference or downloads are repeated.
The saved tables contain 204 measured model slots, 12 unavailable slots and 936
assumed-cost scenarios, with non-overlapping intervals and session exposure. Daily
bar timestamps certify aggregation dates, not exact auction/trade/fill timestamps.

**408 research tests pass.** The separate
[multi-horizon notebook](financial_sentiment.multi_horizon.ipynb) has **7 executed
code cells, zero errors and exact reproduction of all 36 prediction/metric/cost
comparisons** in 22.15 seconds. See the separate
[report](financial_sentiment.multi_horizon_report.md) for all counts, targets,
MAE tables, exclusions, price-timestamp limits and cost assumptions. Prior reports
and the delivered eight-page PDF remain unchanged.

```bash
RESEARCH_PYTHON=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/multi_horizon.py \
  --repo "$PWD" \
  --registration research/financial_sentiment_using_prices/multi_horizon_2023_protocol.json \
  --output-dir reports/financial_sentiment_runs/my_new_multi_horizon_run
```

Choose a new private output directory; existing output is rejected. Retained data
and tone receipts are required, but no credentials or network calls are used.
Artifacts: `reports/financial_sentiment_runs/multi_horizon_2023_20261021/`, including
`delivery/metrics.csv`, `coverage.csv`, `cost_scenarios.csv`, and executed notebook/HTML
in `notebook_delivery/`. Remaining course work: LM baseline, price-label transformer
fine-tuning, independent large-move attribution gold evaluation, strict availability
and total-return evidence, Docker execution and owner-authorized submission/video.


## October 21: official Loughran–McDonald baseline completed

The official project's Milestone 2 explicitly specifies the **Loughran–McDonald
dictionary**; LM here means that financial lexicon. The official Notre Dame source
permits academic research, while commercial use needs separate licensing. Its
1993–2025 CSV was obtained anonymously (9,093,460 bytes, SHA-256
`e2d1328682bab7d2187684fb9f5420bb730401c9eefc00daf835edd203f4859d`).
Raw dictionary and permission/retrieval receipts remain in the ignored private
run directory, with no commercial deployment or redistribution claim. The current
version was retrieved in 2026 and does not certify a 2023 as-of dictionary.

The registered score counts positive-minus-negative word occurrences divided by
retained ASCII tokens, then equally averages distinct original headlines per
company-day. No-match titles retain numeric zero and explicit diagnostics. Two
training-only Ridge controls (LM and price-plus-LM) now cover all 36 fixed 2023
company/horizon/target/pool cases. All 451 company-days have a score; 5,235 of 7,293
distinct titles have no polarity hit and no rows are selectively removed. Original
rows, labels, controls and cost intervals are unchanged; existing baselines are not
refitted. The resulting tables have 276 measured model slots and the same 12
unavailable prior FinBERT slots, plus 1,152 assumed-cost scenarios. Development
results are inconsistent and do not establish alpha.

**422 research tests pass**, including 14 added LM tests. The separate
[LM notebook](financial_sentiment.lm.ipynb) has **7 executed code cells, zero errors
and exact reproduction of all 36 cases**, including original predictions/costs,
new calibrations, scores, metrics and paired losses. Execution took 7.86 seconds;
the primary comparison took 3.16 seconds. See the independent
[LM report](financial_sentiment.lm_report.md) for official meaning/license evidence,
the preregistered score, full counts, both targets/pools, all controls and limitations.
Previous reports and the delivered PDF remain unchanged.

```bash
RESEARCH_PYTHON=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
"$RESEARCH_PYTHON" research/financial_sentiment_using_prices/lm_baseline.py \
  --repo "$PWD" \
  --registration research/financial_sentiment_using_prices/lm_2023_protocol.json \
  --output-dir reports/financial_sentiment_runs/my_new_LM_run
```

Use a new private output directory and retain the versioned dictionary/receipts
and fixed archives. Reruns are offline and do not retrieve resources or accept
terms. Artifacts are under `reports/financial_sentiment_runs/lm_2023_20261021/`:
`evaluation/`, `delivery/` CSVs and `notebook_delivery/` executed notebook/HTML.
Both raw and excess targets exclude dividends; strict total-return eligible labels
remain zero. Remaining course work is transformer fine-tuning, independent
attribution evaluation, strict clock/return evidence, Docker execution and
owner-authorized video/submission. This bounded slice starts none of those tasks.


## October 28: saved Quant.ai signals and read-only inspection

The current signal explorer reads the frozen `comparison_v1` replay under
`reports/quant_logic_review_20261028/`. It covers NVDA, SNDK and TSLA over 32
sessions, September 14–October 27, 2026: 96 company/session series and 7,296
company-level decisions. A is the original five-minute price model; C is the
thirty-minute price-only control; B adds a residual text correction to C at the
same horizon. The snapshot records 50 nonzero company forecast corrections.
This count is neither a count of changed orders nor evidence of higher profit.

The existing Quant.ai React research view displays price bars, actual saved
simulated holdings and fill markers, A/C/B forecasts, full/effective text
corrections, and linear feature contributions. Near the session exit, C/B's
effective horizon is explicitly shortened. Later realized price returns are
separate retrospective diagnostics at the matching horizon, not decision inputs
or portfolio PnL. Contributions reconcile the intercept, clipping and saved
rounding; they explain model arithmetic, not why the market moved.

Text eligibility requires verified receipt plus a declared simulated 60-second
processing delay. Displayed evidence has only two distinct receipt dates
(October 12 and 21); a 48-hour window can reuse one batch across decision dates.
New October 28 collections are not backfilled into this replay. Unknown text,
unavailable calibration and a deliberate zero correction remain distinct states.
The default NVDA/October 23 selection is the earliest nonzero correction, chosen
without ranking subsequent profit.

From the repository root, reproduce the public snapshot and local view with:

```bash
python3.11 scripts/export_quant_signal_explorer.py
python3.11 scripts/render_quant_signal_explorer.py
npm --prefix frontend run build
python3.11 scripts/serve_financial_sentiment_preview.py --port 8138
```

Open `http://127.0.0.1:8138/?tab=financial_sentiment`. This dedicated preview serves saved research
routes, rejects mutation requests, restricts browser connections to its own
origin, and does not import the trading API or brokerage services. Building or
exporting this view does not run the strategy. The original trading application
has separate local controls; the preview is the reproduction entry point here.

`GET /api/research/financial-sentiment/signals` validates the public whitelist,
source clocks, horizon arithmetic, saved contributions and later price endpoints.
It serves a cached, pre-serialized response with gzip/ETag support; changing the
file invalidates the cache and triggers validation. Invalid snapshots fail closed.
The deterministic `reports/financial_sentiment_signal_explorer.json.gz` is the
small public artifact; the full-precision `.json` stays local. A gzip-only deployment
is supported with bounded decompression. The private export audit records input,
generator and output hashes. Article bodies, local paths and account identifiers
are excluded. The static `.png` is a companion view of the same saved data.


## October 28: SEC CompanyFacts collection attempt

The bounded collector in `company_facts.py` supports reported revenue, operating
income, net income, operating cash flow, cash and total assets. It preserves units,
filing versions and reported duration; cumulative six/nine-month values are not
silently treated as quarterly figures. A filing date alone does not establish
historical pipeline availability, and numerical facts do not replace filing
narrative or a reviewed investment thesis.

The actual October 28 attempt made **five SEC requests, all HTTP 403**: four fresh
submissions/identity requests for NVDA, SNDK, TSLA and PLTR, followed by one SNDK
CompanyFacts request using a previously verified official submissions archive.
This was one CompanyFacts request, not five successful company downloads.
**Zero companies supplied usable financial facts.** Metric coverage and eight-quarter
coverage therefore remain unknown, not zero. No automatic investment rating or
fundamental alpha was produced. Responses and failure reasons are retained under
`reports/financial_sentiment_runs/continuation_20261028/company_facts/`; access
restrictions were not bypassed. This work does not change the A/C/B replay.


## October 28: independent 2023 price-label BERT experiment

The new registration `price_bert_2023_protocol_v2_20261028.json` retains the old
protocol and its artifacts. It uses the official Apache-2.0
`google-bert/bert-base-uncased` checkpoint at the registered revision. Only the
last encoder layer and a scalar regression head are updated; embeddings and
earlier layers remain frozen. This is partial-model fine-tuning of BERT, not
FinBERT fine-tuning or full-model training.

The experiment uses Agilent (A), Amazon (AMZN) and Microsoft (MSFT). Company ticker
A is not the original Quant.ai strategy A. It uses a fixed September 1, 2023
split and a ten-trading-session company-minus-SPY split-adjusted price-return
target. It predicts a relative price reaction, not a human sentiment category.
Each company's model starts independently from the same checkpoint. All distinct
retained headlines for one company-day are averaged into one prediction and one
equal-weight training loss; headlines do not become independent price labels.
Training uses one fixed epoch, 272 company-days and 272 actual optimizer steps,
without held-out checkpoint selection or hyperparameter search.

All 154 held-out predictions were generated and saved before their outcome labels
were opened. Training and evaluation completed with all three companies and 272
actual optimizer steps. Eight existing controls keep their saved predictions and
identical rows. The independent run's aggregate results are in
[`reports/financial_sentiment_price_bert.json`](../../reports/financial_sentiment_price_bert.json); detailed receipts and model states
remain under `reports/financial_sentiment_runs/price_bert_20261028_v2/`.
The isolated `requirements-price-bert.txt` environment is for this experiment
only and must not be used as the app environment. Training is not a deployment
step, and exporting the signal view never retrains this model.

Held-out MAE below is in **percentage points of ten-session SPY-excess price
return**; smaller is better. Direction accuracy is the sign of that relative
return, not the direction of the stock's absolute return.

| Company | Train / held-out rows | Price-label BERT MAE | Training-mean MAE | Price-only Ridge MAE | BERT direction accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Agilent (A) | 52 / 28 | 5.6832 pp | 5.6557 pp | 5.3556 pp | 32.14% |
| Amazon (AMZN) | 110 / 61 | 2.7115 pp | 3.2371 pp | 3.5316 pp | 39.34% |
| Microsoft (MSFT) | 110 / 65 | 2.5896 pp | 2.5281 pp | 2.4826 pp | 69.23% |

AMZN's magnitude error improves in this development sample, while its direction
accuracy is below the training-mean control's 50.82%. Agilent and Microsoft do
not improve MAE over that simple control. Microsoft's 69.23% direction accuracy
equals the constant training-mean baseline. These mixed results do not justify
promoting the model to live trading. All nine models' metrics and illustrative
cost scenarios are retained in the aggregate summary; sparse company intervals
are not Quant.ai portfolio profits.

The October 27 rehearsal remains a historical record of **zero actual optimizer
steps and 272 mock markers**. Its status is not rewritten by the later real run.
The signal explorer shows separate historical/current tracks. This 2023 model
does **not** feed the September–October 2026 A/C/B curves or change their recorded
holdings. Later-retrieved 2023 news lacks verified historical receipt clocks;
development metrics and illustrative interval returns do not establish live alpha.

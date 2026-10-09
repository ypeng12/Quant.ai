# Train_Financial_Sentinment_Analysis_Using_Prices

This Python research module tests whether text labels derived from subsequent price reactions can add information to Quant.ai. The directory preserves the spelling of the assigned project title. See the [owner's research plan](../../docs/financial_sentiment_using_prices_plan.md) for scope and milestones; this README describes reproduction.

**Status: Not trained / Not evaluated.** The module loads an existing audit, describes its fields, computes coverage, and checks exploratory price labels. No sentiment model, trading A/B experiment, or demonstrated return improvement is included.

## Course template adaptation

The module follows the API/example notebook structure of the [course starter template](https://github.com/gpsaggese/umd_classes/tree/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/project_template), reviewed at commit `60df5bc966d6da403eb54ee059372edc5cf20099`, including its [project creation tool](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/create_project.py) and [Docker instructions](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/project_template/docker_scripts.README.md).

This is a starter adapted to Quant's layout; the official creation tool was not run. Local utilities remove dependencies on the course repository root and `helpers_root`. Python 3.11 matches the verified research environment. The image name is lowercase, and Jupyter retains token authentication with a localhost-only host port. The assigned issue, final directory, branch naming, and submission must still follow the [course guidelines](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/README.md). No course PR has been submitted.

## Files

| File | Purpose |
|---|---|
| `financial_sentiment.API.ipynb` / `.API.py` | Loading API, field definitions, and small authorized local samples |
| `financial_sentiment.example.ipynb` / `.example.py` | Coverage, exclusions, and independent price-label recomputation |
| `financial_sentiment_utils.py` | Reusable read-only loading and validation |
| `Dockerfile` / `requirements.txt` | Python 3.11 and notebook dependencies; no trading SDK |
| `docker_build.sh` / `docker_bash.sh` / `docker_jupyter.sh` | Build, container commands, and Jupyter entry point |
| `docker_name.sh` / `utils.sh` / `run_jupyter.sh` | Image configuration, mounts, and startup |

Notebooks and scripts use Jupytext `ipynb,py:percent` pairing. After editing, run `jupytext --sync financial_sentiment.API.ipynb`; do the same for the example notebook.

## Data and reproducibility

The default input is `../../reports/market_impact_data_audit_20261007/`. Set `FINANCIAL_SENTIMENT_DATA_DIR` to another existing audit directory if needed. The module does not fetch replacement data. Missing or incomplete archives raise errors.

The local audit contains 187 news articles, 120 Futu query records representing 118 distinct post IDs, five trading sessions for seven price symbols, and SEC filing metadata. Of 203 article-stock candidate pairs, 90 satisfy the exploratory window requirements and involve 81 articles. The other 113 have recorded exclusion reasons. These counts are calculated from the archive when the notebooks run.

The exploratory entry is the first five-minute boundary after `max(created_at, updated_at) + 60 seconds`; exit is 60 minutes later. Labels compare stock and SPY opening-price returns within one trading session, ending no later than 15:55. Validation also checks candidate pairs, duplicate bars, archived hashes, and saved statistics. This verifies internal consistency; it does not establish historical text availability, independent events, causality, predictive performance, or returns after costs. Missing response-receipt timestamps in the first Futu snapshot remain missing.

Raw articles and posts remain local. A clean clone does not contain that corpus; reproduction requires the same authorized archive or an explicitly agreed replacement dataset. The public Quant.ai interface uses aggregate audit counts, not the private corpus.

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

## Quant.ai display and next steps

The production display belongs in the existing [Quant.ai Hugging Face app](https://huggingface.co/spaces/Ypeng12/quant-ai), under **Financial Sentiment**, immediately after Live Alpha. It shows aggregate historical coverage and the separate community database snapshot. A waiting feed is not evidence of successful continuous collection.

Next, establish ongoing collection with real receipt timestamps, implement sentiment baselines and price-label models, validate on time-separated data, and then compare equal-capital Quant.ai variants. Data-audit success alone does not establish predictive or trading value.

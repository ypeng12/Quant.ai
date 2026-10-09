#!/usr/bin/env bash
set -euo pipefail
FINANCIAL_SENTIMENT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FINANCIAL_SENTIMENT_ROOT"
FINANCIAL_SENTIMENT_PYTHON="${FINANCIAL_SENTIMENT_PYTHON:-python3.11}"
FINANCIAL_SENTIMENT_REQUIREMENTS="${FINANCIAL_SENTIMENT_REQUIREMENTS:-requirements-financial-sentiment.lock.txt}"
"$FINANCIAL_SENTIMENT_PYTHON" -m venv .venv
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Financial Sentiment Using Prices requires Python 3.11; select it with FINANCIAL_SENTIMENT_PYTHON."'
.venv/bin/python -m pip install -r "$FINANCIAL_SENTIMENT_REQUIREMENTS"
.venv/bin/python -m pip check
npm --prefix frontend ci
printf '\nFinancial Sentiment Using Prices dependencies are ready. Run: make financial-sentiment-dev\n'

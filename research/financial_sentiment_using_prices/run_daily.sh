#!/usr/bin/env bash
# One manual run. Reuses installed Python and existing local data credentials.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_dir"
if [[ -n "${FIN_SENTIMENT_PYTHON:-}" ]]; then
  research_python="$FIN_SENTIMENT_PYTHON"
elif command -v python3.11 >/dev/null 2>&1; then
  research_python="$(command -v python3.11)"
elif [[ -x /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 ]]; then
  research_python=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
else
  echo "Set FIN_SENTIMENT_PYTHON to an existing Python 3.11 interpreter with requirements-experiments.txt installed." >&2
  exit 2
fi
"$research_python" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Use the verified Python 3.11 environment"'
exec "$research_python" research/financial_sentiment_using_prices/daily_collection.py \
  --output-root reports/financial_sentiment_runs/daily_610 "$@"

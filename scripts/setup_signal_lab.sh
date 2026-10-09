#!/usr/bin/env bash
set -euo pipefail
SIGNAL_LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SIGNAL_LAB_ROOT"
SIGNAL_LAB_PYTHON="${SIGNAL_LAB_PYTHON:-python3.11}"
SIGNAL_LAB_REQUIREMENTS="${SIGNAL_LAB_REQUIREMENTS:-requirements-signal-lab.lock.txt}"
"$SIGNAL_LAB_PYTHON" -m venv .venv
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Signal Lab requires Python 3.11; select it with SIGNAL_LAB_PYTHON."'
.venv/bin/python -m pip install -r "$SIGNAL_LAB_REQUIREMENTS"
.venv/bin/python -m pip check
npm --prefix frontend ci
printf '\nSignal Lab dependencies are ready. Run: make signal-lab-dev\n'

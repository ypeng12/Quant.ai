#!/usr/bin/env bash
set -euo pipefail
# Keep Jupyter's generated authentication token enabled.
exec jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root \
    --ServerApp.root_dir=/workspace

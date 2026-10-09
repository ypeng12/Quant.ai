#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/utils.sh"
require_docker
set_run_options
docker run "${RUN_OPTIONS[@]}" "$IMAGE_NAME" bash "$@"

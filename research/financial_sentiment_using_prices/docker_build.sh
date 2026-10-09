#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/utils.sh"
require_docker
docker build --tag "$IMAGE_NAME" "$@" "$PROJECT_DIR"

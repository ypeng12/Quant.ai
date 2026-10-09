#!/usr/bin/env bash
# Adapt the UMD helpers to this project directory; do not source the Quant app.
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$PROJECT_DIR/docker_name.sh"

require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker is not installed. Use the documented local Python audit, or install Docker separately." >&2
        return 1
    fi
}

resolve_audit_dir() {
    local candidate="${FINANCIAL_SENTIMENT_DATA_DIR:-$PROJECT_DIR/../../reports/market_impact_data_audit_20261007}"
    if [[ ! -d "$candidate" ]]; then
        echo "Audit data is missing: $candidate. Set FINANCIAL_SENTIMENT_DATA_DIR to the retained archive." >&2
        return 1
    fi
    AUDIT_DIR="$(cd -- "$candidate" && pwd)"
    if [[ ! -f "$AUDIT_DIR/alpaca/exploratory_labels.json" ]]; then
        echo "The archive is incomplete: alpaca/exploratory_labels.json is missing." >&2
        return 1
    fi
}

set_run_options() {
    resolve_audit_dir
    RUN_OPTIONS=(--rm --init --workdir /workspace
        --volume "$PROJECT_DIR:/workspace"
        --volume "$AUDIT_DIR:/data/audit:ro"
        --env FINANCIAL_SENTIMENT_DATA_DIR=/data/audit)
    if [[ -t 0 && -t 1 ]]; then
        RUN_OPTIONS+=(-it)
    fi
}

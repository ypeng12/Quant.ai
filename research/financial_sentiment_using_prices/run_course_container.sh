#!/usr/bin/env bash
# Build locally, then replay the frozen notebook without runtime network access.
# Never starts/installs Docker, changes its permissions, or mounts credentials.
set -euo pipefail
research_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$research_dir/../.." && pwd)"
if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Docker unavailable: no docker executable on PATH. Install/start an approved local Docker environment separately; no container was built or run.' >&2
  exit 127
fi
if ! docker info >/dev/null; then
  printf '%s\n' 'Docker daemon unavailable or inaccessible. No permission, context, credential, or daemon settings were changed.' >&2
  exit 1
fi
if [[ "${1:-}" == '--check' ]]; then
  printf '%s\n' 'Docker executable and daemon are accessible.'
  exit 0
fi
if [[ $# -ne 0 ]]; then printf '%s\n' 'Usage: run_course_container.sh [--check]' >&2; exit 2; fi
history_dir="$repo_dir/reports/financial_sentiment_runs/historical_development_20261021"
course_dir="$repo_dir/reports/financial_sentiment_runs/course_delivery_20261021"
for required in "$history_dir/capture/manifest.json" "$course_dir/tone_request/tone_request.json" "$course_dir/tone_inference/tone_features.json"; do
  if [[ ! -f "$required" ]]; then printf 'Required retained input is missing: %s\n' "$required" >&2; exit 2; fi
done
run_name="$(date -u +%Y%m%dT%H%M%SZ)-$$"
result_dir="$course_dir/docker_replay_$run_name"
mkdir -m 700 "$result_dir"
printf '*\n' > "$result_dir/.gitignore"
image_tag="financial-sentiment-research:$run_name"
docker build -f "$research_dir/Dockerfile.research" -t "$image_tag" "$research_dir" > "$result_dir/build.log" 2>&1
container_result="/workspace/reports/financial_sentiment_runs/course_delivery_20261021/docker_replay_$run_name"
docker run --rm --network none --read-only --tmpfs /tmp \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$research_dir,target=/workspace/research/financial_sentiment_using_prices,readonly" \
  --mount "type=bind,source=$history_dir,target=/workspace/reports/financial_sentiment_runs/historical_development_20261021,readonly" \
  --mount "type=bind,source=$course_dir,target=/workspace/reports/financial_sentiment_runs/course_delivery_20261021" \
  -w /workspace -e MPLCONFIGDIR=/tmp/matplotlib -e IPYTHONDIR=/tmp/ipython \
  -e JUPYTER_RUNTIME_DIR=/tmp/jupyter -e XDG_CACHE_HOME=/tmp/cache \
  "$image_tag" python -m nbconvert --to notebook --execute \
  --ExecutePreprocessor.timeout=120 --output-dir "$container_result" \
  /workspace/research/financial_sentiment_using_prices/financial_sentiment.research.ipynb \
  > "$result_dir/replay.log" 2>&1
printf 'Docker notebook replay completed: %s\n' "$result_dir"

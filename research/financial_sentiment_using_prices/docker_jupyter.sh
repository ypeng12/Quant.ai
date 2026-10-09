#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/utils.sh"
HOST_PORT=8890
while getopts "hp:" option; do
    case "$option" in
        h) echo "Usage: $0 [-p PORT] (default: 8890; binds only to 127.0.0.1)"; exit 0 ;;
        p) HOST_PORT="$OPTARG" ;;
        *) exit 2 ;;
    esac
done
shift $((OPTIND - 1))
if [[ $# -ne 0 || ! "$HOST_PORT" =~ ^[0-9]{1,5}$ ]] || ((10#$HOST_PORT < 1 || 10#$HOST_PORT > 65535)); then
    echo "Provide only -p with a port between 1 and 65535." >&2
    exit 2
fi
require_docker
set_run_options
echo "Open the token-bearing URL printed by Jupyter; replace its port with $HOST_PORT if needed."
docker run "${RUN_OPTIONS[@]}" --publish "127.0.0.1:$HOST_PORT:8888" \
    "$IMAGE_NAME" bash /workspace/run_jupyter.sh

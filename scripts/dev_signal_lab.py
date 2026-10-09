#!/usr/bin/env python3
"""Start the isolated Signal Lab API and UI; Ctrl-C stops both process groups."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def check_port(port: int) -> None:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Port {port} is in use. Select different --api-port / --ui-port values.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8001)
    parser.add_argument("--ui-port", type=int, default=5175)
    args = parser.parse_args()
    if args.api_port == args.ui_port or not all(1024 <= n <= 65535 for n in [args.api_port, args.ui_port]):
        parser.error("Use two different ports between 1024 and 65535.")
    python = ROOT / ".venv/bin/python"
    npm = shutil.which("npm")
    if not python.exists() or not npm or not (ROOT / "frontend/node_modules/vite").exists():
        raise SystemExit("Run `make signal-lab-setup` to prepare Python and frontend dependencies.")
    check_port(args.api_port)
    check_port(args.ui_port)
    processes = []
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    env = os.environ.copy()
    env["SIGNAL_LAB_API_URL"] = f"http://127.0.0.1:{args.api_port}"
    try:
        processes.append(subprocess.Popen(
            [str(python), "-m", "uvicorn", "backend.signal_lab.api:app", "--host", "127.0.0.1",
             "--port", str(args.api_port), "--reload", "--reload-dir", str(ROOT / "backend/signal_lab")],
            cwd=ROOT, env=env, start_new_session=True))
        processes.append(subprocess.Popen(
            [npm, "run", "dev:signal-lab", "--", "--host", "127.0.0.1", "--port", str(args.ui_port)],
            cwd=ROOT / "frontend", env=env, start_new_session=True))
        print(f"Signal Lab: http://127.0.0.1:{args.ui_port}/signal-lab.html", flush=True)
        print(f"API docs: http://127.0.0.1:{args.api_port}/docs", flush=True)
        while not stopping:
            for child in processes:
                if child.poll() is not None:
                    return child.returncode or 1
            time.sleep(.25)
        return 0
    finally:
        for child in processes:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in processes:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    sys.exit(main())

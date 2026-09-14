#!/usr/bin/env python3
"""Explicitly manage a local macOS data-only Alpaca L1 launch agent.

The launch agent contains paths only, never credentials. A small source
snapshot outside Desktop avoids reliance on iCloud placeholder files. No
trading modules are copied or imported.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.market_data.history import credentials, validate_symbol

LABEL = "com.quantai.l1-capture"
SOURCES = (
    "scripts/capture_alpaca_l1.py",
    "backend/app/market_data/alpaca_l1_capture.py",
    "backend/app/market_data/history.py",
    "backend/app/research/universe.py",
)


def service_config(python: str, runtime: Path, output: Path, env_file: Path,
                   symbols: list[str], feed: str, logs: Path, *,
                   prevent_sleep_ac: bool = False) -> dict:
    command = [python, "-u", str(runtime / "scripts/capture_alpaca_l1.py"),
               "--symbols", *symbols, "--feed", feed,
               "--output-dir", str(output), "--env-file", str(env_file)]
    if prevent_sleep_ac:
        # -s applies only on AC power and expires when the utility exits. This
        # neither keeps the display awake nor changes global power settings.
        command = ["/usr/bin/caffeinate", "-s", *command]
    return {
        "Label": LABEL,
        "ProgramArguments": command,
        "WorkingDirectory": str(runtime), "RunAtLoad": True, "KeepAlive": True,
        # Collection was explicitly requested and must keep up with arriving
        # events. Standard still has light system limits; it is not a promise
        # of real-time scheduling or immunity to sleep/network interruption.
        "ThrottleInterval": 60, "ExitTimeOut": 30,
        "ProcessType": "Standard", "LowPriorityIO": False,
        "LowPriorityBackgroundIO": False, "Umask": 0o077,
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(logs / "stdout.log"),
        "StandardErrorPath": str(logs / "stderr.log"),
    }


def _process_info(pid: int) -> dict | None:
    """Read one process without exposing its command in status output."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,ppid=,command="],
            capture_output=True, text=True, timeout=2,
        )
        row = result.stdout.strip().split(None, 2)
        if result.returncode or len(row) != 3 or int(row[0]) != pid:
            return None
        return {"pid": pid, "ppid": int(row[1]), "args": shlex.split(row[2])}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def collector_process_relation(running_pid: int | None, status: dict | None,
                               runtime: Path, *, inspect_process=None) -> str:
    """Verify both process identity and optional caffeinate supervisor.

    A status file from a previous run, a reused PID, or an unrelated Python
    process must not be reported as the live collector.
    """
    inspect_process = inspect_process or _process_info
    pid = status.get("pid") if isinstance(status, dict) else None
    if (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0
            or not isinstance(running_pid, int) or running_pid <= 0):
        return "unverified"
    collector = inspect_process(pid)
    script = str(runtime / "scripts/capture_alpaca_l1.py")
    if not collector or script not in collector.get("args", []):
        return "unverified"
    if pid == running_pid:
        return "direct"
    supervisor = inspect_process(running_pid)
    args = supervisor.get("args", []) if supervisor else []
    if (collector.get("ppid") == running_pid and len(args) >= 3
            and args[:2] == ["/usr/bin/caffeinate", "-s"] and script in args):
        return "caffeinate_child"
    return "unverified"


def received_age_seconds(status: dict | None) -> float | None:
    """Wall-clock diagnostic only; a recent write can contain stale quotes."""
    value = status.get("last_received_at") if isinstance(status, dict) else None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        return (datetime.now(timezone.utc) - timestamp).total_seconds()
    except (AttributeError, TypeError, ValueError):
        return None


def launchctl(*args: str):
    return subprocess.run(["launchctl", *args], text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "stop"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--symbols", nargs="+", default=["SNDK", "TSLA", "PLTR", "NVDA"])
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--prevent-sleep-ac", action="store_true",
                        help="Optionally hold an AC-only sleep assertion while the collector runs")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/share/quant-l1")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This service manager requires macOS; use capture_alpaca_l1.py directly elsewhere")
    state = args.state_dir.expanduser().resolve()
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    if args.action == "status":
        result = launchctl("print", target)
        manifest_path = state / "service.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        status_file = Path(manifest.get("data_dir", state / "data/live_iex")) / "capture_status.json"
        status = json.loads(status_file.read_text()) if status_file.exists() else None
        process = re.search(r"^\s*pid = (\d+)\s*$", result.stdout, re.MULTILINE)
        running_pid = int(process.group(1)) if process else None
        relation = collector_process_relation(running_pid, status, state / "runtime")
        print(json.dumps({"service_loaded": result.returncode == 0, "collector": status,
                          "running_pid": running_pid,
                          "collector_pid": status.get("pid") if status else None,
                          "collector_process_matches": result.returncode == 0 and relation != "unverified",
                          "collector_process_relation": relation,
                          "last_received_age_seconds": received_age_seconds(status),
                          "sleep_assertion_requested_ac_only": manifest.get("prevent_sleep_ac", False),
                          "state_dir": str(state)}, indent=2))
        return 0
    if args.action == "stop":
        result = launchctl("bootout", target)
        # Remove only the exact launch agent managed by this command.
        if plist.exists():
            plist.unlink()
        print(json.dumps({"service_stopped": result.returncode == 0, "autostart_removed": True}))
        return 0 if result.returncode == 0 else 1
    if not args.env_file:
        parser.error("install requires --env-file pointing to an existing private .env")
    if launchctl("print", target).returncode == 0 or plist.exists():
        parser.error("L1 service already installed; inspect status or explicitly stop it before replacing")
    env_file = args.env_file.expanduser().resolve()
    if not env_file.is_file():
        parser.error("Credential file does not exist")
    credentials(env_file)  # presence only; never serialize or print values
    symbols = list(dict.fromkeys(validate_symbol(s) for s in args.symbols))
    if not symbols:
        parser.error("At least one symbol required")
    runtime = state / "runtime"
    logs = state / "logs"
    output = state / "data" / f"live_{args.feed}"
    for directory in (runtime, logs, output):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    hashes = {}
    for relative in SOURCES:
        source = ROOT / relative
        destination = runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        hashes[relative] = hashlib.sha256(destination.read_bytes()).hexdigest()
    # Namespace packages avoid copying application initialization side effects.
    config = service_config(sys.executable, runtime, output, env_file, symbols, args.feed, logs,
                            prevent_sleep_ac=args.prevent_sleep_ac)
    plist.parent.mkdir(parents=True, exist_ok=True)
    with plist.open("xb") as handle:
        plistlib.dump(config, handle)
    plist.chmod(0o600)
    manifest = {"source_root": str(ROOT), "source_hashes": hashes, "symbols": symbols,
                "feed": args.feed, "data_dir": str(output), "service_label": LABEL,
                "prevent_sleep_ac": args.prevent_sleep_ac,
                "process_type": config["ProcessType"], "low_priority_io": False,
                "purpose": "market_data_collection_only", "credential_file": str(env_file)}
    (state / "service.json").write_text(json.dumps(manifest, indent=2) + "\n")
    result = launchctl("bootstrap", domain, str(plist))
    print(json.dumps({"installed": result.returncode == 0, "launchctl_exit_code": result.returncode,
                      "data_dir": str(output), "state_dir": str(state)}, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

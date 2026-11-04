"""Export the course checkpoint from Desktop/Quant's single source of truth.

An explicit source allowlist excludes credentials, trading code, raw captures,
account records, and local environments. Never merge changes back from an export.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research/financial_sentiment_using_prices"
BRANCH = "UmdTask861_MSML610_Fall2026_Train_Financial_Sentinment_Analysis_Using_Prices"
PUBLIC = ("financial_sentiment_price_bert.json", "financial_sentiment_strategy_comparison.json")


def export(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Use a new export directory; existing work is never overwritten")
    source_map = {}
    for source in (RESEARCH / "course").rglob("*"):
        relative = source.relative_to(RESEARCH / "course")
        if source.is_file() and not any(x in {"__pycache__", "executed", ".ipynb_checkpoints"} for x in relative.parts):
            if source.suffix in {".py", ".ipynb", ".md", ".txt", ".sh", ".json"} or source.name in {"Dockerfile", "etc_sudoers", "bashrc", ".dockerignore", ".gitignore"}:
                source_map[relative] = source
    # Research implementation and tests are preserved as a separately named
    # source tree, never confused with the portable evidence-audit entry points.
    for source in RESEARCH.glob("*.py"):
        source_map[Path("research_sources") / source.name] = source
    for source in (RESEARCH / "tests").glob("*.py"):
        source_map[Path("research_sources/tests") / source.name] = source
    for source in RESEARCH.glob("requirements*.txt"):
        source_map[Path("research_sources") / source.name] = source
    for name in PUBLIC:
        source_map[Path("public_results") / name] = ROOT / "reports" / name
    for source in RESEARCH.glob("financial_sentiment.*_report.md"):
        source_map[Path("research_reports") / source.name] = source
    destination.mkdir(parents=True)
    entries = {}
    for relative, source in sorted(source_map.items()):
        if source.is_symlink():
            raise ValueError(f"Symlinks are not exportable: {source.name}")
        raw = source.read_bytes()
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if source.suffix == ".sh":
            target.chmod(0o755)
        entries[str(relative)] = {"source": str(source.relative_to(ROOT)), "sha256": hashlib.sha256(raw).hexdigest()}
    manifest = {"sha256": {name: entries[f"public_results/{name}"]["sha256"] for name in PUBLIC}}
    (destination / "public_results/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    receipt = {"source_repository": "https://github.com/ypeng12/Quant.ai", "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "source_worktree_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest(),
               "course_issue": "https://github.com/gpsaggese/gpsaggese.github.io/issues/861", "branch": BRANCH,
               "scope": "checkpoint; independent attribution validation and student presentation pending", "files": entries}
    (destination / "source_manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return {"files": len(entries), "destination": str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(json.dumps(export(parser.parse_args().destination), indent=2))

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("cloud_research", ROOT / "scripts/cloud_profit_research.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def packet(tmp_path):
    path = tmp_path / "price.json"
    path.write_text("{}")
    manifest = dict(files={"price.json":hashlib.sha256(path.read_bytes()).hexdigest()},
                    contains_actual_account_transactions=False, contains_credentials=False)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_manifest_detects_input_mutation(tmp_path):
    packet(tmp_path)
    module.verify_packet(tmp_path)
    (tmp_path / "price.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="hash"):
        module.verify_packet(tmp_path)


def test_private_account_data_cannot_be_substituted(tmp_path):
    manifest = packet(tmp_path)
    manifest["contains_actual_account_transactions"] = True
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Account"):
        module.verify_packet(tmp_path)


def test_packet_cannot_read_outside_its_directory(tmp_path):
    packet(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["files"] = {"../outside": "irrelevant"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash"):
        module.verify_packet(tmp_path)

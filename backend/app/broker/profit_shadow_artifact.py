"""Materialize an optional private model, never fetch data or enable trading."""
import hashlib
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo


def prepare_shadow_artifact(backend_dir):
    raw = os.environ.get("QUANT_SHADOW_POLICY_JSON")
    configured = os.environ.get("QUANT_SHADOW_POLICY_PATH")
    if not raw and not configured:
        return None, {}
    path = Path(configured or ".runtime_state/profit_shadow/model.json")
    if not path.is_absolute():
        path = Path(backend_dir) / path
    metadata = {}
    if raw:
        content = raw.encode("utf-8")
        if len(content) > 65536:
            raise ValueError("Inline shadow model exceeds the configuration size")
        model = json.loads(raw)
        if not isinstance(model, dict) or model.get("kind") != "profit_signal_shadow_v1" or model.get("deployment") != "shadow_only":
            raise ValueError("Only a shadow model may be configured")
        # Full numerical validation happens in the observer before comparison.
        # Configuration is not trusted public text. Expose only known candidate
        # identifiers and a normalized session date, never arbitrary JSON fields.
        metadata = {"model_sha256": hashlib.sha256(content).hexdigest()}
        spec = model.get("spec")
        name = spec.get("name") if isinstance(spec, dict) else None
        if isinstance(name, str) and re.fullmatch(r"ridge(?:30_single|30_plan(?:_long_only)?|60_plan)(?:_refresh_price)?", name):
            metadata["candidate"] = name
        cutoff = model.get("trained_before")
        if isinstance(cutoff, str) and len(cutoff) <= 40:
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cutoff):
                    day = date.fromisoformat(cutoff)
                else:
                    stamp = datetime.fromisoformat(cutoff)
                    if stamp.tzinfo is None:
                        raise ValueError("Aware cutoff required")
                    stamp = stamp.astimezone(ZoneInfo("America/New_York"))
                    if (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) != (0, 0, 0, 0):
                        raise ValueError("Session cutoff must be midnight")
                    day = stamp.date()
                metadata["model_trained_before"] = day.isoformat()
            except ValueError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return str(path), metadata

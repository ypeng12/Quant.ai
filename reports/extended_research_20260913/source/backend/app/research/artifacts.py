"""Read-only artifact integrity checks; does not import application/broker config."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import math
ROOT=Path(__file__).resolve().parents[3]
DEFAULT=ROOT/'reports/platform_research_20260913_qp'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def published_input_path(name, root=None):
    """Relocate archived repository inputs without editing the signed registry.

    Only the reports subtree can move; the caller still verifies its original
    content hash. Prefer the deployment copy over an old workstation path.
    """
    root = Path(root) if root is not None else ROOT
    path = Path(name)
    if 'reports' in path.parts:
        relative = Path(*path.parts[path.parts.index('reports'):])
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to((root / 'reports').resolve()):
            raise ValueError('Input path escapes reports')
        if candidate.is_file():
            return candidate
    return path if path.is_absolute() else root / path


def checked_path(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Artifact path escapes bundle')
    return path


def load_platform_results(directory=DEFAULT):
    root=Path(directory)
    try:
        if digest(root/'registry.json') != (root/'registry.sha256').read_text().strip():
            raise ValueError('Registry checksum mismatch')
        registry=json.loads((root/'registry.json').read_text())
        if registry.get('status')!='complete':raise ValueError('Experiment incomplete')
        if not registry.get('artifact_hashes'):raise ValueError('Missing artifact checksums')
        for name,expected in registry['artifact_hashes'].items():
            if digest(checked_path(root,name))!=expected:raise ValueError(f'Artifact checksum mismatch: {name}')
        for symbol,expected in registry['data_hashes'].items():
            if digest(published_input_path(registry['data_paths'][symbol]))!=expected:raise ValueError(f'Data checksum mismatch: {symbol}')
        for name,expected in registry.get('l1_input_hashes',{}).items():
            if digest(published_input_path(name))!=expected:raise ValueError('L1 input checksum mismatch')
        for trial in registry['trials']:
            if trial['status']!='complete':continue
            s=trial['summary']
            amounts=[s['net_pnl'],s['gross_pnl'],s['costs'],s['starting_equity'],s['ending_equity'],s['turnover_dollars']]
            if not all(math.isfinite(v) for v in amounts):raise ValueError('Nonfinite summary')
            def same(a,b):return math.isclose(a,b,abs_tol=1e-6,rel_tol=1e-10)
            if not same(s['gross_pnl']-s['costs'],s['net_pnl']) or not same(s['ending_equity']-s['starting_equity'],s['net_pnl']):
                raise ValueError('Summary PnL mismatch')
            if not same(s['costs'],s['turnover_dollars']*trial['cost_bps']/10000):raise ValueError('Summary cost mismatch')
            if not same(sum(v['net_pnl'] for v in trial['per_symbol'].values()),s['net_pnl']):raise ValueError('Symbol attribution mismatch')
        registry['source_matches_workspace']={name:(ROOT/name).is_file() and digest(ROOT/name)==expected for name,expected in registry['sources'].items()}
        # Published results describe their recorded source hashes, even if code subsequently evolves.
        return dict(success=True,status='complete',research=registry)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return dict(success=False,status='unavailable',reason=str(exc))

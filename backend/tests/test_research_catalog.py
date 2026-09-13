import ast
from pathlib import Path
import sys
import hashlib
import json
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from app.research import catalog
from app.research import artifacts
from app.research.platform import features_for_panel
from test_quant_policy import session


def test_api_delegates_to_read_only_catalog_without_application_startup(monkeypatch):
    source=Path(__file__).resolve().parents[1]/'main_api.py'
    tree=ast.parse(source.read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='get_platform_research_results')
    fn.decorator_list=[]
    # Evaluate only this inert handler; importing main_api would start the broker.
    namespace={};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),namespace)
    calls=[]
    def fake(name):calls.append(name);return dict(status='complete')
    monkeypatch.setattr(catalog,'research_bundle',fake)
    assert namespace['get_platform_research_results']('thirty_two_weeks')['status']=='complete'
    assert calls==['thirty_two_weeks']


def test_catalog_never_interprets_request_as_path():
    assert catalog.research_bundle('../../backend/.env')['status']=='unavailable'


def test_published_bundle_relocates_inputs_and_still_rejects_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, 'ROOT', tmp_path)
    bars = tmp_path / 'reports' / 'inputs' / 'A.parquet'
    bars.parent.mkdir(parents=True)
    bars.write_bytes(b'original bars')
    bundle = tmp_path / 'reports' / 'study'
    bundle.mkdir()
    (bundle / 'detail.json').write_text('{}')
    registry = dict(status='complete', artifact_hashes={'detail.json': artifacts.digest(bundle / 'detail.json')},
                    data_paths={'A': '/old/workstation/reports/inputs/A.parquet'},
                    data_hashes={'A': artifacts.digest(bars)}, sources={}, trials=[])
    (bundle / 'registry.json').write_text(json.dumps(registry))
    (bundle / 'registry.sha256').write_text(artifacts.digest(bundle / 'registry.json'))
    assert artifacts.load_platform_results(bundle)['status'] == 'complete'
    bars.write_bytes(b'tampered bars')
    result = artifacts.load_platform_results(bundle)
    assert result['status'] == 'unavailable' and 'Data checksum mismatch' in result['reason']
    with pytest.raises(ValueError, match='escapes reports'):
        artifacts.published_input_path('/old/reports/../../backend/.env')


def test_market_residual_uses_same_completed_bar_and_past_beta_only():
    frames={s:pd.concat([session('2026-09-08',n),session('2026-09-09',n+1),session('2026-09-10',n+2)]) for s,n in [('SPY',1),('A',5),('B',9)]}
    all_features=features_for_panel(frames,'context')
    assert 'market_residual_1' in all_features['A'] and 'market_residual_1' not in all_features['SPY']
    earlier=features_for_panel({s:f.iloc[:-40] for s,f in frames.items()},'context')
    for s in earlier:pd.testing.assert_frame_equal(earlier[s],all_features[s].iloc[:-40])

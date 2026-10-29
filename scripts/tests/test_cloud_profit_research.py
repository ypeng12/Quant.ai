"""Small artificial packets only: no real fitting, market replay or network."""
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
    names={f'{s}.parquet' for s in module.INPUTS}|{'decisions.jsonl.gz','training.json'}
    names|={f'baseline/cost_{cost}bps/{name}/{f}' for cost in (2,5)
            for name in ('A','B','C','equal_weight') for f in ('summary.json','daily.csv.gz','fills.csv.gz')}
    for name in names:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'artificial fixture; never parsed as market data')
    dates=module.pd.bdate_range('2026-09-14','2026-10-27').strftime('%Y-%m-%d').tolist()
    manifest=dict(schema_version=1,packet_id=module.PACKET_ID,prepared_at='2026-10-28T23:00:00Z',
        input_symbols=list(module.INPUTS),traded_symbols=list(module.SYMBOLS),starting_capital=50000.,
        start=dates[0],end=dates[-1],dates=dates,evaluation_kind='already_inspected_retrospective_development',
        source=module.PACKET_SOURCE,private_dataset_only=True,contains_actual_account_transactions=False,
        contains_credentials=False,contains_raw_news=False,
        files={n:hashlib.sha256((tmp_path/n).read_bytes()).hexdigest() for n in sorted(names)})
    save_manifest(tmp_path,manifest)
    return manifest


def save_manifest(folder,manifest):
    (folder/'manifest.json').write_text(json.dumps(manifest))


def test_manifest_requires_all_30_bound_numeric_files(tmp_path):
    manifest=packet(tmp_path)
    assert len(module.verify_packet(tmp_path)['files'])==30
    manifest['files'].pop('NVDA.parquet');save_manifest(tmp_path,manifest)
    with pytest.raises(ValueError,match='30 required'):module.verify_packet(tmp_path)


def test_manifest_detects_input_mutation(tmp_path):
    packet(tmp_path);(tmp_path/'NVDA.parquet').write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash'):module.verify_packet(tmp_path)


def test_unmanifested_extra_input_is_rejected_without_reading_it(tmp_path):
    packet(tmp_path);(tmp_path/'not_an_input.txt').write_text('fixture')
    with pytest.raises(ValueError,match='unmanifested'):module.verify_packet(tmp_path)


def test_missing_baseline_is_rejected(tmp_path):
    packet(tmp_path);(tmp_path/'baseline/cost_5bps/B/fills.csv.gz').unlink()
    with pytest.raises(ValueError,match='missing'):module.verify_packet(tmp_path)


@pytest.mark.parametrize('field,value',[
    ('contains_actual_account_transactions',True),('contains_credentials','false'),
    ('contains_raw_news',True),('private_dataset_only',False)])
def test_privacy_flags_are_strict_booleans(tmp_path,field,value):
    manifest=packet(tmp_path);manifest[field]=value;save_manifest(tmp_path,manifest)
    with pytest.raises(ValueError,match='privacy'):module.verify_packet(tmp_path)


@pytest.mark.parametrize('field,value',[
    ('packet_id','another_packet'),('schema_version',True),('traded_symbols',['NVDA']),
    ('starting_capital',1),('dates',['2026-10-27','2026-09-14']),('end','2026-10-26'),
    ('evaluation_kind','prospective_validation')])
def test_fixed_identity_dates_universe_and_capital(tmp_path,field,value):
    manifest=packet(tmp_path);manifest[field]=value;save_manifest(tmp_path,manifest)
    with pytest.raises(ValueError,match='contract'):module.verify_packet(tmp_path)


def test_packet_cannot_read_outside_its_directory(tmp_path):
    manifest=packet(tmp_path);manifest['files']['../outside']='0'*64;save_manifest(tmp_path,manifest)
    with pytest.raises(ValueError,match='30 required'):module.verify_packet(tmp_path)


def test_unexpected_manifest_fields_are_rejected(tmp_path):
    manifest=packet(tmp_path);manifest['extra']='not an allowed field';save_manifest(tmp_path,manifest)
    with pytest.raises(ValueError,match='schema fields'):module.verify_packet(tmp_path)


def test_failure_persists_day_progress_without_a_complete_summary(tmp_path,monkeypatch):
    out=tmp_path/'run'
    def fail(packet,destination,update):
        update(stage='running_text_ablations',completed_candidates=['fixture'],
               candidate_completed_dates={'fixture':['2026-09-14']})
        module.write(destination/'summary.partial.json',{'status':'partial'})
        raise RuntimeError('artificial failure')
    monkeypatch.setattr(module,'_execute',fail)
    with pytest.raises(RuntimeError):module.execute(tmp_path/'unused',out)
    progress=json.loads((out/'progress.json').read_text())
    assert progress['status']=='failed'
    assert progress['candidate_completed_dates']=={'fixture':['2026-09-14']}
    assert progress['stage_at_failure']=='running_text_ablations'
    assert not (out/'summary.json').exists()
    assert json.loads((out/'summary.partial.json').read_text())['status']=='partial'


def test_incomplete_ablation_cannot_create_overall_completion(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'_execute',lambda *args:{'status':'complete','text_ablations_status':'failed'})
    out=tmp_path/'run'
    with pytest.raises(ValueError,match='completed text'):module.execute(tmp_path/'unused',out)
    assert json.loads((out/'progress.json').read_text())['status']=='failed'
    assert not (out/'summary.json').exists()


def test_success_publishes_complete_summary_only_after_all_components(tmp_path,monkeypatch):
    expected={'status':'complete','text_ablations_status':'complete','duration_seconds':0.25,
              'candidates':{'fixture':{'net_pnl':12.34}}}
    def success(packet,destination,update):
        assert not (destination/'summary.json').exists()
        update(stage='running_text_ablations')
        return expected
    monkeypatch.setattr(module,'_execute',success)
    out=tmp_path/'run';result=module.execute(tmp_path/'unused',out)
    assert result==expected
    assert json.loads((out/'summary.json').read_text())==expected
    assert json.loads((out/'progress.json').read_text())['status']=='complete'

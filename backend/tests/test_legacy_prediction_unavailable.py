"""Classic display endpoints expose provenance, never pass archives off as live."""
import ast
from pathlib import Path
from typing import Optional

def handler(name):
    source=Path(__file__).resolve().parents[1]/'main_api.py'
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[];scope={'Optional':Optional}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
    return scope[name]

def test_archived_ml_cards_are_available_and_labelled():
    result=handler('get_ml_prediction')(' tsla ')
    assert result['success'] and result['ticker']=='TSLA'
    assert result['status']=='archived_demo'
    assert result['data_provenance']['is_live'] is False
    assert result['data_provenance']['as_of'] is None

def test_missing_snapshot_is_not_an_invented_prediction():
    result=handler('get_ml_prediction')('ZZZZZZ')
    assert not result['success'] and result['result'] is None

def test_classic_trajectory_uses_requested_historical_day():
    result=handler('get_ml_prediction_trajectory')(' tsla ','2026-09-11')
    assert result['success'] and result['date']=='2026-09-11'
    assert result['data_provenance']['is_live'] is False
    assert len(result['times'])==len(result['actual_prices'])==len(result['predicted_prices'])
    assert not handler('get_ml_prediction_trajectory')('TSLA','2026-01-01')['success']

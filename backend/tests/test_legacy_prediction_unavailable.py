"""Evaluate only inert handlers; importing main_api would start trading."""
import ast
from pathlib import Path
from typing import Optional
import pytest


@pytest.mark.parametrize('name', ['get_ml_prediction', 'get_ml_prediction_trajectory'])
def test_unverified_legacy_predictions_return_missing_not_probabilities(name):
    source=Path(__file__).resolve().parents[1]/'main_api.py'
    tree=ast.parse(source.read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    fn.decorator_list=[]
    scope={'Optional':Optional}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),scope)
    result=scope[name](' tsla ')
    assert result['success'] is False and result['status']=='unavailable'
    assert result['ticker']=='TSLA'
    assert result.get('p_win_series',[])==[]
    assert result.get('result') is None

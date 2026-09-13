from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pytest
from app.research.active_policy import single_stock_target
from app.research.liquid_policy import LiquidityRules,LiquidRuntime,LiquidCandidate
from app.research.strategy_extensions import ResearchSpec
from test_liquid_policy import histories,metadata

def test_single_stock_comparator_can_choose_cash_and_pays_both_sides_of_rotation():
    spec=ResearchSpec('single',symbol_limit=.95);cov=np.eye(2)*1e-6;symbols=('a','b')
    w,_=single_stock_target(dict(a=0,b=0),cov,{},symbols,dict(a=True,b=True),spec)
    assert w==dict(a=0,b=0)
    w,details=single_stock_target(dict(a=0,b=.02),cov,dict(a=.95,b=0),symbols,dict(a=True,b=True),spec)
    assert w==dict(a=0,b=.95)
    assert details['estimated_turnover_cost']==pytest.approx(1.9*.0005)
    w,_=single_stock_target(dict(a=0,b=.02),cov,{},symbols,dict(a=True,b=False),spec)
    assert w==dict(a=0,b=0)
    with pytest.raises(ValueError,match='All current exposure'):
        single_stock_target(dict(a=0,b=.02),cov,dict(c=.2),symbols,dict(a=True,b=True),spec)

def test_relaxed_size_preference_still_requires_positive_known_market_cap():
    frames=histories();meta=metadata(frames);meta['MSTR']['market_cap']=1e9;meta['NVDA']['market_cap']=0
    rules=LiquidityRules(min_adv=1,min_market_cap=0);c=LiquidCandidate('test',universe='four')
    r=LiquidRuntime(frames,rules,meta).prepare(c,'2026-08-31',frames['TSLA'].loc['2026-08-31'].index)
    assert r['eligibility']['MSTR']['eligible'] and not r['eligibility']['NVDA']['eligible']

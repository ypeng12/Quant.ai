"""Fixed read-only comparison catalog; request text is never a filesystem path."""
import json
from .artifacts import ROOT,load_platform_results
BUNDLES={
    'four_two_weeks':'platform_research_20260913_qp',
    'four_recent_week':'platform_research_week_20260913_qp',
    'thirty_two_weeks':'platform_research_universe30_20260913_qp_fast',
    'extended_two_weeks':'extended_research_20260913_final',
    'largecap_two_weeks':'liquid_research_20260913_v2',
    'active_two_weeks':'active_research_20260913',
    'direction_two_weeks':'direction_research_20260913',
    'noncrypto_two_weeks':'stock_research_20260913',
    'conditional_two_weeks':'conditional_research_20260913',
    'incremental_two_weeks':'incremental_research_20260913_v2',
    'incremental_earlier':'incremental_earlier_20260913_v2',
}


def research_bundle(name='four_two_weeks'):
    if name not in BUNDLES:return dict(success=False,status='unavailable',reason='Unknown research dataset')
    root=ROOT/'reports'/BUNDLES[name]
    result=load_platform_results(root)
    if name=='noncrypto_two_weeks' and result.get('status')=='complete':
        training=json.loads((root/'noncrypto_stock_selector_cost5/training.json').read_text())
        result['research']['universe_admission']=dict(day=training[-1]['day'],stocks=training[-1]['eligibility'])
        result['research']['stock_selection']=[dict(day=t['day'],**t['selection']) for t in training]
    if name in ('largecap_two_weeks','active_two_weeks','direction_two_weeks') and result.get('status')=='complete':
        # load_platform_results verifies this file against the bundle hashes first.
        candidate={'largecap_two_weeks':'largecap_integrated','active_two_weeks':'liquid_dynamic_70','direction_two_weeks':'market_curve_ridge'}[name]
        training=json.loads((root/f'{candidate}_cost5/training.json').read_text())
        result['research']['universe_admission']=dict(day=training[-1]['day'],stocks=training[-1]['eligibility'])
    return result

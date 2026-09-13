"""Fixed read-only comparison catalog; request text is never a filesystem path."""
from .artifacts import ROOT,load_platform_results
BUNDLES={
    'four_two_weeks':'platform_research_20260913_qp',
    'four_recent_week':'platform_research_week_20260913_qp',
    'thirty_two_weeks':'platform_research_universe30_20260913_qp_fast',
}


def research_bundle(name='four_two_weeks'):
    if name not in BUNDLES:return dict(success=False,status='unavailable',reason='Unknown research dataset')
    return load_platform_results(ROOT/'reports'/BUNDLES[name])

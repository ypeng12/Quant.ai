"""Read-only Alpha library status; implementation is distinct from validation."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[3]
BUNDLE=ROOT/'reports/paper_alpha_library_20260913'
ENTRIES=(
    dict(id='alpha158_subset',name='Alpha158 精选',features=18,data='OHLCV',purpose='K 线位置、量能、滚动价格统计',source='https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/loader.py'),
    dict(id='alpha101_subset',name='Alpha101 精选',features=6,data='同步股票面板 OHLCV',purpose='002 / 003 / 004 / 006 / 012 / 101；保留原公式编号',source='https://arxiv.org/abs/1601.00991'),
    dict(id='cross_sectional',name='截面与同行残差',features=7,data='同步股票面板 + SPY',purpose='同行收益、同组残差、过去估计的市场 Beta；不宣称完全中性',source=None),
    dict(id='paper_l1',name='真实 L1 扩展',features=12,data='真实 Quote / Trade',purpose='OFI、深度归一化、价差与时段交互、QI、加权中间价',source='https://arxiv.org/abs/1011.6402'),
    dict(id='qi_logistic',name='QI Logistic',features=1,data='真实报价 + 下次中间价变动标签',purpose='预测下次中间价向上概率；不是交易胜率',source='https://arxiv.org/abs/1512.03492'),
    dict(id='transition_microprice',name='状态转移 Microprice',features=None,data='真实报价状态转移样本',purpose='学习 Q / R 转移矩阵及有限次价格变动修正',source='https://github.com/sstoikov/microprice'),
)


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paper_library_payload(root=None):
    folder=Path(root) if root is not None else BUNDLE
    result=dict(success=True,status='implemented',entries=list(ENTRIES),performance_verified=False,
                report=None,report_status='unavailable',reason='尚未生成数据与训练记录')
    try:
        raw=folder/'registry.json'
        if not raw.exists(): return result
        if digest(raw)!=(folder/'registry.sha256').read_text().strip(): raise ValueError('Registry hash mismatch')
        report=json.loads(raw.read_text())
        if report['status']!='complete': raise ValueError('Incomplete library build')
        for name,expected in report['artifact_hashes'].items():
            file=(folder/name).resolve()
            if not file.is_relative_to(folder.resolve()) or digest(file)!=expected: raise ValueError('Artifact hash mismatch')
        result.update(report=report,report_status='complete',reason=None)
    except (OSError,ValueError,KeyError) as exc:
        result.update(report_status='invalid',reason=str(exc))
    return result

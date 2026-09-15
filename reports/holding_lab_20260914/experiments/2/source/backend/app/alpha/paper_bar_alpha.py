"""Small, auditable OHLCV factor library; one engine for training and inference.

Alpha158 definitions: Microsoft Qlib loader.py. Alpha101: arXiv:1601.00991.
These are five-minute, session-reset adaptations, NOT replications of the daily
paper experiments. Windows count observed grid slots, including missing slots.
The fixed input panel is part of the feature contract; ranks never use the future.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd
from ..quant_policy import normalize_bars

VERSION = "paper_bar_alpha_v1"
FAMILIES = ("alpha158_subset", "alpha101_subset", "cross_sectional", "paper_library")
# Explicit contemporary research universe; not historical constituent membership.
STOCKS = ("AAPL", "MSFT", "NVDA", "AMD", "AVGO", "MU", "SNDK", "TSLA",
          "META", "AMZN", "GOOGL", "NFLX", "ORCL", "PLTR", "SMCI", "INTC",
          "TSM", "CRM", "UBER", "JPM", "BAC")
REFERENCES = ("SPY", "QQQ", "SOXX")
PEERS = {**dict.fromkeys(("NVDA", "AMD", "AVGO", "MU", "SNDK", "INTC", "TSM", "SMCI"), "semiconductors"),
         **dict.fromkeys(("MSFT", "ORCL", "PLTR", "CRM"), "software"),
         **dict.fromkeys(("META", "GOOGL", "NFLX"), "communication"),
         **dict.fromkeys(("JPM", "BAC"), "banks")}


@dataclass(frozen=True)
class BarAlphaSpec:
    family: str = "paper_library"
    windows: tuple[int, ...] = (5, 20)
    peer_window: int = 20
    frequency: str = "5min"

    def __post_init__(self):
        if self.family not in FAMILIES or self.frequency != "5min":
            raise ValueError("Supported family and five-minute bars required")
        if (not self.windows or len(set(self.windows)) != len(self.windows)
                or any(type(w) is not int or w < 2 for w in self.windows)
                or type(self.peer_window) is not int or self.peer_window < 2):
            raise ValueError("Unique integer windows >= 2 required")


def _rank(frame):
    return frame.rank(axis=1, method="average", pct=True)


def _alpha158(b, windows):
    o, h, l, c, v = (b[n] for n in ("open", "high", "low", "close", "volume"))
    out = {"a158_kmid": (c-o)/o, "a158_klen": (h-l)/o,
           "a158_kmid2": (c-o)/(h-l+1e-12),
           "a158_kup": (h-pd.concat([o,c],axis=1).max(axis=1))/o,
           "a158_klow": (pd.concat([o,c],axis=1).min(axis=1)-l)/o,
           "a158_ksft": (2*c-h-l)/o}
    for w in windows:
        # Qlib ROC is delayed close / current close, not the usual ROC return.
        out.update({f"a158_roc_{w}": (c.shift(w)/c).where(c.notna().rolling(w+1).sum()==w+1),
                    f"a158_ma_{w}": c.rolling(w).mean()/c,
                    f"a158_std_{w}": c.rolling(w).std(ddof=1)/c,
                    f"a158_rsv_{w}": (c-l.rolling(w).min())/(h.rolling(w).max()-l.rolling(w).min()+1e-12),
                    f"a158_vma_{w}": v.rolling(w).mean()/(v+1e-12),
                    f"a158_corr_{w}": c.rolling(w).corr(np.log(v+1))})
    return pd.DataFrame(out, index=b.index).where(b.notna().all(axis=1), np.nan)


def _alpha101(panel):
    o,h,l,c,v = (panel[n] for n in ("open","high","low","close","volume"))
    return {
        "a101_002": -_rank(np.log(v.where(v>0)).diff(2)).rolling(6).corr(_rank((c-o)/o)),
        "a101_003": -_rank(o).rolling(10).corr(_rank(v)),
        "a101_004": -_rank(l).rolling(9).rank(method="average",pct=True),
        "a101_006": -o.rolling(10).corr(v),
        "a101_012": np.sign(v.diff()) * -c.diff(),
        "a101_101": (c-o)/(h-l+0.001),
    }


def bar_alpha_panel(frames, spec=BarAlphaSpec(), *, as_of=None, peers=None, rank_symbols=None):
    """Rows are bar-open timestamps; values become available at bar-close.

    Supply the same symbol panel in training/inference. Reference ETFs are
    excluded from ranks by default. Missing peers remain missing; no imputation.
    """
    bars = {s: normalize_bars(f) for s,f in sorted(frames.items())}
    if not bars:
        raise ValueError("An observed OHLCV panel is required")
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None: raise ValueError("as_of must be timezone-aware")
        bars = {s:b.loc[b.index+pd.Timedelta(spec.frequency)<=cutoff] for s,b in bars.items()}
    members = tuple(sorted(rank_symbols if rank_symbols is not None else set(bars)-set(REFERENCES)))
    if not members or not set(members).issubset(bars):
        raise ValueError("Rank members must be supplied in the panel")
    groups = PEERS if peers is None else peers
    chunks = {s:[] for s in bars}
    days = sorted({d for b in bars.values() for d in b.index.date})
    for day in days:
        observed = {s:b.loc[b.index.date==day] for s,b in bars.items()}
        last = max(b.index[-1] for b in observed.values() if len(b))
        grid = pd.date_range(pd.Timestamp(day,tz="America/New_York")+pd.Timedelta(hours=9,minutes=30),last,freq=spec.frequency)
        aligned = {s:b.reindex(grid) for s,b in observed.items()}
        p = {n:pd.DataFrame({s:b[n] for s,b in aligned.items()}) for n in ("open","high","low","close","volume")}
        a101 = _alpha101({n:f.loc[:,members] for n,f in p.items()}) if spec.family in ("alpha101_subset","paper_library") else {}
        returns = p["close"].pct_change(fill_method=None)
        ranked_return = _rank(returns.loc[:,members])
        for s,b in aligned.items():
            result = _alpha158(b,spec.windows) if spec.family in ("alpha158_subset","paper_library") else pd.DataFrame(index=grid)
            for name,values in a101.items(): result[name] = values[s] if s in values else np.nan
            if spec.family in ("cross_sectional","paper_library"):
                others = [t for t in members if t!=s]
                group = [t for t in others if s in groups and groups.get(t)==groups[s]]
                own = returns[s]
                result["xs_return_rank"] = ranked_return[s] if s in ranked_return else np.nan
                result["xs_peer_return"] = returns[others].mean(axis=1)
                result["xs_peer_residual"] = own-result.xs_peer_return
                result["xs_group_residual"] = own-returns[group].mean(axis=1)
                market = returns["SPY"] if "SPY" in returns and s!="SPY" else pd.Series(np.nan,index=grid)
                # Beta excludes the current observation. It does not assert neutrality.
                beta = own.rolling(spec.peer_window).cov(market).shift()/market.rolling(spec.peer_window).var().shift().replace(0,np.nan)
                result["xs_market_beta"] = beta
                result["xs_market_residual"] = own-beta*market
                result["xs_peer_count"] = returns[others].count(axis=1)
            result = result.replace([np.inf,-np.inf],np.nan).where(b.notna().all(axis=1),np.nan)
            chunks[s].append(result.reindex(observed[s].index))
    out = {s:pd.concat(parts) if parts else pd.DataFrame(index=bars[s].index) for s,parts in chunks.items()}
    for f in out.values():
        f.attrs.update(feature_version=VERSION,spec={**asdict(spec),"windows":list(spec.windows)},panel_symbols=list(bars),rank_symbols=list(members),
                       peer_groups=dict(groups),timestamp_convention="bar_open_available_at_end",window_unit="five_minute_bars_within_session")
    return out

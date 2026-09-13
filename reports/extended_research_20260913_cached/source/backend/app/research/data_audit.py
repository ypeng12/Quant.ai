"""Audit regular-session bars against an independent exchange calendar."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import exchange_calendars as xcals
import pandas as pd
from ..quant_policy import normalize_bars


def expected_sessions(start,end):
    if pd.Timestamp(start)>pd.Timestamp(end):raise ValueError('start must not follow end')
    calendar=xcals.get_calendar('XNYS',start=pd.Timestamp(start)-pd.Timedelta(days=7),end=pd.Timestamp(end)+pd.Timedelta(days=7))
    sessions=calendar.sessions_in_range(start,end)
    # Current replay explicitly supports 390-minute sessions only. Never silently
    # drop an early-close session from an experiment's requested interval.
    for date in sessions:
        if calendar.session_close(date)-calendar.session_open(date) != pd.Timedelta(minutes=390):
            raise ValueError(f'Request includes unsupported early-close session: {date.date()}')
    return [str(d.date()) for d in sessions]


def audit_bars(frames,start,end):
    expected=expected_sessions(start,end);report={}
    if not expected:raise ValueError('No exchange sessions requested')
    for symbol,raw in frames.items():
        frame=normalize_bars(raw)
        dates=set(frame.index.strftime('%Y-%m-%d'))
        missing=sorted(set(expected)-dates)
        if missing:raise ValueError(f'{symbol}: missing exchange sessions {missing}')
        report[symbol]=dict(rows=len(frame),first=frame.index[0].isoformat(),last=frame.index[-1].isoformat(),
                            sessions=len(dates),expected_evaluation_sessions=len(expected))
    return expected,report


def input_provenance(directory,symbols):
    root=Path(directory);manifest=root/'manifest.json'
    if not manifest.exists():return dict(status='unverified_origin',reason='No vendor/source manifest retained')
    payload=json.loads(manifest.read_text())
    if payload.get('source')=='alpaca_stock_historical':
        if payload.get('status')!='complete':raise ValueError('Historical download incomplete')
        entries={e['path']:e['sha256'] for e in payload.get('normalized_files',[])}
        for symbol in symbols:
            path=root/f'{symbol}.parquet'
            if entries.get(path.name)!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('Historical bar checksum mismatch')
    else:
        for symbol in symbols:
            path=root/f'{symbol}.parquet'
            if payload.get(symbol,{}).get('sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('Retained bar manifest checksum mismatch')
    return dict(status='retained_source_manifest_matches',manifest=payload,
                limitation='Local retained source metadata; vendor was not independently re-queried.')

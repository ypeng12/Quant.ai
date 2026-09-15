#!/usr/bin/env python3
"""Atomically publish completed real WebSocket L1 features for the runner.

Run after each completed five-minute interval, alongside the existing collector.
Raw files are read in chunks; historical exchange-clock inputs are rejected.
--as-of is for arrival-time replay diagnostics, never for relabelling stale data.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.alpha.paper_l1_alpha import enhanced_l1_features, PAPER_L1_FEATURES
from app.research.holding_l1 import CONTRACT


def build_snapshot(root, symbols, as_of):
    now = pd.Timestamp(as_of)
    if now.tzinfo is None:
        raise ValueError('Aware observation time required')
    end = now.floor('5min')
    stamp = end - pd.Timedelta(minutes=5)
    day = str(stamp.tz_convert('America/New_York').date())
    packet = dict(available_at=now.isoformat(), bar_time=stamp.isoformat(), symbols={}, unavailable={})
    for symbol in symbols:
        if not symbol.isalnum():
            raise ValueError('Invalid stock symbol')
        try:
            parts = []
            path = Path(root) / day / f'{symbol}.jsonl'
            if not path.is_file():
                raise FileNotFoundError(f'No captured events for {symbol}')
            for chunk in pd.read_json(path, lines=True, chunksize=20000, convert_dates=False):
                if not chunk.source.eq('alpaca_stock_websocket').all():
                    raise ValueError('Recorded WebSocket arrivals required')
                arrival = pd.to_datetime(chunk.received_at, utc=True, format='mixed', errors='raise')
                keep = arrival.ge(stamp - pd.Timedelta(minutes=5)) & arrival.lt(end)
                parts.append(chunk.loc[keep])
            events = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
            if events.empty or not events.symbol.eq(symbol).all():
                raise ValueError('No events for requested symbol and completed window')
            events.index = pd.DatetimeIndex(pd.to_datetime(events.pop('timestamp'), utc=True, format='mixed'))
            book = enhanced_l1_features(events, as_of=end)
            row = book.loc[stamp, list(PAPER_L1_FEATURES)]
            if not np.isfinite(row.to_numpy(dtype=float)).all():
                raise ValueError('Incomplete real L1 features')
            packet['symbols'][symbol] = dict(features=row.to_dict(), contract={k:book.attrs[k] for k in CONTRACT})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            packet['unavailable'][symbol] = str(exc)
    return packet


def atomic_write(packet, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(packet, handle, allow_nan=False)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--symbols', nargs='+', default=['SNDK','TSLA','PLTR','NVDA'])
    parser.add_argument('--as-of')
    args = parser.parse_args()
    packet = build_snapshot(args.input, args.symbols, args.as_of or pd.Timestamp.now(tz='UTC'))
    packet['mode'] = 'arrival_replay_diagnostic' if args.as_of else 'live'
    packet['generated_at'] = pd.Timestamp.now(tz='UTC').isoformat()
    if not args.as_of:
        packet['available_at'] = packet['generated_at']
    atomic_write(packet, args.output)
    print(json.dumps(dict(bar_time=packet['bar_time'], available=list(packet['symbols']), unavailable=packet['unavailable'])))

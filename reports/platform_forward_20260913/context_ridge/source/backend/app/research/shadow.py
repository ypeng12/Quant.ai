"""Frozen, append-only future decision log. No order submission or simulated PnL."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path
import pandas as pd
from .artifacts import ROOT, digest


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def register(directory, specification, sources, *, now=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    stamp=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='UTC')
    if stamp.tzinfo is None:raise ValueError('Registration must have timezone')
    manifest=dict(schema_version=1,registered_at=stamp.isoformat(),status='awaiting_future_observations',
                  specification=specification,sources={s:digest(ROOT/s) for s in sources},orders_enabled=False,
                  library_versions={s:version(s) for s in ['numpy','pandas','scipy','scikit-learn','lightgbm']})
    for s in sources:
        p=directory/'source'/s;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/s).read_bytes())
    (directory/'manifest.json').write_text(canonical(manifest)+'\n')
    (directory/'manifest.sha256').write_text(digest(directory/'manifest.json')+'\n')
    return manifest


def read_manifest(directory):
    directory=Path(directory)
    if digest(directory/'manifest.json') != (directory/'manifest.sha256').read_text().strip():raise ValueError('Shadow registration checksum mismatch')
    manifest=json.loads((directory/'manifest.json').read_text())
    for source,expected in manifest['sources'].items():
        if digest(ROOT/source)!=expected:raise ValueError('Source changed since registration; register a new experiment')
    for name,expected in manifest['library_versions'].items():
        if version(name)!=expected:raise ValueError('Library version changed since registration')
    return manifest


def verify_log(directory):
    directory=Path(directory);manifest=read_manifest(directory);previous=digest(directory/'manifest.json');records=[]
    path=directory/'decisions.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            record=json.loads(line);claimed=record.pop('record_hash')
            if record['previous_hash']!=previous or hashlib.sha256(canonical(record).encode()).hexdigest()!=claimed:
                raise ValueError('Shadow log hash chain mismatch')
            payload=record['payload']
            for expected in [*payload.get('data_hashes',{}).values(),*payload.get('l1_event_hashes',{}).values()]:
                if digest(directory/'inputs'/(expected+'.parquet'))!=expected:raise ValueError('Retained shadow input checksum mismatch')
            if payload.get('account_hash') and digest(directory/'inputs'/(payload['account_hash']+'.json'))!=payload['account_hash']:
                raise ValueError('Retained account snapshot checksum mismatch')
            record['record_hash']=claimed;records.append(record);previous=claimed
    return manifest,records,previous


def append_decision(directory,payload,*,now=None):
    directory=Path(directory);stamp=pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz='UTC')
    if stamp.tzinfo is None:raise ValueError('Recording timestamp must have timezone')
    with (directory/'append.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        manifest,records,previous=verify_log(directory)
        available=pd.Timestamp(payload['available_at']);registered=pd.Timestamp(manifest['registered_at'])
        if available.tzinfo is None or not registered < available <= stamp:
            raise ValueError('Only completed future observations after registration can be recorded')
        if (stamp-available).total_seconds()>manifest['specification']['max_data_age_seconds']:
            raise ValueError('Historical/stale data cannot be labelled as a current shadow decision')
        if records and available<=pd.Timestamp(records[-1]['payload']['available_at']):raise ValueError('Observation duplicated or out of order')
        record=dict(previous_hash=previous,recorded_at=stamp.isoformat(),payload=payload)
        record['record_hash']=hashlib.sha256(canonical(record).encode()).hexdigest()
        with (directory/'decisions.jsonl').open('a') as handle:
            handle.write(canonical(record)+'\n');handle.flush();os.fsync(handle.fileno())
        return record

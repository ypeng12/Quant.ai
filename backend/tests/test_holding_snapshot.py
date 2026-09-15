import importlib.util
import json
from pathlib import Path
import pandas as pd
from test_paper_alpha_library import quotes


def test_snapshot_uses_completed_arrivals_and_preserves_missing_data(tmp_path):
    path=Path(__file__).resolve().parents[2]/'scripts/build_holding_l1_snapshot.py'
    spec=importlib.util.spec_from_file_location('holding_snapshot',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    q=quotes(601);q['source']='alpaca_stock_websocket';q['quote_size_unit']='round_lots'
    q['received_at']=(q.index+pd.Timedelta(milliseconds=1)).astype(str)
    t=q.iloc[::2].copy();t['event_type']='trade';t['price']=t.ask_price;t['size']=100
    t.index+=pd.Timedelta(milliseconds=100);t['received_at']=(t.index+pd.Timedelta(milliseconds=1)).astype(str)
    events=pd.concat([q,t]).sort_index();events['timestamp']=events.index.astype(str)
    folder=tmp_path/'2026-09-01';folder.mkdir();capture=folder/'AAA.jsonl'
    capture.write_text(''.join(json.dumps(row)+'\n' for row in events.to_dict('records')))
    now=pd.Timestamp('2026-09-01T09:40:00-04:00')
    packet=module.build_snapshot(tmp_path,['AAA','MISSING'],now)
    assert packet['symbols']['AAA']['contract']['clock']=='recorded_arrival'
    assert packet['symbols']['AAA']['features']['l1_quote_updates']==300
    assert 'MISSING' in packet['unavailable'] and 'MISSING' not in packet['symbols']
    later=events.iloc[[-1]].copy();later['bid_price']=9999;later['ask_price']=10000
    with capture.open('a') as f:f.write(json.dumps(later.to_dict('records')[0])+'\n')
    again=module.build_snapshot(tmp_path,['AAA'],now)
    assert again['symbols']==packet['symbols']
    module.atomic_write(again,tmp_path/'snapshot.json')
    assert json.loads((tmp_path/'snapshot.json').read_text())['symbols']==again['symbols']

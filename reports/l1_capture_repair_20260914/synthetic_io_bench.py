from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / "source_snapshot/backend"))
import asyncio, importlib.util,json,statistics,tempfile,time
from app.market_data.alpaca_l1_capture import AlpacaL1Capture
spec=importlib.util.spec_from_file_location('app.market_data._before_io_fix',str(Path(__file__).with_name('collector_before_io_fix.py')))
before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
q={'T':'q','S':'TSLA','t':'2026-09-14T14:30:00.123456789Z','bp':300,'ap':300.02,'bs':10,'as':20}
async def bench(cls,async_writer,n=10000):
 with tempfile.TemporaryDirectory() as tmp:
  c=cls(['TSLA'],tmp)
  if async_writer:c._start_writer()
  spans=[];lags=[];done=False
  async def heartbeat():
   deadline=time.monotonic()+.005
   while not done:
    await asyncio.sleep(.005);now=time.monotonic();lags.append(max(0,now-deadline)*1000);deadline=now+.005
  ticker=asyncio.create_task(heartbeat());await asyncio.sleep(0)
  start=time.perf_counter()
  for i in range(n):
   t=time.perf_counter();await c.on_quote(q);spans.append((time.perf_counter()-t)*1000)
  enqueue_end=time.perf_counter()
  if async_writer:await asyncio.to_thread(c._drain_writer)
  await asyncio.sleep(.01);done=True;await ticker
  elapsed=time.perf_counter()-start
  status=c.status()
  return {'mode':'bounded_writer' if async_writer else 'baseline_sync','events':n,'total_seconds':elapsed,'events_per_second':n/elapsed,'enqueue_seconds':enqueue_end-start,'callback_p50_ms':statistics.median(spans),'callback_p99_ms':sorted(spans)[int(.99*n)-1],'heartbeat_max_delay_ms':max(lags),'queue_high_watermark':status.get('queue_high_watermark'),'max_queue_delay_ms':status.get('max_queue_delay_ms'),'backpressure_events':status.get('backpressure_events'),'flushed_events':status.get('flushed_events')}
async def main():
 result={'conditions':'10,000 synthetic events local tempfile, one continuous SDK-style decoded frame; heartbeat period 5ms; NOT explanation of actual incident','runs':[await bench(before.AlpacaL1Capture,False),await bench(AlpacaL1Capture,True)]}
 print(json.dumps(result,indent=2))
asyncio.run(main())

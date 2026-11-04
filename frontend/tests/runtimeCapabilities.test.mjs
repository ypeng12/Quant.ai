import test from 'node:test';
import assert from 'node:assert/strict';
import {
  INITIAL_RUNTIME, PREVIEW_MESSAGE, PUBLIC_READ_ONLY_MESSAGE, runtimeFromResponse, readRuntimeCapabilities,
  maySendAutomaticRequests, requestRuntimeAction, serviceIssue, liveStatusFromResponse,
  botHeading, emptyPositionsView, executionHistoryNotice,
} from '../src/runtimeCapabilities.ts';

const preview = runtimeFromResponse(200, {
  mode: 'research_preview', trading_available: false,
  account_available: false, market_status_available: false,
});
const legacy = runtimeFromResponse(404, { detail: 'Not Found' });

test('a preview never sends a trading or watchlist mutation', async () => {
  const sent = [];
  const fakeFetch = async (...args) => { sent.push(args); return new Response('{}'); };
  for (const path of ['/api/live/start', '/api/live/watchlist/sync', '/api/ai_tune']) {
    await assert.rejects(requestRuntimeAction(preview, path, { method: 'POST' }, fakeFetch), {
      message: PREVIEW_MESSAGE,
    });
  }
  assert.deepEqual(sent, []);
  assert.equal(maySendAutomaticRequests(INITIAL_RUNTIME), false);
  assert.equal(maySendAutomaticRequests(preview), false);
  assert.equal(maySendAutomaticRequests(runtimeFromResponse(503, {})), false);
});

test('legacy capability 404 preserves ordinary requests without inventing observed status', async () => {
  assert.equal(legacy.mode, 'application');
  assert.equal(legacy.account_available, null);
  assert.equal(legacy.market_status_available, null);
  assert.equal(maySendAutomaticRequests(legacy), true);
  let calls = 0;
  const response = await requestRuntimeAction(legacy, '/api/live/start', { method: 'POST' }, async () => {
    calls += 1;
    return new Response('{"success":true}', { status: 200 });
  });
  assert.equal(calls, 1);
  assert.equal(response.status, 200);
});

test('the public website permits account reads but never sends a start request', async () => {
  const website = runtimeFromResponse(200, {
    mode: 'public_read_only', trading_available: false,
    account_available: true, market_status_available: false,
  });
  assert.equal(website.mode, 'public_read_only');
  assert.equal(website.account_available, true);
  assert.equal(maySendAutomaticRequests(website), false);
  assert.match(botHeading(website, false), /Public Website.*Read-only/);
  let calls = 0;
  await assert.rejects(requestRuntimeAction(website, '/api/live/start', { method: 'POST' }, async () => {
    calls += 1;
    return new Response('{}');
  }), { message: PUBLIC_READ_ONLY_MESSAGE });
  assert.equal(calls, 0);
  assert.equal(liveStatusFromResponse(200, {
    success: true, status: { is_running: false, is_market_open: null },
  }).marketOpen, null);
});

test('an explicitly local server keeps normal execution controls', async () => {
  const local = runtimeFromResponse(200, { mode: 'local', trading_available: true, account_available: true });
  assert.equal(local.mode, 'application');
  assert.equal(maySendAutomaticRequests(local), true);
  let calls = 0;
  await requestRuntimeAction(local, '/api/live/start', { method: 'POST' }, async () => {
    calls += 1;
    return new Response('{}');
  });
  assert.equal(calls, 1);
});

test('capability discovery uses only a GET and handles missing, malformed and offline servers', async () => {
  const calls = [];
  const response = await readRuntimeCapabilities('http://fixture.invalid', async (url, options) => {
    calls.push([url, options.method ?? 'GET']);
    return new Response(JSON.stringify({ mode: 'research_preview' }), { status: 200 });
  });
  assert.equal(response.mode, 'research_preview');
  assert.deepEqual(calls, [['http://fixture.invalid/api/runtime/capabilities', 'GET']]);
  assert.equal((await readRuntimeCapabilities('', async () => new Response('Not Found', { status: 404 }))).mode, 'application');
  assert.equal((await readRuntimeCapabilities('', async () => new Response('<html>Error</html>'))).mode, 'unavailable');
  assert.equal((await readRuntimeCapabilities('', async () => { throw new TypeError('Offline'); })).mode, 'unavailable');
});

test('HTTP and generic account failures never become a missing-key diagnosis', () => {
  for (const [status, body] of [
    [404, { detail: 'Only saved research reports are available in this preview.' }],
    [500, { error: 'Broker request failed.' }],
    [401, { error: 'Unauthorized' }],
    [200, { success: false, status: 'unavailable', error: 'Broker account could not be read.' }],
    [0, null],
  ]) {
    const issue = serviceIssue('Account service', status, body);
    assert.doesNotMatch(issue, /configure|missing.*credential|key.*secret/i);
  }
  assert.match(serviceIssue('Account service', 503, { error: 'Upstream timed out.' }), /HTTP 503.*Upstream timed out/);
  assert.match(serviceIssue('Account service', 200, { code: 'missing_credentials' }), /server reports missing Alpaca credentials/);
});

test('unknown, failed and malformed live status stay unknown instead of paused or closed', () => {
  for (const [status, body] of [
    [404, { detail: 'Not Found' }], [503, { success: false }], [0, null],
    [200, { success: true, status: {} }],
    [200, { success: true, status: { is_running: 'false', is_market_open: 0 } }],
    [500, { success: true, status: { is_running: false, is_market_open: false } }],
  ]) {
    const view = liveStatusFromResponse(status, body);
    assert.equal(view.running, null);
    assert.equal(view.marketOpen, null);
    assert.doesNotMatch(botHeading(legacy, view.running), /Paused|Running/);
    assert.doesNotMatch(emptyPositionsView(true, view.marketOpen, view.running).title, /Closed|Scanning/);
  }
});

test('verified false and true remain distinct from unavailable fields', () => {
  const closed = liveStatusFromResponse(200, { success: true, status: { is_running: false, is_market_open: false } });
  assert.equal(closed.running, false);
  assert.equal(closed.marketOpen, false);
  assert.match(botHeading(legacy, closed.running), /Paused/);
  assert.equal(emptyPositionsView(true, closed.marketOpen, closed.running).title, 'Market Closed');
  assert.equal(liveStatusFromResponse(200, { success: true, status: { is_running: true } }).marketOpen, null);
  assert.match(botHeading(preview, false), /Research Preview/);
  assert.doesNotMatch(botHeading(preview, false), /Paused/);
});

test('empty or unavailable positions never imply an active scanner', () => {
  assert.equal(emptyPositionsView(false, false, false).title, 'Positions unavailable');
  assert.equal(emptyPositionsView(null, null, null).title, 'Positions unavailable');
  for (const running of [false, null]) {
    const view = emptyPositionsView(true, true, running);
    assert.doesNotMatch(view.title + view.detail, /scanning|Bot Running/i);
  }
  assert.match(emptyPositionsView(true, true, true).title, /Bot Running/);
});

test('preview and failed history reads cannot appear as zero trades or active reconciliation', () => {
  for (const available of [null, false, true]) {
    const notice = executionHistoryNotice(preview, available);
    assert.match(notice, /unavailable.*research preview.*No broker account/);
    assert.doesNotMatch(notice, /zero|0 orders|reconciling|real-time/i);
  }
  assert.match(executionHistoryNotice(legacy, null), /Waiting/);
  assert.match(executionHistoryNotice(legacy, false), /unavailable/);
  assert.equal(executionHistoryNotice(legacy, true), '');
  const publicWebsite = runtimeFromResponse(200, { mode: 'public_read_only', account_available: true });
  assert.equal(executionHistoryNotice(publicWebsite, true), '');
});

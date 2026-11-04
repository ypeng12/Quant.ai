import test from 'node:test';
import assert from 'node:assert/strict';
import { runtimeFromResponse } from '../src/runtimeCapabilities.ts';
import { startControlSnapshotFromResponse, startControlView, startResultFromResponse } from '../src/startControlView.ts';

const publicRuntime = runtimeFromResponse(200, {
  mode: 'public_read_only', trading_available: false, owner_login_available: true,
});
const ownerRuntime = runtimeFromResponse(200, {
  mode: 'owner_authenticated', owner_authenticated: true, trading_available: true,
  owner_session_expires_at: '2099-01-01T00:00:00Z',
});
const stoppedPaper = {
  success: true,
  status: {
    is_running: false, is_market_open: null,
    execution_connection: { connected: true, is_paper: true },
    quant_policy: { state: 'stopped', reason: 'Explicit start request required' },
  },
};

test('connected paper account, owner sign-in, stopped bot and unknown market are distinct', () => {
  const snapshot = startControlSnapshotFromResponse(200, stoppedPaper);
  const view = startControlView(publicRuntime, snapshot);
  assert.equal(view.heading, 'Bot stopped · Start required');
  assert.equal(view.connection, 'Paper account connected.');
  assert.match(view.access, /Sign in as the owner.*Sign-in does not start/);
  assert.match(view.detail, /explicit Start request is required/);
  assert.match(view.market, /not been observed recently/);
  assert.doesNotMatch(view.market, /^Market closed/);
  const unlocked = startControlView(ownerRuntime, snapshot);
  assert.equal(unlocked.heading, view.heading);
  assert.match(unlocked.access, /unlocked.*explicit execution request/);
});

test('market closure does not overwrite a running or stopped execution state', () => {
  for (const running of [true, false]) {
    const snapshot = startControlSnapshotFromResponse(200, {
      success: true, status: { is_running: running, is_market_open: false },
    });
    const view = startControlView(ownerRuntime, snapshot);
    assert.equal(view.heading, running ? 'Bot running' : 'Bot stopped · Start required');
    assert.match(view.market, /^Market closed.*separate/);
  }
});

test('failed or malformed status cannot invent running, a closed market or a connected account', () => {
  for (const [status, body] of [
    [503, stoppedPaper], [0, null], [200, { success: false, status: stoppedPaper.status }],
    [200, { success: true, status: { is_running: 'true', is_market_open: 0, execution_connection: { connected: 'true' } } }],
  ]) {
    const snapshot = startControlSnapshotFromResponse(status, body);
    assert.equal(snapshot.running, null);
    assert.equal(snapshot.marketOpen, null);
    assert.equal(snapshot.connected, null);
    const view = startControlView(publicRuntime, snapshot);
    assert.equal(view.heading, 'Bot status unavailable');
    assert.match(view.connection, /not been verified/);
  }
});

test('execution disconnection preserves its specific reason without inventing missing credentials', () => {
  const snapshot = startControlSnapshotFromResponse(200, {
    ...stoppedPaper,
    status: { ...stoppedPaper.status,
      execution_connection: { connected: false, reason: 'Broker initialization failed (TimeoutError)' },
      quant_policy: { state: 'unavailable', reason: 'Broker initialization failed (TimeoutError)' },
    },
  });
  const view = startControlView(ownerRuntime, snapshot);
  assert.match(view.connection, /disconnected.*TimeoutError/);
  assert.match(view.detail, /stopped.*TimeoutError/);
  assert.doesNotMatch(view.connection, /missing|configure.*key/i);
});

test('preview and expired owner sessions retain their existing control explanation', () => {
  const preview = runtimeFromResponse(200, { mode: 'research_preview' });
  const snapshot = startControlSnapshotFromResponse(200, stoppedPaper);
  assert.match(startControlView(preview, snapshot).heading, /Research preview/);
  const expired = { ...ownerRuntime, owner_session_expires_at: '2000-01-01T00:00:00Z' };
  assert.match(startControlView(expired, snapshot).access, /expired/);
});

test('HTTP 200 start rejection exposes the backend policy reason', () => {
  const result = startResultFromResponse(200, {
    success: false, status: { is_running: false,
      quant_policy: { state: 'unavailable', reason: 'Trading credentials unavailable' } },
  });
  assert.equal(result.accepted, false);
  assert.equal(result.running, null);
  assert.match(result.issue, /not accepted.*Trading credentials unavailable/);
});

test('start rejection falls back to execution connection, HTTP and explicit API reasons', () => {
  assert.match(startResultFromResponse(200, {
    success: false, status: { execution_connection: { reason: 'Broker read timed out' } },
  }).issue, /Broker read timed out/);
  assert.match(startResultFromResponse(200, {
    success: false, code: 'broker_unavailable', error: 'Private exception must not be rendered',
  }).issue, /execution account could not be verified/);
  assert.match(startResultFromResponse(403, {
    detail: 'Owner sign-in is required to use trading controls on this public website.',
  }).issue, /HTTP 403.*Owner sign-in/);
});

test('private exceptions, paths, keys and traces are never included in start messages', () => {
  for (const privateReason of [
    '/private/user/models/model.json does not exist',
    'api_key=fixture-private-key',
    'Traceback: secret fixture-private-key',
    'A'.repeat(400),
  ]) {
    const response = { success: false, error: privateReason, detail: privateReason,
      status: { is_running: false, quant_policy: { reason: privateReason },
        execution_connection: { connected: false, reason: privateReason } } };
    for (const status of [200, 500]) {
      assert.ok(!startResultFromResponse(status, response).issue.includes(privateReason));
    }
    const snapshot = startControlSnapshotFromResponse(200, { ...response, success: true });
    assert.equal(snapshot.connectionReason, '');
    assert.equal(snapshot.policyReason, '');
  }
});

test('only successful start plus boolean running true confirms a start', () => {
  assert.deepEqual(startResultFromResponse(200, { success: true, status: { is_running: true } }), {
    accepted: true, running: true, issue: '',
  });
  for (const [status, body] of [
    [200, { success: true, status: { is_running: false } }],
    [200, { success: true, status: { is_running: 'true' } }],
    [200, { success: true }],
    [200, { success: false, status: { is_running: true } }],
    [500, { success: true, status: { is_running: true } }],
  ]) {
    const result = startResultFromResponse(status, body);
    assert.equal(result.accepted, false);
    assert.equal(result.running, null);
    assert.notEqual(result.issue, '');
  }
});

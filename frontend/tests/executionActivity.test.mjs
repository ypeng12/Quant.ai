import test from 'node:test';
import assert from 'node:assert/strict';
import { executionActivityFromResponse } from '../src/components/executionActivity.ts';

// Artificial fixtures only; no account, order, or market observations.
const fill = (overrides = {}) => ({
  time: '2025-01-15 09:35:12', ticker: 'TEST', action: 'COVER',
  shares: 3, price: 125.25, order_status: 'filled',
  source: 'alpaca_fill_activity', ...overrides,
});
const snapshot = (rows, overrides = {}) => ({
  trade_history: rows, history_source: 'alpaca_fill_activity', accounting_state: 'ready', ...overrides,
});

test('current confirmed fills replace obsolete action strings and remain newest first', () => {
  const payload = snapshot([fill(), fill({ time: '2025-01-15 09:40:21', action: 'BUY' })], {
    action_logs: ['[2024-09-11 15:00:00] old action'],
  });
  const original = structuredClone(payload);
  const view = executionActivityFromResponse(200, payload);
  assert.equal(view.logs.length, 2);
  assert.match(view.logs[0], /09:40:21 America\/New_York.*BUY × 3 shs/);
  assert.match(view.logs[1], /COVER × 3 shs @ \$125.2500/);
  assert.doesNotMatch(view.logs.join(' '), /2024-09-11/);
  assert.deepEqual(payload, original);
});

test('short sales and partial fills retain the broker ledger action and filled quantity', () => {
  const view = executionActivityFromResponse(200, snapshot([
    fill({ action: 'SHORT', shares: 1.25, order_status: 'partially_filled', pnl: 999, pnl_complete: false }),
  ]));
  assert.match(view.logs[0], /SHORT × 1.25 shs.*Broker-confirmed partial fill/);
  assert.doesNotMatch(view.logs[0], /PnL|999|fee/);
});

test('legacy archives never claim verified executions even when row metadata looks confirmed', () => {
  for (const history_source of ['legacy_archive_pending_verification', undefined]) {
    const view = executionActivityFromResponse(200, snapshot([fill()], { history_source }));
    assert.deepEqual(view.logs, []);
    assert.match(view.notice, /Waiting for broker fill verification/);
  }
});

test('stale and reconciling snapshots disclose freshness while retaining verified historical fills', () => {
  for (const accounting_state of ['stale_broker_fills', 'reconciling_broker_fills', 'TimeoutError']) {
    const view = executionActivityFromResponse(200, snapshot([fill()], { accounting_state }));
    assert.equal(view.logs.length, 1);
    assert.match(view.notice, /last verified|previously verified/);
    assert.doesNotMatch(view.notice, /No executed/);
  }
});

test('unavailable responses do not look like a verified empty account', () => {
  for (const [status, payload] of [[0, null], [503, snapshot([])], [200, { success: false }], [200, {}]]) {
    const view = executionActivityFromResponse(status, payload);
    assert.deepEqual(view.logs, []);
    assert.match(view.notice, /unavailable/);
  }
  assert.match(executionActivityFromResponse(200, snapshot([])).notice, /Broker-confirmed account fills/);
});

test('unfilled or malformed records cannot appear as executed activity', () => {
  const view = executionActivityFromResponse(200, snapshot([
    fill({ order_status: 'new' }), fill({ shares: 0 }), fill({ price: NaN }),
    fill({ source: 'legacy_archive' }), fill({ action: 'SUBMIT' }), fill({ time: 'unknown' }),
  ]));
  assert.deepEqual(view.logs, []);
  assert.match(view.notice, /incomplete fill records/);
});

test('the activity limit is applied after chronological ordering', () => {
  const view = executionActivityFromResponse(200, snapshot([
    fill(), fill({ time: '2025-01-15 09:40:21' }), fill({ time: '2025-01-15 09:40:22' }),
  ]), 1);
  assert.equal(view.logs.length, 1);
  assert.match(view.logs[0], /09:40:22/);
});

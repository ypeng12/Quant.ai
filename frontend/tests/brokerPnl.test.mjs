import test from 'node:test';
import assert from 'node:assert/strict';
import { matchedPnlView } from '../src/components/brokerPnl.ts';

const summary = {
  date: '2026-10-02', realized_pnl: 25, unrealized_pnl: -5,
  realized_pnl_complete: true, accounting_state: 'ready',
};

test('a complete snapshot combines matched and floating PnL without modeled fees', () => {
  assert.deepEqual(matchedPnlView(summary, summary.date), {
    pending: false, realized: 25, floating: -5, total: 20,
  });
});

test('missing, incomplete and stale accounting never becomes zero profit', () => {
  for (const value of [null, { ...summary, realized_pnl_complete: false },
    { ...summary, accounting_state: 'stale_broker_fills' },
    { ...summary, realized_pnl: null }, { ...summary, realized_pnl: NaN }]) {
    const view = matchedPnlView(value, summary.date);
    assert.equal(view.pending, true);
    assert.equal(view.realized, null);
    assert.equal(view.total, null);
  }
});

test('yesterday cannot be presented as today after exchange-date rollover', () => {
  assert.deepEqual(matchedPnlView(summary, '2026-10-03'), {
    pending: true, realized: null, floating: null, total: null,
  });
});

test('verified zero is shown; missing floating PnL is not guessed as zero', () => {
  assert.equal(matchedPnlView({ ...summary, realized_pnl: 0, unrealized_pnl: 0 }, summary.date).total, 0);
  assert.equal(matchedPnlView({ ...summary, unrealized_pnl: null }, summary.date).total, null);
});

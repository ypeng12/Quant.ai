import test from 'node:test';
import assert from 'node:assert/strict';
import { profitShadowFromResponse, profitShadowView } from '../src/components/profitShadowView.ts';

const now = Date.parse('2026-11-04T15:10:02Z');
const observation = {
  configured: true, state: 'observed', execution_enabled: false,
  comparison_kind: 'targets_from_same_observed_holdings_not_independent_pnl',
  candidate: 'slow_hold_h3', model_trained_before: '2026-11-04',
  observed_at: '2026-11-04T10:10:01-05:00', bar_time: '2026-11-04T10:05:00-05:00',
  comparison_count: 2, skipped_count: 1, duplicate_count: 0,
  shared_symbols: ['NVDA', 'SNDK', 'TSLA'], differing_target_count: 2,
  max_abs_weight_delta: 0.125, journal_state: 'written',
};
const render = value => profitShadowView(value, 'application', now);
const allText = view => Object.values(view).join(' ');

test('verified targets display differences and explicitly exclude portfolio or PnL claims', () => {
  const view = render(observation);
  assert.equal(view.label, 'Observed');
  assert.equal(view.observed, true);
  assert.match(view.comparison, /2 of 3 shared targets differ.*12.50 percentage points/);
  assert.match(view.scope, /original strategy's observed holdings.*not an independent portfolio or a PnL comparison.*original strategy controls orders/);
  assert.match(view.freshness, /2026-11-04T15:05:00.000Z/);
  assert.match(view.identity, /slow_hold_h3.*2026-11-04/);
});

test('missing data or unverified execution scope never becomes an observed comparison', () => {
  for (const value of [null, {}, { ...observation, comparison_count: 0 },
    { ...observation, shared_symbols: ['NVDA'] }, { ...observation, max_abs_weight_delta: null },
    { ...observation, differing_target_count: NaN }, { ...observation, bar_time: null },
    { ...observation, observed_at: 'secret account path' }, { ...observation, execution_enabled: true },
    { ...observation, comparison_kind: 'pnl' }]) {
    const view = render(value);
    assert.equal(view.observed, false);
    assert.equal(view.comparison, '');
    assert.doesNotMatch(view.label, /Observed/);
    assert.doesNotMatch(allText(view), /profit|profitable|outperform|secret account/i);
  }
});

test('configured, queued, computing and unavailable do not reuse old comparison results', () => {
  const labels = { waiting_for_decision: 'Waiting for a decision', queued: 'Queued', computing: 'Computing', unavailable: 'Unavailable' };
  for (const [state, label] of Object.entries(labels)) {
    const view = render({ ...observation, state });
    assert.equal(view.label, label);
    assert.equal(view.observed, false);
    assert.equal(view.comparison, '');
  }
  assert.equal(render({ ...observation, configured: false }).label, 'Not configured');
});

test('research preview ignores even a complete live response', () => {
  const view = profitShadowView(observation, 'research_preview', now);
  assert.equal(view.observed, false);
  assert.equal(view.comparison, '');
  assert.equal(view.identity, '');
  assert.match(view.detail, /unavailable in this preview/);
});

test('failed/malformed status reads clear previous data and strip nonpublic fields', () => {
  const body = { success: true, status: { profit_signal_shadow: { ...observation,
    error_type: '/private/account', equity: 50000, target_shares: { TSLA: 8 } } } };
  let current = profitShadowFromResponse(200, body);
  assert.equal(render(current).observed, true);
  assert.equal('error_type' in current, false);
  assert.equal('equity' in current, false);
  assert.equal('target_shares' in current, false);
  for (const [http, payload] of [[500, body], [0, null], [200, null], [200, { success: false }],
    [200, { success: true, status: {} }]]) {
    current = profitShadowFromResponse(http, payload);
    assert.equal(current, null);
    assert.equal(render(current).observed, false);
  }
});

test('errors are explicit fixed messages, with no raw exception or path text', () => {
  const mismatch = render({ ...observation, state: 'unavailable', reason_code: 'model_session_mismatch' });
  assert.match(mismatch.detail, /not fitted for this trading session/);
  const gap = render({ ...observation, state: 'unavailable', reason_code: 'holding_observation_gap' });
  assert.match(gap.detail, /gap.*waiting for flat holdings/);
  const untrusted = render({ ...observation, state: 'unavailable', reason_code: '/private/secret',
    candidate: '/private/model.json', error_type: 'account_key_secret', error: 'balance 10000' });
  assert.doesNotMatch(allText(untrusted), /private|secret|10000/);
  assert.equal(untrusted.warning, true);
  assert.equal(typeof render({ ...observation, state: 'unavailable', reason_code: 'constructor' }).detail, 'string');
});

test('old comparisons retain their original time and are explicitly stale', () => {
  const view = profitShadowView(observation, 'application', now + 11 * 60 * 1000);
  assert.equal(view.label, 'Observed · stale');
  assert.match(view.freshness, /Observation age: 11 min.*Stale/);
  assert.equal(view.warning, true);
  assert.equal(render({ ...observation, age_seconds: 1200 }).label, 'Observed · stale');
  assert.equal(render({ ...observation, observed_at: '2026-11-04T16:00:00Z' }).observed, false);
});

test('same-bar repeats explicitly preserve the first baseline comparison', () => {
  const view = render({ ...observation, reason_code: 'same_bar_already_observed', duplicate_count: 3 });
  assert.match(view.detail, /already compared.*first comparison.*not a comparison against a later/);
  assert.match(view.diagnostics, /3 repeated bars/);
  assert.equal(view.comparison, render(observation).comparison);
});

test('local journal failure does not imply a failed computation or hide the logging gap', () => {
  const view = render({ ...observation, journal_state: 'unavailable' });
  assert.equal(view.observed, true);
  assert.match(view.diagnostics, /Local comparison log unavailable/);
  assert.equal(view.warning, true);
});

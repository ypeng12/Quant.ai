// Public diagnostics only. Target differences do not measure trading returns.
export type ProfitShadowStatus = Record<string, unknown>;

const COMPARISON_KIND = 'targets_from_same_observed_holdings_not_independent_pnl';
const SYMBOLS = ['NVDA', 'SNDK', 'TSLA'];
const SCOPE = 'Targets use the original strategy\'s observed holdings and each policy\'s settings. This is not an independent portfolio or a PnL comparison. The original strategy controls orders. MSTR: original strategy only.';
const MAX_AGE_SECONDS = 600;
const PUBLIC_FIELDS = ['configured', 'state', 'reason_code', 'execution_enabled', 'comparison_kind',
  'candidate', 'model_trained_before', 'observed_at', 'bar_time', 'age_seconds',
  'comparison_count', 'skipped_count', 'duplicate_count', 'shared_symbols',
  'max_abs_weight_delta', 'differing_target_count', 'journal_state'];

function record(value: unknown): ProfitShadowStatus | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as ProfitShadowStatus : null;
}

/** A failed/malformed fetch returns null, so callers replace stale UI state. */
export function profitShadowFromResponse(httpStatus: number, body: unknown): ProfitShadowStatus | null {
  const envelope = record(body);
  const payload = record(record(envelope?.status)?.profit_signal_shadow);
  if (httpStatus < 200 || httpStatus >= 300 || envelope?.success !== true || !payload) return null;
  return Object.fromEntries(PUBLIC_FIELDS.filter(key => key in payload).map(key => [key, payload[key]]));
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function count(value: unknown): value is number {
  return finite(value) && Number.isSafeInteger(value) && value >= 0;
}

function timestamp(value: unknown): number | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function dateOnly(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 10) === value ? value : null;
}

const REASONS: Record<string, string> = {
  model_missing: 'The candidate model is missing.',
  model_invalid: 'The candidate model could not be validated.',
  model_changed_during_read: 'The candidate model changed during loading; waiting for a stable file.',
  model_session_mismatch: 'The candidate model is not fitted for this trading session.',
  input_symbols_missing: 'Required market data is missing.',
  baseline_unavailable: 'The original strategy decision is unavailable.',
  baseline_clock_mismatch: 'The original decision and completed market bar do not match.',
  baseline_share_quantities_invalid: 'The original share targets could not be validated.',
  comparison_universe_mismatch: 'The two strategies do not have the required shared symbols.',
  permissions_unavailable: 'The observed trading permissions are unavailable.',
  holding_start_unknown: 'Waiting for flat holdings to establish a reliable comparison start.',
  holding_observation_gap: 'A gap in observations prevents reliable holding-time comparison; waiting for flat holdings.',
  snapshot_unavailable: 'The comparison input could not be captured.',
  comparison_unavailable: 'The comparison could not be calculated.',
};

export function profitShadowView(status: ProfitShadowStatus | null, runtimeMode: string, now = Date.now()) {
  const view = {
    label: 'Unavailable', detail: 'No current comparison status from the server.',
    identity: '', comparison: '', freshness: '', diagnostics: '', scope: SCOPE,
    warning: false, observed: false,
  };
  if (runtimeMode === 'research_preview') {
    return { ...view, label: 'Research preview', detail: 'Live parallel comparisons are unavailable in this preview.' };
  }
  if (runtimeMode === 'loading') {
    return { ...view, label: 'Waiting', detail: 'Waiting for the server capabilities.' };
  }
  if (!status) return { ...view, warning: true };
  if (status.configured === false) {
    return { ...view, label: 'Not configured', detail: 'No candidate model is configured for parallel comparison.' };
  }
  if (status.configured !== true || status.execution_enabled !== false || status.comparison_kind !== COMPARISON_KIND) {
    return { ...view, warning: true, detail: 'The server has not supplied a valid diagnostic comparison status.' };
  }

  const candidate = typeof status.candidate === 'string' && /^[A-Za-z][A-Za-z0-9_+-]{0,79}$/.test(status.candidate)
    ? status.candidate : 'Unavailable';
  const session = dateOnly(status.model_trained_before);
  view.identity = `Candidate: ${candidate} · Model session: ${session ?? 'Unavailable'}`;
  const completed = count(status.comparison_count) ? status.comparison_count : null;
  const skipped = count(status.skipped_count) ? status.skipped_count : null;
  const duplicates = count(status.duplicate_count) ? status.duplicate_count : null;
  view.diagnostics = [completed !== null ? `${completed} comparisons` : '',
    skipped !== null ? `${skipped} skipped while busy` : '',
    duplicates !== null ? `${duplicates} repeated bars` : ''].filter(Boolean).join(' · ');
  if (status.journal_state === 'unavailable') view.diagnostics += `${view.diagnostics ? ' · ' : ''}Local comparison log unavailable`;

  switch (status.state) {
    case 'waiting_for_decision':
      return { ...view, label: 'Waiting for a decision', detail: 'Configured. Waiting for the original strategy\'s next completed-bar decision.' };
    case 'queued':
      return { ...view, label: 'Queued', detail: 'A comparison is queued. No new comparison result yet.' };
    case 'computing':
      return { ...view, label: 'Computing', detail: 'The candidate is being compared in the background. No new result yet.' };
    case 'unavailable':
      return { ...view, warning: true, detail: typeof status.reason_code === 'string' && Object.hasOwn(REASONS, status.reason_code)
        ? REASONS[status.reason_code]
        : 'The comparison is unavailable. Check the server diagnostics.' };
    case 'observed':
      break;
    default:
      return { ...view, warning: true, detail: 'The server has not supplied a recognized comparison state.' };
  }

  const observed = timestamp(status.observed_at);
  const bar = timestamp(status.bar_time);
  const difference = status.differing_target_count;
  const delta = status.max_abs_weight_delta;
  const shared = status.shared_symbols;
  if (observed === null || bar === null || bar >= observed || observed > now || completed === null || completed < 1
    || !session || !Array.isArray(shared) || shared.length !== 3 || !SYMBOLS.every(symbol => shared.includes(symbol))
    || !count(difference) || difference > 3 || !finite(delta) || delta < 0) {
    return { ...view, warning: true, detail: 'Comparison data is incomplete or its timestamps are invalid; no verified result is shown.' };
  }
  const age = Math.max((now - observed) / 1000, finite(status.age_seconds) ? status.age_seconds : 0);
  const stale = age > MAX_AGE_SECONDS || now - bar > (MAX_AGE_SECONDS + 300) * 1000;
  const repeated = status.reason_code === 'same_bar_already_observed';
  return {
    ...view, observed: true, warning: stale || status.journal_state === 'unavailable',
    label: stale ? 'Observed · stale' : 'Observed',
    detail: repeated ? 'This bar was already compared. Showing its first comparison, not a comparison against a later original-strategy decision.'
      : 'The candidate and original strategy targets were compared from the same observed holdings.',
    comparison: `${difference} of 3 shared targets differ (shares) · Largest weight difference: ${(delta * 100).toFixed(2)} percentage points`,
    freshness: `Last compared bar: ${new Date(bar).toISOString()} · Observation age: ${Math.floor(age / 60)} min${stale ? ' · Stale: no fresh comparison within 10 minutes' : ''}`,
  };
}

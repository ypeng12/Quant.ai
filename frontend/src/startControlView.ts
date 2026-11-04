import type { RuntimeCapabilities } from './runtimeCapabilities.ts';
import { liveStatusFromResponse, runtimeActionNotice, serviceIssue } from './runtimeCapabilities.ts';

const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : '';
const booleanOrUnknown = (value: unknown): boolean | null => typeof value === 'boolean' ? value : null;

const REASON_CODES: Record<string, string> = {
  missing_credentials: 'Trading credentials are not configured on the server.',
  alpaca_credentials_missing: 'Trading credentials are not configured on the server.',
  broker_unavailable: 'The execution account could not be verified.',
  broker_initialization_failed: 'The execution account could not be verified.',
  public_read_only: 'Owner sign-in is required to use trading controls on this public website.',
  owner_access_unconfigured: 'Owner access has not been configured on this server.',
  origin_rejected: 'Open the website directly to unlock owner controls.',
  invalid_owner_secret: 'Owner access was not accepted.',
};
const PUBLIC_REASONS = new Set([
  'Explicit start request required', 'Explicit start request accepted',
  'Explicit stop request accepted', 'Trading credentials unavailable',
  'Trading credentials unavailable; account display alone does not establish execution connectivity',
  'Expected an official Alpaca trading endpoint',
  'Live account-display credentials require explicit trading configuration',
  'Broker account read failed', 'Broker read timed out',
  'Existing configuration permits paper execution only',
  ...Object.values(REASON_CODES),
]);

// Startup currently publishes these controlled runner/resolver messages. Never
// render an arbitrary upstream exception, path, credential value or traceback.
function publicReason(value: unknown): string {
  const message = text(value);
  if (message.length > 320) return '';
  if (PUBLIC_REASONS.has(message)
      || /^Incomplete (APCA|ALPACA|ALPACA_ACCOUNT_PAPER_FALLBACK) credential pair$/.test(message)
      || /^Broker initialization failed \([A-Za-z][A-Za-z0-9_]{0,63}\)$/.test(message)) return message;
  return '';
}

function reasonCode(value: unknown): string {
  const code = text(value);
  return Object.hasOwn(REASON_CODES, code) ? REASON_CODES[code] : '';
}

export interface StartControlSnapshot {
  running: boolean | null;
  marketOpen: boolean | null;
  connected: boolean | null;
  isPaper: boolean | null;
  connectionReason: string;
  policyState: string;
  policyReason: string;
}

export function startControlSnapshotFromResponse(status: number, payload: unknown): StartControlSnapshot {
  const body = object(payload);
  const valid = status >= 200 && status < 300 && body.success === true;
  const state = valid ? object(body.status) : {};
  const connection = object(state.execution_connection), policy = object(state.quant_policy);
  const live = liveStatusFromResponse(status, payload);
  return {
    running: live.running, marketOpen: live.marketOpen,
    connected: booleanOrUnknown(connection.connected), isPaper: booleanOrUnknown(connection.is_paper),
    connectionReason: reasonCode(connection.reason_code) || publicReason(connection.reason),
    policyState: /^[a-z_]{1,64}$/.test(text(policy.state)) ? text(policy.state) : '',
    policyReason: reasonCode(policy.reason_code) || publicReason(policy.reason),
  };
}

/** Explain independent server states; this helper never enables or sends a control request. */
export function startControlView(runtime: RuntimeCapabilities, snapshot: StartControlSnapshot) {
  if (runtime.mode === 'research_preview') return {
    heading: 'Research preview · Trading unavailable', detail: runtime.message,
    connection: 'Execution account unavailable in research preview.',
    access: 'Trading controls are unavailable in this preview.',
    market: 'Market status has not been observed.',
  };

  const heading = snapshot.running === true ? 'Bot running'
    : snapshot.running === false ? 'Bot stopped · Start required' : 'Bot status unavailable';
  const detail = snapshot.running === false
    ? snapshot.policyReason && snapshot.policyReason !== 'Explicit start request required'
      ? `The execution service is stopped. ${snapshot.policyReason}`
      : 'The execution service is stopped. Sign-in and an account connection do not start it; an explicit Start request is required.'
    : snapshot.running === true
      ? 'The server reports an active execution worker. Orders depend on the policy, account and market conditions.'
      : 'The server has not supplied a current execution status. Refresh status before interpreting the bot as stopped or running.';
  const connection = snapshot.connected === true
    ? `${snapshot.isPaper === true ? 'Paper' : snapshot.isPaper === false ? 'Live' : 'Execution'} account connected.`
    : snapshot.connected === false
      ? `Execution account disconnected.${snapshot.connectionReason ? ` ${snapshot.connectionReason}` : ''}`
      : 'Execution account connection has not been verified. Account balances alone do not verify execution access.';
  const access = runtime.mode === 'public_read_only'
    ? runtime.owner_login_available === false
      ? 'Owner access is not configured on this server.'
      : 'Sign in as the owner to unlock Start. Sign-in does not start the bot.'
    : runtime.mode === 'owner_authenticated'
      ? runtimeActionNotice(runtime) || 'Owner controls are unlocked. Start sends an explicit execution request.'
      : runtime.mode === 'loading' ? 'Checking access to trading controls.'
        : runtime.mode === 'unavailable' ? 'Access to trading controls could not be verified.'
          : 'Local execution controls are available.';
  const market = snapshot.marketOpen === true ? 'Market open, as reported by the server.'
    : snapshot.marketOpen === false ? 'Market closed, as reported by the server. Market hours and bot start/stop status are separate.'
      : 'Market status has not been observed recently. A stopped bot does not mean the market is closed.';
  return { heading, detail, connection, access, market };
}

/** HTTP 200 alone is not a successful start; require the server's running state. */
export function startResultFromResponse(status: number, payload: unknown) {
  const body = object(payload), state = object(body.status), policy = object(state.quant_policy);
  const connection = object(state.execution_connection);
  const running = booleanOrUnknown(state.is_running);
  const accepted = status >= 200 && status < 300 && body.success === true && running === true;
  if (accepted) return { accepted: true, running: true as boolean | null, issue: '' };

  const reason = reasonCode(body.code ?? body.error_code) || reasonCode(policy.reason_code)
    || publicReason(policy.reason) || reasonCode(connection.reason_code) || publicReason(connection.reason)
    || publicReason(body.error) || publicReason(body.detail);
  if (status < 200 || status >= 300) {
    return { accepted: false, running: null,
      issue: serviceIssue('Start request', status, { error: reason }) };
  }
  const fallback = running === true
    ? 'The server reports that the bot is already running. Refresh status to verify it.'
    : running === false ? 'The server still reports that the bot is stopped.'
      : 'The response did not confirm a running bot. Refresh status to verify it.';
  return {
    accepted: false, running: null,
    issue: `${body.success === true ? 'Start was not confirmed.' : 'Start request was not accepted.'} ${reason || fallback}`,
  };
}

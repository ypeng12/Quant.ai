export interface RuntimeCapabilities {
  mode: 'loading' | 'research_preview' | 'public_read_only' | 'owner_authenticated' | 'application' | 'unavailable';
  trading_available: boolean | null;
  account_available: boolean | null;
  market_status_available: boolean | null;
  message: string;
  owner_login_available?: boolean | null;
  owner_session_expires_at?: string | null;
}

export const PREVIEW_MESSAGE = 'Research preview: saved reports only. Trading and account connections are unavailable here.';
export const PUBLIC_READ_ONLY_MESSAGE = 'Public view: sign in as the owner to use trading controls. Account and research views remain available.';
export const OWNER_MESSAGE = 'Owner controls are unlocked for this browser. Start AI Bot sends an execution request.';
export const OWNER_SESSION_CHANGED_EVENT = 'quant-owner-session-changed';
export const INITIAL_RUNTIME: RuntimeCapabilities = {
  mode: 'loading', trading_available: null, account_available: null,
  market_status_available: null, message: 'Checking server capabilities…',
};

const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
const booleanOrUnknown = (value: unknown): boolean | null => typeof value === 'boolean' ? value : null;

/** A legacy server's missing capability route does not establish account/market state. */
export function runtimeFromResponse(status: number, payload: unknown): RuntimeCapabilities {
  const body = object(payload);
  if (status === 404) return { ...INITIAL_RUNTIME, mode: 'application', message: '' };
  if (status >= 200 && status < 300 && body.mode === 'research_preview') {
    return {
      mode: 'research_preview', trading_available: false, account_available: false,
      market_status_available: false, message: PREVIEW_MESSAGE,
    };
  }
  if (status >= 200 && status < 300 && body.mode === 'public_read_only') {
    return {
      mode: 'public_read_only', trading_available: false,
      account_available: booleanOrUnknown(body.account_available),
      market_status_available: booleanOrUnknown(body.market_status_available),
      message: PUBLIC_READ_ONLY_MESSAGE,
      owner_login_available: booleanOrUnknown(body.owner_login_available),
    };
  }
  if (status >= 200 && status < 300 && body.mode === 'owner_authenticated'
      && body.owner_authenticated === true && body.trading_available === true) {
    return {
      mode: 'owner_authenticated', trading_available: true,
      account_available: booleanOrUnknown(body.account_available),
      market_status_available: booleanOrUnknown(body.market_status_available), message: OWNER_MESSAGE,
      owner_login_available: booleanOrUnknown(body.owner_login_available),
      owner_session_expires_at: typeof body.owner_session_expires_at === 'string' ? body.owner_session_expires_at : null,
    };
  }
  if (status >= 200 && status < 300 && (body.mode === 'application' || body.mode === 'local')) {
    return {
      mode: 'application', trading_available: booleanOrUnknown(body.trading_available),
      account_available: booleanOrUnknown(body.account_available),
      market_status_available: booleanOrUnknown(body.market_status_available), message: '',
    };
  }
  return { ...INITIAL_RUNTIME, mode: 'unavailable', message: 'Server capabilities could not be read.' };
}

export async function readRuntimeCapabilities(apiBase: string, fetcher: typeof fetch = fetch) {
  try {
    const response = await fetcher(`${apiBase}/api/runtime/capabilities`, {
      signal: AbortSignal.timeout(5000), cache: 'no-store', credentials: 'same-origin',
    });
    const payload = await response.json().catch(() => null);
    return runtimeFromResponse(response.status, payload);
  } catch {
    return runtimeFromResponse(0, null);
  }
}

export const maySendAutomaticRequests = (runtime: RuntimeCapabilities) => runtime.mode === 'application';

export function runtimeActionNotice(runtime: RuntimeCapabilities): string {
  if (runtime.mode === 'research_preview') return PREVIEW_MESSAGE;
  if (runtime.mode === 'public_read_only') return PUBLIC_READ_ONLY_MESSAGE;
  if (runtime.mode === 'loading') return 'Checking server capabilities. Please try again shortly.';
  if (runtime.mode === 'owner_authenticated' && runtime.owner_session_expires_at
      && Date.parse(runtime.owner_session_expires_at) <= Date.now()) {
    return 'Your owner session has expired. Sign in again to use trading controls.';
  }
  return '';
}

/** Preview controls remain visible, but cannot dispatch a mutation to this server. */
export async function requestRuntimeAction(
  runtime: RuntimeCapabilities, url: string, init: RequestInit, fetcher: typeof fetch = fetch,
) {
  const notice = runtimeActionNotice(runtime);
  if (notice) throw new Error(notice);
  const response = await fetcher(url, { ...init, credentials: 'same-origin' });
  if (runtime.mode === 'owner_authenticated' && [401, 403].includes(response.status)
      && typeof window !== 'undefined') {
    window.dispatchEvent(new Event(OWNER_SESSION_CHANGED_EVENT));
  }
  return response;
}

export async function signInOwner(apiBase: string, secret: string, fetcher: typeof fetch = fetch) {
  const response = await fetcher(`${apiBase}/api/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ secret }), credentials: 'same-origin', cache: 'no-store',
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || body?.success !== true) throw new Error(serviceIssue('Owner sign-in', response.status, body));
  const runtime = await readRuntimeCapabilities(apiBase, fetcher);
  if (runtime.mode !== 'owner_authenticated') {
    throw new Error('The owner session was not received. Open the website directly and allow its secure session cookie.');
  }
  return runtime;
}

export async function signOutOwner(apiBase: string, fetcher: typeof fetch = fetch) {
  const response = await fetcher(`${apiBase}/api/auth/logout`, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || body?.success !== true) throw new Error(serviceIssue('Owner sign-out', response.status, body));
  return readRuntimeCapabilities(apiBase, fetcher);
}

export function serviceIssue(resource: string, status: number, payload: unknown): string {
  const body = object(payload);
  if (status === 404) return `${resource} is unavailable on this server (HTTP 404).`;
  if (status === 0) return `${resource} could not be reached. Check the server connection.`;
  const code = body.error_code ?? body.code;
  if (code === 'missing_credentials' || code === 'alpaca_credentials_missing') {
    return 'The server reports missing Alpaca credentials. Configure the account connection on the server.';
  }
  const detail = typeof body.error === 'string' ? body.error
    : typeof body.detail === 'string' ? body.detail : '';
  const http = status >= 200 && status < 300 ? '' : ` (HTTP ${status})`;
  return `${resource} is unavailable${http}.${detail ? ` ${detail}` : ''}`;
}

export function liveStatusFromResponse(status: number, payload: unknown) {
  const body = object(payload), state = object(body.status);
  if (status < 200 || status >= 300 || body.success !== true) {
    return { running: null, marketOpen: null, issue: serviceIssue('Trading status', status, payload) };
  }
  const running = booleanOrUnknown(state.is_running), marketOpen = booleanOrUnknown(state.is_market_open);
  return { running, marketOpen,
    issue: running === null || marketOpen === null ? 'Some trading or market status fields are unavailable.' : '' };
}

export function botHeading(runtime: RuntimeCapabilities, running: boolean | null) {
  if (runtime.mode === 'research_preview') return 'Research Preview · Trading Not Connected';
  if (runtime.mode === 'public_read_only') return 'Public Website · Trading Controls Read-only';
  if (runtime.mode === 'owner_authenticated' && running === null) return 'Owner Controls Unlocked · Bot Status Unavailable';
  if (running === null) return 'AI Trading Status Unavailable';
  return running ? '⚡ AI Quant Bot Running' : '⏸️ AI Automated Trading Paused';
}

export function emptyPositionsView(positionsAvailable: boolean | null, marketOpen: boolean | null, running: boolean | null) {
  if (positionsAvailable !== true) return {
    title: 'Positions unavailable', detail: 'No current position data has been received from the account service.',
  };
  if (marketOpen === null) return {
    title: 'No open positions', detail: 'Market status is unavailable; trading hours have not been verified.',
  };
  if (!marketOpen) return {
    title: 'Market Closed', detail: 'The server reports that the regular market session is closed. No open positions are reported.',
  };
  return {
    title: running === true ? 'Market Open · Bot Running (Currently Flat)' : 'Market Open · No Open Positions',
    detail: running === true ? 'The server reports that the bot is running. The account has no open positions.'
      : running === false ? 'The server reports that the bot is paused.' : 'Bot status is unavailable.',
  };
}

export function executionHistoryNotice(runtime: RuntimeCapabilities, historyAvailable: boolean | null): string {
  if (runtime.mode === 'research_preview') {
    return 'Execution history is unavailable in research preview. No broker account is connected here.';
  }
  if (runtime.mode === 'loading' || historyAvailable === null) return 'Waiting for execution history from the server.';
  return historyAvailable ? '' : 'Execution history is unavailable. The server has not supplied a current trade history.';
}

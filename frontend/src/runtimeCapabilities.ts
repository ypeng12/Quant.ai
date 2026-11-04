export interface RuntimeCapabilities {
  mode: 'loading' | 'research_preview' | 'public_read_only' | 'application' | 'unavailable';
  trading_available: boolean | null;
  account_available: boolean | null;
  market_status_available: boolean | null;
  message: string;
}

export const PREVIEW_MESSAGE = 'Research preview: saved reports only. Trading and account connections are unavailable here.';
export const PUBLIC_READ_ONLY_MESSAGE = 'Public website: account data is read-only. Starting trading and changing settings are unavailable here.';
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
      signal: AbortSignal.timeout(5000), cache: 'no-store',
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
  return '';
}

/** Preview controls remain visible, but cannot dispatch a mutation to this server. */
export async function requestRuntimeAction(
  runtime: RuntimeCapabilities, url: string, init: RequestInit, fetcher: typeof fetch = fetch,
) {
  const notice = runtimeActionNotice(runtime);
  if (notice) throw new Error(notice);
  return fetcher(url, init);
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

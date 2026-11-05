export interface ExecutionActivity {
  logs: string[];
  notice: string;
}

const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;

/** Present the account-scoped fill snapshot already used by Trade History. */
export function executionActivityFromResponse(status: number, payload: unknown, limit = 50): ExecutionActivity {
  const data = object(payload);
  if (status < 200 || status >= 300 || data?.success === false || !Array.isArray(data?.trade_history)) {
    return { logs: [], notice: 'Execution activity is unavailable. The latest account fills could not be verified.' };
  }
  if (data.history_source !== 'alpaca_fill_activity') {
    return { logs: [], notice: 'Waiting for broker fill verification. Archived activity does not establish current account executions.' };
  }

  let incomplete = false;
  const fills = data.trade_history.flatMap(value => {
    const row = object(value);
    if (!row || row.source !== 'alpaca_fill_activity'
      || typeof row.time !== 'string' || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(row.time)
      || typeof row.ticker !== 'string' || !/^[A-Z][A-Z0-9.\-]{0,14}$/.test(row.ticker)
      || typeof row.action !== 'string' || !['BUY', 'SHORT', 'SELL', 'COVER'].includes(row.action)
      || !['filled', 'partially_filled'].includes(String(row.order_status))
      || typeof row.shares !== 'number' || !Number.isFinite(row.shares) || row.shares <= 0
      || typeof row.price !== 'number' || !Number.isFinite(row.price) || row.price <= 0) {
      incomplete = true;
      return [];
    }
    const kind = row.order_status === 'partially_filled' ? 'Broker-confirmed partial fill' : 'Broker-confirmed fill';
    return [{ time: row.time, text: `[${row.time} America/New_York] [${row.ticker}] ${row.action} × ${row.shares} shs @ $${row.price.toFixed(4)} | ${kind}` }];
  });
  const logs = fills.sort((a, b) => b.time.localeCompare(a.time))
    .slice(0, Math.max(0, Math.trunc(limit))).map(row => row.text);
  const notice = data.accounting_state === 'ready'
    ? 'Broker-confirmed account fills. Times are in America/New_York.'
    : data.accounting_state === 'stale_broker_fills'
      ? 'Showing the last verified account fills. The latest broker refresh is stale.'
      : 'Showing previously verified account fills. The latest broker refresh is unavailable or still reconciling.';
  return { logs, notice: incomplete ? `${notice} Some incomplete fill records could not be displayed.` : notice };
}

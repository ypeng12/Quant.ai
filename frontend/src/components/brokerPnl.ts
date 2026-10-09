export interface MatchedPnlSummary {
  date: string;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  realized_pnl_complete?: boolean;
  accounting_state?: string;
}

const finite = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/** Keep FIFO and floating PnL in the same trading-account snapshot. */
export function matchedPnlView(summary: MatchedPnlSummary | null, day: string) {
  const current = summary?.date === day;
  const complete = current && summary.realized_pnl_complete === true
    && summary.accounting_state === 'ready' && finite(summary.realized_pnl);
  const realized = complete ? summary.realized_pnl : null;
  const floating = current && finite(summary.unrealized_pnl) ? summary.unrealized_pnl : null;
  return {
    pending: !complete,
    realized,
    floating,
    total: realized == null || floating == null ? null : Number((realized + floating).toFixed(2)),
  };
}

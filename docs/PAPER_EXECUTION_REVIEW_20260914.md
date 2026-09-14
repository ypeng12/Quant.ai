# Paper execution repair for review — 2026-09-14

Status: local implementation and verification only. No commit, push, cloud
configuration write, order submission, cancellation, or position closure was
performed by this diagnostic/repair run. The deployed service is still on
`bab6298b4620af898be660ee435e4ac1fbc855fb` as last checked.

## Problem and resulting behavior

The deployed account display can read its configured Paper account, but the
runner did not recognize the `ALPACA_ACCOUNT_*` credential family. It started a
loop with a Mock adapter and unavailable quant policy. A running thread did not
mean an operational brokerage execution chain. The closed-market branch also
returned before reconciling leftover inventory and queued orders.

This change connects that existing Paper credential family to the runner and
continues inventory reconciliation outside regular hours. It does not alter the
model's alpha, increase leverage, or establish a new profit estimate.

## Exact proposed execution changes

1. Resolve one complete credential family in order: `APCA_*`, `ALPACA_*`, then
   `ALPACA_ACCOUNT_*` Paper fallback. Do not combine a key and secret from different
   families. A partial explicit family reports a configuration error. Accept
   official HTTPS Alpaca endpoints with optional `/v2`. Account-display live
   credentials cannot implicitly activate live trading. Existing Paper-only
   authorization remains in force.
2. Read the account successfully before reporting an execution connection.
   Expose `execution_connection.connected`, credential family, endpoint and reason
   in status, without exposing credentials. Initialization and start share the
   same resolver. Mock mode reports the connection problem explicitly.
3. Preserve the existing five-minute pre-close liquidation window, now named
   `flatten_before_close_minutes`. Derive the regular close from the broker clock,
   including early-close days. Cancel entries and overlapping closes; wait for
   broker confirmation before another close of that symbol. A cancellation error
   on one symbol is reported and does not prevent another symbol's close.
4. Read the broker clock again immediately before a regular-session market order.
   If computation crossed the close or the existing flatten boundary, reconcile
   in the next cycle instead of knowingly queuing a late market order for the
   next session. This reduces the race; a network request cannot atomically lock
   the exchange clock.
5. When the regular market is closed, read actual open orders and positions and
   use broker calendar session boundaries. During eligible premarket, afterhours,
   or overnight sessions, plan only position reductions: sell the actual long
   quantity with `sell_to_close`; buy the actual short quantity with
   `buy_to_close`. Preserve fractional residual quantities.
6. Use extended-hours DAY limit orders priced from the current opposite-side
   quote, rounded to a valid price increment. Defaults are IEX quotes, 30-second
   maximum quote age and 20-second reprice interval. These are named execution
   configuration values, not alpha scores. Quote validation allows five seconds
   of timestamp lead; the runner refreshes broker time after quote retrieval.
   An unmarketable old close is canceled, then resized from confirmed remaining
   inventory in a later cycle. No position mark or fixed percentage price offset
   is used by this new automatic cleanup path. Alpaca documents extended-hours
   eligibility for limit orders; acceptance does not guarantee execution.
   [Order documentation](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
7. Store an account-scoped close client ID before sending. A timeout or unknown
   outcome is looked up by that ID before another automatic close can be sent.
   Persist the journal under ignored `backend/.runtime_state/` using atomic file
   replacement. Reconcile actual inventory after filled closes. Report
   `session_flat` only with no broker positions and no unresolved orders;
   otherwise report `session_close_pending` and the reason.
8. Serialize the automatic cycle and the existing manual extended-hours route
   with one lock. During the existing flatten window and outside regular hours,
   that manual route must reduce confirmed inventory and must not overlap a
   working order. It no longer falls back to a market order if extended limit
   submission is unavailable. Other manual broker routes are outside this change.
9. Preserve actual broker fill quantities and prices. A limit submission with no
   fill has `filled_avg_price: null`. The existing sync worker records confirmed
   fills; accepted orders do not create PnL or confirm a flat account.

## Deployment choice and visible behavior

Use the existing cloud `ALPACA_ACCOUNT_API_KEY`, `ALPACA_ACCOUNT_SECRET_KEY` and
`ALPACA_ACCOUNT_BASE_URL` through the new fallback. Do not also add standard
variables as part of this rollout: existing `app.config.load_watchlist()` treats
standard credentials as permission to import the broker watchlist, which currently
differs from the checked-in four-symbol list. That could remove PLTR from the
display. No watchlist, README, frontend, chart, indicator or interaction change is
included in this patch.

**Deployment can activate automatic Paper trading immediately on service start.**
The current cloud account credentials are sufficient after this repair. Outside
regular hours, the runner may cancel leftover entry orders and submit eligible
position reductions. During regular hours, the existing model may rebalance.
Approval should cover that operational effect, not just a credential-name edit.

## Verification and limits

- Read-only account connection succeeded at 17:04 EDT on 2026-09-14. Positions were
  still present; this run did not close them. Private account evidence is retained
  outside the repository under `~/.local/share/quant-l1/reports/paper_execution_repair_20260914/`.
- The selected artifact loads and forecasts from synchronized completed 15:45
  bars for a 15:50 diagnostic decision. It is `price_volume_h1_g50`, a **12-feature
  Ridge** model, training cutoff `2026-09-12`, assumed **2 bps one-way cost**.
  Model SHA-256: `a3f186e60e54e901bd1d22c349e8aa86d5bfa37c8a51c802ba186e55328cf418`.
  This was a historical decision-time component check with current inventory,
  not a backtest or a submitted target portfolio.
- PLTR remains visible but unmodeled by this artifact. MSTR remains an input
  required by the old artifact; its trading target is zero under the current
  watchlist. The new 31-feature and L1 fusion models are not activated here.
- Current account probes: realtime SIP returned HTTP 403; delayed SIP was
  accessible but roughly 15 minutes delayed; latest IEX quotes for the held
  symbols were left at the 16:00 close. The cleanup diagnostic therefore returned
  `awaiting_fresh_quote` for both symbols. **This patch cannot promise automatic
  afterhours liquidation with the presently observed free quote coverage.**
  Overnight use also requires broker asset eligibility and fresh indicative
  overnight quotes. No data subscription is purchased by this repair.
- A local journal survives process restart on the same filesystem. A Hugging Face
  rebuild can discard ephemeral files. Live open-order reconciliation still
  applies, but durable recovery of every unknown request across a full rebuild
  is not proven. Concurrent external account activity is not locked by this app.
- The sync test checks cumulative partial fills, final fills, duplicate snapshots,
  actual prices and short-cover FIFO. It does not certify a complete historical
  account ledger: the existing worker queries orders submitted since local
  midnight, while older orders can fill later. Alpaca's order `after` filter is
  based on submission time; a comprehensive cross-day audit must also use fill
  activities. [Order query semantics](https://docs.alpaca.markets/us/reference/getallorders-1)
- Test totals and source hashes are in
  `reports/paper_execution_repair_20260914/validation.json`. No frontend changes
  were made, so no frontend rebuild was required for this backend repair.

## Reproducible checks

```bash
PYTHONPATH=backend python3 -m pytest backend/tests/test_trading_credentials.py backend/tests/test_intraday_liquidation.py backend/tests/test_research_execution.py backend/tests/test_quant_policy.py backend/tests/test_account_view.py -q
python3 scripts/check_paper_execution.py --env-file /path/to/private/backend/.env --forecast-at 2026-09-14T15:50:00-04:00 --output /path/outside/repo/preflight.json
git diff --check
```

The preflight does not instantiate LiveTradingRunner or start workers, submit or
cancel orders, change cloud settings, or import the broker-synced watchlist. Its
forecast option reads the local watchlist and may refresh existing market caches.
It writes the requested report exclusively, refusing to overwrite an old report.

## Approval and rollback

Review `backend/app/broker/live_runner.py`, the two new broker helpers, adapter
changes and this document before committing or pushing. The applicable instruction
is `.agents/AGENTS.md:16`: “You MUST wait for the user to review and explicitly
approve before committing and pushing.”

After approval, commit the reviewed source/tests/report, push GitHub and the Space,
then verify deployed revision, Paper connection, policy/session state, unresolved
orders and actual inventory. Do not interpret a closed-market pending state as
`ready`, or claim filled positions without a broker read. If rollback is needed,
revert the repair commit and redeploy; that cannot undo broker orders or fills
already submitted. Reconcile those separately before any restart.

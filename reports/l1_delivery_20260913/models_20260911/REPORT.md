# Real L1 research training

Status: complete
Trained, unvalidated models: 28; unavailable: 0

No trading orders, validation accuracy, or profit are produced by this training run.

See registry.json for source hashes, clocks, model contracts and individual reasons.

## Unverified assumptions

- Model parameters have not been evaluated on held-out or future sessions.
- Future-mid returns are not executable returns or cost-adjusted PnL.
- Historical exchange timestamps do not verify actual arrival latency.
- IEX top-of-book is one venue's L1; it is not consolidated SIP or L2/L3.
- Transition-model spread bins are learned only before the training cutoff; optional exact-tick states remain configurable.
- An IEX microprice is a venue-mid estimate, not an executable NBBO opportunity.

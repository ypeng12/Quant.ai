# Account display connection

The account funds cards stay visible when disconnected and use `—` for missing values.
Connected cards show broker equity, cash, net position value, buying power, account mode,
and the time the snapshot was read. Buying power is not account equity.

To connect the display independently of the trading runner, configure these server secrets:

```dotenv
ALPACA_ACCOUNT_API_KEY=<account key>
ALPACA_ACCOUNT_SECRET_KEY=<matching secret>
ALPACA_ACCOUNT_BASE_URL=https://paper-api.alpaca.markets
```

This path makes account, position and portfolio history reads only. It does not submit orders
or supply credentials to `live_runner`. Responses are cached in memory for five seconds.
If these optional variables are absent, the existing broker connection remains the source.
A failed configured display account never falls back to a different account's balance.

Keep credentials in a local ignored `.env` or the hosting platform's secret settings.
Do not commit credentials or account screenshots to the repository.

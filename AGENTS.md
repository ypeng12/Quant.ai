# Project preferences

- Write public README files and other public project entry documentation in English. Owner strategy and planning documents remain Chinese.
- Write all new or modified user-facing website text in English, including labels, navigation, messages, helper text, and placeholders.
- Communicate with the user in Chinese unless they request another language.
- Write strategy and planning documents intended for the project owner in Chinese. Keep one clear primary plan per active project and avoid creating separate Markdown files for small updates.
- Keep the SIG Predictions Cup tab and its strategy documentation focused on the 2026 U.S. midterm elections. Futu community data belongs to separate Quant.ai stock research and is not part of SIG work.

# Financial Sentiment Using Prices development

- The active Financial Sentiment Using Prices plan is `docs/financial_sentiment_using_prices_plan.md`; update it instead of creating parallel planning documents.
- Develop the research in `research/financial_sentiment_using_prices/` within this Quant.ai repository. Follow the course notebook/Docker structure; defer the course fork/issue/PR process until submission.
- Use the optional archive viewer entry point `backend.financial_sentiment.api:app` and the `financial-sentiment.html` frontend for local Financial Sentiment Using Prices work. The legacy `backend/main_api.py` initializes a trading runner.
- Preserve dated audit evidence. New collection runs must use new output directories under the ignored `reports/financial_sentiment_runs/<run-id>/` tree.
- Never describe historical audit rows as live signals or trained predictions.

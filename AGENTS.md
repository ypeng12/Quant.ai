# Project preferences

- Write all new or modified user-facing website text in English, including labels, navigation, messages, helper text, and placeholders.
- Communicate with the user in Chinese unless they request another language.
- Write strategy and planning documents intended for the project owner in Chinese. Keep one clear primary plan per active project and avoid creating separate Markdown files for small updates.
- Keep the SIG Predictions Cup tab and its strategy documentation focused on the 2026 U.S. midterm elections. Futu community data belongs to separate Quant.ai stock research and is not part of SIG work.

# Signal Lab development

- The active Signal Lab plan is `docs/signal_lab_plan.md`; update it instead of creating parallel planning documents.
- Use the research entry point `backend.signal_lab.api:app` and the `signal-lab.html` frontend for local Signal Lab work. The legacy `backend/main_api.py` initializes a trading runner.
- Preserve dated audit evidence. New collection runs must use new output directories under the ignored `reports/signal_lab_runs/<run-id>/` tree.
- Never describe historical audit rows as live signals or trained predictions.

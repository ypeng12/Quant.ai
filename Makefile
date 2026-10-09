.PHONY: test experiment oos clean

test:
	pytest tests/ -v

experiment:
	python scripts/run_experiment.py

oos:
	python scripts/run_experiment.py

clean:
	rm -rf data/raw/*.parquet reports/*.json __pycache__ src/**/__pycache__

.PHONY: financial-sentiment-setup financial-sentiment-dev financial-sentiment-check

financial-sentiment-setup:
	bash scripts/setup_financial_sentiment.sh

financial-sentiment-dev:
	python3 scripts/dev_financial_sentiment.py

financial-sentiment-check:
	.venv/bin/python scripts/verify_financial_sentiment_data_audit.py
	.venv/bin/python -m pytest backend/tests/test_financial_sentiment_api.py -q
	npm --prefix frontend run build:financial-sentiment

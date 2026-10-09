.PHONY: test experiment oos clean

test:
	pytest tests/ -v

experiment:
	python scripts/run_experiment.py

oos:
	python scripts/run_experiment.py

clean:
	rm -rf data/raw/*.parquet reports/*.json __pycache__ src/**/__pycache__

.PHONY: signal-lab-setup signal-lab-dev signal-lab-check

signal-lab-setup:
	bash scripts/setup_signal_lab.sh

signal-lab-dev:
	python3 scripts/dev_signal_lab.py

signal-lab-check:
	.venv/bin/python scripts/verify_signal_lab_data_audit.py
	.venv/bin/python -m pytest backend/tests/test_signal_lab_api.py -q
	npm --prefix frontend run build:signal-lab

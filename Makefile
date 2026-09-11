.PHONY: test experiment oos clean

test:
	pytest tests/ -v

experiment:
	python scripts/run_experiment.py

oos:
	python scripts/run_experiment.py

clean:
	rm -rf data/raw/*.parquet reports/*.json __pycache__ src/**/__pycache__

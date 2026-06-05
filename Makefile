.PHONY: install dev test lint fmt clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

test-cov:
	pytest tests/ -v --cov=magent --cov-report=term-missing

lint:
	ruff check src/ tests/
	mypy src/magent

fmt:
	ruff format src/ tests/
	ruff check --fix src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf dist/ build/ *.egg-info/

run:
	magent

setup:
	magent setup

doctor:
	magent doctor

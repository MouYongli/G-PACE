# Environment and checks run through uv; the virtual environment lives in .venv (git-ignored).
.DEFAULT_GOAL := help
.PHONY: help setup test test-contracts lint

help:
	@echo "make setup           create .venv and install the package with test deps (uv sync)"
	@echo "make test            run all tests"
	@echo "make test-contracts  run contract tests only"
	@echo "make lint            run ruff"

setup:
	@command -v uv >/dev/null || { echo "uv is not installed; see https://docs.astral.sh/uv/"; exit 1; }
	uv sync --extra test

test:
	uv run python -m unittest discover -s tests -t .

test-contracts:
	uv run python -m unittest discover -s tests/contracts -t .

lint:
	uv run ruff check .

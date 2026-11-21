# Environment and checks run through uv; the virtual environment lives in .venv (git-ignored).
.DEFAULT_GOAL := help
.PHONY: help setup test test-contracts lint clean clean-all

help:
	@echo "make setup           create .venv and install the package with test deps (uv sync)"
	@echo "make test            run all tests"
	@echo "make test-contracts  run contract tests only"
	@echo "make lint            run ruff"
	@echo "make clean           remove caches and build output"
	@echo "make clean-all       clean, then remove .venv (uv.lock is kept)"

setup:
	@command -v uv >/dev/null || { echo "uv is not installed; see https://docs.astral.sh/uv/"; exit 1; }
	uv sync --extra test

test:
	uv run python -m unittest discover -s tests -t .

test-contracts:
	uv run python -m unittest discover -s tests/contracts -t .

lint:
	uv run ruff check .

# Never descend into the shared stores, other worktrees or the environment.
clean:
	find . \( -path ./.git -o -path ./.venv -o -path ./data -o -path ./runs -o -path ./.claude/worktrees \) -prune \
		-o -type d \( -name __pycache__ -o -name '*.egg-info' -o -name .ruff_cache -o -name .pytest_cache -o -name .mypy_cache \) \
		-exec rm -rf {} +
	rm -rf build dist htmlcov .coverage

clean-all: clean
	rm -rf .venv

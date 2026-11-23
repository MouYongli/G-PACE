# Environment and checks run through uv; the virtual environment lives in .venv (git-ignored).
.DEFAULT_GOAL := help
.PHONY: help setup setup-serve test test-contracts lint plan clean clean-all

help:
	@echo "make setup           create .venv (Python 3.12) with the package, analysis and test deps (uv sync)"
	@echo "make setup-serve     create envs/serve/.venv with vLLM for local GPU inference"
	@echo "make test            run all tests"
	@echo "make test-contracts  run contract tests only"
	@echo "make lint            run ruff"
	@echo "make plan            serve the plan viewer at http://localhost:8000/docs/work/plan/"
	@echo "make clean           remove caches and build output"
	@echo "make clean-all       clean, then remove .venv and envs/serve/.venv (lock files are kept)"

setup:
	@command -v uv >/dev/null || { echo "uv is not installed; see https://docs.astral.sh/uv/"; exit 1; }
	uv sync --extra analysis --extra test

setup-serve:
	@command -v uv >/dev/null || { echo "uv is not installed; see https://docs.astral.sh/uv/"; exit 1; }
	uv sync --project envs/serve

test:
	uv run python -m unittest discover -s tests -t .

test-contracts:
	uv run python -m unittest discover -s tests/contracts -t .

lint:
	uv run ruff check .

# The viewer fetches plan.yaml and the node files, so it needs an HTTP server.
plan:
	@echo "open http://localhost:8000/docs/work/plan/"
	uv run python -m http.server 8000 --bind 127.0.0.1

# Never descend into the shared stores, other worktrees or the environment.
clean:
	find . \( -path ./.git -o -path ./.venv -o -path ./envs/serve/.venv -o -path ./data -o -path ./runs -o -path ./.claude/worktrees \) -prune \
		-o -type d \( -name __pycache__ -o -name '*.egg-info' -o -name .ruff_cache -o -name .pytest_cache -o -name .mypy_cache \) \
		-exec rm -rf {} +
	rm -rf build dist htmlcov .coverage

clean-all: clean
	rm -rf .venv envs/serve/.venv

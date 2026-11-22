#!/usr/bin/env bash
# Download LoCoMo with the independent audit's error lists into $PROJECT_ROOT/data/locomo/<version>/ (sources: configs/data/sources.yaml).
# Extra arguments are passed on, e.g. --dry-run or --dest DIR.
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
exec uv run python -m grace.cli.data.download locomo "$@"

#!/usr/bin/env bash
# Download HaluMem-Medium into $PROJECT_ROOT/data/halumem-medium/<version>/ (sources: configs/data/sources.yaml).
# Extra arguments are passed on, e.g. --dry-run or --dest DIR.
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
exec uv run python -m grace.cli.data.download halumem-medium "$@"

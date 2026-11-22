#!/usr/bin/env bash
# Download MultiWOZ 2.4, 2.2 and 2.1 into $PROJECT_ROOT/data/multiwoz/<version>/ (sources: configs/data/sources.yaml).
# Extra arguments are passed on, e.g. --dry-run or --dest DIR.
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
exec uv run python -m grace.cli.data.download multiwoz "$@"

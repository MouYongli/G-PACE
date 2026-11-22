#!/usr/bin/env bash
# Download the MemoryAgentBench files holding LongMemEval(S*) and FactConsolidation into $PROJECT_ROOT/data/memoryagentbench/<version>/ (sources: configs/data/sources.yaml).
# Extra arguments are passed on, e.g. --dry-run or --dest DIR.
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
exec uv run python -m grace.cli.data.download memoryagentbench "$@"

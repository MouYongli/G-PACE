#!/usr/bin/env bash
# MultiWOZ offer-turn census (task T006): deterministic, model-free count of annotations.
# Writes one run directory under $PROJECT_ROOT/runs/T006/artifacts/census/.
# Examples: scripts/multiwoz-offer-census.sh --split dev
#           scripts/multiwoz-offer-census.sh --split held-out --allow-held-out-annotations
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
exec uv run python -m grace.cli.data.multiwoz_offers "$@"

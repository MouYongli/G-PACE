#!/usr/bin/env bash
# Fragment-coverage annotation of LoCoMo (task T012): write the sheet, report coverage, compute kappa.
# Guideline: docs/research/fragment-coverage.md. Examples:
#   scripts/annotation/fragment-coverage.sh sheet
#   scripts/annotation/fragment-coverage.sh coverage docs/research/annotations/fragment-coverage/labels-<annotator>.csv
#   scripts/annotation/fragment-coverage.sh agreement labels-a.csv labels-b.csv
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
exec uv run python -m grace.cli.annotate.fragment "$@"

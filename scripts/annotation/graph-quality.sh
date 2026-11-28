#!/usr/bin/env bash
# Graph-quality annotation (task T024): draw the segments, check label files, agreement, merge.
# Guideline: docs/research/graph-quality-annotation.md. Examples:
#   scripts/annotation/graph-quality.sh sample
#   scripts/annotation/graph-quality.sh validate labels-<annotator>.jsonl
#   scripts/annotation/graph-quality.sh agreement labels-a.jsonl labels-b.jsonl
#   scripts/annotation/graph-quality.sh merge labels-a.jsonl labels-b.jsonl --out merged.jsonl
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
exec uv run python -m grace.cli.annotate.graph_quality "$@"

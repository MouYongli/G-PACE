#!/usr/bin/env bash
# LoCoMo evidence-anchored read points (task T007; plan 6.5). Model-free and deterministic.
# Usage: scripts/locomo_read_points.sh dev|all [--out DIR] [--tokens qwen3-8b|whitespace] [--held-out-annotation-only]
# Without --out, writes a new directory $PROJECT_ROOT/runs/T007/artifacts/read-points-<stage>-<UTC time>/.
set -euo pipefail
cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
PROJECT_ROOT="${PROJECT_ROOT:-$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")}"
export PROJECT_ROOT
stage="${1:?usage: $0 dev|all [options]}"
shift
args=("$@")
if [[ " ${args[*]} " != *" --out "* ]]; then
  args+=(--out "$PROJECT_ROOT/runs/T007/artifacts/read-points-${stage}-$(date -u +%Y%m%dT%H%M%SZ)")
fi
exec uv run python -m grace.cli.data.locomo_read_points "$stage" "${args[@]}"

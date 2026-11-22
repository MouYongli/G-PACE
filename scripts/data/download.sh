#!/usr/bin/env bash
# Download every benchmark by running scripts/data/b<N>_<slug>.sh in order.
# Extra arguments are passed to each script, e.g. --dry-run or --dest DIR.
# The controlled change sequences (change-seq) are generated, not downloaded.
set -euo pipefail
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
status=0
for script in "$dir"/b[0-9]*_*.sh; do
  echo "== $(basename "$script")"
  "$script" "$@" || status=1
done
exit "$status"

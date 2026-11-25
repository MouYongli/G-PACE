"""The single entry point for loading benchmark splits, with the held-out guard.

Every split is loaded through `load_split` (docs/work/plan/structure.md, "Guards written into
code"). It refuses a held-out split until the preregistration tag of T033 exists, checks the
manifest of every data version the benchmark uses, converts the split with the benchmark's
adapter, checks the records against the contracts and the counts against the config, and
optionally writes the record files into a RUN_DIR.

Command line (writes only under the given output directory, never into `$PROJECT_ROOT/data`):

    uv run python -m grace.eval.datasets.benchmarks.splits <slug> <split> --out <dir>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from grace.config.paths import REPO_ROOT, project_root, shared_dir
from grace.eval.datasets.benchmarks.base import (
    Adapter,
    BenchmarkConfig,
    DataError,
    Records,
    check_counts,
    load_config,
    validate,
    verify_manifest,
    write_records,
)

# Name of the git tag T033 creates on the committed preregistration protocol (plan 6.9).
# The name is provisional until T033 fixes it; a change here is a one-line edit.
PREREGISTRATION_TAG = "preregistration"


class HeldOutLocked(PermissionError):
    """A held-out split was requested before the preregistration tag exists."""


def preregistration_tag_exists(tag: str = PREREGISTRATION_TAG, repo: Path = REPO_ROOT) -> bool:
    result = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                            cwd=repo, capture_output=True, text=True, check=False)
    return result.returncode == 0


def adapters() -> dict[str, Adapter]:
    from grace.eval.datasets.benchmarks import (
        halumem,
        locomo,
        longmemeval,
        memoryagentbench,
        multiwoz,
    )
    return {a.slug: a for a in (locomo.LoCoMoAdapter(), longmemeval.LongMemEvalAdapter(),
                                multiwoz.MultiWOZAdapter(), halumem.HaluMemAdapter(),
                                memoryagentbench.MemoryAgentBenchAdapter())}


def load_split(slug: str, split: str, *, config: BenchmarkConfig | None = None,
               data_root: Path | None = None, check_files: bool = True,
               tag_exists: Callable[[], bool] = preregistration_tag_exists) -> Records:
    """Load one split of one benchmark as checked records.

    `config` defaults to `configs/benchmarks/<slug>.yaml`; `data_root` is the directory that
    holds `<data_root of the config>` (default: PROJECT_ROOT). Raises `HeldOutLocked` for a
    held-out split before the preregistration tag exists, `DataError` on a manifest, hash or count
    mismatch, and `RecordError` on any contract violation.
    """
    config = config or load_config(slug)
    if config.benchmark != slug:
        raise DataError(f"config is for {config.benchmark!r}, not {slug!r}")
    if split not in config.splits:
        raise DataError(f"{slug}: unknown split {split!r}; known: {sorted(config.splits)}")
    spec = config.splits[split]
    if spec.kind == "held-out" and not tag_exists():
        raise HeldOutLocked(f"{slug}/{split} is held out; it can be loaded only after the "
                            f"preregistration tag {PREREGISTRATION_TAG!r} of T033 exists")
    root = data_root if data_root is not None else project_root()
    source_dirs = {}
    for version, expected in config.manifests().items():
        directory = config.source_dir(root, version)
        verify_manifest(directory, expected, check_files=check_files)
        source_dirs[version] = directory
    spec = spec.resolve(source_dirs[config.version])
    adapter = adapters().get(slug)
    if adapter is None:
        raise DataError(f"no adapter for {slug!r}")
    records = adapter.convert(source_dirs, spec, config.options)
    validate(records)
    check_counts(records, spec.counts)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("slug")
    parser.add_argument("split")
    parser.add_argument("--out", type=Path, required=True,
                        help="output directory; must lie under runs_root")
    args = parser.parse_args(argv)
    runs = shared_dir("runs_root").resolve()
    out = args.out.resolve()
    if runs not in out.parents:
        parser.error(f"--out must lie under {runs}")
    records = load_split(args.slug, args.split)
    for path in write_records(records, out):
        print(path)
    print(records.counts(), dict(records.exclusions))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Retrieval channels, routing and fusion (plan 5.5; T025).

- `candidates`: the candidate type and the unified evidence ID space (one ID per message).
- `text`: the BM25 and dense channels over `memory/index/`.
- `graph`: the graph channel; maps a query result passed in by the engine to candidates.
- `route`: rule-based routing from structural signals; all channels when confidence is low.
- `fuse`: reciprocal rank fusion (main configuration) and weighted score fusion.
- `retrieve`: one retrieval step: route, run the channels, fuse to a fixed number of candidates.

This package imports only `context/api.py` and `context/memory/index/` (structure.md). It never
calls `pipeline/query/`: the engine runs the planner and the query and hands the result in.
"""

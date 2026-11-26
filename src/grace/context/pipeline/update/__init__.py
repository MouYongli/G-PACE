"""The write path: extraction, validation, attribution guard and commit (plan 5.1, 5.2; T022).

- `segment`: extraction granularity (message, segment of n messages, session) and units.
- `candidates`: the graph and vocabulary fragment the writer sees (never views).
- `patch`: the writer's claim patch and the check that makes an output usable.
- `extract`: the extractor interface and the LLM writer (call type `extract`).
- `validate`: program checks that resolve a patch to graph terms; history-local vocabulary.
- `guard`: the attribution guard and exclusivity rules (append, supersede or keep in parallel).
- `commit`: one change set per version, committed to the claim store.
- `updater`: the write path of one history, unit by unit; writer configuration.
"""

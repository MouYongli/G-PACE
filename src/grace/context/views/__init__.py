"""Views: template families, view store, rendering, rebuild (plan 3.4, 5.4; T018).

- `view`: the six components of a view; rows, sentences and their binding.
- `dependencies`: dependency patterns from the query representation.
- `template_families`: the six template families, the view config, bindings and threshold.
- `render`: template serialisation, LLM rendering, the rendering check and its fallback.
- `rebuild`: evaluation, full build, local rebuild, citation patching.
- `store`: the view store; resident and temporary life cycles; the seam for `staleness/` (T019).
"""

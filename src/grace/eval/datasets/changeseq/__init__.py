"""Generator of the controlled change sequences (task T015; design
docs/research/change-sequences.md).

- `template_families`: scenario families, the split, grammar constants, cell configs;
- `events`: event grammar, event log, well-formedness checks G1-G8;
- `generate`: the sequence planner (macros, budget, episodes);
- `gold`: event log -> gold claim graph (T014 entry types and store);
- `invalidation`: derived state, the six reference functions, Hist, gold staleness and change
  types, computed from the event log without the query compiler;
- `regraph`: independent re-evaluation of the views on the gold graph (acceptance item 3);
- `schedule`: read schedules, questions, gold answers and witnesses;
- `render`: renderer interface, output checks, the deterministic development renderer;
- `build`: the checked pipeline per sequence and the dataset writer.

From `context/` only `memory/graph/` is imported (D013 import rule).
"""

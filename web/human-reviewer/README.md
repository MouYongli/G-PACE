# Human reviewer pages

Static pages for human annotators, one directory per benchmark. Each page loads its data from the repository and runs entirely in the browser; nothing leaves the machine.

## Start

Open a page's `index.html` straight from disk, or serve the repository root (or the root of any worktree) and open the page:

```bash
uv run python -m http.server 8000 --bind 127.0.0.1
# http://localhost:8000/web/human-reviewer/locomo/
# http://localhost:8000/web/human-reviewer/multiwoz/
# http://localhost:8000/web/human-reviewer/graph-quality/
```

Both ways show the same page. Opened from disk, keep the folders of `web/human-reviewer/` together, and export often: browsers keep the drafts of a `file://` page less dependably than those of an HTTP page, and may lose them when the folder moves.

## Layout

| Path | Content |
| --- | --- |
| `css/base.css` | Shared colours and components |
| `css/shell.css` | Shell of the annotation pages: header, list view, workspace with collapsible sidebars, label area, help |
| `css/<benchmark>.css` | Content of one benchmark page |
| `js/base.js` | Shared helpers (`window.HR`: DOM builder) |
| `js/<benchmark>-data.js` | One page without the DOM: data file reader, label checks, label file (CSV or TSV); also runs under node |
| `js/<benchmark>.js` | Behaviour of one benchmark page |
| `<benchmark>/index.html` | The page |
| `<benchmark>/data/example.js` | Synthetic example data: plain JSON assigned to `window.HR_EXAMPLE`, loaded as a script so that the page needs no HTTP server |
| `<benchmark>/data/example.json` | The same data as a JSON file, for trying `Import data` (`graph-quality/` has `example-segments.jsonl` and `example-merged.jsonl`) |

## Pages

| Page | Task | Example data |
| --- | --- | --- |
| `locomo/` | T012 fragment coverage | Two invented conversations (`example-1`: 3 sessions, 16 turns, 16 questions; `example-2`: 2 sessions, 6 turns, 4 questions) |
| `graph-quality/` | T024 review of the merged agent annotation (outside the plan; user decision 2026-11-28) | Two invented segments (`example:ex-1`, `example:ex-2`) with ten merged rows |
| `multiwoz/` | T006 offer-turn check | Three invented dialogues (`EXAMPLE-A.json`, `-B`, `-C`; 24 turns, 6 offer turns) |

### `locomo/`

Two views, switched through the URL (`#/`, `#/example-1`, `#/example-1/q2`):

- **Conversation list**: one row per conversation with its progress. `Import data`, `Import labels`, `Export CSV` and the annotator ID are here.
- **One conversation**: question list and message tree (both collapsible), the messages, and the label form. Choosing a question marks its evidence turns in the tree and in the messages; `Evidence` hides the other turns behind rows that can be opened.

Data. Without imported data the page shows `locomo/data/example.js`. `Import data` reads a local file, either the original `locomo10.json` or a file in the shape of the example, and keeps it in the browser (IndexedDB). The original file carries no overlap marks and lists every conversation, including those outside the development split; build a file in the example's shape to show only the questions of the annotation sheet.

Labels. Every change is kept at once as a draft in the browser (`localStorage`), per annotator ID. A question is `todo`, `draft` or `done`; it becomes `done` through `Confirm` when a label, the rationale and (for `other`) a reason are present, and returns to `draft` when it is changed. A flag marks a question for a second look and does not change its status. `Export CSV` downloads the `done` questions as `labels-<annotator>.csv` with the columns of `docs/research/annotations/fragment-coverage/labels-*.csv`; `Import labels` reads such a file back, to continue in another browser.

### `graph-quality/`

A human reviews the merged agent annotation of the 40 T024 segments (`docs/research/annotations/graph-quality/merged-agent-A-agent-B.jsonl`, guideline `docs/research/graph-quality-annotation.md`, sections 6 and 7). Two views: the segment list with progress (`#/`) and one segment (`#/seg/<segment key>`).

- **One segment**: the context messages (grey, not annotated), then each message with its claim rows. A pair shows A and B side by side with the differing fields highlighted; an `A only` or `B only` row shows the one version. Per row: `Accept A`, `Accept B` (a pair identical in both versions has one `Accept`, already counted as accepted), `Reject` or `Edit` (closed values for `object_type`, `function`, `report_mode`, `polarity`, `certainty`; the quote must occur verbatim in the message), and an optional note. `+ Add claim` under a message adds a claim both agents missed. `Need review` hides the identical pairs. `Mark segment done` needs every row decided and every edited or added claim valid; changing a decision reopens the segment.

Data. The segment texts are development data and are not in the repository, as with the other pages. `Import data` reads two files, picked together or one after the other: `segments.jsonl` (`$PROJECT_ROOT/runs/T024/artifacts/sample/`) and the merged JSONL; they are kept in the browser (IndexedDB). Without imported data the page shows `graph-quality/data/example.js`.

Labels. Every decision is kept at once in the browser (`localStorage`). `Save draft` downloads decisions, notes, added claims and done marks as a JSON backup; `Load draft` reads it back, to continue in another browser. `Export JSONL` (annotator ID required) writes the done segments as `labels-<annotator>.jsonl` in the guideline's label format: accepted, edited and added claims in message order with fresh IDs `c1`..`cN`, and one `segment_done` per segment (`minutes` from the field in the footer, else `null`). The merged file holds no stances or entity alignments, so none are exported. The file is complete, and `scripts/annotation/graph-quality.sh validate` accepts it without problems, once all 40 segments are done; notes are not part of the label file and stay in the draft.

### `multiwoz/`

The unit of work is an offer turn: the user turn right after a system offer, which the T006 rule labelled accept, reject or none. The annotator says whether that label is right. The page has the same header, the same two views (`#/`, `#/EXAMPLE-A.json`, `#/EXAMPLE-A.json/2`) and the same draft, status and flag behaviour as `locomo/`.

- **Dialogue list**: one row per dialogue with its offer turns and progress.
- **One dialogue**: the list of offer turns (collapsible; it holds the offer turns of every dialogue, grouped by dialogue, and `Confirm` moves on across dialogues), the turns with the acts of 2.1 and 2.2, and the verdict form with the gold state of 2.1, 2.2 and 2.4 after the turn. The user goal is not shown.

Data. Without imported data the page shows `multiwoz/data/example.js`. `Import data` reads a file in the page's own shape only: one dialogue as in the example, a list of them, or `{"dialogues": [...], "tasks": [{"task_id": "<dialogue_id>:<turn index>", "acts_version": "2.1"}]}`, where `tasks` names the offer turns to check. Without `tasks`, every turn with a rule record is checked. The checked label is the one on 2.1 acts, the act source of the T006 check sample, unless a task names another.

Verdicts. `correct` or `incorrect`, with a note that is required for `incorrect`. `Export TSV` downloads the `done` offer turns as `offer-turns-check-<annotator>.tsv` with the columns of the T006 check sample (`n`, `task_id`, `label`, `offer_kinds`, `verdict`, `note`, `checked_by`); `Import labels` reads such a file back.

The example data is synthetic: the conversations, questions, dialogues, acts, states and rule records were written for these pages, and none of it is benchmark text or annotation. Benchmark data stays in `$PROJECT_ROOT/data` and reaches a page only through `Import data`. The examples are small but cover the cases a page has to show:

- `locomo/`: every category (1–4); a question for each label, operation, flag and `other` reason; evidence in one turn, across sessions, in an image turn, missing, and naming a turn that does not exist; overlap marks; an audit record.
- `multiwoz/`: every rule label (accept explicit and implicit, reject, none) and offer kind (`inform-entity`, `booking-inform`, `offerbook`, `recommend`, `select`); labels that are right, wrong and debatable; the two act sources disagreeing; a turn with no acts; states that differ between versions; one and two domains.

### Keys

| Page | Keys |
| --- | --- |
| `locomo/` | `j` / `k`: next / previous question. `1`–`5`: choose the label. `e`: next evidence turn. `Enter`: confirm and go on. `f`: flag. `v`: all messages / evidence only. `[` / `]`: question list / message tree. `?`: help |
| `graph-quality/` | None; every action is a button |
| `multiwoz/` | `j` / `k`: next / previous offer turn. `c` / `x`: rule label correct / incorrect. `n`: write the note. `Enter`: confirm and go on. `f`: flag. `[`: list of offer turns. `?`: help |

# Human reviewer pages

Static pages for human annotators, one directory per benchmark. Each page loads its data from the repository and runs entirely in the browser; nothing leaves the machine.

## Start

Open a page's `index.html` straight from disk, or serve the repository root (or the root of any worktree) and open the page:

```bash
uv run python -m http.server 8000 --bind 127.0.0.1
# http://localhost:8000/web/human-reviewer/locomo/
# http://localhost:8000/web/human-reviewer/multiwoz/
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
| `<benchmark>/data/example.js` | One complete development data point: plain JSON assigned to `window.HR_EXAMPLE`, loaded as a script so that the page needs no HTTP server |

## Pages

| Page | Task | Example data point |
| --- | --- | --- |
| `locomo/` | T012 fragment coverage | LoCoMo history `conv-26` (19 sessions, 419 turns, 152 questions of categories 1–4) |
| `multiwoz/` | T006 offer-turn check | MultiWOZ dialogue `SNG01196.json` (12 turns, 2 offer turns) |

### `locomo/`

Two views, switched through the URL (`#/`, `#/conv-26`, `#/conv-26/q11`):

- **Conversation list**: one row per conversation with its progress. `Import data`, `Import labels`, `Export CSV` and the annotator ID are here.
- **One conversation**: question list and message tree (both collapsible), the messages, and the label form. Choosing a question marks its evidence turns in the tree and in the messages; `Evidence` hides the other turns behind rows that can be opened.

Data. Without imported data the page shows `locomo/data/example.js`. `Import data` reads a local file, either the original `locomo10.json` or a file in the shape of the example, and keeps it in the browser (IndexedDB). The original file carries no overlap marks and lists every conversation, including those outside the development split; build a file in the example's shape to show only the questions of the annotation sheet.

Labels. Every change is kept at once as a draft in the browser (`localStorage`), per annotator ID. A question is `todo`, `draft` or `done`; it becomes `done` through `Confirm` when a label, the rationale and (for `other`) a reason are present, and returns to `draft` when it is changed. A flag marks a question for a second look and does not change its status. `Export CSV` downloads the `done` questions as `labels-<annotator>.csv` with the columns of `docs/research/annotations/fragment-coverage/labels-*.csv`; `Import labels` reads such a file back, to continue in another browser.

### `multiwoz/`

The unit of work is an offer turn: the user turn right after a system offer, which the T006 rule labelled accept, reject or none. The annotator says whether that label is right. The page has the same header, the same two views (`#/`, `#/SNG01196.json`, `#/SNG01196.json/6`) and the same draft, status and flag behaviour as `locomo/`.

- **Dialogue list**: one row per dialogue with its offer turns and progress.
- **One dialogue**: the list of offer turns (collapsible; it holds the offer turns of every dialogue, grouped by dialogue, and `Confirm` moves on across dialogues), the turns with the acts of 2.1 and 2.2, and the verdict form with the gold state of 2.1, 2.2 and 2.4 after the turn. The user goal is not shown.

Data. Without imported data the page shows `multiwoz/data/example.js`. `Import data` reads a file in the page's own shape only: one dialogue as in the example, a list of them, or `{"dialogues": [...], "tasks": [{"task_id": "<dialogue_id>:<turn index>", "acts_version": "2.1"}]}`, where `tasks` names the offer turns to check. Without `tasks`, every turn with a rule record is checked. The checked label is the one on 2.1 acts, the act source of the T006 check sample, unless a task names another.

Verdicts. `correct` or `incorrect`, with a note that is required for `incorrect`. `Export TSV` downloads the `done` offer turns as `offer-turns-check-<annotator>.tsv` with the columns of the T006 check sample (`n`, `task_id`, `label`, `offer_kinds`, `verdict`, `note`, `checked_by`); `Import labels` reads such a file back.

The data files copy development data only: LoCoMo `snap-research/locomo` @ `3eb6f2c` (CC BY-NC 4.0), with questions as in `docs/research/annotations/fragment-coverage/sheet.csv`; MultiWOZ 2.1, 2.2 and 2.4, with the offer-turn records of census run `T006-20261125T010238Z-7565`.

### Keys

| Page | Keys |
| --- | --- |
| `locomo/` | `j` / `k`: next / previous question. `1`–`5`: choose the label. `e`: next evidence turn. `Enter`: confirm and go on. `f`: flag. `v`: all messages / evidence only. `[` / `]`: question list / message tree. `?`: help |
| `multiwoz/` | `j` / `k`: next / previous offer turn. `c` / `x`: rule label correct / incorrect. `n`: write the note. `Enter`: confirm and go on. `f`: flag. `[`: list of offer turns. `?`: help |

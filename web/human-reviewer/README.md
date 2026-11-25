# Human reviewer pages

Static pages for human annotators. Each page loads its inputs from the repository and keeps labels in the browser (localStorage). Labels leave the machine only as a CSV file that the annotator downloads.

## Start

Serve the repository root (or the root of any worktree) and open the page:

```bash
uv run python -m http.server 8000 --bind 127.0.0.1
# http://localhost:8000/web/human-reviewer/t012.html
```

A page opened as a `file://` URL cannot fetch its inputs. It then asks for the files instead.

## Pages

| Page | Task | Inputs | Output |
| --- | --- | --- | --- |
| `t012.html` | T012 fragment coverage | `docs/research/annotations/fragment-coverage/sheet.csv`, `labels-agent-m01-T012.csv`, guideline `docs/research/fragment-coverage.md` | `labels-<annotator>.csv`, read by `scripts/annotation/fragment-coverage.sh` |

### `t012.html`

- **Set.** Annotator A labels all 308 questions. Annotator B, the second annotator of decision D007, chooses "B: 100 overlap questions".
- **Blind mode.** Blind mode is on by default. The agent pre-annotation for a question is shown only after you have saved your own label for it, so that the labels stay independent (guideline section 7). Turn blind mode off only after you have finished.
- **Labelling.** The form enforces the label-file rules of `src/grace/eval/analysis/annotation/fragment.py`:
  - five labels;
  - operations and flags for `in_fragment` only;
  - a reason for `other`;
  - a rationale for every label.
- **Keys.**
  - `1`–`5`: choose the label.
  - `j` / `k`: next / previous question.
  - `r`: jump to the rationale.
  - `Ctrl+Enter`: save and go to the next open question.
  - `g`: show or hide the guideline.
- **Export.**
  - "Export CSV" downloads `labels-<annotator>.csv`: a full copy of the sheet with the six annotator columns filled in.
  - Put the file in `docs/research/annotations/fragment-coverage/` and commit it through a PR.
- **Resume.** "Import labels" loads an earlier export, for example on another machine or browser.
- **Storage.** Labels live in the browser until exported. Clearing the browser data deletes them, so export regularly.

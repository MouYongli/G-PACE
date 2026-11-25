// MultiWOZ page, data side: reading a data file, the offer turns to check, verdict checks and the
// verdict TSV. No DOM access, so the same file runs in the browser (window.HRMultiwozData) and
// under node.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HRMultiwozData = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const VERSIONS = ["2.1", "2.2", "2.4"];
  const ACT_SOURCES = ["2.1", "2.2"]; // 2.4 keeps system acts only
  const PRIMARY = "2.1"; // act source of the T006 check sample
  const VERDICTS = [["correct", "c"], ["incorrect", "x"]];
  const TSV_COLUMNS = ["n", "task_id", "label", "offer_kinds", "verdict", "note", "checked_by"];

  // Accepts one dialogue (the example in data/example.js), a list of dialogues, or {dialogues: [...], tasks: [...]}.
  // tasks, when given, names the offer turns to check: [{task_id: "<dialogue_id>:<turn index>",
  // acts_version?: "2.1"}]; otherwise every turn with a rule record is checked.
  function normalise(json) {
    const dialogues = Array.isArray(json) ? json : Array.isArray(json && json.dialogues) ? json.dialogues : [json];
    if (!dialogues.length) throw new Error("the file holds no dialogue");
    const byId = new Map();
    dialogues.forEach((d, position) => {
      if (!d || !d.dialogue_id || !Array.isArray(d.turns)) {
        throw new Error(`entry ${position + 1} is not a dialogue in the page format (dialogue_id, turns)`);
      }
      if (byId.has(d.dialogue_id)) throw new Error(`dialogue ${d.dialogue_id} appears twice`);
      byId.set(d.dialogue_id, d);
    });
    const tasks = [];
    const add = (dialogue, turn, wanted) => {
      const version = wanted && turn.census[wanted] ? wanted : turn.census[PRIMARY] ? PRIMARY : Object.keys(turn.census)[0];
      const record = turn.census[version];
      tasks.push({
        id: `${dialogue.dialogue_id}:${turn.index}`,
        dialogue,
        turn,
        version,
        label: record.label,
        how: record.how || "",
        offer_kinds: record.offer_kinds || {},
        offered: record.offered || {},
        others: Object.keys(turn.census).filter((v) => v !== version)
          .map((v) => ({ version: v, label: turn.census[v].label, how: turn.census[v].how || "" })),
      });
    };
    const named = !Array.isArray(json) && json && Array.isArray(json.tasks) ? json.tasks : null;
    if (named) {
      for (const item of named) {
        const cut = String(item.task_id).lastIndexOf(":");
        const dialogue = byId.get(String(item.task_id).slice(0, cut));
        const turn = dialogue && dialogue.turns.find((t) => String(t.index) === String(item.task_id).slice(cut + 1));
        if (!turn || !turn.census) throw new Error(`task ${item.task_id} names no offer turn of the loaded dialogues`);
        add(dialogue, turn, item.acts_version);
      }
    } else {
      for (const dialogue of dialogues) {
        for (const turn of dialogue.turns) if (turn.census) add(dialogue, turn, null);
      }
    }
    if (!tasks.length) throw new Error("the file holds no offer turn to check");
    return { dialogues: [...new Set(tasks.map((t) => t.dialogue))], tasks };
  }

  function emptyEntry() {
    return { verdict: "", note: "", status: "draft", flagged: false };
  }

  const isBlank = (entry) => !entry || (!entry.verdict && !entry.note.trim());

  // todo: nothing entered. draft: something entered, not confirmed. done: confirmed and complete.
  function statusOf(entry) {
    if (isBlank(entry)) return "todo";
    return entry.status === "done" ? "done" : "draft";
  }

  function problems(entry) {
    const out = [];
    if (!entry || !entry.verdict) out.push("Choose correct or incorrect.");
    else if (entry.verdict === "incorrect" && !entry.note.trim()) out.push("Say in the note why the rule label is wrong.");
    return out;
  }

  // JSON in the spacing of Python's json.dumps, so an exported file compares equal to the census one.
  function pyJson(value) {
    if (Array.isArray(value)) return "[" + value.map(pyJson).join(", ") + "]";
    if (value && typeof value === "object") {
      return "{" + Object.entries(value).map(([k, v]) => JSON.stringify(k) + ": " + pyJson(v)).join(", ") + "}";
    }
    return JSON.stringify(value);
  }

  function cell(value) {
    const text = String(value == null ? "" : value);
    return /["\t\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function toTsv(rows, columns = TSV_COLUMNS) {
    return [columns, ...rows.map((row) => columns.map((c) => row[c]))]
      .map((cells) => cells.map(cell).join("\t")).join("\n") + "\n";
  }

  // Tab-separated reader with CSV quoting ("" inside a quoted cell). Returns objects keyed by the header.
  function parseTsv(text) {
    const rows = [];
    let row = [], value = "", quoted = false;
    const source = text.replace(/^﻿/, "");
    for (let i = 0; i < source.length; i += 1) {
      const ch = source[i];
      if (quoted) {
        if (ch === '"' && source[i + 1] === '"') { value += '"'; i += 1; }
        else if (ch === '"') quoted = false;
        else value += ch;
      } else if (ch === '"' && value === "") quoted = true;
      else if (ch === "\t") { row.push(value); value = ""; }
      else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && source[i + 1] === "\n") i += 1;
        row.push(value); rows.push(row); row = []; value = "";
      } else value += ch;
    }
    if (value !== "" || row.length) { row.push(value); rows.push(row); }
    const filled = rows.filter((r) => r.some((c) => c !== ""));
    if (!filled.length) return [];
    const header = filled[0].map((name) => name.trim());
    return filled.slice(1).map((r) => Object.fromEntries(header.map((name, i) => [name, r[i] || ""])));
  }

  function entryToRow(n, task, annotator, entry) {
    return {
      n,
      task_id: task.id,
      label: task.label,
      offer_kinds: pyJson(task.offer_kinds),
      verdict: entry.verdict,
      note: entry.note.trim(),
      checked_by: annotator,
    };
  }

  // A row of a verdict file -> an entry. A complete row comes back as done, an incomplete one as draft.
  function rowToEntry(row) {
    const entry = emptyEntry();
    const verdict = (row.verdict || "").trim();
    entry.verdict = VERDICTS.some(([value]) => value === verdict) ? verdict : "";
    entry.note = row.note || "";
    entry.status = problems(entry).length ? "draft" : "done";
    return entry;
  }

  return {
    VERSIONS, ACT_SOURCES, PRIMARY, VERDICTS, TSV_COLUMNS,
    normalise, emptyEntry, isBlank, statusOf, problems, pyJson, toTsv, parseTsv, entryToRow, rowToEntry,
  };
});

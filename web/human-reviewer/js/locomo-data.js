// LoCoMo page, data side: reading a data file, the label vocabulary, label checks and the label CSV.
// No DOM access, so the same file runs in the browser (window.HRLocomoData) and under node.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HRLocomoData = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const LABELS = [
    ["in_fragment", "In fragment"],
    ["open_reasoning", "Open reasoning"],
    ["date_arithmetic", "Date arithmetic"],
    ["common_sense", "Common sense"],
    ["other", "Other"],
  ];
  const OPERATIONS = ["filter", "join", "negation", "count", "latest"];
  const FLAGS = ["relative_time", "partial_image"];
  const OTHER_REASONS = ["image_only", "annotation_error", "beyond_fragment"];
  const CATEGORY_NAMES = { 1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop" };
  const CSV_COLUMNS = ["question_id", "annotator", "label", "operations", "other_reason", "flags", "rationale"];
  const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december"];

  // "1:56 pm on 8 May, 2023" -> "2023-05-08T13:56". Returns "" when the text has another shape.
  function parseRawDate(text) {
    const m = /^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s+on\s+(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})\s*$/i.exec(text || "");
    if (!m) return "";
    const month = MONTHS.indexOf(m[5].toLowerCase());
    if (month < 0) return "";
    let hour = Number(m[1]) % 12;
    if (m[3].toLowerCase() === "pm") hour += 12;
    const two = (n) => String(n).padStart(2, "0");
    return `${m[6]}-${two(month + 1)}-${two(m[4])}T${two(hour)}:${m[2]}`;
  }

  // One sample of the original locomo10.json -> the shape the page shows. Category 5 questions,
  // the summaries shipped with the data set, image URLs and date keys without a session are left out.
  function fromRaw(sample) {
    const conversation = sample.conversation || {};
    const sessions = [];
    for (const key of Object.keys(conversation)) {
      const m = /^session_(\d+)$/.exec(key);
      if (!m || !Array.isArray(conversation[key])) continue;
      const rawDate = conversation[key + "_date_time"] || "";
      sessions.push({
        id: "S" + m[1],
        index: Number(m[1]),
        date_time: parseRawDate(rawDate),
        date_text: rawDate,
        turns: conversation[key].map((turn) => ({
          id: turn.dia_id,
          speaker: turn.speaker,
          text: turn.text || "",
          image: turn.blip_caption || turn.img_url
            ? { caption: turn.blip_caption || "", query: turn.query || "" } : null,
        })),
      });
    }
    sessions.sort((a, b) => a.index - b.index);
    const known = new Set(sessions.flatMap((s) => s.turns.map((t) => t.id)));
    const questions = [];
    let adversarial = 0;
    (sample.qa || []).forEach((qa, index) => {
      if (qa.category === 5) { adversarial += 1; return; }
      const listed = qa.evidence || [];
      const ids = [...new Set(listed.flatMap((e) => String(e).match(/D\d+:\d+/g) || []))];
      const clean = listed.every((e) => /^D\d+:\d+$/.test(e)) && ids.every((id) => known.has(id));
      questions.push({
        id: `${sample.sample_id}:q${index}`,
        category: qa.category,
        category_name: CATEGORY_NAMES[qa.category] || "",
        overlap: null, // unknown: the overlap set is defined by the annotation sheet, not by the data set
        question: qa.question,
        gold_answer: qa.answer == null ? "" : String(qa.answer),
        evidence_ids: ids,
        evidence_status: !ids.length ? "none" : clean ? "complete" : "malformed",
        audit_error_type: "",
        audit_correct_answer: "",
      });
    });
    return {
      history_id: sample.sample_id,
      speakers: [conversation.speaker_a, conversation.speaker_b].filter(Boolean),
      excluded: { category_5_questions: adversarial },
      sessions,
      questions,
    };
  }

  // Accepts the original locomo10.json (a list of samples), one sample, one conversation in the
  // page's own shape (the example in data/example.js), a list of those, or {histories: [...]}.
  function normalise(json) {
    const items = Array.isArray(json) ? json : Array.isArray(json && json.histories) ? json.histories : [json];
    if (!items.length) throw new Error("the file holds no conversation");
    const conversations = items.map((item, position) => {
      if (item && item.sample_id && item.conversation) return fromRaw(item);
      if (item && item.history_id && Array.isArray(item.sessions) && Array.isArray(item.questions)) return item;
      throw new Error(`entry ${position + 1} is neither a LoCoMo sample (sample_id, conversation, qa) ` +
        "nor a conversation in the page format (history_id, sessions, questions)");
    });
    const seen = new Set();
    for (const c of conversations) {
      if (seen.has(c.history_id)) throw new Error(`conversation ${c.history_id} appears twice`);
      seen.add(c.history_id);
    }
    return conversations;
  }

  function emptyEntry() {
    return { label: "", operations: [], flags: [], other_reason: "", rationale: "", status: "draft", flagged: false };
  }

  function isBlank(entry) {
    return !entry || (!entry.label && !entry.operations.length && !entry.flags.length &&
      !entry.other_reason && !entry.rationale.trim());
  }

  // todo: nothing entered. draft: something entered, not confirmed. done: confirmed and complete.
  function statusOf(entry) {
    if (isBlank(entry)) return "todo";
    return entry.status === "done" ? "done" : "draft";
  }

  // What still keeps an entry from being confirmed; an empty list means it is complete.
  function problems(entry) {
    const out = [];
    if (!entry || !entry.label) out.push("Choose a label.");
    else if (!LABELS.some(([value]) => value === entry.label)) out.push(`Unknown label "${entry.label}".`);
    if (entry && entry.label === "other" && !entry.other_reason) out.push("Choose a reason for “other”.");
    if (!entry || !entry.rationale.trim()) out.push("Write the rationale.");
    return out;
  }

  function csvCell(value) {
    const text = String(value == null ? "" : value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function toCsv(rows, columns = CSV_COLUMNS) {
    return [columns, ...rows.map((row) => columns.map((c) => row[c]))]
      .map((cells) => cells.map(csvCell).join(",")).join("\n") + "\n";
  }

  // RFC 4180 reader: quoted cells may hold commas, quotes ("") and line breaks. Returns objects
  // keyed by the header row.
  function parseCsv(text) {
    const rows = [];
    let row = [], cell = "", quoted = false;
    const source = text.replace(/^﻿/, "");
    for (let i = 0; i < source.length; i += 1) {
      const ch = source[i];
      if (quoted) {
        if (ch === '"' && source[i + 1] === '"') { cell += '"'; i += 1; }
        else if (ch === '"') quoted = false;
        else cell += ch;
      } else if (ch === '"') quoted = true;
      else if (ch === ",") { row.push(cell); cell = ""; }
      else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && source[i + 1] === "\n") i += 1;
        row.push(cell); rows.push(row); row = []; cell = "";
      } else cell += ch;
    }
    if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
    const filled = rows.filter((r) => r.some((c) => c !== ""));
    if (!filled.length) return [];
    const header = filled[0].map((name) => name.trim());
    return filled.slice(1).map((r) => Object.fromEntries(header.map((name, i) => [name, r[i] || ""])));
  }

  const splitList = (text) => (text || "").split(";").map((s) => s.trim()).filter(Boolean);

  function entryToRow(questionId, annotator, entry) {
    return {
      question_id: questionId,
      annotator,
      label: entry.label,
      operations: entry.operations.join(";"),
      other_reason: entry.other_reason,
      flags: entry.flags.join(";"),
      rationale: entry.rationale.trim(),
    };
  }

  // A row of a label file -> an entry. A complete row comes back as done, an incomplete one as draft.
  function rowToEntry(row) {
    const entry = emptyEntry();
    entry.label = (row.label || "").trim();
    entry.operations = splitList(row.operations).filter((v) => OPERATIONS.includes(v));
    entry.flags = splitList(row.flags).filter((v) => FLAGS.includes(v));
    entry.other_reason = OTHER_REASONS.includes((row.other_reason || "").trim()) ? row.other_reason.trim() : "";
    entry.rationale = row.rationale || "";
    entry.status = problems(entry).length ? "draft" : "done";
    return entry;
  }

  return {
    LABELS, OPERATIONS, FLAGS, OTHER_REASONS, CATEGORY_NAMES, CSV_COLUMNS,
    parseRawDate, fromRaw, normalise, emptyEntry, isBlank, statusOf, problems,
    toCsv, parseCsv, entryToRow, rowToEntry,
  };
});

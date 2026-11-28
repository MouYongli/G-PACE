// Graph-quality review page, data side: reading the segment and merged files, the claim vocabulary of
// the guideline (docs/research/graph-quality-annotation.md), claim checks and the label file (JSONL).
// No DOM access, so the same file runs in the browser (window.HRGraphQualityData) and under node.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HRGraphQualityData = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const ENUMS = {
    object_type: ["entity", "string", "integer", "boolean", "date", "dateTime", "time"],
    function: ["inform", "request", "offer", "accept", "reject", "confirm", "commit", "question"],
    report_mode: ["own", "quote", "hypothetical"],
    polarity: ["positive", "negative"],
    certainty: ["certain", "probable", "possible", "underspecified"],
  };
  const TEXT_FIELDS = ["subject", "predicate", "object", "speaker"];
  const BOOL_FIELDS = ["derived", "correction"];
  const NULLABLE_FIELDS = ["time_expression", "valid_from", "valid_until"];
  // Order of the fields of a claim record (guideline section 6).
  const CLAIM_FIELDS = ["id", "message_id", "subject", "predicate", "object", "object_type", "speaker",
    "function", "report_mode", "polarity", "certainty", "derived", "correction", "time_expression",
    "valid_from", "valid_until", "quote"];
  // Fields a reviewer sees and edits, in display order.
  const SHOWN_FIELDS = ["subject", "predicate", "object", "object_type", "speaker", "function", "report_mode",
    "polarity", "certainty", "derived", "correction", "time_expression", "valid_from", "valid_until", "quote"];
  const DATE = /^\d{4}-\d{2}-\d{2}$/;
  const PREDICATE = /^[a-z][A-Za-z0-9]*$/;

  function parseJsonl(text, name) {
    const rows = [];
    text.split(/\r?\n/).forEach((line, n) => {
      if (!line.trim()) return;
      try { rows.push(JSON.parse(line)); }
      catch (error) { throw new Error(`${name || "file"}:${n + 1}: not JSON`); }
    });
    return rows;
  }

  // The segments file (segments.jsonl of the T024 run directory) holds rows with "messages".
  function readSegments(rows) {
    return rows.map((r) => {
      if (!r.key || !Array.isArray(r.messages)) throw new Error("a segment row needs key and messages");
      return {
        key: r.key, benchmark: r.benchmark || "", history_id: r.history_id || "",
        segment_id: r.segment_id || "", participants: r.participants || [],
        context: r.context || [], messages: r.messages,
      };
    });
  }

  // The merged file holds rows with "agreement"; the two annotator names are the other object keys.
  const MERGED_KEYS = new Set(["segment", "message_id", "agreement", "strict", "differs"]);
  function readMerged(rows) {
    const names = [];
    for (const r of rows) {
      if (!r.segment || !r.agreement) throw new Error("a merged row needs segment and agreement");
      for (const k of Object.keys(r)) if (!MERGED_KEYS.has(k) && !names.includes(k)) names.push(k);
    }
    names.sort();
    if (names.length !== 2) throw new Error(`expected two annotators in the merged file, found ${names.length}`);
    const counter = new Map();
    const out = rows.map((r) => {
      const a = r[names[0]] || null, b = r[names[1]] || null;
      const base = `${r.segment}|${a ? a.id : ""}|${b ? b.id : ""}`;
      const n = (counter.get(base) || 0) + 1;
      counter.set(base, n);
      return {
        uid: n > 1 ? `${base}#${n}` : base, segment: r.segment, message_id: r.message_id,
        agreement: r.agreement, strict: !!r.strict, differs: r.differs || [], a, b,
      };
    });
    return { names, rows: out };
  }

  // Fields in which the two versions of a pair differ (every shown field, not only the compared ones).
  function diffFields(a, b) {
    if (!a || !b) return [];
    return SHOWN_FIELDS.filter((f) => JSON.stringify(a[f] ?? null) !== JSON.stringify(b[f] ?? null));
  }

  // Row kind: "identical" (a pair with no difference), "differs", "a_only", "b_only".
  function rowKind(row) {
    if (row.a && row.b) return diffFields(row.a, row.b).length || row.differs.length ? "differs" : "identical";
    return row.a ? "a_only" : "b_only";
  }

  // Cross-check the two files: every merged row names a known segment and message.
  function checkData(segments, merged) {
    const problems = [];
    const byKey = new Map(segments.map((s) => [s.key, s]));
    for (const r of merged.rows) {
      const seg = byKey.get(r.segment);
      if (!seg) { problems.push(`merged row ${r.uid}: unknown segment`); continue; }
      if (!seg.messages.some((m) => m.message_id === r.message_id)) {
        problems.push(`merged row ${r.uid}: message ${r.message_id} is not in the segment`);
      }
    }
    return problems;
  }

  // The decision of a row; a pair identical in both versions counts as accepted until changed.
  function effective(row, decisions) {
    const d = decisions[row.uid];
    return d && d.choice ? d : rowKind(row) === "identical" ? { choice: "a" } : null;
  }

  // The claim a decision resolves to, or null (rejected or undecided). Fields are those of a claim
  // record without id and quote checks; see claimProblems.
  function resolve(row, decision) {
    if (!decision) return null;
    if (decision.choice === "a") return row.a ? { ...row.a } : null;
    if (decision.choice === "b") return row.b ? { ...row.b } : null;
    if (decision.choice === "edit") return decision.edit ? { ...decision.edit } : null;
    return null;
  }

  // Normalise the values of an edit form: trimmed strings, empty -> null for the nullable fields.
  function cleanClaim(c) {
    const out = { ...c };
    for (const f of TEXT_FIELDS) out[f] = String(out[f] ?? "").trim();
    for (const f of NULLABLE_FIELDS) {
      const v = out[f] == null ? "" : String(out[f]).trim();
      out[f] = v === "" ? null : v;
    }
    for (const f of BOOL_FIELDS) out[f] = out[f] === true;
    out.quote = String(out.quote ?? "");
    return out;
  }

  // Problems of one claim against its message text, mirroring the label check of the CLI.
  function claimProblems(claim, text) {
    const c = cleanClaim(claim);
    const p = [];
    if (!c.quote || !text.includes(c.quote)) p.push("the quote must occur verbatim in the message");
    for (const f of ["subject", "object", "speaker"]) if (!c[f]) p.push(`${f} is empty`);
    if (!PREDICATE.test(c.predicate)) p.push("predicate must be lowerCamelCase");
    for (const [f, values] of Object.entries(ENUMS)) if (!values.includes(c[f])) p.push(`${f} is not a valid value`);
    for (const f of ["valid_from", "valid_until"]) {
      if (c[f] != null && !DATE.test(c[f])) p.push(`${f} must be YYYY-MM-DD or empty`);
    }
    return p;
  }

  // A blank claim for a missed one, attributed to a message.
  function blankClaim(message) {
    return {
      message_id: message.message_id, subject: "", predicate: "", object: "", object_type: "entity",
      speaker: message.speaker, function: "inform", report_mode: "own", polarity: "positive",
      certainty: "certain", derived: false, correction: false, time_expression: null,
      valid_from: null, valid_until: null, quote: "",
    };
  }

  // The label file of the finished segments: claims in message order with fresh IDs c1..cN,
  // then one segment_done per segment. state = {decisions, added, done, minutes}.
  function toRecords(segments, merged, state, annotator) {
    const records = [];
    for (const seg of segments) {
      if (!state.done[seg.key]) continue;
      const order = new Map(seg.messages.map((m, n) => [m.message_id, n]));
      const claims = [];
      merged.rows.filter((r) => r.segment === seg.key).forEach((r, n) => {
        const c = resolve(r, effective(r, state.decisions));
        if (c) claims.push({ order: order.get(c.message_id ?? r.message_id), n, c });
      });
      (state.added[seg.key] || []).forEach((a, n) => claims.push({ order: order.get(a.fields.message_id), n: 1e6 + n, c: a.fields }));
      claims.sort((x, y) => x.order - y.order || x.n - y.n);
      claims.forEach(({ c }, i) => {
        const clean = cleanClaim(c);
        const rec = { segment: seg.key, annotator, kind: "claim" };
        for (const f of CLAIM_FIELDS) rec[f] = f === "id" ? `c${i + 1}` : clean[f];
        records.push(rec);
      });
      const minutes = state.minutes[seg.key];
      records.push({ segment: seg.key, annotator, kind: "segment_done",
        minutes: Number.isFinite(minutes) ? minutes : null, note: "" });
    }
    return records;
  }

  function toJsonl(records) {
    return records.map((r) => JSON.stringify(r)).join("\n") + (records.length ? "\n" : "");
  }

  return { ENUMS, TEXT_FIELDS, BOOL_FIELDS, NULLABLE_FIELDS, CLAIM_FIELDS, SHOWN_FIELDS, parseJsonl,
    readSegments, readMerged, diffFields, rowKind, effective, checkData, resolve, cleanClaim, claimProblems,
    blankClaim, toRecords, toJsonl };
});

// LoCoMo extraction correction page, data side: reading the bundle written by
// `python -m grace.cli.annotate.locomo_correction bundle`, effective decisions (human over agent
// proposal), field checks and the correction file (JSONL, read by `... locomo_correction apply`).
// No DOM access, so the same file runs in the browser (window.HRLocomoCorrectionData) and under node.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HRLocomoCorrectionData = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const DATATYPES = ["string", "integer", "boolean", "date", "dateTime", "time"];
  const KINDS = ["change", "correction"];
  const ADD_DECISIONS = ["add_claim", "add_ending", "add_supersession"];
  const ENTITY = /^[A-Za-z0-9_]+$/;
  const PREDICATE = /^[A-Za-z][A-Za-z0-9_]*$/;
  const LEXICAL = {
    integer: /^-?(0|[1-9]\d*)$/, boolean: /^(true|false)$/, date: /^\d{4}-\d{2}-\d{2}$/,
    dateTime: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/,
    time: /^\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/,
  };
  const TIME_BOUND = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/;

  const key = (hid, id) => hid + "|" + id;

  function parseJsonl(text, name) {
    const rows = [];
    text.split(/\r?\n/).forEach((line, n) => {
      if (!line.trim()) return;
      try { rows.push(JSON.parse(line)); }
      catch (error) { throw new Error(`${name || "file"}:${n + 1}: not JSON`); }
    });
    return rows;
  }

  // ---------- bundle ----------

  function readBundle(data) {
    if (!data || data.kind !== "locomo-correction-bundle" || !Array.isArray(data.histories)) {
      throw new Error("not a correction bundle (kind locomo-correction-bundle)");
    }
    const histories = data.histories.map((h) => {
      if (!h.history_id || !Array.isArray(h.messages) || !Array.isArray(h.items)) {
        throw new Error("a history needs history_id, messages and items");
      }
      const itemsOf = new Map(h.messages.map((m) => [m.message_id, []]));
      const versionOf = new Map(h.messages.map((m) => [m.message_id, m.version]));
      for (const item of h.items) {
        if (!itemsOf.has(item.message_id)) throw new Error(`${h.history_id}: item ${item.item_id} names unknown message ${item.message_id}`);
        itemsOf.get(item.message_id).push(item);
      }
      const segmentOf = new Map((h.segments || []).map((s) => [s.segment_id, s]));
      return { history_id: h.history_id, messages: h.messages, items: h.items, labels: h.entity_labels || {},
        itemsOf, versionOf, segmentOf, byId: new Map(h.items.map((i) => [i.item_id, i])) };
    });
    const proposals = new Map();
    const addsOf = new Map();   // history -> message -> agent additions
    for (const p of data.proposals || []) {
      const id = p.item_id || p.add_id;
      if (!p.history_id || !id) throw new Error("a proposal needs history_id and item_id or add_id");
      proposals.set(key(p.history_id, id), p);
      if (p.add_id) {
        if (!addsOf.has(p.history_id)) addsOf.set(p.history_id, new Map());
        const m = addsOf.get(p.history_id);
        if (!m.has(p.message_id)) m.set(p.message_id, []);
        m.get(p.message_id).push(p);
      }
    }
    return { source: data.source || {}, histories, proposals, addsOf,
      byHistory: new Map(histories.map((h) => [h.history_id, h])) };
  }

  // ---------- display ----------

  function objectText(obj, labels) {
    if (!obj) return "—";
    if ("entity" in obj) return (labels && labels[obj.entity]) || obj.entity;
    return `"${obj.value}"` + (obj.datatype && obj.datatype !== "string" ? `^^${obj.datatype}` : "");
  }

  function timeText(vt) {
    if (!vt) return "";
    const parts = [];
    if (vt.start || vt.end) parts.push(`[${vt.start || "?"}, ${vt.end || "open"})`);
    if (vt.expression) parts.push(`“${vt.expression}”`);
    return parts.join(" ");
  }

  function claimText(claim, labels) {
    if (!claim) return "(claim not found)";
    const name = (e) => (labels && labels[e]) || e;
    return `${name(claim.subject)} · ${claim.predicate} · ${objectText(claim.object, labels)}` +
      (claim.scope ? ` [scope ${claim.scope}]` : "");
  }

  function quotes(item, text) {
    return (item.evidence || []).filter((e) => e.span && e.message_id === item.message_id)
      .map((e) => text.slice(e.span.start, e.span.end));
  }

  // Short label of the change type of an item, or null.
  function changeLabel(item) {
    const c = item.change || [];
    for (const k of ["ending", "supersession", "correction"]) if (c.includes(k)) return k;
    if (c.includes("replacing")) return "new value (replacing)";
    if (c.includes("negative")) return "negative stance";
    if (c.includes("agent")) return "change event (agent)";
    return null;
  }

  // ---------- decisions ----------

  function sameFields(a, b) { return JSON.stringify(a || null) === JSON.stringify(b || null); }

  // The decision shown for an item: the human's if any, else the agent proposal.
  function effective(bundle, store, hid, id) {
    const human = store.decisions[key(hid, id)];
    if (human && human.decision) return { ...human, source: "human" };
    const p = bundle.proposals.get(key(hid, id));
    if (p) return { decision: p.decision, fields: p.fields, note: p.reason, source: "agent" };
    return null;
  }

  function basisOf(bundle, hid, id, decision, fields) {
    const p = bundle.proposals.get(key(hid, id));
    if (!p) return "human";
    return p.decision === decision && sameFields(p.fields, fields) ? "agent-confirmed" : "agent-overridden";
  }

  // Problems of a claim edit or an added claim (fields as in the correction file).
  function claimProblems(f, partial) {
    const out = [];
    const has = (k) => !partial || k in f;
    if (has("subject") && !(f.subject && ENTITY.test(f.subject))) out.push("subject: an entity ID of letters, digits and _");
    if (has("predicate") && !(f.predicate && PREDICATE.test(f.predicate))) out.push("predicate: a name like hasHobby (letters, digits, _)");
    if (has("object")) {
      const o = f.object || {};
      if ("entity" in o) { if (!ENTITY.test(o.entity || "")) out.push("object: an entity ID of letters, digits and _"); }
      else if ("value" in o) {
        if (!DATATYPES.includes(o.datatype)) out.push("object: unknown datatype");
        else if (o.datatype === "string" ? !String(o.value).trim() : !LEXICAL[o.datatype].test(o.value)) out.push(`object: not a canonical ${o.datatype}`);
      } else out.push("object: missing");
    }
    if (has("valid_time") && f.valid_time) {
      for (const b of ["start", "end"]) {
        const v = f.valid_time[b];
        if (v && !TIME_BOUND.test(v)) out.push(`valid time ${b}: YYYY-MM-DD or a dateTime`);
      }
      const { start, end } = f.valid_time;
      if (start && end && start.length !== end.length) out.push("valid time: both bounds of one datatype");
      else if (start && end && start >= end) out.push("valid time: start must be before end");
    }
    return out;
  }

  function supersessionProblems(f, claimIds) {
    const out = [];
    if (!KINDS.includes(f.kind || "change")) out.push("kind: change or correction");
    if (f.valid_end && !TIME_BOUND.test(f.valid_end)) out.push("valid end: YYYY-MM-DD or a dateTime");
    if (f.valid_end && f.kind === "correction") out.push("a correction carries no valid end");
    if ("claim_id" in f && !f.claim_id) out.push("the claim that ends is missing");
    for (const k of ["claim_id", "replacing_claim_id"]) {
      if (f[k] && claimIds && !claimIds.has(f[k])) out.push(`${k}: no claim ${f[k]} at or before this message`);
    }
    if (f.claim_id && f.claim_id === f.replacing_claim_id) out.push("a claim cannot replace itself");
    return out;
  }

  function addProblems(add, claimIds) {
    if (add.decision === "add_claim") return claimProblems(add.fields || {}, false);
    const out = supersessionProblems(add.fields || {}, claimIds);
    if (add.decision === "add_supersession" && !(add.fields || {}).replacing_claim_id) out.push("the replacing claim is missing");
    return out;
  }

  // ---------- correction file ----------

  function progress(bundle, store, hid) {
    const h = bundle.byHistory.get(hid);
    const adds = [...((bundle.addsOf.get(hid) || new Map()).values())].flat();
    let decided = 0, change = 0, changeDecided = 0;
    for (const item of h.items) {
      const d = store.decisions[key(hid, item.item_id)];
      const isChange = (item.change || []).length > 0;
      if (isChange) change++;
      if (d && d.decision) { decided++; if (isChange) changeDecided++; }
    }
    for (const p of adds) {
      const d = store.decisions[key(hid, p.add_id)];
      change++;
      if (d && d.decision) { decided++; changeDecided++; }
    }
    const total = h.items.length + adds.length;
    return { total, decided, change, changeDecided, added: (store.added[hid] || []).length, agentAdds: adds.length };
  }

  function toRecords(bundle, store, annotator) {
    const out = [];
    for (const h of bundle.histories) {
      const hid = h.history_id;
      for (const m of h.messages) {
        for (const item of h.itemsOf.get(m.message_id)) {
          const d = store.decisions[key(hid, item.item_id)];
          if (!d || !d.decision) continue;
          const fields = d.decision === "edit" ? d.fields : null;
          const p = bundle.proposals.get(key(hid, item.item_id));
          const basis = basisOf(bundle, hid, item.item_id, d.decision, fields);
          out.push({ history_id: hid, item_id: item.item_id, add_id: null, message_id: m.message_id,
            decision: d.decision, fields, reason: d.note || (basis === "agent-confirmed" && p ? p.reason : ""),
            annotator, basis });
        }
        for (const p of ((bundle.addsOf.get(hid) || new Map()).get(m.message_id) || [])) {
          const d = store.decisions[key(hid, p.add_id)];
          if (!d || !d.decision) continue;
          if (d.decision === "dismiss") {
            out.push({ history_id: hid, item_id: null, add_id: p.add_id, message_id: m.message_id, decision: "dismiss",
              fields: null, reason: d.note || "", annotator, basis: "agent-overridden" });
          } else {
            const fields = d.fields || p.fields;
            const same = sameFields(fields, p.fields);
            out.push({ history_id: hid, item_id: null, add_id: p.add_id, message_id: m.message_id, decision: p.decision,
              fields, reason: d.note || p.reason || "", annotator, basis: same ? "agent-confirmed" : "agent-overridden" });
          }
        }
        for (const a of (store.added[hid] || []).filter((x) => x.message_id === m.message_id)) {
          out.push({ history_id: hid, item_id: null, add_id: a.add_id, message_id: m.message_id, decision: a.decision,
            fields: a.fields, reason: a.note || "", annotator, basis: "human" });
        }
      }
    }
    return out;
  }

  const toJsonl = (records) => records.map((r) => JSON.stringify(r)).join("\n") + (records.length ? "\n" : "");

  // A correction file back into the stored decisions (replaces those of the histories it names).
  function fromRecords(bundle, records) {
    const decisions = {}, added = {}, counters = {};
    for (const [n, r] of records.entries()) {
      const where = `record ${n + 1}`;
      const h = bundle.byHistory.get(r.history_id);
      if (!h) throw new Error(`${where}: history ${r.history_id} is not in the data`);
      if (r.item_id) {
        if (!h.byId.has(r.item_id)) throw new Error(`${where}: unknown item ${r.item_id}`);
        decisions[key(r.history_id, r.item_id)] = { decision: r.decision, fields: r.decision === "edit" ? r.fields : undefined, note: r.reason || "" };
      } else if (/^p/.test(r.add_id || "")) {
        const p = bundle.proposals.get(key(r.history_id, r.add_id));
        if (!p) throw new Error(`${where}: unknown agent proposal ${r.add_id}`);
        decisions[key(r.history_id, r.add_id)] = r.decision === "dismiss"
          ? { decision: "dismiss", note: r.reason || "" }
          : { decision: "confirm", fields: sameFields(r.fields, p.fields) ? undefined : r.fields, note: r.reason === p.reason ? "" : (r.reason || "") };
      } else if (/^h\d+\.\d+$/.test(r.add_id || "") && ADD_DECISIONS.includes(r.decision)) {
        (added[r.history_id] = added[r.history_id] || []).push({ add_id: r.add_id, message_id: r.message_id, decision: r.decision, fields: r.fields, note: r.reason || "" });
        const [v, i] = r.add_id.slice(1).split(".").map(Number);
        counters[key(r.history_id, v)] = Math.max(counters[key(r.history_id, v)] || 0, i);
      } else throw new Error(`${where}: neither an item decision nor an addition`);
    }
    return { decisions, added, counters, annotator: records.length ? records[0].annotator : null };
  }

  return { DATATYPES, KINDS, ADD_DECISIONS, key, parseJsonl, readBundle, objectText, timeText, claimText, quotes,
    changeLabel, effective, basisOf, claimProblems, supersessionProblems, addProblems, progress, toRecords, toJsonl,
    fromRecords };
});

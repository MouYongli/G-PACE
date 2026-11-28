// LoCoMo extraction correction page (E009 preparation). View 1 lists the conversations; view 2 shows
// one conversation message by message with the items the writer extracted there (claims, later
// mentions, endings and supersessions), the agent pre-review proposal of each item, and the missed
// events the agent proposes. Decisions are kept in localStorage, the imported bundle in IndexedDB;
// nothing leaves the browser except the files exported.
(function () {
  "use strict";

  const { $, h } = window.HR;
  const D = window.HRLocomoCorrectionData;
  const STORE_KEY = "hr.locomo-correction.v1";
  const MARK = { todo: "○", draft: "◐", done: "✓" };
  const LABEL = { accept: "accepted", reject: "rejected", edit: "edited", confirm: "confirmed", dismiss: "dismissed" };

  const store = { annotator: "", decisions: {}, added: {}, counters: {}, ui: { filter: "all" } };
  const state = { bundle: null, imported: false, editing: new Set() };

  // ---------- storage ----------

  function loadStore() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (saved) {
        for (const k of ["annotator", "decisions", "added", "counters"]) if (saved[k] != null) store[k] = saved[k];
        Object.assign(store.ui, saved.ui || {});
      }
    } catch (error) { state.saved = { ok: false }; }
  }

  function saveStore() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); state.saved = { ok: true }; }
    catch (error) { state.saved = { ok: false }; }
    for (const n of document.querySelectorAll("[data-save]")) {
      n.classList.toggle("saved", state.saved.ok);
      n.classList.toggle("failed", !state.saved.ok);
      n.textContent = state.saved.ok ? "Saved in this browser" : "Not saved: browser storage unavailable. Export often";
    }
  }

  function idb(mode, fn) {
    return new Promise((resolve, reject) => {
      const open = indexedDB.open("hr-locomo-correction", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("data");
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const req = fn(open.result.transaction("data", mode).objectStore("data"));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      };
    });
  }
  const loadImported = () => idb("readonly", (s) => s.get("bundle")).catch(() => null);
  const saveImported = (value) => idb("readwrite", (s) => s.put(value, "bundle")).catch(() => null);

  // ---------- helpers ----------

  const K = D.key;
  const hist = (hid) => state.bundle.byHistory.get(hid);
  const agentAdds = (hid, mid) => (state.bundle.addsOf.get(hid) || new Map()).get(mid) || [];
  const humanAdds = (hid, mid) => (store.added[hid] || []).filter((a) => a.message_id === mid);
  const isChangeItem = (item) => (item.change || []).length > 0;

  function touch() { saveStore(); renderProgress(); }

  // Claims known at a message (for endings and supersessions): extracted, agent-added (not
  // dismissed) and human-added claims at or before its version.
  function claimsUpTo(hid, version) {
    const hh = hist(hid);
    const out = new Map();
    for (const item of hh.items) if (item.kind === "claim" && item.version <= version) out.set(item.item_id, D.claimText(item.claim, hh.labels) + ` (${item.message_id})`);
    for (const [mid, list] of state.bundle.addsOf.get(hid) || new Map()) {
      if (hh.versionOf.get(mid) > version) continue;
      for (const p of list) {
        const d = store.decisions[K(hid, p.add_id)];
        if (p.decision === "add_claim" && !(d && d.decision === "dismiss")) out.set(p.add_id, D.claimText((d && d.fields) || p.fields, hh.labels) + ` (${mid}, agent)`);
      }
    }
    for (const a of store.added[hid] || []) {
      if (a.decision === "add_claim" && hh.versionOf.get(a.message_id) <= version) out.set(a.add_id, D.claimText(a.fields, hh.labels) + ` (${a.message_id}, added)`);
    }
    return out;
  }

  // ---------- routing and views ----------

  function route() {
    const m = /^#\/([^/]+)$/.exec(location.hash);
    const hid = m ? decodeURIComponent(m[1]) : null;
    return hid && state.bundle.byHistory.has(hid) ? hid : null;
  }

  function render() {
    const hid = route();
    $("list-view").hidden = !!hid;
    $("conv-view").hidden = !hid;
    hid ? renderConv(hid) : renderList();
  }

  function renderList() {
    const tbody = $("convs").querySelector("tbody");
    tbody.replaceChildren();
    for (const hh of state.bundle.histories) {
      const p = D.progress(state.bundle, store, hh.history_id);
      const st = p.decided === 0 && !p.added ? "todo" : p.decided === p.total ? "done" : "draft";
      const open = () => { location.hash = "#/" + encodeURIComponent(hh.history_id); };
      tbody.append(h("tr", { tabindex: 0, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
        h("td", { class: "cid" }, hh.history_id),
        h("td", { class: "num" }, hh.messages.length),
        h("td", { class: "num" }, hh.items.length),
        h("td", { class: "num wide-only" }, p.change),
        h("td", { class: "num wide-only" }, p.agentAdds),
        h("td", { class: "progress-cell" },
          h("div", { class: "meter" }, h("div", { class: st === "done" ? "done" : "draft", style: `width:${(100 * p.decided) / Math.max(1, p.total)}%` })),
          h("div", { class: "progress-note" }, h("span", { class: "st " + st }, MARK[st]),
            ` ${p.decided}/${p.total} decided · change events ${p.changeDecided}/${p.change}` + (p.added ? ` · ${p.added} added by you` : "")))));
    }
    const src = state.bundle.source.name || state.bundle.source.run_id || "data";
    $("data-source").textContent = "Data: " + src + (state.imported ? " (imported)" : " (synthetic example)");
    $("help-source").textContent = $("data-source").textContent;
  }

  function renderProgress() {
    const hid = route();
    if (!hid) return;
    const p = D.progress(state.bundle, store, hid);
    $("conv-progress").textContent = `${p.decided}/${p.total} decided · change events ${p.changeDecided}/${p.change}` + (p.added ? ` · ${p.added} added` : "");
  }

  function renderConv(hid) {
    const sel = $("conv-select");
    if (sel.dataset.built !== "1") {
      sel.replaceChildren(...state.bundle.histories.map((x) => h("option", { value: x.history_id }, x.history_id)));
      sel.dataset.built = "1";
    }
    sel.value = hid;
    for (const b of document.querySelectorAll("[data-filter]")) b.classList.toggle("on", b.dataset.filter === store.ui.filter);
    renderProgress();
    const hh = hist(hid);
    const ids = claimsUpTo(hid, Infinity);
    $("claim-ids").replaceChildren(...[...ids].map(([id, text]) => h("option", { value: id }, text)));
    const inner = $("lc-inner");
    inner.replaceChildren();
    let segment = null, shown = 0;
    for (const m of hh.messages) {
      const block = messageBlock(hid, m);
      if (!block) continue;
      if (m.segment_id !== segment) {
        segment = m.segment_id;
        const s = hh.segmentOf.get(segment);
        inner.append(h("div", { class: "session" }, h("b", {}, segment || "—"), s && (s.timestamp_raw || s.timestamp) ? h("span", { class: "muted" }, s.timestamp_raw || s.timestamp) : null));
      }
      inner.append(block);
      shown++;
    }
    if (!shown) inner.append(h("p", { class: "muted" }, "No message matches the filter."));
  }

  function rerenderMessage(hid, m) {
    const old = document.getElementById("m-" + m.message_id);
    const block = messageBlock(hid, m, true);
    if (old && block) old.replaceWith(block);
    renderProgress();
  }

  // ---------- one message ----------

  function messageBlock(hid, m, force) {
    const hh = hist(hid);
    const filter = store.ui.filter;
    let items = hh.itemsOf.get(m.message_id);
    const agent = agentAdds(hid, m.message_id);
    const mine = humanAdds(hid, m.message_id);
    if (filter === "change") {
      items = items.filter((i) => isChangeItem(i) || (store.decisions[K(hid, i.item_id)] || {}).decision === "edit");
      const humanChange = mine.filter((a) => a.decision !== "add_claim");
      if (!force && !items.length && !agent.length && !humanChange.length) return null;
    } else if (filter === "items" && !force && !items.length && !agent.length && !mine.length) return null;
    const block = h("div", { class: "msg", id: "m-" + m.message_id },
      h("div", { class: "msg-head" }, h("b", {}, m.speaker || "—"), h("span", { class: "mono" }, m.message_id),
        h("span", { class: "muted" }, "v" + m.version)),
      h("div", { class: "msg-text" }, highlighted(m.text, hh.itemsOf.get(m.message_id), m.message_id)));
    const rows = h("div", { class: "rows" },
      items.map((item) => itemCard(hid, m, item)),
      agent.map((p) => addCard(hid, m, p, true)),
      (filter === "change" ? mine.filter((a) => a.decision !== "add_claim") : mine).map((a) => addCard(hid, m, a, false)));
    block.append(rows);
    const pending = items.filter((i) => !(store.decisions[K(hid, i.item_id)] || {}).decision && state.bundle.proposals.has(K(hid, i.item_id)));
    block.append(h("div", { class: "msg-actions" },
      pending.length > 1 ? h("button", { type: "button", onclick: () => {
        for (const i of pending) {
          const p = state.bundle.proposals.get(K(hid, i.item_id));
          store.decisions[K(hid, i.item_id)] = { decision: p.decision, fields: p.fields ? JSON.parse(JSON.stringify(p.fields)) : undefined, note: "" };
        }
        touch(); rerenderMessage(hid, m);
      } }, `Confirm the ${pending.length} item proposals`) : null,
      h("button", { type: "button", class: "add", onclick: () => addHuman(hid, m, "add_claim") }, "+ Missed claim"),
      h("button", { type: "button", class: "add", onclick: () => addHuman(hid, m, "add_ending") }, "+ Missed ending"),
      h("button", { type: "button", class: "add", onclick: () => addHuman(hid, m, "add_supersession") }, "+ Missed supersession")));
    return block;
  }

  // Message text with the evidence spans of its items underlined.
  function highlighted(text, items, mid) {
    const marks = new Array(text.length).fill(false);
    for (const item of items) for (const e of item.evidence || []) {
      if (e.span && e.message_id === mid) for (let i = e.span.start; i < Math.min(e.span.end, text.length); i++) marks[i] = true;
    }
    const out = [];
    let i = 0;
    while (i < text.length) {
      let j = i;
      while (j < text.length && marks[j] === marks[i]) j++;
      out.push(marks[i] ? h("mark", {}, text.slice(i, j)) : text.slice(i, j));
      i = j;
    }
    return out;
  }

  // ---------- items ----------

  function itemCard(hid, m, item) {
    const hh = hist(hid);
    const k = K(hid, item.item_id);
    const human = store.decisions[k];
    const proposal = state.bundle.proposals.get(k);
    const eff = D.effective(state.bundle, store, hid, item.item_id);
    const change = D.changeLabel(item);
    const decided = human && human.decision;
    const decide = (decision, fields) => {
      store.decisions[k] = { ...(human || {}), decision, fields: fields ? JSON.parse(JSON.stringify(fields)) : undefined };
      if (decision === "edit") state.editing.add(k); else state.editing.delete(k);
      touch(); rerenderMessage(hid, m);
    };
    const kindChip = item.kind === "claim" ? "claim" : item.kind === "attribution" ? "mention of " + item.claim_id : "supersession";
    const card = h("div", { class: `item ${item.kind}` + (change ? " change" : "") + (decided ? " decided" : "") + (eff && eff.decision === "reject" ? " rejected" : "") },
      h("div", { class: "item-head" },
        h("span", { class: "chip" }, kindChip), change ? h("span", { class: "chip warn" }, change) : null,
        h("span", { class: "mono muted" }, item.item_id), h("span", { class: "spacer" }),
        h("span", { class: "st " + (decided ? "done" : "todo") }, decided ? "✓ " + LABEL[human.decision] : "○ undecided")),
      itemBody(hh, m, item, eff));
    if (proposal) card.append(proposalBox(proposal, decided, () => decide(proposal.decision, proposal.fields || undefined)));
    const canEdit = item.kind !== "attribution";
    const btn = (id, text, cls) => h("button", { type: "button", class: (decided && human.decision === id ? "on " : "") + (cls || ""),
      onclick: () => decide(id, id === "edit" ? { ...((human && human.fields) || (proposal && proposal.decision === "edit" && proposal.fields) || {}) } : undefined) }, text);
    card.append(h("div", { class: "actions" }, btn("accept", "Accept"), btn("reject", "Reject", "reject"), canEdit ? btn("edit", "Edit") : null,
      h("input", { type: "text", class: "note", placeholder: "Reason or note (optional)", value: (human && human.note) || "", "aria-label": "Note",
        oninput: (e) => { store.decisions[k] = { ...(store.decisions[k] || {}), note: e.target.value }; saveStore(); } })));
    if (decided && human.decision === "edit") {
      card.append(item.kind === "claim" ? claimEditForm(hid, m, item, human) : supersessionEditForm(hid, m, item, human));
    }
    return card;
  }

  function itemBody(hh, m, item, eff) {
    const labels = hh.labels;
    const edited = eff && eff.decision === "edit" && eff.fields ? eff.fields : null;
    if (item.kind === "supersession") {
      const s = { ...item.supersession, ...(edited || {}) };
      const rep = s.replacing_claim_id ? hh.byId.get(s.replacing_claim_id) : null;
      return h("div", { class: "body" },
        h("div", { class: "core" }, s.replacing_claim_id ? `${s.kind}: ` : `ending (${s.kind}): `,
          h("span", { class: "mono" }, s.claim_id), " ", D.claimText(item.claim, labels), " ", h("span", { class: "muted" }, D.timeText(item.claim && item.claim.valid_time))),
        s.replacing_claim_id ? h("div", { class: "core" }, "replaced by ", h("span", { class: "mono" }, s.replacing_claim_id), " ",
          rep ? D.claimText(rep.claim, labels) : (item.replacing ? D.claimText(item.replacing, labels) : "")) : null,
        h("div", { class: "attrs" }, `licensed by ${s.attribution_id}` + (s.valid_end ? ` · valid end ${s.valid_end}` : "")));
    }
    const claim = item.claim;
    const shown = edited ? { ...claim, ...edited } : claim;
    const atts = item.attributions || [];
    const qs = D.quotes(item, m.text);
    return h("div", { class: "body" },
      h("div", { class: "core" + (edited ? " edited" : "") }, D.claimText(shown, labels), " ",
        h("span", { class: "muted" }, D.timeText(shown && shown.valid_time)),
        item.kind === "attribution" ? h("span", { class: "muted" }, ` (from ${claim ? claim.version : "?"}: ${hh.messages.find((x) => x.version === (claim && claim.version))?.message_id || ""})`) : null),
      edited ? h("div", { class: "was muted" }, "extracted: " + D.claimText(claim, labels) + " " + D.timeText(claim.valid_time)) : null,
      atts.map((a) => h("div", { class: "attrs" + (a.polarity === "negative" ? " neg" : "") },
        `${a.speaker} · ${a.function} · ${a.polarity} · ${a.report_mode} · ${a.certainty}` + (a.derived ? " · derived" : "") + ` (${a.attribution_id})`)),
      qs.length ? h("div", { class: "quote" }, qs.map((q) => "“" + q + "”").join(" ")) : null);
  }

  function proposalBox(p, decided, confirm) {
    const fields = p.fields ? fieldsText(p.decision, p.fields) : "";
    return h("div", { class: "proposal" },
      h("span", { class: "chip on" }, "agent proposal"), " ",
      h("b", {}, p.decision.replace("_", " ")), fields ? h("span", { class: "mono" }, " " + fields) : null,
      h("span", { class: "muted" }, " — " + (p.reason || "")),
      !decided ? h("button", { type: "button", class: "confirm", onclick: confirm }, "Confirm") : null);
  }

  function fieldsText(decision, f) {
    if (decision === "add_ending") return `ends ${f.claim_id}`;
    if (decision === "add_supersession") return `${f.claim_id} → ${f.replacing_claim_id}`;
    return Object.entries(f).filter(([k]) => k !== "quote").map(([k, v]) =>
      `${k}=${k === "object" ? D.objectText(v) : k === "valid_time" ? (D.timeText(v) || "none") : v}`).join(", ");
  }

  // ---------- edit forms ----------

  function field(label, value, set, attrs) {
    return h("label", attrs || {}, label, h("input", { type: "text", value: value == null ? "" : value, spellcheck: "false", oninput: (e) => set(e.target.value) }));
  }

  function select(label, value, options, set) {
    return h("label", {}, label, h("select", { onchange: (e) => set(e.target.value) }, options.map((o) => h("option", { value: o, selected: o === value }, o))));
  }

  // Edits only the fields that differ from the extraction are kept in `fields`.
  function claimEditForm(hid, m, item, human) {
    const base = item.claim;
    const f = human.fields = human.fields || {};
    const cur = () => ({ ...base, ...f });
    const problems = h("ul", { class: "problems" });
    const check = () => { problems.replaceChildren(...D.claimProblems(f, true).map((p) => h("li", {}, p))); };
    const set = (name, value) => {
      if (JSON.stringify(value) === JSON.stringify(base[name])) delete f[name]; else f[name] = value;
      saveStore(); check();
    };
    const obj = () => cur().object;
    const vt = () => cur().valid_time || { start: null, end: null, expression: null };
    const objKind = "entity" in obj() ? "entity" : "value";
    const form = h("div", { class: "edit" },
      field("subject", cur().subject, (v) => set("subject", v.trim())),
      field("predicate", cur().predicate, (v) => set("predicate", v.trim())),
      select("object kind", objKind, ["entity", "value"], (v) => {
        const o = obj();
        const text = "entity" in o ? o.entity : o.value;
        set("object", v === "entity" ? { entity: String(text).replace(/\W+/g, "_") } : { value: text, datatype: "string" });
        rerenderMessage(hid, m);
      }),
      field(objKind === "entity" ? "object (entity ID)" : "object (value)", objKind === "entity" ? obj().entity : obj().value,
        (v) => set("object", objKind === "entity" ? { entity: v.trim() } : { value: v, datatype: obj().datatype || "string" })),
      objKind === "value" ? select("datatype", obj().datatype || "string", D.DATATYPES, (v) => set("object", { value: obj().value, datatype: v })) : null,
      field("valid from", vt().start, (v) => set("valid_time", { ...vt(), start: v.trim() || null })),
      field("valid until", vt().end, (v) => set("valid_time", { ...vt(), end: v.trim() || null })),
      field("time expression", vt().expression, (v) => set("valid_time", { ...vt(), expression: v.trim() || null })),
      problems);
    check();
    return form;
  }

  function supersessionEditForm(hid, m, item, human) {
    const base = item.supersession;
    const f = human.fields = human.fields || {};
    const cur = () => ({ ...base, ...f });
    const ids = new Set(claimsUpTo(hid, m.version).keys());
    const problems = h("ul", { class: "problems" });
    const check = () => { problems.replaceChildren(...D.supersessionProblems(cur(), ids).map((p) => h("li", {}, p))); };
    const set = (name, value) => {
      if ((value || null) === (base[name] || null)) delete f[name]; else f[name] = value || null;
      saveStore(); check();
    };
    const form = h("div", { class: "edit" },
      select("kind", cur().kind, D.KINDS, (v) => set("kind", v)),
      field("valid end", cur().valid_end, (v) => set("valid_end", v.trim())),
      field("replacing claim (empty: ending)", cur().replacing_claim_id, (v) => set("replacing_claim_id", v.trim()), { class: "wide" }),
      problems);
    form.querySelectorAll("input")[1].setAttribute("list", "claim-ids");
    check();
    return form;
  }

  // ---------- additions ----------

  function addHuman(hid, m, decision) {
    const ck = K(hid, m.version);
    const n = (store.counters[ck] || 0) + 1;
    store.counters[ck] = n;
    const fields = decision === "add_claim"
      ? { subject: m.speaker ? m.speaker.replace(/\W+/g, "_") : "", predicate: "", object: { entity: "" }, valid_time: { start: null, end: null, expression: null }, quote: "" }
      : decision === "add_ending" ? { claim_id: "", kind: "change", valid_end: null }
        : { claim_id: "", replacing_claim_id: "", kind: "change", valid_end: null };
    (store.added[hid] = store.added[hid] || []).push({ add_id: `h${m.version}.${n}`, message_id: m.message_id, decision, fields, note: "" });
    touch(); rerenderMessage(hid, m);
  }

  function addCard(hid, m, add, isAgent) {
    const k = K(hid, add.add_id);
    const d = isAgent ? store.decisions[k] : null;
    const decided = isAgent ? d && d.decision : true;
    const dismissed = isAgent && d && d.decision === "dismiss";
    const title = { add_claim: "missed claim", add_ending: "missed ending", add_supersession: "missed supersession" }[add.decision];
    const card = h("div", { class: "item added" + (isAgent ? " agent" : " mine") + (dismissed ? " rejected" : "") + (add.decision !== "add_claim" || add.change_event ? " change" : "") },
      h("div", { class: "item-head" },
        h("span", { class: "chip " + (isAgent ? "on" : "ok") }, isAgent ? "agent: " + title : "added by you: " + title),
        h("span", { class: "mono muted" }, add.add_id), h("span", { class: "spacer" }),
        isAgent ? h("span", { class: "st " + (decided ? "done" : "todo") }, decided ? "✓ " + LABEL[d.decision] : "○ undecided") : null));
    if (isAgent) {
      const fields = (d && d.fields) || add.fields;
      card.append(addSummary(hid, m, add.decision, fields), h("div", { class: "proposal" }, h("span", { class: "muted" }, add.reason || "")));
      const set = (decision, extra) => { store.decisions[k] = { ...(d || {}), decision, ...(extra || {}) }; touch(); rerenderMessage(hid, m); };
      card.append(h("div", { class: "actions" },
        h("button", { type: "button", class: d && d.decision === "confirm" && !d.fields ? "on" : "", onclick: () => set("confirm", { fields: undefined }) }, "Confirm"),
        h("button", { type: "button", class: "reject" + (dismissed ? " on" : ""), onclick: () => set("dismiss", { fields: undefined }) }, "Dismiss"),
        h("button", { type: "button", class: d && d.fields ? "on" : "", onclick: () => set("confirm", { fields: JSON.parse(JSON.stringify(add.fields)) }) }, "Edit"),
        h("input", { type: "text", class: "note", placeholder: "Reason or note (optional)", value: (d && d.note) || "", "aria-label": "Note",
          oninput: (e) => { store.decisions[k] = { ...(store.decisions[k] || {}), note: e.target.value }; saveStore(); } })));
      if (d && d.fields) card.append(addForm(hid, m, add.decision, d.fields));
    } else {
      card.append(addForm(hid, m, add.decision, add.fields),
        h("div", { class: "actions" },
          h("input", { type: "text", class: "note", placeholder: "Reason or note (optional)", value: add.note || "", "aria-label": "Note",
            oninput: (e) => { add.note = e.target.value; saveStore(); } }),
          h("button", { type: "button", onclick: () => { store.added[hid] = store.added[hid].filter((a) => a !== add); touch(); rerenderMessage(hid, m); } }, "Remove")));
    }
    return card;
  }

  function addSummary(hid, m, decision, f) {
    const hh = hist(hid);
    const ids = claimsUpTo(hid, m.version);
    if (decision === "add_claim") {
      return h("div", { class: "body" }, h("div", { class: "core" }, D.claimText(f, hh.labels), " ", h("span", { class: "muted" }, D.timeText(f.valid_time))),
        f.quote ? h("div", { class: "quote" }, "“" + f.quote + "”") : null);
    }
    return h("div", { class: "body" },
      h("div", { class: "core" }, decision === "add_ending" ? "ends " : "", h("span", { class: "mono" }, f.claim_id), " ", ids.get(f.claim_id) || "(unknown claim)"),
      f.replacing_claim_id ? h("div", { class: "core" }, "replaced by ", h("span", { class: "mono" }, f.replacing_claim_id), " ", ids.get(f.replacing_claim_id) || "(unknown claim)") : null,
      h("div", { class: "attrs" }, `kind ${f.kind || "change"}` + (f.valid_end ? ` · valid end ${f.valid_end}` : "")));
  }

  function addForm(hid, m, decision, f) {
    const problems = h("ul", { class: "problems" });
    const ids = new Set(claimsUpTo(hid, m.version).keys());
    const check = () => { problems.replaceChildren(...D.addProblems({ decision, fields: f }, ids).map((p) => h("li", {}, p))); };
    const set = (name, value) => { f[name] = value; saveStore(); check(); };
    let form;
    if (decision === "add_claim") {
      const vt = () => f.valid_time || (f.valid_time = { start: null, end: null, expression: null });
      const objKind = f.object && "value" in f.object ? "value" : "entity";
      form = h("div", { class: "edit" },
        field("subject (entity ID)", f.subject, (v) => set("subject", v.trim())),
        field("predicate", f.predicate, (v) => set("predicate", v.trim())),
        select("object kind", objKind, ["entity", "value"], (v) => { set("object", v === "entity" ? { entity: "" } : { value: "", datatype: "string" }); rerenderMessage(hid, m); }),
        field(objKind === "entity" ? "object (entity ID)" : "object (value)", objKind === "entity" ? f.object.entity : f.object.value,
          (v) => set("object", objKind === "entity" ? { entity: v.trim() } : { value: v, datatype: f.object.datatype || "string" })),
        objKind === "value" ? select("datatype", f.object.datatype || "string", D.DATATYPES, (v) => set("object", { value: f.object.value, datatype: v })) : null,
        field("valid from", vt().start, (v) => { vt().start = v.trim() || null; saveStore(); check(); }),
        field("valid until", vt().end, (v) => { vt().end = v.trim() || null; saveStore(); check(); }),
        field("time expression", vt().expression, (v) => { vt().expression = v.trim() || null; saveStore(); check(); }),
        field("quote (verbatim from the message; optional)", f.quote, (v) => set("quote", v), { class: "wide" }),
        problems);
    } else {
      form = h("div", { class: "edit" },
        field(decision === "add_ending" ? "claim that ends" : "claim that is replaced", f.claim_id, (v) => set("claim_id", v.trim())),
        decision === "add_supersession" ? field("replacing claim", f.replacing_claim_id, (v) => set("replacing_claim_id", v.trim())) : null,
        select("kind", f.kind || "change", D.KINDS, (v) => set("kind", v)),
        field("valid end (optional)", f.valid_end, (v) => set("valid_end", v.trim() || null)),
        field("quote (verbatim from the message; optional)", f.quote, (v) => set("quote", v), { class: "wide" }),
        problems);
      const inputs = form.querySelectorAll("input");
      inputs[0].setAttribute("list", "claim-ids");
      if (decision === "add_supersession") inputs[1].setAttribute("list", "claim-ids");
    }
    check();
    return form;
  }

  // ---------- navigation ----------

  function nextOpen() {
    const hid = route();
    if (!hid) return;
    const hh = hist(hid);
    const open = [];
    for (const m of hh.messages) {
      const items = hh.itemsOf.get(m.message_id).filter((i) => store.ui.filter !== "change" || isChangeItem(i));
      if (items.some((i) => !(store.decisions[K(hid, i.item_id)] || {}).decision) ||
          agentAdds(hid, m.message_id).some((p) => !(store.decisions[K(hid, p.add_id)] || {}).decision)) open.push(m.message_id);
    }
    const main = $("lc-main");
    const top = main.getBoundingClientRect().top;
    const target = open.map((id) => document.getElementById("m-" + id)).find((n) => n && n.getBoundingClientRect().top > top + 8)
      || (open.length ? document.getElementById("m-" + open[0]) : null);
    if (target) target.scrollIntoView({ block: "start" });
    else notice("Nothing left to decide" + (store.ui.filter === "change" ? " among the change events." : "."));
  }

  // ---------- files ----------

  function notice(text, bad) {
    $("notice-text").textContent = text;
    $("notice").classList.toggle("bad", !!bad);
    $("notice").hidden = false;
  }

  function download(name, type, content) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    h("a", { href: url, download: name }).click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function exportJsonl() {
    const annotator = store.annotator.trim();
    if (!annotator) { notice("Type your annotator ID first.", true); $("annotator").focus(); return; }
    const records = D.toRecords(state.bundle, store, annotator);
    if (!records.length) { notice("Nothing decided yet.", true); return; }
    download(`locomo-corrections-${annotator}.jsonl`, "application/jsonl", D.toJsonl(records));
    const total = state.bundle.histories.reduce((n, x) => n + D.progress(state.bundle, store, x.history_id).total, 0);
    const decided = state.bundle.histories.reduce((n, x) => n + D.progress(state.bundle, store, x.history_id).decided, 0);
    notice(`Exported ${records.length} decisions (${decided} of ${total} items and agent proposals decided). Undecided items keep the writer's extraction when the file is applied.`);
  }

  async function importData(file) {
    try {
      const bundle = D.readBundle(JSON.parse(await file.text()));
      state.bundle = bundle;
      state.imported = true;
      await saveImported(JSON.parse(await file.text()));
      $("conv-select").dataset.built = "";
      location.hash = "#/";
      render();
      notice(`Imported ${bundle.histories.length} conversations, ${bundle.histories.reduce((n, x) => n + x.items.length, 0)} items, ${bundle.proposals.size} agent proposals.`);
    } catch (error) { notice("Import failed: " + error.message, true); }
  }

  async function importLabels(file) {
    try {
      const parsed = D.fromRecords(state.bundle, D.parseJsonl(await file.text(), file.name));
      const names = new Set(Object.keys(parsed.decisions).map((k) => k.split("|")[0]).concat(Object.keys(parsed.added)));
      for (const k of Object.keys(store.decisions)) if (names.has(k.split("|")[0])) delete store.decisions[k];
      for (const hid of names) store.added[hid] = parsed.added[hid] || [];
      Object.assign(store.decisions, parsed.decisions);
      Object.assign(store.counters, parsed.counters);
      if (!store.annotator && parsed.annotator) { store.annotator = parsed.annotator; $("annotator").value = parsed.annotator; }
      saveStore(); render();
      notice(`Loaded the decisions of ${[...names].join(", ")}; earlier decisions of these conversations were replaced.`);
    } catch (error) { notice("Labels not loaded: " + error.message, true); }
  }

  // ---------- boot ----------

  function wire() {
    $("annotator").value = store.annotator;
    $("annotator").addEventListener("input", (e) => { store.annotator = e.target.value; saveStore(); });
    $("import-data").addEventListener("click", () => $("data-file").click());
    $("data-file").addEventListener("change", (e) => { if (e.target.files[0]) importData(e.target.files[0]); e.target.value = ""; });
    $("import-labels").addEventListener("click", () => $("labels-file").click());
    $("labels-file").addEventListener("change", (e) => { if (e.target.files[0]) importLabels(e.target.files[0]); e.target.value = ""; });
    $("export-jsonl").addEventListener("click", exportJsonl);
    $("next-open").addEventListener("click", nextOpen);
    $("notice-close").addEventListener("click", () => { $("notice").hidden = true; });
    document.querySelector(".help-button").addEventListener("click", () => $("help").showModal());
    $("conv-select").addEventListener("change", (e) => { location.hash = "#/" + encodeURIComponent(e.target.value); });
    for (const b of document.querySelectorAll("[data-filter]")) {
      b.addEventListener("click", () => { store.ui.filter = b.dataset.filter; saveStore(); render(); $("lc-main").scrollTop = 0; });
    }
    window.addEventListener("hashchange", render);
  }

  async function boot() {
    loadStore();
    wire();
    const imported = await loadImported();
    try {
      if (imported) { state.bundle = D.readBundle(imported); state.imported = true; }
    } catch (error) { state.bundle = null; }
    if (!state.bundle) { state.bundle = D.readBundle(window.HR_EXAMPLE); state.imported = false; }
    render();
  }

  boot();
})();

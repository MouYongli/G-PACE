// Graph-quality review page. View 1 lists the 40 segments; view 2 shows one segment as its messages
// with the claim rows of the merged agent annotation under each message. Decisions are kept in
// localStorage, imported data in IndexedDB; nothing leaves the browser except the files exported.
(function () {
  "use strict";

  const { $, h } = window.HR;
  const D = window.HRGraphQualityData;
  const STORE_KEY = "hr.graph-quality.v1";
  const MARK = { todo: "○", draft: "◐", done: "✓" };

  // Kept across reloads.
  const store = { annotator: "", decisions: {}, added: {}, done: {}, minutes: {}, ui: { show: "all" } };
  // Rebuilt on every load.
  const state = {
    segments: [], merged: { names: ["A", "B"], rows: [] }, source: { name: "data/example.js", imported: false },
    byKey: new Map(), rowsOf: new Map(), editing: new Set(), saved: null,
  };

  // ---------- storage ----------

  function loadStore() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (saved) {
        for (const k of ["annotator", "decisions", "added", "done", "minutes"]) if (saved[k] != null) store[k] = saved[k];
        Object.assign(store.ui, saved.ui || {});
      }
    } catch (error) { state.saved = { ok: false }; }
  }

  function saveStore() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); state.saved = { ok: true, at: new Date() }; }
    catch (error) { state.saved = { ok: false }; }
    renderSaveState();
  }

  function renderSaveState() {
    for (const n of document.querySelectorAll("[data-save]")) {
      n.classList.toggle("saved", !!state.saved && state.saved.ok);
      n.classList.toggle("failed", !!state.saved && !state.saved.ok);
      n.textContent = !state.saved ? "" : state.saved.ok ? "Saved in this browser" : "Not saved: browser storage unavailable. Export often";
    }
  }

  function idb(mode, fn) {
    return new Promise((resolve, reject) => {
      const open = indexedDB.open("hr-graph-quality", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("data");
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const req = fn(open.result.transaction("data", mode).objectStore("data"));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      };
    });
  }
  const loadImported = () => idb("readonly", (s) => s.get("data")).catch(() => null);
  const saveImported = (value) => idb("readwrite", (s) => s.put(value, "data")).catch(() => null);

  // ---------- data ----------

  function setData(segments, merged, source) {
    state.segments = segments;
    state.merged = merged;
    state.source = source;
    state.byKey = new Map(segments.map((s) => [s.key, s]));
    state.rowsOf = new Map(segments.map((s) => [s.key, []]));
    for (const r of merged.rows) if (state.rowsOf.has(r.segment)) state.rowsOf.get(r.segment).push(r);
  }

  const kindOf = (row) => D.rowKind(row);
  const needsReview = (row) => kindOf(row) !== "identical";
  const decisionOf = (row) => D.effective(row, store.decisions);

  function segStats(key) {
    const rows = state.rowsOf.get(key) || [];
    const review = rows.filter(needsReview);
    const decided = review.filter((r) => decisionOf(r)).length;
    const added = (store.added[key] || []).length;
    const status = store.done[key] ? "done" : decided || added || rows.some((r) => (store.decisions[r.uid] || {}).choice) ? "draft" : "todo";
    return { rows: rows.length, review: review.length, decided, added, status };
  }

  // Problems that block marking a segment done: undecided rows, invalid claims.
  function segProblems(key) {
    const seg = state.byKey.get(key);
    const text = (id) => (seg.messages.find((m) => m.message_id === id) || {}).text || "";
    const out = [];
    for (const r of state.rowsOf.get(key) || []) {
      const d = decisionOf(r);
      if (!d) { out.push(`undecided row in ${r.message_id}`); continue; }
      if (d.choice === "edit") {
        const p = D.claimProblems(d.edit, text(r.message_id));
        if (p.length) out.push(`${r.message_id}: ${p[0]}`);
      }
    }
    for (const a of store.added[key] || []) {
      const p = D.claimProblems(a.fields, text(a.fields.message_id));
      if (p.length) out.push(`added claim in ${a.fields.message_id}: ${p[0]}`);
    }
    return out;
  }

  function touch(key) { // any change reopens the segment
    delete store.done[key];
    saveStore();
  }

  // ---------- views ----------

  function route() {
    const m = /^#\/seg\/(.+)$/.exec(location.hash);
    const key = m ? decodeURIComponent(m[1]) : null;
    return key && state.byKey.has(key) ? key : null;
  }

  function render() {
    const key = route();
    $("list-view").hidden = !!key;
    $("seg-view").hidden = !key;
    key ? renderSegment(key) : renderList();
    renderSaveState();
  }

  function renderList() {
    const tbody = $("segments").querySelector("tbody");
    tbody.replaceChildren();
    let done = 0;
    for (const seg of state.segments) {
      const s = segStats(seg.key);
      if (s.status === "done") done++;
      const pct = (n) => (s.review ? (100 * n) / s.review : 0) + "%";
      const open = () => { location.hash = "#/seg/" + encodeURIComponent(seg.key); };
      tbody.append(h("tr", { tabindex: 0, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
        h("td", { class: "cid" }, seg.key),
        h("td", {}, seg.benchmark),
        h("td", { class: "num wide-only" }, seg.messages.length),
        h("td", { class: "num" }, s.rows),
        h("td", { class: "num wide-only" }, s.review),
        h("td", { class: "progress-cell" },
          h("div", { class: "meter" }, h("div", { class: s.status === "done" ? "done" : "draft", style: `width:${s.status === "done" ? 100 : (100 * s.decided) / Math.max(1, s.review)}%` })),
          h("div", { class: "progress-note" }, h("span", { class: "st " + s.status }, MARK[s.status]), ` ${s.decided}/${s.review} decided` + (s.added ? `, ${s.added} added` : "")))));
    }
    $("list-total").textContent = `${done} of ${state.segments.length} segments done`;
    $("data-source").textContent = "Data: " + state.source.name;
    $("help-source").textContent = "Data shown: " + state.source.name + (state.source.imported ? " (imported)" : " (synthetic example)");
  }

  function renderSegment(key, keepScroll) {
    const seg = state.byKey.get(key);
    const sel = $("seg-select");
    if (sel.dataset.built !== "1") {
      sel.replaceChildren(...state.segments.map((s) => h("option", { value: s.key }, s.key)));
      sel.dataset.built = "1";
    }
    sel.value = key;
    for (const b of document.querySelectorAll("[data-show]")) b.classList.toggle("on", b.dataset.show === store.ui.show);
    const st = segStats(key);
    $("seg-progress").textContent = `${MARK[st.status]} ${st.decided}/${st.review} to review decided, ${st.rows - st.review} identical pairs`;

    const main = $("gq-main");
    const top = main.scrollTop;
    const rowsByMsg = new Map();
    for (const r of state.rowsOf.get(key)) {
      if (!rowsByMsg.has(r.message_id)) rowsByMsg.set(r.message_id, []);
      rowsByMsg.get(r.message_id).push(r);
    }
    const inner = $("gq-inner");
    inner.replaceChildren();
    for (const m of seg.context) inner.append(messageBlock(m, true));
    for (const m of seg.messages) {
      const rows = (rowsByMsg.get(m.message_id) || []).filter((r) => store.ui.show === "all" || needsReview(r));
      const added = (store.added[key] || []).filter((a) => a.fields.message_id === m.message_id);
      const block = messageBlock(m, false);
      block.append(h("div", { class: "rows" }, rows.map((r) => rowCard(key, m, r)), added.map((a) => addedCard(key, m, a))),
        h("button", { type: "button", class: "add-claim", onclick: () => addClaim(key, m) }, "+ Add claim"));
      inner.append(block);
    }
    renderFoot(key);
    if (keepScroll) main.scrollTop = top; else main.scrollTop = 0;
  }

  function messageBlock(m, context) {
    return h("div", { class: "msg" + (context ? " context" : ""), id: "m-" + m.message_id },
      h("div", { class: "msg-head" }, h("b", {}, m.speaker), h("span", { class: "mono" }, m.message_id),
        m.date ? h("span", {}, m.date) : null, context ? h("span", { class: "chip" }, "context") : null),
      h("div", { class: "msg-text" }, m.text));
  }

  // ---------- rows ----------

  function version(label, cls, claim, diffs, chosen) {
    if (!claim) return h("div", { class: "version " + cls }, h("h3", {}, label), h("div", { class: "none" }, "no claim"));
    const hi = (f, text) => h("span", { class: diffs.includes(f) ? "diff" : "" }, text);
    const fmt = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));
    return h("div", { class: "version " + cls + (chosen ? " chosen" : "") },
      h("h3", {}, label),
      h("div", { class: "core" }, hi("subject", claim.subject), " ", h("span", { class: "pred" }, hi("predicate", claim.predicate)),
        " ", hi("object", claim.object)),
      h("div", { class: "quote" }, hi("quote", "“" + claim.quote + "”")),
      h("div", { class: "attrs" }, ["object_type", "speaker", "function", "report_mode", "polarity", "certainty", "derived",
        "correction", "time_expression", "valid_from", "valid_until"].map((f) =>
        h("span", {}, h("span", { class: "k" }, f + " "), h("span", { class: "v" }, hi(f, fmt(claim[f])))))));
  }

  function rowCard(key, msg, row) {
    const kind = kindOf(row);
    const dec = store.decisions[row.uid];
    const choice = dec && dec.choice;
    const [na, nb] = state.merged.names;
    const diffs = D.diffFields(row.a, row.b);
    const label = { identical: "A = B", differs: "A / B differ", a_only: na + " only", b_only: nb + " only" }[kind];
    const decide = (patch) => { store.decisions[row.uid] = { ...(dec || {}), ...patch }; touch(key); renderSegment(key, true); };
    const btn = (id, text, extra) => h("button", { type: "button", class: (choice === id ? "on " : "") + (extra || ""), onclick: () =>
      decide({ choice: id, edit: id === "edit" ? { ...(dec && dec.edit ? dec.edit : (row.a || row.b)) } : undefined }) }, text);
    const buttons = [];
    if (kind === "identical") buttons.push(h("button", { type: "button", class: choice === "a" || !choice ? "on" : "", onclick: () => decide({ choice: "a", edit: undefined }) }, "Accept"));
    else {
      if (row.a) buttons.push(btn("a", "Accept " + na));
      if (row.b) buttons.push(btn("b", "Accept " + nb));
    }
    buttons.push(btn("reject", "Reject", "reject"), btn("edit", "Edit"));
    const effective = decisionOf(row);
    const shown = effective && effective.choice;
    const card = h("div", { class: `row ${kind}` + (effective ? " decided" : "") + (shown === "reject" ? " rejected" : "") },
      h("div", { class: "row-head" },
        h("span", { class: "chip " + (kind === "identical" ? "ok" : kind === "differs" ? "warn" : "") }, label),
        kind !== "a_only" && kind !== "b_only" && row.strict === false ? h("span", { class: "chip" }, "anchor match only") : null,
        h("span", { class: "spacer" }),
        h("span", { class: "st " + (effective ? "done" : "todo") }, effective ? "✓ " + (shown === "reject" ? "rejected" : shown === "edit" ? "edited" : "accepted") : "○ undecided")),
      kind === "identical"
        ? h("div", { class: "versions" }, version(na + " = " + nb, "a", row.a, [], shown === "a"))
        : h("div", { class: "versions" }, version(na, "a", row.a, diffs, shown === "a"), version(nb, "b", row.b, diffs, shown === "b")),
      h("div", { class: "actions" }, buttons,
        h("input", { type: "text", class: "note", placeholder: "Note (optional)", value: (dec && dec.note) || "", "aria-label": "Note",
          oninput: (e) => { store.decisions[row.uid] = { ...(store.decisions[row.uid] || {}), note: e.target.value }; saveStore(); } })),
      shown === "edit" ? editForm(key, msg, dec.edit, () => { touch(key); }) : null);
    return card;
  }

  function addedCard(key, msg, entry) {
    const remove = () => { store.added[key] = store.added[key].filter((a) => a !== entry); touch(key); renderSegment(key, true); };
    return h("div", { class: "row added" },
      h("div", { class: "row-head" }, h("span", { class: "chip on" }, "added by you"), h("span", { class: "spacer" }),
        h("button", { type: "button", onclick: remove }, "Remove")),
      editForm(key, msg, entry.fields, () => { touch(key); }));
  }

  function addClaim(key, msg) {
    (store.added[key] = store.added[key] || []).push({ fields: D.blankClaim(msg) });
    touch(key);
    renderSegment(key, true);
  }

  // Form for the fields of one claim; edits the object in place and saves at once.
  function editForm(key, msg, claim, changed) {
    const problems = h("ul", { class: "problems" });
    const check = () => { problems.replaceChildren(...D.claimProblems(claim, msg.text).map((p) => h("li", {}, p))); };
    const set = (f, v) => { claim[f] = v; changed(); check(); };
    const text = (f, wide) => h("label", { class: wide ? "wide" : "" }, f,
      h("input", { type: "text", value: claim[f] == null ? "" : claim[f], spellcheck: "false", oninput: (e) => set(f, e.target.value) }));
    const select = (f) => h("label", {}, f,
      h("select", { onchange: (e) => set(f, e.target.value) }, D.ENUMS[f].map((v) => h("option", { value: v, selected: claim[f] === v }, v))));
    const check1 = (f) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: !!claim[f], onchange: (e) => set(f, e.target.checked) }), f);
    const form = h("div", { class: "edit" },
      text("subject"), text("predicate"), text("object"), select("object_type"), text("speaker"),
      select("function"), select("report_mode"), select("polarity"), select("certainty"),
      text("time_expression"), text("valid_from"), text("valid_until"), check1("derived"), check1("correction"),
      h("label", { class: "wide" }, "quote (verbatim from the message; select text in the message and paste)",
        h("input", { type: "text", value: claim.quote || "", spellcheck: "false", oninput: (e) => set("quote", e.target.value) })),
      problems);
    check();
    return form;
  }

  function renderFoot(key) {
    const st = segStats(key);
    const done = !!store.done[key];
    const problems = segProblems(key);
    const idx = state.segments.findIndex((s) => s.key === key);
    const next = state.segments[idx + 1];
    const minutes = h("input", { type: "text", inputmode: "numeric", value: store.minutes[key] ?? "", "aria-label": "Minutes spent",
      oninput: (e) => { const n = Number(e.target.value); if (e.target.value.trim() && Number.isFinite(n)) store.minutes[key] = n; else delete store.minutes[key]; saveStore(); } });
    $("gq-foot").replaceChildren(
      h("span", { class: "st " + st.status }, MARK[st.status]),
      h("span", { class: "muted" }, done ? "Segment done" : problems.length ? `${problems.length} open: ${problems[0]}` : "All rows decided"),
      h("span", { class: "spacer" }),
      h("label", { class: "muted" }, "Minutes ", minutes),
      done
        ? h("button", { type: "button", onclick: () => { delete store.done[key]; saveStore(); renderSegment(key, true); } }, "Reopen")
        : h("button", { type: "button", class: "primary", disabled: problems.length > 0, onclick: () => {
            store.done[key] = true; saveStore();
            if (next) location.hash = "#/seg/" + encodeURIComponent(next.key); else location.hash = "#/";
          } }, "Mark segment done" + (next ? " and go on" : "")));
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
    const records = D.toRecords(state.segments, state.merged, store, annotator);
    const n = state.segments.filter((s) => store.done[s.key]).length;
    if (!n) { notice("No segment is marked done yet.", true); return; }
    download(`labels-${annotator}.jsonl`, "application/jsonl", D.toJsonl(records));
    notice(`Exported ${n} done segments (${records.length} records). Not-done segments are left out, so the file is complete only when all 40 are done.`);
  }

  async function importData(files) {
    let segments = null, merged = null;
    try {
      for (const file of files) {
        const rows = D.parseJsonl(await file.text(), file.name);
        if (rows.length && rows[0].messages) segments = D.readSegments(rows);
        else if (rows.length && rows[0].agreement) merged = D.readMerged(rows);
        else throw new Error(`${file.name}: neither a segments file nor a merged file`);
      }
      const current = state.source.imported ? await loadImported() : null;
      segments = segments || (current && current.segments);
      merged = merged || (current && current.merged);
      if (!segments || !merged) throw new Error("both files are needed: segments.jsonl and the merged JSONL");
      const problems = D.checkData(segments, merged);
      if (problems.length) throw new Error(problems.slice(0, 3).join("; ") + (problems.length > 3 ? ` (${problems.length} problems)` : ""));
      await saveImported({ segments, merged });
      setData(segments, merged, { name: `${segments.length} segments, ${merged.rows.length} rows (imported)`, imported: true });
      $("seg-select").dataset.built = "";
      location.hash = "#/";
      render();
      notice(`Imported ${segments.length} segments and ${merged.rows.length} merged rows.`);
    } catch (error) {
      notice("Import failed: " + error.message, true);
    }
  }

  function saveDraft() {
    download(`graph-quality-draft-${store.annotator.trim() || "reviewer"}.json`, "application/json",
      JSON.stringify({ kind: "graph-quality-draft", version: 1, annotator: store.annotator, decisions: store.decisions,
        added: store.added, done: store.done, minutes: store.minutes }, null, 1));
  }

  async function loadDraft(file) {
    try {
      const d = JSON.parse(await file.text());
      if (d.kind !== "graph-quality-draft") throw new Error("not a draft file");
      for (const k of ["annotator", "decisions", "added", "done", "minutes"]) store[k] = d[k] ?? store[k];
      $("annotator").value = store.annotator;
      saveStore(); render();
      notice("Draft loaded.");
    } catch (error) { notice("Draft not loaded: " + error.message, true); }
  }

  // ---------- boot ----------

  function wire() {
    $("annotator").value = store.annotator;
    $("annotator").addEventListener("input", (e) => { store.annotator = e.target.value; saveStore(); });
    $("import-data").addEventListener("click", () => $("data-file").click());
    $("data-file").addEventListener("change", (e) => { if (e.target.files.length) importData([...e.target.files]); e.target.value = ""; });
    $("load-draft").addEventListener("click", () => $("draft-file").click());
    $("draft-file").addEventListener("change", (e) => { if (e.target.files[0]) loadDraft(e.target.files[0]); e.target.value = ""; });
    $("save-draft").addEventListener("click", saveDraft);
    $("export-jsonl").addEventListener("click", exportJsonl);
    $("notice-close").addEventListener("click", () => { $("notice").hidden = true; });
    document.querySelector(".help-button").addEventListener("click", () => $("help").showModal());
    $("seg-select").addEventListener("change", (e) => { location.hash = "#/seg/" + encodeURIComponent(e.target.value); });
    for (const b of document.querySelectorAll("[data-show]")) {
      b.addEventListener("click", () => { store.ui.show = b.dataset.show; saveStore(); render(); });
    }
    window.addEventListener("hashchange", render);
  }

  async function boot() {
    loadStore();
    wire();
    const imported = await loadImported();
    if (imported && imported.segments && imported.merged) {
      setData(imported.segments, imported.merged, { name: `${imported.segments.length} segments, ${imported.merged.rows.length} rows (imported)`, imported: true });
    } else {
      const ex = window.HR_EXAMPLE;
      setData(D.readSegments(ex.segments), D.readMerged(ex.merged), { name: "data/example.js (synthetic)", imported: false });
    }
    render();
  }

  boot();
})();

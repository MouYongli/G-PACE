// LoCoMo annotation page. View 1 lists the conversations; view 2 shows one conversation as
// questions | message tree | messages | label. Drafts are kept in localStorage per annotator,
// imported data in IndexedDB; nothing leaves the browser except the CSV the annotator exports.
(function () {
  "use strict";

  const { $, h } = window.HR;
  const D = window.HRLocomoData;
  const STORE_KEY = "hr.locomo.v1";
  const EXAMPLE = "data/example.js"; // sets window.HR_EXAMPLE
  const STATUS_MARK = { todo: "○", draft: "◐", done: "✓" };
  const STATUS_FILTERS = [["all", "All"], ["todo", "Todo"], ["draft", "Draft"], ["done", "Done"], ["flagged", "⚑"]];

  // Kept across reloads.
  const store = { annotator: "", labels: {}, ui: { questions: null, tree: null, evidenceOnly: false } };
  // Rebuilt on every load.
  const state = {
    conversations: [],
    source: { name: EXAMPLE, imported: false },
    conv: null, // conversation shown in view 2
    turns: new Map(), // turn id -> {turn, session}
    qid: null, // selected question id
    filter: { status: "all", categories: new Set(), overlap: false, search: "" },
    expanded: new Set(), // session indexes open in the tree
    revealed: new Set(), // turn ids shown although hidden by "Evidence"
    evidenceCursor: 0,
    overlay: null, // sidebar opened over the content on a narrow screen
    showProblems: false,
    saved: null, // {ok, at}
  };

  // ---------- storage ----------

  function loadStore() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (saved) {
        store.annotator = saved.annotator || "";
        store.labels = saved.labels || {};
        Object.assign(store.ui, saved.ui || {});
      }
    } catch (error) {
      state.saved = { ok: false, at: new Date() };
    }
  }

  function saveStore() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(store));
      state.saved = { ok: true, at: new Date() };
    } catch (error) {
      state.saved = { ok: false, at: new Date() };
    }
    renderSaveState();
  }

  function renderSaveState() {
    for (const node of document.querySelectorAll("[data-save]")) {
      node.classList.toggle("saved", !!state.saved && state.saved.ok);
      node.classList.toggle("failed", !!state.saved && !state.saved.ok);
      if (!state.saved) node.textContent = "";
      else if (!state.saved.ok) node.textContent = "Not saved: browser storage is unavailable. Export before closing.";
      else node.textContent = "Draft saved " + state.saved.at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    }
  }

  function idb(mode, run) {
    return new Promise((resolve, reject) => {
      const open = indexedDB.open("hr-locomo", 1);
      open.onupgradeneeded = () => open.result.createObjectStore("data");
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const tx = open.result.transaction("data", mode);
        const request = run(tx.objectStore("data"));
        tx.oncomplete = () => resolve(request && request.result);
        tx.onerror = () => reject(tx.error);
      };
    });
  }

  // ---------- labels ----------

  const bucket = () => (store.labels[store.annotator] = store.labels[store.annotator] || {});
  const entryOf = (qid) => bucket()[qid];
  const statusOf = (qid) => D.statusOf(entryOf(qid));

  function editEntry(qid, change) {
    const entries = bucket();
    const entry = entries[qid] || D.emptyEntry();
    change(entry);
    entry.status = "draft"; // any change to a done question needs a new confirmation
    if (D.isBlank(entry) && !entry.flagged) delete entries[qid];
    else entries[qid] = entry;
    saveStore();
  }

  function countsOf(conv) {
    const counts = { todo: 0, draft: 0, done: 0, flagged: 0, total: conv.questions.length };
    for (const q of conv.questions) {
      counts[statusOf(q.id)] += 1;
      if (entryOf(q.id)?.flagged) counts.flagged += 1;
    }
    return counts;
  }

  // ---------- small helpers ----------

  function formatDate(session, long) {
    if (!session.date_time) return session.date_text || "no date";
    const d = new Date(session.date_time);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: long ? "numeric" : undefined });
  }
  const formatTime = (session) => (session.date_time ? session.date_time.slice(11, 16) : "");
  const shortId = (conv, qid) => (qid.startsWith(conv.history_id + ":") ? qid.slice(conv.history_id.length + 1) : qid);
  const isNarrow = () => window.innerWidth <= 900;
  const question = () => state.conv && state.conv.questions.find((q) => q.id === state.qid);
  const evidenceIds = () => (question() ? question().evidence_ids.filter((id) => state.turns.has(id)) : []);

  function visibleQuestions() {
    const needle = state.filter.search.trim().toLowerCase();
    return state.conv.questions.filter((q) => {
      const f = state.filter;
      if (f.status === "flagged" ? !entryOf(q.id)?.flagged : f.status !== "all" && statusOf(q.id) !== f.status) return false;
      if (f.categories.size && !f.categories.has(q.category)) return false;
      if (f.overlap && !q.overlap) return false;
      return !needle || (q.question + " " + q.gold_answer).toLowerCase().includes(needle);
    });
  }

  function notice(text, bad) {
    const node = $("notice");
    node.hidden = !text;
    $("notice-text").textContent = text || "";
    node.classList.toggle("bad", !!bad);
  }

  // ---------- routing: #/  #/example-1  #/example-1/q2 ----------

  function go(convId, qid) {
    const conv = convId && state.conversations.find((c) => c.history_id === convId);
    let hash = "#/";
    if (conv) hash += encodeURIComponent(convId) + (qid ? "/" + encodeURIComponent(shortId(conv, qid)) : "");
    if (location.hash === hash) route();
    else location.hash = hash;
  }

  function route() {
    const [convId, short] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    const conv = state.conversations.find((c) => c.history_id === convId);
    $("list-view").hidden = !!conv;
    $("conv-view").hidden = !conv;
    if (!conv) {
      state.conv = null;
      document.title = "LoCoMo annotation";
      renderList();
      return;
    }
    if (state.conv !== conv) openConversation(conv);
    const q = short && conv.questions.find((x) => shortId(conv, x.id) === short);
    selectQuestion(q ? q.id : null);
  }

  // ---------- view 1: conversation list ----------

  // Redraws whatever depends on the labels, in the view that is showing.
  function refresh() {
    $("annotator").value = store.annotator;
    if (!state.conv) { renderList(); return; }
    renderProgress();
    renderQuestions();
    renderLabel();
  }

  function renderList() {
    $("annotator").value = store.annotator;
    const rows = state.conversations.map((conv) => {
      const c = countsOf(conv);
      const turns = conv.sessions.reduce((n, s) => n + s.turns.length, 0);
      const overlap = conv.questions.some((q) => q.overlap != null)
        ? conv.questions.filter((q) => q.overlap).length : "–";
      const note = [`${c.done} / ${c.total} done`, c.draft ? `${c.draft} draft` : "", c.flagged ? `${c.flagged} ⚑` : ""]
        .filter(Boolean).join(" · ");
      const open = () => go(conv.history_id);
      return h("tr", { tabindex: "0", onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
        h("td", { class: "cid" }, conv.history_id),
        h("td", {}, conv.speakers.join(" · ")),
        h("td", { class: "num wide-only" }, conv.sessions.length),
        h("td", { class: "num wide-only" }, turns),
        h("td", { class: "num" }, c.total),
        h("td", { class: "num wide-only" }, overlap),
        h("td", { class: "progress-cell" },
          h("div", { class: "meter", role: "img", "aria-label": note },
            h("span", { class: "done", style: `width:${(100 * c.done) / (c.total || 1)}%` }),
            h("span", { class: "draft", style: `width:${(100 * c.draft) / (c.total || 1)}%` })),
          h("div", { class: "progress-note" }, note)));
    });
    $("conversations").querySelector("tbody").replaceChildren(...rows);
    const all = state.conversations.map(countsOf);
    const sum = (key) => all.reduce((n, c) => n + c[key], 0);
    $("list-total").textContent = `Total ${sum("total")} questions · ${sum("done")} done` +
      (sum("draft") ? ` · ${sum("draft")} draft` : "");
    $("data-source").replaceChildren(
      "Data: " + state.source.name,
      state.source.imported ? " · " : "",
      state.source.imported ? h("button", { type: "button", class: "link", onclick: removeImported }, "back to the example") : "");
    renderSaveState();
  }

  function setAnnotator(name) {
    const next = name.trim();
    if (next === store.annotator) return;
    // Labels entered before a name was given move to the name; an existing set is never overwritten.
    if (store.annotator === "" && store.labels[""] && !store.labels[next]) {
      store.labels[next] = store.labels[""];
      delete store.labels[""];
    }
    store.annotator = next;
    saveStore();
    refresh();
  }

  // ---------- import and export ----------

  function useData(conversations, name, imported) {
    state.conversations = conversations;
    state.source = { name, imported };
    state.conv = null;
    const first = conversations[0].source;
    $("help-source").textContent = first && first.synthetic
      ? "Example data: synthetic, written for this page; it holds no text or annotation of the benchmark."
      : first && first.repository
      ? `Example data: LoCoMo, ${first.repository} @ ${first.version}, ${first.license}. Category 5 (adversarial) ` +
        "questions and the summaries shipped with the data set are not shown."
      : "Category 5 (adversarial) questions and the summaries shipped with the data set are not shown.";
  }

  async function importData(file) {
    notice("");
    try {
      const conversations = D.normalise(JSON.parse(await file.text()));
      useData(conversations, file.name, true);
      try { await idb("readwrite", (s) => s.put({ name: file.name, conversations }, "current")); }
      catch (error) { notice(`Loaded ${file.name}, but the browser could not keep it; import it again after a reload.`, true); }
      go(null);
      if ($("notice").hidden) notice(`Loaded ${conversations.length} conversation(s) from ${file.name}.`);
    } catch (error) {
      notice(`Could not read ${file.name}: ${error.message}`, true);
    }
  }

  async function removeImported() {
    try { await idb("readwrite", (s) => s.delete("current")); } catch (error) { /* nothing stored */ }
    loadExample();
    go(null);
  }

  function loadExample() {
    try {
      if (!window.HR_EXAMPLE) throw new Error("the file did not load");
      useData(D.normalise(window.HR_EXAMPLE), EXAMPLE, false);
      notice("");
    } catch (error) {
      state.conversations = [];
      notice(`Could not load ${EXAMPLE} (${error.message}). Keep the page's folders together, or use Import data.`, true);
    }
  }

  async function importLabels(file) {
    try {
      const rows = D.parseCsv(await file.text()).filter((row) => row.question_id && row.label);
      if (!rows.length) throw new Error("no row with question_id and label");
      const names = [...new Set(rows.map((row) => (row.annotator || "").trim()))];
      if (names.length > 1) throw new Error(`the file mixes annotators (${names.join(", ")})`);
      const name = names[0] || store.annotator;
      if (store.annotator && name !== store.annotator &&
          !window.confirm(`This file belongs to annotator "${name}". Switch from "${store.annotator}" to "${name}" and load it?`)) return;
      const target = (store.labels[name] = store.labels[name] || {});
      const clash = rows.filter((row) => target[row.question_id]).length;
      if (clash && !window.confirm(`${clash} question(s) already have a label or draft in this browser. Replace them with the file?`)) return;
      const known = new Set(state.conversations.flatMap((c) => c.questions.map((q) => q.id)));
      let drafts = 0;
      for (const row of rows) {
        const entry = D.rowToEntry(row);
        if (entry.status !== "done") drafts += 1;
        target[row.question_id] = entry;
      }
      store.annotator = name;
      saveStore();
      refresh();
      const unknown = rows.filter((row) => !known.has(row.question_id)).length;
      notice(`Loaded ${rows.length} label(s) for "${name}" from ${file.name}` +
        (drafts ? `; ${drafts} incomplete, kept as draft` : "") +
        (unknown ? `; ${unknown} for questions not in the loaded data` : "") + ".");
    } catch (error) {
      notice(`Could not read ${file.name}: ${error.message}`, true);
    }
  }

  function exportCsv() {
    if (!store.annotator) {
      notice("Enter your annotator ID before exporting.", true);
      $("annotator").focus();
      return;
    }
    const rows = [];
    let open = 0;
    for (const conv of state.conversations) {
      for (const q of conv.questions) {
        if (statusOf(q.id) === "done") rows.push(D.entryToRow(q.id, store.annotator, entryOf(q.id)));
        else open += 1;
      }
    }
    if (!rows.length) { notice("Nothing to export: no question is done yet.", true); return; }
    if (open && !window.confirm(`${open} question(s) are not done and will be left out. Export the ${rows.length} done?`)) return;
    const url = URL.createObjectURL(new Blob([D.toCsv(rows)], { type: "text/csv" }));
    const name = `labels-${store.annotator.replace(/[^\w.-]+/g, "_")}.csv`;
    h("a", { href: url, download: name }).click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice(`Exported ${rows.length} label(s) to ${name}` + (open ? `; ${open} not done were left out.` : "."));
  }

  // ---------- view 2: one conversation ----------

  function openConversation(conv) {
    state.conv = conv;
    state.turns = new Map();
    for (const session of conv.sessions) {
      for (const turn of session.turns) state.turns.set(turn.id, { turn, session });
    }
    state.qid = undefined; // forces selectQuestion to render
    state.filter = { status: "all", categories: new Set(), overlap: false, search: "" };
    state.expanded = new Set();
    $("search").value = "";
    $("conv-select").replaceChildren(...state.conversations.map((c) =>
      h("option", { value: c.history_id, selected: c === conv }, c.history_id)));
    document.title = `${conv.history_id} · LoCoMo annotation`;
    renderFilters();
    applySidebars();
  }

  function selectQuestion(qid) {
    if (qid === state.qid) return;
    state.qid = qid;
    state.evidenceCursor = 0;
    state.revealed = new Set();
    state.showProblems = false;
    for (const id of evidenceIds()) state.expanded.add(state.turns.get(id).session.index);
    renderProgress();
    renderQuestions();
    renderTree();
    renderMessages();
    renderLabel();
    const first = evidenceIds()[0];
    if (first) scrollToTurn(first, false);
    else $("dialogue").scrollTop = 0;
    updateCurrentSession();
  }

  function renderProgress() {
    const c = countsOf(state.conv);
    $("conv-progress").textContent = `${c.done} / ${c.total} done` +
      (c.draft ? ` · ${c.draft} draft` : "") + (c.flagged ? ` · ${c.flagged} ⚑` : "");
  }

  // Sidebars are open or closed by the annotator's choice; without one, by the room there is.
  function sidebarOpen(name) {
    if (isNarrow()) return state.overlay === name;
    if (store.ui[name] != null) return store.ui[name];
    return name === "questions" ? window.innerWidth >= 1080 : window.innerWidth >= 1400;
  }

  function applySidebars() {
    const q = sidebarOpen("questions"), t = sidebarOpen("tree");
    $("workspace").classList.toggle("q-closed", !q);
    $("workspace").classList.toggle("t-closed", !t);
    $("questions-side").classList.toggle("closed", !q);
    $("tree-side").classList.toggle("closed", !t);
  }

  function toggleSidebar(name) {
    const open = sidebarOpen(name);
    if (isNarrow()) state.overlay = open ? null : name;
    else { store.ui[name] = !open; saveStore(); }
    applySidebars();
  }

  function closeOverlay() {
    if (state.overlay) { state.overlay = null; applySidebars(); }
  }

  // ---- questions sidebar ----

  function renderFilters() {
    const f = state.filter;
    const chip = (on, text, onclick, title) =>
      h("button", { type: "button", class: "chip" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false", onclick, title }, text);
    $("status-filter").replaceChildren(...STATUS_FILTERS.map(([value, text]) =>
      chip(f.status === value, text, () => { f.status = value; renderFilters(); renderQuestions(); },
        value === "flagged" ? "Flagged" : null)));
    const categories = [...new Set(state.conv.questions.map((q) => q.category))].sort();
    const hasOverlap = state.conv.questions.some((q) => q.overlap);
    $("category-filter").replaceChildren(
      ...categories.map((category) => chip(f.categories.has(category), `${category} ${D.CATEGORY_NAMES[category] || ""}`, () => {
        if (f.categories.has(category)) f.categories.delete(category); else f.categories.add(category);
        renderFilters(); renderQuestions();
      })),
      hasOverlap ? chip(f.overlap, "overlap", () => { f.overlap = !f.overlap; renderFilters(); renderQuestions(); },
        "Questions labelled by both annotators") : null);
  }

  function renderQuestions() {
    const visible = visibleQuestions();
    $("question-count").textContent = visible.length === state.conv.questions.length
      ? `· ${visible.length}` : `· ${visible.length} of ${state.conv.questions.length}`;
    const items = visible.map((q) => {
      const entry = entryOf(q.id);
      const status = D.statusOf(entry);
      const sub = [entry?.label, ...(entry?.operations || []), entry?.other_reason].filter(Boolean).join(" · ");
      return h("li", { class: q.id === state.qid ? "selected" : "", "data-qid": q.id,
        onclick: () => { closeOverlay(); go(state.conv.history_id, q.id); } },
        h("span", { class: "st " + status, title: status }, STATUS_MARK[status]),
        h("span", { class: "text" },
          h("span", { class: "qid" }, shortId(state.conv, q.id)),
          entry?.flagged ? h("span", { class: "flag-mark", title: "flagged" }, "⚑ ") : null,
          q.question),
        sub ? h("span", { class: "sub" }, sub) : null);
    });
    $("questions").replaceChildren(...(items.length ? items : [h("li", { class: "empty" }, "No question matches the filters.")]));
    $("questions").querySelector("li.selected")?.scrollIntoView({ block: "nearest" });
  }

  // ---- message tree sidebar ----

  function renderTree() {
    const evidence = new Set(evidenceIds());
    const first = state.conv.speakers[0];
    $("tree").replaceChildren(...state.conv.sessions.map((session) => {
      const open = state.expanded.has(session.index);
      const hits = session.turns.filter((t) => evidence.has(t.id)).length;
      return h("li", { class: "session" + (hits ? " has-evidence" : ""), "data-session": session.index },
        h("div", { class: "session-row", onclick: () => { state.expanded.add(session.index); renderTree(); scrollToSession(session); },
          title: `Session ${session.index} · ${formatDate(session, true)} ${formatTime(session)}` },
          h("button", { type: "button", class: "twist", "aria-label": open ? "Collapse" : "Expand", "aria-expanded": String(open),
            onclick: (event) => {
              event.stopPropagation();
              if (open) state.expanded.delete(session.index); else state.expanded.add(session.index);
              renderTree();
            } }, open ? "▾" : "▸"),
          h("span", { class: "sid" }, "S" + session.index),
          h("span", { class: "date" }, formatDate(session, false)),
          h("span", { class: "n" }, session.turns.length),
          h("span", { class: "ev" }, hits ? "◆" : "")),
        open ? h("ol", {}, session.turns.map((turn) =>
          h("li", { class: "leaf" + (turn.speaker === first ? "" : " b") + (evidence.has(turn.id) ? " evidence" : ""),
            title: `${turn.speaker}: ${turn.text}`, onclick: () => { closeOverlay(); scrollToTurn(turn.id, true); } },
            h("span", { class: "ev" }, evidence.has(turn.id) ? "◆" : ""),
            h("span", { class: "tid" }, turn.id),
            h("span", { class: "sp" }, (turn.speaker || "?")[0]),
            h("span", { class: "snip" }, turn.text || (turn.image ? "[image]" : ""))))) : null);
    }));
    const rail = $("tree-side").querySelector(".rail");
    rail.querySelector(".rail-mark")?.remove();
    if (evidence.size) rail.append(h("span", { class: "rail-mark" }, "◆"));
    markCurrentSession();
  }

  // ---- messages ----

  const evidenceMode = () => store.ui.evidenceOnly && evidenceIds().length > 0;

  function renderMessages() {
    const ids = evidenceIds();
    const evidence = new Set(ids);
    const filtered = evidenceMode();
    for (const button of document.querySelectorAll("[data-show]")) {
      const isEvidence = button.dataset.show === "evidence";
      button.classList.toggle("on", isEvidence === !!store.ui.evidenceOnly);
      button.disabled = isEvidence && !ids.length;
      button.title = isEvidence && !ids.length ? "The selected question lists no evidence turn" : "";
    }
    // In evidence mode a turn shows when it is evidence, the turn just before evidence, or revealed.
    const shown = (session, i) => {
      const turn = session.turns[i];
      if (!filtered || evidence.has(turn.id) || state.revealed.has(turn.id)) return true;
      const next = session.turns[i + 1];
      return !!next && evidence.has(next.id);
    };
    const reveal = (turns) => () => {
      for (const turn of turns) state.revealed.add(turn.id);
      const top = $("dialogue").scrollTop;
      renderMessages();
      $("dialogue").scrollTop = top;
    };
    const first = state.conv.speakers[0];
    const out = [];
    let hiddenSessions = [];
    const flushSessions = () => {
      if (!hiddenSessions.length) return;
      const group = hiddenSessions;
      const turns = group.flatMap((s) => s.turns);
      const span = group.length === 1 ? `session ${group[0].index}` : `sessions ${group[0].index}–${group[group.length - 1].index}`;
      out.push(h("div", { class: "gap-row" },
        h("button", { type: "button", onclick: reveal(turns) }, `⋯ ${span} hidden (${turns.length} turns) · show`)));
      hiddenSessions = [];
    };
    for (const session of state.conv.sessions) {
      const flags = session.turns.map((_, i) => shown(session, i));
      if (!flags.some(Boolean)) { hiddenSessions.push(session); continue; }
      flushSessions();
      out.push(h("div", { class: "session-head", "data-session": session.index },
        h("span", { class: "mono muted" }, "session " + session.index),
        h("span", { class: "date" }, formatDate(session, true)),
        h("span", { class: "muted" }, formatTime(session)),
        h("span", { class: "muted" }, session.turns.length + " turns")));
      let run = [];
      const flushRun = () => {
        if (!run.length) return;
        out.push(h("div", { class: "gap-row" },
          h("button", { type: "button", onclick: reveal(run) }, `⋯ ${run.length} turn${run.length > 1 ? "s" : ""} hidden · show`)));
        run = [];
      };
      session.turns.forEach((turn, i) => {
        if (!flags[i]) { run.push(turn); return; }
        flushRun();
        const position = ids.indexOf(turn.id);
        out.push(h("div", { class: "turn " + (turn.speaker === first ? "a" : "b") + (position >= 0 ? " evidence" : ""), "data-turn": turn.id },
          h("div", { class: "bubble" },
            h("div", { class: "who" },
              h("span", { class: "name" }, turn.speaker),
              h("span", { class: "mono" }, turn.id),
              position >= 0 ? h("span", { class: "mark" }, `◆ evidence ${position + 1}/${ids.length}`) : null),
            h("div", {}, turn.text),
            turn.image ? h("div", { class: "image" }, h("b", {}, "[image]"), turn.image.caption || "no caption") : null)));
      });
      flushRun();
    }
    flushSessions();
    $("dialogue-inner").replaceChildren(...out);
  }

  const turnNode = (id) => $("dialogue-inner").querySelector(`[data-turn="${CSS.escape(id)}"]`);

  function scrollToTurn(id, flash) {
    if (!turnNode(id) && state.turns.has(id)) { state.revealed.add(id); renderMessages(); }
    const node = turnNode(id);
    if (!node) return;
    node.scrollIntoView({ block: "center" });
    if (flash) {
      node.classList.remove("flash");
      void node.offsetWidth; // restarts the animation
      node.classList.add("flash");
    }
    updateCurrentSession();
  }

  function scrollToSession(session) {
    let head = $("dialogue-inner").querySelector(`.session-head[data-session="${session.index}"]`);
    if (!head) {
      for (const turn of session.turns) state.revealed.add(turn.id);
      renderMessages();
      head = $("dialogue-inner").querySelector(`.session-head[data-session="${session.index}"]`);
    }
    head?.scrollIntoView({ block: "start" });
    updateCurrentSession();
  }

  // The session whose head is the last one above the upper third of the messages pane.
  function updateCurrentSession() {
    const pane = $("dialogue");
    const line = pane.getBoundingClientRect().top + pane.clientHeight / 3;
    let current = null;
    for (const head of pane.querySelectorAll(".session-head")) {
      if (head.getBoundingClientRect().top > line && current) break;
      current = head;
    }
    const session = current && state.conv.sessions.find((s) => String(s.index) === current.dataset.session);
    state.currentSession = session ? session.index : null;
    $("current-session").replaceChildren(...(session
      ? [h("b", {}, "S" + session.index), ` · ${formatDate(session, true)} · ${session.turns.length} turns`] : []));
    markCurrentSession();
  }

  function markCurrentSession() {
    for (const node of $("tree").querySelectorAll(".session")) {
      node.classList.toggle("current", node.dataset.session === String(state.currentSession));
    }
  }

  function setEvidenceOnly(on) {
    store.ui.evidenceOnly = on;
    saveStore();
    state.revealed = new Set();
    renderMessages();
    const id = evidenceIds()[state.evidenceCursor] || evidenceIds()[0];
    if (id) scrollToTurn(id, false);
    updateCurrentSession();
  }

  // ---- label area ----

  function renderLabel() {
    const q = question();
    const visible = visibleQuestions();
    if (!q) {
      const next = state.conv.questions.find((x) => statusOf(x.id) !== "done");
      $("label-head").replaceChildren(h("span", { class: "where muted" }, "No question selected"));
      $("question-card").replaceChildren(h("div", { class: "placeholder" },
        "Choose a question from the list to label it. The messages stay readable without one.",
        next ? h("button", { type: "button", onclick: () => go(state.conv.history_id, next.id) },
          `Start with ${shortId(state.conv, next.id)}`) : "Every question of this conversation is done."));
      $("label-form").replaceChildren();
      $("label-foot").replaceChildren();
      return;
    }
    const position = visible.findIndex((x) => x.id === q.id);
    $("label-head").replaceChildren(
      h("span", { class: "where" }, h("b", {}, shortId(state.conv, q.id)),
        position >= 0 ? ` · ${position + 1} / ${visible.length}` : " · outside the filters"),
      h("span", { class: "spacer" }),
      h("button", { type: "button", class: "nav", title: "Previous question (k)", "aria-label": "Previous question", onclick: () => step(-1) }, "◀"),
      h("button", { type: "button", class: "nav", title: "Next question (j)", "aria-label": "Next question", onclick: () => step(1) }, "▶"));

    const ids = q.evidence_ids;
    const sessions = new Set(evidenceIds().map((id) => state.turns.get(id).session.index));
    $("question-card").replaceChildren(
      h("div", { class: "tags" },
        h("span", { class: "chip", id: "status-chip" }),
        h("span", { class: "chip" }, `${q.category} · ${q.category_name || D.CATEGORY_NAMES[q.category] || ""}`),
        q.overlap ? h("span", { class: "chip on", title: "Labelled by both annotators" }, "overlap") : null,
        sessions.size > 1 ? h("span", { class: "chip" }, `${sessions.size} sessions`) : null,
        q.evidence_status && q.evidence_status !== "complete" ? h("span", { class: "chip bad" }, "evidence " + q.evidence_status) : null),
      h("div", { class: "q" }, q.question),
      h("div", { class: "row" }, h("b", {}, "Gold"), h("span", { class: "value" }, q.gold_answer || "(none)")),
      h("div", { class: "row" }, h("b", {}, "Evidence"),
        ids.length ? ids.map((id) => {
          const hit = state.turns.get(id);
          return h("button", { type: "button", class: "chip " + (hit ? "warn" : "bad"), disabled: !hit,
            title: hit ? `${hit.turn.speaker}, session ${hit.session.index}, ${formatDate(hit.session, true)}` : "This turn is not in the conversation",
            onclick: () => scrollToTurn(id, true) }, hit ? id : id + " ?");
        }) : h("span", { class: "muted" }, "none listed")),
      q.audit_error_type ? h("div", { class: "row" }, h("b", {}, "Audit"),
        h("span", { class: "chip bad" }, q.audit_error_type),
        q.audit_correct_answer ? h("span", { class: "value" }, "corrected answer: " + q.audit_correct_answer) : null) : null);
    renderForm();
  }

  function checkGroup(name, values, chosen) {
    return h("div", { class: "choices" }, values.map((value) =>
      h("label", { class: "choice" },
        h("input", { type: "checkbox", name, value, checked: chosen.includes(value),
          onchange: (event) => change((entry) => {
            const set = new Set(entry[name]);
            if (event.target.checked) set.add(value); else set.delete(value);
            entry[name] = values.filter((v) => set.has(v));
          }, false) }),
        h("span", { class: "mono" }, value))));
  }

  // Applies a change to the selected question's entry and refreshes what depends on it. The form
  // itself is rebuilt only when its shape changes (another label), so typing keeps the focus.
  function change(apply, rebuild) {
    editEntry(state.qid, apply);
    if (rebuild) renderForm(); else renderFormStatus();
    renderQuestions();
    renderProgress();
  }

  function setLabel(value) {
    change((entry) => {
      entry.label = value;
      if (value !== "in_fragment") { entry.operations = []; entry.flags = []; }
      if (value !== "other") entry.other_reason = "";
    }, true);
    $("label-form").querySelector(`input[name="label"][value="${value}"]`)?.focus();
  }

  function renderForm() {
    const entry = entryOf(state.qid) || D.emptyEntry();
    $("label-form").replaceChildren(
      h("div", { class: "form-row" },
        h("label", { class: "title" }, "Label"),
        h("div", { class: "labels" }, D.LABELS.map(([value], index) =>
          h("label", { class: "choice" },
            h("input", { type: "radio", name: "label", value, checked: entry.label === value, onchange: () => setLabel(value) }),
            h("span", { class: "key" }, index + 1), h("span", { class: "mono" }, value))))),
      entry.label === "in_fragment" ? h("div", { class: "form-row" },
        h("label", { class: "title" }, "Operations beyond a single claim pattern"),
        checkGroup("operations", D.OPERATIONS, entry.operations)) : null,
      entry.label === "in_fragment" ? h("div", { class: "form-row" },
        h("label", { class: "title" }, "Flags"),
        checkGroup("flags", D.FLAGS, entry.flags)) : null,
      entry.label === "other" ? h("div", { class: "form-row" },
        h("label", { class: "title", for: "other-reason" }, "Reason"),
        h("select", { id: "other-reason", onchange: (event) => change((e) => { e.other_reason = event.target.value; }, false) },
          h("option", { value: "" }, "choose"),
          D.OTHER_REASONS.map((value) => h("option", { value, selected: entry.other_reason === value }, value)))) : null,
      h("div", { class: "form-row" },
        h("label", { class: "title", for: "rationale" }, "Rationale"),
        h("textarea", { id: "rationale", placeholder: "The claim pattern, or what is missing",
          oninput: (event) => change((e) => { e.rationale = event.target.value; }, false) }, entry.rationale)),
      h("ul", { class: "problems", id: "problems" }));
    renderFormStatus();
  }

  function renderFormStatus() {
    const entry = entryOf(state.qid);
    const status = D.statusOf(entry);
    const chip = $("status-chip");
    if (chip) {
      chip.textContent = `${STATUS_MARK[status]} ${status}`;
      chip.className = "chip" + (status === "done" ? " ok" : status === "draft" ? " warn" : "");
    }
    $("problems").replaceChildren(...(state.showProblems ? D.problems(entry).map((text) => h("li", {}, text)) : []));
    const flagged = !!entry?.flagged;
    $("label-foot").replaceChildren(
      h("button", { type: "button", class: flagged ? "flagged" : "", title: "Mark for a second look (f)", "aria-pressed": String(flagged), onclick: toggleFlag },
        flagged ? "⚑ Flagged" : "⚑ Flag"),
      h("span", { class: "spacer" }),
      h("button", { type: "button", class: "primary", title: "Confirm and go to the next question (Enter)", onclick: confirmAndNext },
        status === "done" ? "Next ⏎" : "Confirm & next ⏎"));
  }

  function toggleFlag() {
    if (!state.qid) return;
    const entries = bucket();
    const entry = entries[state.qid] || D.emptyEntry();
    entry.flagged = !entry.flagged; // a flag is a note to oneself; it does not undo a confirmation
    if (D.isBlank(entry) && !entry.flagged) delete entries[state.qid]; else entries[state.qid] = entry;
    saveStore();
    renderFormStatus();
    renderQuestions();
    renderProgress();
  }

  function confirmAndNext() {
    if (!state.qid) return;
    const entry = entryOf(state.qid);
    if (D.problems(entry).length) {
      state.showProblems = true;
      renderFormStatus();
      return;
    }
    // The follower is fixed before the status changes, because a status filter may drop this question.
    const visible = visibleQuestions();
    const index = visible.findIndex((q) => q.id === state.qid);
    const next = visible[index + 1];
    entry.status = "done";
    saveStore();
    if (next) go(state.conv.history_id, next.id);
    else { state.showProblems = false; renderFormStatus(); renderQuestions(); renderProgress(); }
  }

  function step(delta) {
    const visible = visibleQuestions();
    if (!visible.length) return;
    const index = visible.findIndex((q) => q.id === state.qid);
    const target = index < 0 ? 0 : Math.min(visible.length - 1, Math.max(0, index + delta));
    go(state.conv.history_id, visible[target].id);
  }

  // ---------- keys ----------

  function onKey(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && state.conv && state.qid) { confirmAndNext(); event.preventDefault(); }
      return;
    }
    if ($("help").open || !state.conv) return;
    const tag = event.target.tagName;
    const typing = tag === "TEXTAREA" || tag === "SELECT" || (tag === "INPUT" && !["radio", "checkbox"].includes(event.target.type));
    if (typing) {
      if (event.key === "Escape") event.target.blur();
      return;
    }
    if (event.key === "j") step(1);
    else if (event.key === "k") step(-1);
    else if (event.key === "e") {
      const ids = evidenceIds();
      if (ids.length) {
        state.evidenceCursor = (state.evidenceCursor + 1) % ids.length;
        scrollToTurn(ids[state.evidenceCursor], true);
      }
    } else if (/^[1-5]$/.test(event.key) && state.qid) setLabel(D.LABELS[Number(event.key) - 1][0]);
    else if (event.key === "Enter" && tag !== "BUTTON" && tag !== "A" && state.qid) confirmAndNext();
    else if (event.key === "f") toggleFlag();
    else if (event.key === "v") setEvidenceOnly(!store.ui.evidenceOnly);
    else if (event.key === "[") toggleSidebar("questions");
    else if (event.key === "]") toggleSidebar("tree");
    else if (event.key === "?") $("help").showModal();
    else if (event.key === "Escape") closeOverlay();
    else return;
    event.preventDefault();
  }

  // ---------- start ----------

  function wire() {
    $("import-data").addEventListener("click", () => $("data-file").click());
    $("import-labels").addEventListener("click", () => $("labels-file").click());
    $("export-csv").addEventListener("click", exportCsv);
    $("data-file").addEventListener("change", (event) => { const file = event.target.files[0]; event.target.value = ""; if (file) importData(file); });
    $("labels-file").addEventListener("change", (event) => { const file = event.target.files[0]; event.target.value = ""; if (file) importLabels(file); });
    $("notice-close").addEventListener("click", () => notice(""));
    $("annotator").addEventListener("change", (event) => setAnnotator(event.target.value));
    $("conv-select").addEventListener("change", (event) => go(event.target.value));
    $("search").addEventListener("input", (event) => { state.filter.search = event.target.value; renderQuestions(); });
    $("tree-expand").addEventListener("click", () => {
      const all = state.expanded.size === state.conv.sessions.length;
      state.expanded = new Set(all ? [] : state.conv.sessions.map((s) => s.index));
      renderTree();
    });
    for (const button of document.querySelectorAll(".help-button")) button.addEventListener("click", () => $("help").showModal());
    for (const button of document.querySelectorAll("[data-toggle]")) button.addEventListener("click", () => toggleSidebar(button.dataset.toggle));
    for (const button of document.querySelectorAll("[data-show]")) button.addEventListener("click", () => setEvidenceOnly(button.dataset.show === "evidence"));
    let frame = 0;
    $("dialogue").addEventListener("scroll", () => {
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = 0; if (state.conv) updateCurrentSession(); });
    });
    window.addEventListener("resize", () => {
      if (!isNarrow()) state.overlay = null;
      if (state.conv) applySidebars();
    });
    window.addEventListener("hashchange", route);
    document.addEventListener("keydown", onKey);
  }

  async function start() {
    loadStore();
    wire();
    $("annotator").value = store.annotator;
    renderSaveState();
    let stored = null;
    try { stored = await idb("readonly", (s) => s.get("current")); } catch (error) { /* no IndexedDB: use the example */ }
    if (stored && stored.conversations && stored.conversations.length) useData(stored.conversations, stored.name, true);
    else loadExample();
    route();
  }

  start();
})();

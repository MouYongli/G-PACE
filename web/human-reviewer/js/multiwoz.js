// MultiWOZ annotation page. View 1 lists the dialogues; view 2 shows one dialogue as
// offer turns | messages | verdict. The unit of work is an offer turn: the user turn right after a
// system offer, labelled accept / reject / none by the T006 rule. Drafts are kept in localStorage
// per annotator, imported data in IndexedDB; nothing leaves the browser except the exported TSV.
(function () {
  "use strict";

  const { $, h } = window.HR;
  const D = window.HRMultiwozData;
  const STORE_KEY = "hr.multiwoz.v1";
  const EXAMPLE = "data/example.js"; // sets window.HR_EXAMPLE
  const STATUS_MARK = { todo: "○", draft: "◐", done: "✓" };
  const STATUS_FILTERS = [["all", "All"], ["todo", "Todo"], ["draft", "Draft"], ["done", "Done"], ["flagged", "⚑"]];

  // Kept across reloads.
  const store = { annotator: "", labels: {}, ui: { tasks: null } };
  // Rebuilt on every load.
  const state = {
    dialogues: [],
    tasks: [], // offer turns to check, in file order
    source: { name: EXAMPLE, imported: false },
    conv: null, // dialogue shown in view 2
    taskId: null, // selected offer turn
    focus: null, // index of the user turn whose state is shown
    filter: { status: "all", labels: new Set(), search: "" },
    overlay: false, // sidebar opened over the content on a narrow screen
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
      const open = indexedDB.open("hr-multiwoz", 1);
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

  // ---------- verdicts ----------

  const bucket = () => (store.labels[store.annotator] = store.labels[store.annotator] || {});
  const entryOf = (id) => bucket()[id];
  const statusOf = (id) => D.statusOf(entryOf(id));

  function putEntry(id, entry) {
    const entries = bucket();
    if (D.isBlank(entry) && !entry.flagged) delete entries[id];
    else entries[id] = entry;
    saveStore();
  }

  function editEntry(id, change) {
    const entry = entryOf(id) || D.emptyEntry();
    change(entry);
    entry.status = "draft"; // any change to a done verdict needs a new confirmation
    putEntry(id, entry);
  }

  function countsOf(tasks) {
    const counts = { todo: 0, draft: 0, done: 0, flagged: 0, total: tasks.length };
    for (const task of tasks) {
      counts[statusOf(task.id)] += 1;
      if (entryOf(task.id)?.flagged) counts.flagged += 1;
    }
    return counts;
  }

  const progressText = (c) => `${c.done} / ${c.total} done` +
    (c.draft ? ` · ${c.draft} draft` : "") + (c.flagged ? ` · ${c.flagged} ⚑` : "");

  // ---------- small helpers ----------

  const isNarrow = () => window.innerWidth <= 900;
  const task = () => state.tasks.find((t) => t.id === state.taskId);
  const tasksOf = (dialogue) => state.tasks.filter((t) => t.dialogue === dialogue);
  const turnAt = (index) => state.conv.turns.find((t) => t.index === index);
  const ruleText = (label, how) => label + (how ? " · " + how : "");
  const ruleChip = (label, how, extra) => h("span", { class: `rule ${label} ${extra || ""}` }, ruleText(label, how));

  function visibleTasks() {
    const needle = state.filter.search.trim().toLowerCase();
    return state.tasks.filter((t) => {
      const f = state.filter;
      if (f.status === "flagged" ? !entryOf(t.id)?.flagged : f.status !== "all" && statusOf(t.id) !== f.status) return false;
      if (f.labels.size && !f.labels.has(t.label)) return false;
      return !needle || (t.id + " " + t.turn.text).toLowerCase().includes(needle);
    });
  }

  function offerParts(t) {
    const parts = [];
    for (const [domain, slots] of Object.entries(t.offered)) {
      for (const [slot, values] of Object.entries(slots)) parts.push(`${domain}-${slot} = ${values.join(" | ")}`);
    }
    return parts;
  }
  const offerKinds = (t) => [...new Set(Object.values(t.offer_kinds).flat())];

  function notice(text, bad) {
    const node = $("notice");
    node.hidden = !text;
    $("notice-text").textContent = text || "";
    node.classList.toggle("bad", !!bad);
  }

  // ---------- routing: #/  #/EXAMPLE-A.json  #/EXAMPLE-A.json/2 ----------

  function go(dialogueId, turnIndex) {
    let hash = "#/";
    if (dialogueId) hash += encodeURIComponent(dialogueId) + (turnIndex != null ? "/" + turnIndex : "");
    if (location.hash === hash) route();
    else location.hash = hash;
  }
  const goTask = (t) => go(t.dialogue.dialogue_id, t.turn.index);

  function route() {
    const [dialogueId, turnIndex] = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    const conv = state.dialogues.find((d) => d.dialogue_id === dialogueId);
    $("list-view").hidden = !!conv;
    $("conv-view").hidden = !conv;
    if (!conv) {
      state.conv = null;
      document.title = "MultiWOZ annotation";
      renderList();
      return;
    }
    const changed = state.conv !== conv;
    if (changed) openDialogue(conv);
    const found = state.tasks.find((t) => t.dialogue === conv && String(t.turn.index) === turnIndex);
    selectTask(found ? found.id : null, changed);
  }

  // ---------- view 1: dialogue list ----------

  // Redraws whatever depends on the verdicts, in the view that is showing.
  function refresh() {
    $("annotator").value = store.annotator;
    if (!state.conv) { renderList(); return; }
    renderProgress();
    renderTasks();
    renderLabel();
  }

  function renderList() {
    $("annotator").value = store.annotator;
    const rows = state.dialogues.map((dialogue) => {
      const tasks = tasksOf(dialogue);
      const c = countsOf(tasks);
      // Opens on the first offer turn still to do, so the list leads straight into the work.
      const open = () => goTask(tasks.find((t) => statusOf(t.id) !== "done") || tasks[0]);
      return h("tr", { tabindex: "0", onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
        h("td", { class: "cid" }, dialogue.dialogue_id),
        h("td", { class: "wide-only" }, (dialogue.domains || []).join(", ")),
        h("td", { class: "num wide-only" }, dialogue.turns.length),
        h("td", {}, h("div", { class: "rules" }, tasks.map((t) =>
          h("span", { class: "rule " + t.label, title: `turn ${t.turn.index}: ${statusOf(t.id)}` },
            `${STATUS_MARK[statusOf(t.id)]} ${t.turn.index} ${t.label}`)))),
        h("td", { class: "progress-cell" },
          h("div", { class: "meter", role: "img", "aria-label": progressText(c) },
            h("span", { class: "done", style: `width:${(100 * c.done) / (c.total || 1)}%` }),
            h("span", { class: "draft", style: `width:${(100 * c.draft) / (c.total || 1)}%` })),
          h("div", { class: "progress-note" }, progressText(c))));
    });
    $("dialogues").querySelector("tbody").replaceChildren(...rows);
    const c = countsOf(state.tasks);
    $("list-total").textContent = `Total ${c.total} offer turns in ${state.dialogues.length} dialogue(s) · ${c.done} done` +
      (c.draft ? ` · ${c.draft} draft` : "");
    $("data-source").replaceChildren(
      "Data: " + state.source.name,
      state.source.imported ? " · " : "",
      state.source.imported ? h("button", { type: "button", class: "link", onclick: removeImported }, "back to the example") : "");
    renderSaveState();
  }

  function setAnnotator(name) {
    const next = name.trim();
    if (next === store.annotator) return;
    // Verdicts entered before a name was given move to the name; an existing set is never overwritten.
    if (store.annotator === "" && store.labels[""] && !store.labels[next]) {
      store.labels[next] = store.labels[""];
      delete store.labels[""];
    }
    store.annotator = next;
    saveStore();
    refresh();
  }

  // ---------- import and export ----------

  function useData(json, name, imported) {
    const { dialogues, tasks } = D.normalise(json);
    state.dialogues = dialogues;
    state.tasks = tasks;
    state.source = { name, imported };
    state.conv = null;
    const source = (Array.isArray(json) ? json[0] : json.dialogues ? json.dialogues[0] : json).source;
    $("help-source").textContent = source && source.synthetic
      ? `Example data: synthetic, written for this page; it holds no text or annotation of the benchmark. The checked label is the one on ${D.PRIMARY} acts.`
      : source
      ? `Data: MultiWOZ ${(source.versions || []).join(", ")}, split ${source.split}; utterances of ${source.text_from}; ` +
        `rule labels of census run ${source.census_run}. The checked label is the one on ${D.PRIMARY} acts.`
      : `The checked label is the one on ${D.PRIMARY} acts unless the data file names another act source.`;
  }

  async function importData(file) {
    notice("");
    try {
      const json = JSON.parse(await file.text());
      useData(json, file.name, true);
      try { await idb("readwrite", (s) => s.put({ name: file.name, json }, "current")); }
      catch (error) { notice(`Loaded ${file.name}, but the browser could not keep it; import it again after a reload.`, true); }
      go(null);
      if ($("notice").hidden) notice(`Loaded ${state.tasks.length} offer turn(s) in ${state.dialogues.length} dialogue(s) from ${file.name}.`);
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
      useData(window.HR_EXAMPLE, EXAMPLE, false);
      notice("");
    } catch (error) {
      state.dialogues = [];
      state.tasks = [];
      notice(`Could not load ${EXAMPLE} (${error.message}). Keep the page's folders together, or use Import data.`, true);
    }
  }

  async function importLabels(file) {
    try {
      const rows = D.parseTsv(await file.text()).filter((row) => row.task_id && row.verdict);
      if (!rows.length) throw new Error("no row with task_id and verdict");
      const names = [...new Set(rows.map((row) => (row.checked_by || "").trim()))];
      if (names.length > 1) throw new Error(`the file mixes annotators (${names.join(", ")})`);
      const name = names[0] || store.annotator;
      if (store.annotator && name !== store.annotator &&
          !window.confirm(`This file belongs to annotator "${name}". Switch from "${store.annotator}" to "${name}" and load it?`)) return;
      const target = (store.labels[name] = store.labels[name] || {});
      const clash = rows.filter((row) => target[row.task_id]).length;
      if (clash && !window.confirm(`${clash} offer turn(s) already have a verdict or draft in this browser. Replace them with the file?`)) return;
      const known = new Map(state.tasks.map((t) => [t.id, t]));
      let drafts = 0, unknown = 0, relabelled = 0;
      for (const row of rows) {
        const entry = D.rowToEntry(row);
        if (entry.status !== "done") drafts += 1;
        const t = known.get(row.task_id);
        if (!t) unknown += 1;
        else if (row.label && row.label !== t.label) relabelled += 1;
        target[row.task_id] = entry;
      }
      store.annotator = name;
      saveStore();
      refresh();
      notice(`Loaded ${rows.length} verdict(s) for "${name}" from ${file.name}` +
        (drafts ? `; ${drafts} incomplete, kept as draft` : "") +
        (unknown ? `; ${unknown} for offer turns not in the loaded data` : "") +
        (relabelled ? `; ${relabelled} were given for another rule label than the loaded data shows: check them` : "") + ".",
      relabelled > 0);
    } catch (error) {
      notice(`Could not read ${file.name}: ${error.message}`, true);
    }
  }

  function exportTsv() {
    if (!store.annotator) {
      notice("Enter your annotator ID before exporting.", true);
      $("annotator").focus();
      return;
    }
    const done = state.tasks.filter((t) => statusOf(t.id) === "done");
    const open = state.tasks.length - done.length;
    if (!done.length) { notice("Nothing to export: no offer turn is done yet.", true); return; }
    if (open && !window.confirm(`${open} offer turn(s) are not done and will be left out. Export the ${done.length} done?`)) return;
    const rows = done.map((t, i) => D.entryToRow(i + 1, t, store.annotator, entryOf(t.id)));
    const url = URL.createObjectURL(new Blob([D.toTsv(rows)], { type: "text/tab-separated-values" }));
    const name = `offer-turns-check-${store.annotator.replace(/[^\w.-]+/g, "_")}.tsv`;
    h("a", { href: url, download: name }).click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice(`Exported ${rows.length} verdict(s) to ${name}` + (open ? `; ${open} not done were left out.` : "."));
  }

  // ---------- view 2: one dialogue ----------

  function openDialogue(conv) {
    state.conv = conv;
    state.taskId = undefined; // forces selectTask to render
    $("conv-select").replaceChildren(...state.dialogues.map((d) =>
      h("option", { value: d.dialogue_id, selected: d === conv }, d.dialogue_id)));
    $("dialogue-meta").textContent = `${(conv.domains || []).join(", ")} · ${conv.turns.length} turns`;
    document.title = `${conv.dialogue_id} · MultiWOZ annotation`;
    renderFilters();
    applySidebar();
  }

  function selectTask(id, dialogueChanged) {
    if (id === state.taskId && !dialogueChanged) return;
    state.taskId = id;
    state.showProblems = false;
    const t = task();
    const users = state.conv.turns.filter((turn) => turn.speaker === "user");
    state.focus = t ? t.turn.index : users.length ? users[users.length - 1].index : null;
    renderProgress();
    renderTasks();
    renderTurns();
    renderLabel();
    if (t) (turnNode(t.turn.index - 1) || turnNode(t.turn.index))?.scrollIntoView({ block: "center" });
    else if (dialogueChanged) $("dialogue").scrollTop = 0;
  }

  function renderProgress() {
    $("conv-progress").textContent = progressText(countsOf(state.tasks));
  }

  // The sidebar is open or closed by the annotator's choice; without one, by the room there is.
  function sidebarOpen() {
    if (isNarrow()) return state.overlay;
    return store.ui.tasks != null ? store.ui.tasks : window.innerWidth >= 1080;
  }

  function applySidebar() {
    const open = sidebarOpen();
    $("workspace").classList.toggle("q-closed", !open);
    $("tasks-side").classList.toggle("closed", !open);
  }

  function toggleSidebar() {
    const open = sidebarOpen();
    if (isNarrow()) state.overlay = !open;
    else { store.ui.tasks = !open; saveStore(); }
    applySidebar();
  }

  function closeOverlay() {
    if (state.overlay) { state.overlay = false; applySidebar(); }
  }

  // ---- offer-turn sidebar ----

  function renderFilters() {
    const f = state.filter;
    const chip = (on, text, onclick, title) =>
      h("button", { type: "button", class: "chip" + (on ? " on" : ""), "aria-pressed": on ? "true" : "false", onclick, title }, text);
    $("status-filter").replaceChildren(...STATUS_FILTERS.map(([value, text]) =>
      chip(f.status === value, text, () => { f.status = value; renderFilters(); renderTasks(); },
        value === "flagged" ? "Flagged" : null)));
    const labels = [...new Set(state.tasks.map((t) => t.label))].sort();
    $("label-filter").replaceChildren(...labels.map((label) =>
      chip(f.labels.has(label), label, () => {
        if (f.labels.has(label)) f.labels.delete(label); else f.labels.add(label);
        renderFilters(); renderTasks();
      }, `Rule label ${label}`)));
  }

  function renderTasks() {
    const visible = visibleTasks();
    $("task-count").textContent = visible.length === state.tasks.length
      ? `· ${visible.length}` : `· ${visible.length} of ${state.tasks.length}`;
    const groups = [];
    for (const t of visible) {
      const last = groups[groups.length - 1];
      if (last && last.dialogue === t.dialogue) last.tasks.push(t);
      else groups.push({ dialogue: t.dialogue, tasks: [t] });
    }
    $("tasks").replaceChildren(...(groups.length ? groups.map((group) =>
      h("li", { class: "group" + (group.dialogue === state.conv ? " current" : "") },
        h("div", { class: "name" }, group.dialogue.dialogue_id),
        h("ol", {}, group.tasks.map((t) => {
          const entry = entryOf(t.id);
          const status = D.statusOf(entry);
          return h("li", { class: "task" + (t.id === state.taskId ? " selected" : ""), title: t.turn.text,
            onclick: () => { closeOverlay(); goTask(t); } },
            h("span", { class: "st " + status, title: status }, STATUS_MARK[status]),
            h("span", { class: "tid" }, ":" + t.turn.index),
            h("span", { class: "reply" }, entry?.flagged ? h("span", { class: "flag-mark", title: "flagged" }, "⚑ ") : null, t.turn.text),
            ruleChip(t.label, ""),
            entry?.verdict ? h("span", { class: "sub" }, entry.verdict) : null);
        }))))
      : [h("li", { class: "empty" }, "No offer turn matches the filters.")]));
    $("tasks").querySelector(".task.selected")?.scrollIntoView({ block: "nearest" });
  }

  // ---- messages ----

  function actChip(act) {
    const args = act.slot === "none" ? "" : `(${act.slot}${act.value === "?" ? "=?" : act.value && act.value !== "none" ? "=" + act.value : ""})`;
    return h("span", { class: "act" }, h("span", { class: "name" }, act.act), args);
  }

  function actsBlock(turn) {
    return h("div", { class: "acts" }, D.ACT_SOURCES.filter((v) => turn.acts && turn.acts[v]).map((version) => [
      h("span", { class: "version" }, version),
      h("span", { class: "list" }, turn.acts[version].length
        ? turn.acts[version].map(actChip)
        : h("span", { class: "act empty" }, "no acts annotated")),
    ]));
  }

  const turnNode = (index) => $("turns").querySelector(`[data-turn="${index}"]`);

  function renderTurns() {
    const t = task();
    const mine = new Map(tasksOf(state.conv).map((x) => [x.turn.index, x]));
    $("turns").replaceChildren(...state.conv.turns.map((turn) => {
      const isUser = turn.speaker === "user";
      const own = mine.get(turn.index); // this user turn is an offer turn to check
      const offers = mine.get(turn.index + 1); // this system turn makes the offer of the next turn
      const classes = ["turn", turn.speaker];
      if (t && (turn.index === t.turn.index || turn.index === t.turn.index - 1)) classes.push("checked");
      else if (isUser && turn.index === state.focus) classes.push("focus");
      const pick = isUser ? () => {
        if (own) { goTask(own); return; }
        state.focus = turn.index;
        renderTurns();
        renderState();
      } : null;
      return h("li", { class: classes.join(" "), "data-turn": turn.index },
        h("span", { class: "index" }, turn.index),
        h("div", { class: "body", tabindex: isUser ? "0" : null, onclick: pick,
          onkeydown: isUser ? (event) => { if (event.key === "Enter" && event.target === event.currentTarget) { event.stopPropagation(); pick(); } } : null,
          title: isUser ? (own ? "Check this offer turn" : "Show the state after this turn") : null },
          h("div", { class: "who" },
            h("span", { class: "name" }, turn.speaker),
            !isUser && offers ? h("span", { class: "mark" }, "◆ offer") : null,
            own ? ruleChip(own.label, own.how) : null,
            own ? h("span", { class: "mark" }, "◆ offer turn") : null),
          h("div", { class: "text" }, turn.text),
          actsBlock(turn)));
    }));
  }

  // ---- verdict area ----

  function renderLabel() {
    const t = task();
    const visible = visibleTasks();
    if (!t) {
      const next = tasksOf(state.conv).find((x) => statusOf(x.id) !== "done") || state.tasks.find((x) => statusOf(x.id) !== "done");
      $("label-head").replaceChildren(h("span", { class: "where muted" }, "No offer turn selected"));
      $("task-card").replaceChildren(h("div", { class: "placeholder" },
        "Choose an offer turn from the list, or click one in the dialogue.",
        next ? h("button", { type: "button", onclick: () => goTask(next) }, `Start with ${next.id}`)
          : "Every offer turn is done."));
      $("label-form").replaceChildren();
      $("label-foot").replaceChildren();
      renderState();
      return;
    }
    const position = visible.indexOf(t);
    $("label-head").replaceChildren(
      h("span", { class: "where" }, h("b", {}, t.id), position >= 0 ? ` · ${position + 1} / ${visible.length}` : " · outside the filters"),
      h("span", { class: "spacer" }),
      h("button", { type: "button", class: "nav", title: "Previous offer turn (k)", "aria-label": "Previous offer turn", onclick: () => step(-1) }, "◀"),
      h("button", { type: "button", class: "nav", title: "Next offer turn (j)", "aria-label": "Next offer turn", onclick: () => step(1) }, "▶"));
    const system = turnAt(t.turn.index - 1);
    $("task-card").replaceChildren(
      h("div", { class: "tags" }, h("span", { class: "chip", id: "status-chip" })),
      h("dl", {},
        h("dt", {}, "Offer"),
        h("dd", { class: "quote" }, system ? [h("span", { class: "n" }, system.index), system.text] : "(no system turn before it)"),
        h("dt", {}, "Kind"), h("dd", {}, offerKinds(t).map((k) => h("span", { class: "chip warn" }, k))),
        h("dt", {}, "Offered"), h("dd", {}, offerParts(t).length ? offerParts(t).map((p) => h("span", { class: "chip mono" }, p)) : h("span", { class: "muted" }, "no value")),
        h("dt", {}, "Reply"), h("dd", { class: "quote" }, h("span", { class: "n" }, t.turn.index), t.turn.text),
        h("dt", {}, "Rule label"),
        h("dd", {}, ruleChip(t.label, t.how, "judged"), h("span", { class: "muted" }, `on ${t.version} acts`)),
        t.others.length ? h("dt", {}, "") : null,
        t.others.length ? h("dd", {}, t.others.map((o) =>
          h("span", { class: "muted" }, `on ${o.version} acts: ${ruleText(o.label, o.how)}` + (o.label !== t.label ? " (differs, not checked here)" : "")))) : null));
    renderForm();
    renderState();
  }

  function change(apply) {
    editEntry(state.taskId, apply);
    renderFormStatus();
    renderTasks();
    renderProgress();
  }

  function setVerdict(value) {
    if (!state.taskId) return;
    change((entry) => { entry.verdict = value; });
    const input = $("label-form").querySelector(`input[name="verdict"][value="${value}"]`);
    if (input) { input.checked = true; input.focus(); }
  }

  function renderForm() {
    const t = task();
    const entry = entryOf(t.id) || D.emptyEntry();
    $("label-form").replaceChildren(
      h("div", { class: "form-row" },
        h("label", { class: "title" }, `Is the rule label “${t.label}” right?`),
        h("div", { class: "labels" }, D.VERDICTS.map(([value, key]) =>
          h("label", { class: "choice" },
            h("input", { type: "radio", name: "verdict", value, checked: entry.verdict === value, onchange: () => setVerdict(value) }),
            h("span", { class: "key" }, key), value)))),
      h("div", { class: "form-row" },
        h("label", { class: "title", for: "note" }, "Note"),
        h("textarea", { id: "note", placeholder: "Required when the label is incorrect",
          oninput: (event) => change((e) => { e.note = event.target.value; }) }, entry.note)),
      h("ul", { class: "problems", id: "problems" }));
    renderFormStatus();
  }

  function renderFormStatus() {
    const entry = entryOf(state.taskId);
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
      h("button", { type: "button", class: "primary", title: "Confirm and go to the next offer turn (Enter)", onclick: confirmAndNext },
        status === "done" ? "Next ⏎" : "Confirm & next ⏎"));
  }

  // The state after the focused user turn, one column per annotation version. The rows are every
  // slot set anywhere in the dialogue, so the table keeps its shape from turn to turn.
  function renderState() {
    const turn = state.focus != null ? turnAt(state.focus) : null;
    $("state-section").hidden = !turn || !turn.state;
    if (!turn || !turn.state) return;
    $("state-turn").textContent = `turn ${turn.index}`;
    const users = state.conv.turns.filter((x) => x.speaker === "user" && x.state);
    const before = users[users.indexOf(turn) - 1];
    const slots = [];
    for (const user of users) {
      for (const version of D.VERSIONS) {
        for (const slot of Object.keys(user.state[version] || {})) if (!slots.includes(slot)) slots.push(slot);
      }
    }
    const rows = slots.map((slot) => {
      const values = D.VERSIONS.map((v) => (turn.state[v] || {})[slot] ?? "");
      const differ = new Set(values.map((v) => String(v).toLowerCase())).size > 1;
      return h("tr", { class: differ ? "differ" : "" },
        h("td", { class: "slot" }, slot),
        D.VERSIONS.map((version, i) => {
          const changed = ((before ? before.state[version] || {} : {})[slot] ?? "") !== values[i];
          return h("td", { class: ["value", values[i] ? "" : "unset", changed ? "new" : ""].join(" ") },
            values[i] || (changed ? "removed" : "–"));
        }));
    });
    $("state-table").replaceChildren(
      h("thead", {}, h("tr", {}, h("th", {}, "slot"), D.VERSIONS.map((v) => h("th", {}, v)))),
      h("tbody", {}, rows));
  }

  function toggleFlag() {
    if (!state.taskId) return;
    const entry = entryOf(state.taskId) || D.emptyEntry();
    entry.flagged = !entry.flagged; // a flag is a note to oneself; it does not undo a confirmation
    putEntry(state.taskId, entry);
    renderFormStatus();
    renderTasks();
    renderProgress();
  }

  function confirmAndNext() {
    if (!state.taskId) return;
    const entry = entryOf(state.taskId);
    if (D.problems(entry).length) {
      state.showProblems = true;
      renderFormStatus();
      return;
    }
    // The follower is fixed before the status changes, because a status filter may drop this turn.
    const visible = visibleTasks();
    const next = visible[visible.indexOf(task()) + 1];
    entry.status = "done";
    saveStore();
    if (next) goTask(next);
    else { state.showProblems = false; renderFormStatus(); renderTasks(); renderProgress(); }
  }

  function step(delta) {
    const visible = visibleTasks();
    if (!visible.length) return;
    const index = visible.indexOf(task());
    goTask(visible[index < 0 ? 0 : Math.min(visible.length - 1, Math.max(0, index + delta))]);
  }

  // ---------- keys ----------

  function onKey(event) {
    if (event.ctrlKey || event.metaKey || event.altKey) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && state.conv && state.taskId) { confirmAndNext(); event.preventDefault(); }
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
    else if (event.key === "c") setVerdict("correct");
    else if (event.key === "x") setVerdict("incorrect");
    else if (event.key === "n" && state.taskId) $("note")?.focus();
    else if (event.key === "Enter" && tag !== "BUTTON" && tag !== "A" && tag !== "SUMMARY" && state.taskId) confirmAndNext();
    else if (event.key === "f") toggleFlag();
    else if (event.key === "[") toggleSidebar();
    else if (event.key === "?") $("help").showModal();
    else if (event.key === "Escape") closeOverlay();
    else return;
    event.preventDefault();
  }

  // ---------- start ----------

  function wire() {
    $("import-data").addEventListener("click", () => $("data-file").click());
    $("import-labels").addEventListener("click", () => $("labels-file").click());
    $("export-labels").addEventListener("click", exportTsv);
    $("data-file").addEventListener("change", (event) => { const file = event.target.files[0]; event.target.value = ""; if (file) importData(file); });
    $("labels-file").addEventListener("change", (event) => { const file = event.target.files[0]; event.target.value = ""; if (file) importLabels(file); });
    $("notice-close").addEventListener("click", () => notice(""));
    $("annotator").addEventListener("change", (event) => setAnnotator(event.target.value));
    $("conv-select").addEventListener("change", (event) => {
      const dialogue = state.dialogues.find((d) => d.dialogue_id === event.target.value);
      goTask(tasksOf(dialogue).find((t) => statusOf(t.id) !== "done") || tasksOf(dialogue)[0]);
    });
    $("search").addEventListener("input", (event) => { state.filter.search = event.target.value; renderTasks(); });
    for (const button of document.querySelectorAll(".help-button")) button.addEventListener("click", () => $("help").showModal());
    for (const button of document.querySelectorAll("[data-toggle]")) button.addEventListener("click", toggleSidebar);
    window.addEventListener("resize", () => {
      if (!isNarrow()) state.overlay = false;
      if (state.conv) applySidebar();
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
    try {
      if (stored && stored.json) useData(stored.json, stored.name, true);
      else loadExample();
    } catch (error) {
      loadExample();
    }
    route();
  }

  start();
})();

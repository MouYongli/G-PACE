/* Shared drawing helpers for all paper figures (Fig. 1 to Fig. 5).
 *
 * A figure page loads this file, draws with the helpers below and calls save(height).
 * save(height, width = 1000) puts the SVG into <figure>, sizes the print page to the artwork and adds two buttons
 * to the page header: "Download SVG" and "Print to PDF" (vector, fonts embedded; header and
 * caption are left out of the print).
 *
 * Helpers take positional coordinates and an options object, for example
 *   T(43, 62, "Memory", { size: 17, w: 700, fill: NAVY })
 * Draw order is paint order: later calls are drawn on top.
 */
(function (g) {
  "use strict";
  const SANS = "'Fira Sans', Inter, 'Helvetica Neue', Helvetica, Arial, sans-serif";
  const MONO = "'Fira Code', 'JetBrains Mono', Menlo, Consolas, monospace";
  const C_ = {
    NAVY: "#151A4E", MUTED: "#5A6082",
    IND: "#2B36CE", TINT: "#EEF1FB", TINT2: "#DDE2F8", BORDER: "#B9BFE6", LIGHT: "#C9CFF2",
    CRI: "#C7305C", CRI_T: "#FBECF1", ORG: "#C2621B", ORG_T: "#FBE6D4", GRN: "#1E8A5A", YEL: "#F6C445",
  };
  const { NAVY, MUTED, IND, TINT, TINT2, BORDER, LIGHT, CRI, ORG, GRN, YEL } = C_;
  // Colours that have an arrowhead marker.
  const MARK = { [NAVY]: "navy", [IND]: "ind", [CRI]: "cri", [ORG]: "org", [MUTED]: "muted", [BORDER]: "border" };
  const o = [];

  function T(x, y, s, { size = 14, w = 400, fill = MUTED, anchor = "start", fam = SANS, extra = "" } = {}) {
    o.push(`<text x="${x}" y="${y}" font-family="${fam}" font-size="${size}" font-weight="${w}" fill="${fill}" text-anchor="${anchor}" ${extra}>${s}</text>`);
  }

  function M(x, y, s, { size = 11.5, fill = NAVY, anchor = "start", w = 500 } = {}) {
    T(x, y, s, { size, w, fill, anchor, fam: MONO });
  }

  function R(x, y, w, h, { rx = 10, fill = "#fff", stroke = "none", sw = 1.5, extra = "" } = {}) {
    o.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" ${extra}/>`);
  }

  function P(d, color = NAVY, { sw = 2.2, head = true, dash = null, fill = "none" } = {}) {
    if (head && !MARK[color]) throw new Error(`no arrowhead for colour ${color}`);
    const e = head ? ` marker-end="url(#ah-${MARK[color]})"` : "";
    const da = dash ? ` stroke-dasharray="${dash}"` : "";
    o.push(`<path d="${d}" fill="${fill}" stroke="${color}" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round"${e}${da}/>`);
  }

  function C(cx, cy, r, fill, stroke = "none", sw = 2) {
    o.push(`<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`);
  }

  function RAW(s) { o.push(s); }

  /** Numbered step badge. */
  function N(cx, cy, n, color, r = 11) {
    C(cx, cy, r, color, "#fff", 2);
    T(cx, cy + 5, n, { size: r > 9 ? 14 : 12, w: 700, fill: "#fff", anchor: "middle" });
  }

  /** Yellow dot: this step calls the LLM. */
  function LLM(cx, cy) { C(cx, cy, 5, YEL, "#fff", 1.5); }

  /** Card with a solid offset shadow. */
  function CARD(x, y, w, h, color = IND, { title = null, off = 9 } = {}) {
    R(x - off, y - off, w, h, { rx: 18, fill: color });
    R(x, y, w, h, { rx: 16, fill: "#fff", stroke: color, sw: 2 });
    if (title) T(x + 20, y + 30, title, { size: 19, w: 700, fill: NAVY });
  }

  /** Width of a monospace string. */
  function mw(s, size = 10.5) { return s.length * size * 0.61; }

  /** Monospace pill; returns the x after it (start anchor) or its left x (end anchor). */
  function chip(x, y, s, { fill = TINT, col = NAVY, size = 10.5, anchor = "start" } = {}) {
    const w = Math.round(mw(s, size) + 12);
    const h = Math.round(size + 5);
    if (anchor === "end") x -= w;
    else if (anchor === "middle") x -= w / 2;
    R(x, y, w, h, { rx: h / 2, fill });
    M(x + w / 2, y + h - 4.5, s, { size, fill: col, anchor: "middle" });
    return anchor === "start" ? x + w + 5 : x;
  }

  /** Entity pill centred at (cx, cy); returns its width. */
  function node(cx, cy, s, kind = "plain", size = 11.5) {
    const w = Math.round(mw(s, size) + 18);
    const st = {
      plain: ["#fff", IND, NAVY], new: [IND, IND, "#fff"], old: ["#fff", BORDER, MUTED],
      hot: ["#fff", CRI, NAVY], org: ["#fff", ORG, NAVY],
    }[kind];
    R(cx - w / 2, cy - 12, w, 24, { rx: 12, fill: st[0], stroke: st[1], sw: 2 });
    M(cx, cy + 4, s, { size, fill: st[2], anchor: "middle" });
    return w;
  }

  /** Message bubble; returns its height. */
  function BUB(x, y, w, lines, { kind = "user", tag = null, cite = null, size = 13.5, citeSize = 12 } = {}) {
    const h = 16 + 18 * lines.length + (cite ? 20 : 0);
    const st = {
      user: [TINT2, "none", NAVY, ""], cur: [IND, "none", "#fff", ""],
      agent: ["#fff", BORDER, NAVY, ""], reply: ["#fff", NAVY, NAVY, 'stroke-dasharray="5 4"'],
      ask: ["#fff", CRI, NAVY, ""], bad: ["#fff", CRI, NAVY, 'stroke-dasharray="5 4"'],
    }[kind];
    R(x, y, w, h, { rx: 12, fill: st[0], stroke: st[1], sw: 1.6, extra: st[3] });
    lines.forEach((l, i) => T(x + 10, y + 22 + 18 * i, l, { size, fill: st[2], w: kind === "cur" ? 500 : 400 }));
    if (cite) M(x + 10, y + 22 + 18 * lines.length, cite, { size: citeSize, fill: IND });
    if (tag) {
      const left = ["user", "cur", "ask"].includes(kind);
      T(left ? x - 5 : x + w + 5, y + h / 2 + 5, tag,
        { size: 12.5, fill: MUTED, anchor: left ? "end" : "start", extra: 'font-style="italic"' });
    }
    return h;
  }

  /** Small-caps section label. */
  function label(x, y, s, color = MUTED) {
    T(x, y, s, { size: 11.5, w: 700, fill: color, extra: 'letter-spacing="0.07em"' });
  }

  function check(cx, cy, color = GRN) {
    C(cx, cy, 9, color);
    RAW(`<path d="M${cx - 4},${cy} l3,3 5,-6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`);
  }

  function cross(cx, cy, color = CRI) {
    C(cx, cy, 9, color);
    RAW(`<path d="M${cx - 3.5},${cy - 3.5} l7,7 M${cx + 3.5},${cy - 3.5} l-7,7" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/>`);
  }

  /** The SVG markup drawn so far, `width` units wide and `height` units tall. */
  function svgText(height, width = 1000) {
    const heads = Object.entries(MARK).map(([c, k]) =>
      `<marker id="ah-${k}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="4.6" markerHeight="4.6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${c}"/></marker>`).join("");
    return `<svg id="figure" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">\n<defs>${heads}</defs>\n${o.join("\n")}\n</svg>`;
  }

  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /** Put the figure into the page and add the export buttons. Width defaults to 1000 units. */
  function save(height, width = 1000) {
    const svg = svgText(height, width);
    if (typeof document === "undefined") return svg;  // headless use (e.g. node): just return the markup
    const fig = document.querySelector("figure");
    fig.insertAdjacentHTML("afterbegin", svg);
    // Print page = artwork size, so "Save as PDF" gives a tight vector PDF of the figure alone.
    const st = document.createElement("style");
    st.textContent = `@page { size: ${width}px ${height}px; margin: 0; }
      @media print { html, body { width: ${width}px; height: ${height}px; overflow: hidden; } figure { max-width: none; margin: 0; } }`;
    document.head.append(st);
    const base = (location.pathname.split("/").pop() || "figure").replace(/\.html?$/, "");
    const bar = document.createElement("span");
    bar.className = "export";
    const btn = (text, title, fn) => {
      const b = Object.assign(document.createElement("button"), { type: "button", textContent: text, title });
      b.addEventListener("click", fn);
      bar.append(b);
    };
    btn("Download SVG", "Bare SVG; fonts are referenced, not embedded", () =>
      download(`${base}.svg`, `<?xml version="1.0" encoding="UTF-8"?>\n${svg}\n`, "image/svg+xml"));
    btn("Print to PDF", "Vector PDF with embedded fonts: choose \"Save as PDF\" in the print dialog", () => window.print());
    document.querySelector("header")?.append(bar);
    return svg;
  }

  Object.assign(g, C_, { SANS, MONO, MARK, T, M, R, P, C, RAW, N, LLM, CARD, mw, chip, node, BUB, label, check, cross, svgText, save });
})(globalThis);

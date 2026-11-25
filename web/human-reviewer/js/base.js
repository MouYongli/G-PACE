// Shared helpers of the human-reviewer pages, exposed as window.HR.
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // h("div", {class: "x", onclick: fn}, child, "text") builds a DOM node; strings become text nodes.
  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === false || value == null) continue;
      if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key === "class") node.className = value;
      else node.setAttribute(key, value === true ? "" : value);
    }
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }

  window.HR = { $, h };
})();

# -*- coding: utf-8 -*-
"""Persistable drag-to-reorder for ranking-table column labels.

Streamlit 1.55 can drag native dataframe headers, but that order is
frontend-only and is not returned to Python. This v2 component is the
order we can actually save.
"""
import streamlit as st

_CSS = """
.bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 2px 0 4px 0;
  min-height: 28px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  background: #f0f2f6;
  border: 1px solid #c9cdd6;
  border-radius: 8px;
  cursor: grab;
  user-select: none;
  font-size: 13px;
  line-height: 1.2;
  color: #111827;
}
.chip:active { cursor: grabbing; }
.chip.dragging { opacity: 0.35; }
.chip.over { outline: 2px solid #ff4b4b; outline-offset: 1px; }
.grip {
  color: #6b7280;
  font-size: 12px;
  letter-spacing: -1px;
}
"""

_JS = r"""
export default function(component) {
  const { data, setStateValue, parentElement } = component;
  const items = (data && data.items) || [];
  let bar = parentElement.querySelector(".bar");
  if (!bar) {
    bar = document.createElement("div");
    bar.className = "bar";
    parentElement.appendChild(bar);
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function currentIds() {
    return Array.prototype.map.call(bar.querySelectorAll(".chip"), function (el) {
      return el.getAttribute("data-id");
    });
  }

  function render(list) {
    bar.innerHTML = "";
    (list || []).forEach(function (it) {
      const el = document.createElement("div");
      el.className = "chip";
      el.setAttribute("draggable", "true");
      el.setAttribute("data-id", it.id);
      el.innerHTML = '<span class="grip">::</span><span>' + esc(it.label) + "</span>";
      bar.appendChild(el);
    });
  }

  if (!bar.dataset.bound) {
    bar.dataset.bound = "1";
    let dragId = null;
    bar.addEventListener("dragstart", function (e) {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      dragId = chip.getAttribute("data-id");
      chip.classList.add("dragging");
      try {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", dragId);
      } catch (err) {}
    });
    bar.addEventListener("dragend", function () {
      dragId = null;
      Array.prototype.forEach.call(bar.querySelectorAll(".chip"), function (el) {
        el.classList.remove("dragging", "over");
      });
    });
    bar.addEventListener("dragover", function (e) {
      e.preventDefault();
      const over = e.target.closest(".chip");
      Array.prototype.forEach.call(bar.querySelectorAll(".chip"), function (el) {
        el.classList.toggle("over", !!(over && el === over));
      });
    });
    bar.addEventListener("drop", function (e) {
      e.preventDefault();
      const over = e.target.closest(".chip");
      const fromId = dragId || (e.dataTransfer && e.dataTransfer.getData("text/plain"));
      if (!fromId || !over) return;
      const toId = over.getAttribute("data-id");
      if (!toId || fromId === toId) return;
      const ids = currentIds();
      const from = ids.indexOf(fromId);
      const to = ids.indexOf(toId);
      if (from < 0 || to < 0) return;
      ids.splice(from, 1);
      ids.splice(to, 0, fromId);
      const byId = {};
      items.forEach(function (it) { byId[it.id] = it; });
      render(ids.map(function (id) { return byId[id]; }).filter(Boolean));
      setStateValue("order", ids);
    });
  }

  render(items);
}
"""

_mount = None


def _noop_order_change():
    return None


def render_col_sorter(items, default_ids=None, key="sra_col_sorter"):
    """Show draggable column labels. Returns the current id order."""
    global _mount
    if _mount is None:
        _mount = st.components.v2.component(
            "sra_col_sorter",
            html='<div class="bar"></div>',
            css=_CSS,
            js=_JS,
        )
    ids = list(default_ids or [it["id"] for it in items])
    result = _mount(
        data={"items": items},
        default={"order": ids},
        key=key,
        width="stretch",
        height="content",
        on_order_change=_noop_order_change,
    )
    order = getattr(result, "order", None)
    return list(order) if isinstance(order, list) else ids

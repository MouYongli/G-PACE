"""Figures of the cost tooling (plan 8.3), drawn from the computed data and written to a run
directory only. Every figure has a CSV beside it with the same numbers (the table view).

matplotlib is an analysis extra (`make setup` installs it); it is imported lazily so the ledger
code works without it.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path

from grace.eval.analysis.metrics.cost.amortisation import Curve, PaybackPoint

# Categorical slots in fixed order (never cycled); text stays in neutral inks.
SERIES = ("#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647")
INK, MUTED, GRID = "#1f1f1f", "#5c5c5c", "#e6e6e6"


def _pyplot():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                         "ytick.color": MUTED, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                         "grid.linewidth": 0.8, "font.size": 9, "figure.facecolor": "white",
                         "axes.facecolor": "white", "legend.frameon": False})
    return plt


def _color(labels: Sequence[str]) -> dict[str, str]:
    order: dict[str, None] = {}
    for label in labels:
        order.setdefault(label)
    if len(order) > len(SERIES):
        raise ValueError(f"{len(order)} series; at most {len(SERIES)} per figure")
    return {label: SERIES[i] for i, label in enumerate(order)}


def write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence]) -> None:
    with Path(path).open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def cumulative_figure(curves: Sequence[Curve], out: Path, *, unit: str) -> None:
    """Cumulative cost against read count; one panel per history, one line per system."""
    plt = _pyplot()
    colors = _color([c.label for c in curves])
    histories = list(dict.fromkeys(c.history_id for c in curves))
    fig, axes = plt.subplots(1, len(histories), figsize=(4.2 * len(histories), 3.2),
                             squeeze=False)
    for ax, history_id in zip(axes[0], histories, strict=True):
        for curve in (c for c in curves if c.history_id == history_id):
            xs = range(1, len(curve.points) + 1)
            ax.plot(xs, curve.points, color=colors[curve.label], linewidth=2, label=curve.label)
        ax.set_title(history_id, color=INK, fontsize=9, loc="left")
        ax.set_xlabel("reads")
        ax.set_ylabel(f"cumulative cost ({unit})")
    axes[0][-1].legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def payback_figure(series: Mapping[str, Sequence[PaybackPoint]], marks: Mapping[str, float],
                   out: Path) -> None:
    """M* over the cache ratio c; measured values of c are marked as vertical rules."""
    plt = _pyplot()
    colors = _color(list(series))
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    for label, points in series.items():
        xs = [p.c for p in points if p.m_star is not None]
        ys = [p.m_star for p in points if p.m_star is not None]
        ax.plot(xs, ys, color=colors[label], linewidth=2, marker="o", markersize=3,
                label=label)
    for name, c in marks.items():
        ax.axvline(c, color=MUTED, linewidth=1, linestyle="--")
        ax.annotate(f"{name} = {c:.3f}", (c, 1), xycoords=("data", "axes fraction"),
                    xytext=(3, -12), textcoords="offset points", color=INK, fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_xlabel("cache ratio c (cost of a cache-hit input token)")
    ax.set_ylabel("payback read count M*")
    ax.set_yscale("log")
    ax.legend(loc="center right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def quality_figure(points: Sequence[Mapping], out: Path, *, metric: str, unit: str) -> None:
    """Quality against mean tokens per read, one labelled point per system."""
    plt = _pyplot()
    colors = _color([p["label"] for p in points])
    fig, ax = plt.subplots(figsize=(5.0, 3.4))
    for p in points:
        ax.scatter([p["tokens"]], [p["value"]], s=40, color=colors[p["label"]],
                   edgecolors="white", linewidths=1.5, zorder=3, label=p["label"])
        ax.annotate(p["label"], (p["tokens"], p["value"]), xytext=(5, 4),
                    textcoords="offset points", color=INK, fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel(f"mean system cost per read ({unit})")
    ax.set_ylabel(metric)
    if len(points) > 1:
        ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def success_figure(rows: Sequence[Mapping], out: Path, *, ledger: str) -> None:
    """Cost per successful task, one bar per run; runs without a success are listed, not drawn."""
    plt = _pyplot()
    drawn = [r for r in rows if r["cost_per_success"][ledger] is not None]
    fig, ax = plt.subplots(figsize=(5.0, 0.5 + 0.45 * max(1, len(rows))))
    labels = [r["label"] for r in drawn]
    values = [r["cost_per_success"][ledger] for r in drawn]
    ax.barh(labels, values, color=SERIES[0], height=0.6)
    for y, (value, r) in enumerate(zip(values, drawn, strict=True)):
        ax.annotate(f"{value:,.0f}  (success {r['success_rate']:.0%})", (value, y),
                    xytext=(4, 0), textcoords="offset points", va="center", color=INK,
                    fontsize=8)
    undefined = [r["label"] for r in rows if r["cost_per_success"][ledger] is None]
    if undefined:
        ax.set_title("undefined (no success): " + ", ".join(undefined), fontsize=8, color=MUTED,
                     loc="left")
    ax.set_xlabel(f"cost per successful task ({ledger})")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)

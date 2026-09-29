"""Вкладка «Порівняння»: збережені сценарії поруч — таблиця та стовпчикові діаграми KPI."""
from __future__ import annotations

from tkinter import messagebox, ttk

import numpy as np

from ..engine import SimResult
from .plots import legend, style_ax
from .widgets import DataTable, FigureFrame


def scenario_name(n: int, res: SimResult) -> str:
    cfg = res.cfg
    staff = f"N={cfg.agents}" if cfg.agents_by_hour is None else "розклад " + "/".join(map(str, cfg.capacity()))
    extra = []
    if abs(cfg.load_factor - 1) > 1e-9:
        extra.append(f"λ×{cfg.load_factor * 100:.0f}%")
    if cfg.patience_mean > 0:
        extra.append(f"терпіння {cfg.patience_mean:.0f} с")
    if cfg.acw_mean > 0:
        extra.append(f"ACW {cfg.acw_mean:.0f} с")
    return f"#{n} {staff}" + (", " + ", ".join(extra) if extra else "")


class CompareTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        self.items: list[tuple[str, dict]] = []
        self.counter = 0

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=16, pady=(10, 4))
        ttk.Label(bar, text="Порівняння сценаріїв", style="H1.TLabel").pack(side="left")
        ttk.Button(bar, text="Очистити все", style="Small.TButton", command=self.clear).pack(side="right")
        ttk.Button(bar, text="Видалити виділений", style="Small.TButton", command=self.remove_selected).pack(side="right", padx=6)
        ttk.Button(bar, text="Додати останній результат", style="Small.TButton", command=self.add_last).pack(side="right")
        ttk.Label(self, style="Muted.TLabel", wraplength=1100, justify="left",
                  text="Запускайте симуляції з різними параметрами (штат, навантаження, терпіння клієнтів…) і додавайте результати "
                       "кнопкою «Зберегти сценарій для порівняння» на вкладці «Результати» — тут вони будуть зіставлені за ключовими показниками."
                  ).pack(fill="x", padx=16, pady=(0, 6))

        pan = ttk.Panedwindow(self, orient="vertical")
        pan.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.fig = FigureFrame(pan, self.theme, figsize=(10, 5), save_name="porivnyannia_stsenariiv")
        self.fig.set_placeholder("Збережених сценаріїв ще немає")
        pan.add(self.fig, weight=4)
        self.table = DataTable(pan, self.theme, [("n", "Сценарій", 300), ("sla", "SLA, %", 80), ("w", "Очікування, с", 110),
                                                 ("p", "P95, с", 80), ("u", "Завантаження, %", 120), ("q", "Макс. черга", 100),
                                                 ("l", "Втрачено, %", 90), ("c", "Викликів/день", 100)], height=6)
        pan.add(self.table, weight=1)

    def add(self, res: SimResult):
        self.counter += 1
        s = res.summary
        d = {k: s[k]["mean"] for k in ("sla_pct", "wait_mean", "wait_p95", "util_pct", "q_max", "abandon_pct", "offered_day")}
        d["sla_lo"], d["sla_hi"] = s["sla_pct"]["lo"], s["sla_pct"]["hi"]
        self.items.append((scenario_name(self.counter, res), d))
        self._refresh()

    def add_last(self):
        if self.app.result is None:
            messagebox.showinfo("Порівняння", "Немає результатів — спершу запустіть симуляцію.")
            return
        self.add(self.app.result)

    def clear(self):
        self.items.clear()
        self._refresh()

    def remove_selected(self):
        sel = self.table.tree.selection()
        if not sel:
            return
        idx = sorted((self.table.tree.index(i) for i in sel), reverse=True)
        for i in idx:
            del self.items[i]
        self._refresh()

    def _refresh(self):
        rows = [(n, f"{d['sla_pct']:.1f}", f"{d['wait_mean']:.1f}", f"{d['wait_p95']:.0f}", f"{d['util_pct']:.0f}",
                 f"{d['q_max']:.1f}", f"{d['abandon_pct']:.1f}", f"{d['offered_day']:.0f}") for n, d in self.items]
        self.table.set_rows(rows)
        if not self.items:
            self.fig.clear()
            return
        items = list(self.items)
        self.fig.plot(lambda fig, C: self._plot(fig, C, items))

    @staticmethod
    def _plot(fig, C, items):
        axs = fig.subplots(2, 2)
        names = [n.split(" ", 1)[0] for n, _ in items]
        x = np.arange(len(items))
        specs = [("sla_pct", "SLA, %", C["good"]), ("wait_mean", "Середнє очікування, с", C["accent"]),
                 ("wait_p95", "P95 очікування, с", C["violet"]), ("util_pct", "Завантаження операторів, %", C["warn"])]
        for ax, (key, title, col) in zip(axs.ravel(), specs):
            vals = np.array([d[key] for _, d in items])
            ax.bar(x, vals, color=col, alpha=0.9, width=0.6)
            if key == "sla_pct":
                lo = np.array([d["sla_lo"] for _, d in items])
                hi = np.array([d["sla_hi"] for _, d in items])
                ax.errorbar(x, vals, yerr=[vals - lo, hi - vals], fmt="none", ecolor=C["fg"], capsize=3, lw=1)
            for xi, v in zip(x, vals):
                ax.text(xi, v, f"{v:.1f}" if key != "wait_p95" else f"{v:.0f}", ha="center", va="bottom", fontsize=8, color=C["fg"])
            ax.set_xticks(x)
            ax.set_xticklabels(names, fontsize=8)
            ax.set_ylim(0, max(vals.max() * 1.18, 1e-6))
            style_ax(ax, C, title, None, None)
        if len(items) <= 8:
            fig.text(0.5, 0.005, "   ".join(n for n, _ in items), ha="center", va="bottom", fontsize=7, color=C["muted"], wrap=True)

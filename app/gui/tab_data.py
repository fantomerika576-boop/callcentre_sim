"""Вкладки «Дані» (журнал дзвінків) та «Аналіз даних» (ідентифікація моделі)."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np

from ..config import MONTHS_UA
from ..data import findings_text
from .plots import plot_analysis
from .widgets import DataTable, FigureFrame, kpi_row, scrolled_text, set_text

PAGE = 200


class DataTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        self.cards = kpi_row(self, self.theme, [
            ("calls", "ВИКЛИКІВ У ЖУРНАЛІ"), ("days", "РОБОЧИХ ДНІВ"), ("cpd", "ВИКЛИКІВ / ДЕНЬ"),
            ("wait", "СЕР. ОЧІКУВАННЯ"), ("sla", "SLA ВИКОНАНО"), ("svc", "СЕР. РОЗМОВА"),
            ("agents", "ОПЕРАТОРІВ")])

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=16, pady=(6, 4))
        ttk.Button(bar, text="Відкрити CSV / ZIP…", command=app.open_dialog).pack(side="left")
        self.src = ttk.Label(bar, text="Файл не завантажено", style="Muted.TLabel")
        self.src.pack(side="left", padx=12)

        self.month_var = tk.StringVar(value="Усі місяці")
        self.viol_var = tk.BooleanVar(value=False)
        self.q_var = tk.StringVar()
        ttk.Button(bar, text="Скинути", style="Small.TButton", command=self._reset).pack(side="right")
        ent = ttk.Entry(bar, textvariable=self.q_var, width=16)
        ent.pack(side="right", padx=(4, 10))
        ent.bind("<Return>", lambda e: self._refilter())
        ttk.Label(bar, text="Пошук (№ / дата):").pack(side="right")
        ttk.Checkbutton(bar, text="Лише порушення SLA", variable=self.viol_var,
                        command=self._refilter).pack(side="right", padx=12)
        self.month_cb = ttk.Combobox(bar, textvariable=self.month_var, state="readonly", width=14,
                                     values=["Усі місяці"] + MONTHS_UA)
        self.month_cb.pack(side="right", padx=4)
        self.month_cb.bind("<<ComboboxSelected>>", lambda e: self._refilter())
        ttk.Label(bar, text="Місяць:").pack(side="right")

        cols = [("id", "№ виклику", 80), ("date", "Дата", 100), ("n", "№ за день", 80),
                ("st", "Надходження", 105), ("an", "Відповідь", 105), ("en", "Завершення", 105),
                ("w", "Очікування, с", 105), ("s", "Розмова, с", 95), ("ok", "SLA", 60)]
        self.table = DataTable(self, self.theme, cols, height=16)
        self.table.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Button(nav, text="«", width=3, style="Small.TButton", command=lambda: self._goto(0)).pack(side="left")
        ttk.Button(nav, text="‹ Назад", style="Small.TButton", command=lambda: self._goto(self.page - 1)).pack(side="left", padx=4)
        ttk.Button(nav, text="Далі ›", style="Small.TButton", command=lambda: self._goto(self.page + 1)).pack(side="left")
        ttk.Button(nav, text="»", width=3, style="Small.TButton", command=lambda: self._goto(10 ** 9)).pack(side="left", padx=4)
        self.page_lbl = ttk.Label(nav, text="", style="Muted.TLabel")
        self.page_lbl.pack(side="left", padx=12)
        self.page = 0
        self.view = None

    # ------------------------------------------------------------ дані
    def show(self, data):
        k = data.kpis()
        self.cards["calls"].set(f"{k['calls']:,}".replace(",", " "), data.source)
        self.cards["days"].set(str(k["days"]), f"{data.df['date'].min():%d.%m.%Y} — {data.df['date'].max():%d.%m.%Y}")
        self.cards["cpd"].set(f"{k['calls_per_day']:.0f}", f"від {data.df.groupby('date').size().min()} до {data.df.groupby('date').size().max()}")
        self.cards["wait"].set(f"{k['wait_mean']:.1f} с", f"медіана {k['wait_median']:.0f} · P95 {k['wait_p95']:.0f} с")
        good = "good" if k["sla"] >= 0.9 else "warn"
        self.cards["sla"].set(f"{k['sla'] * 100:.1f}%", f"очікування ≤ {data.sla_seconds:.0f} с", good)
        self.cards["svc"].set(f"{k['service_mean']:.0f} с", f"CV = {k['service_cv']:.2f}")
        self.cards["agents"].set(str(data.n_agents), "макс. одночасних розмов")
        self.src.configure(text=f"Джерело: {data.source}")
        self._reset()

    def _reset(self):
        self.month_var.set("Усі місяці")
        self.viol_var.set(False)
        self.q_var.set("")
        self._refilter()

    def _refilter(self):
        data = self.app.data
        if data is None:
            return
        d = data.df
        m = self.month_var.get()
        if m != "Усі місяці":
            d = d[d["month"] == MONTHS_UA.index(m) + 1]
        if self.viol_var.get():
            d = d[~d["meets_standard"]]
        q = self.q_var.get().strip()
        if q:
            ds = d["date"].dt.strftime("%Y-%m-%d")
            d = d[ds.str.contains(q, regex=False) | (d["call_id"].astype(str) == q)]
        self.view = d
        self.page = 0
        self._render()

    def _goto(self, p):
        if self.view is None:
            return
        last = max(0, (len(self.view) - 1) // PAGE)
        self.page = int(min(max(0, p), last))
        self._render()

    def _render(self):
        d = self.view
        chunk = d.iloc[self.page * PAGE:(self.page + 1) * PAGE]
        rows, flags = [], []
        for r in chunk.itertuples(index=False):
            rows.append((r.call_id, f"{r.date:%d.%m.%Y}", r.daily_caller, r.call_started, r.call_answered,
                         r.call_ended, r.wait_length, r.service_length, "✓" if r.meets_standard else "✗"))
            flags.append("" if r.meets_standard else "bad")
        self.table.set_rows(rows, flags)
        last = max(1, (len(d) - 1) // PAGE + 1)
        self.page_lbl.configure(text=f"Сторінка {self.page + 1} із {last}  ·  записів у вибірці: {len(d):,}".replace(",", " "))


class AnalysisTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True, padx=12, pady=10)
        self.fig = FigureFrame(pan, self.theme, figsize=(9, 6), save_name="analiz_danykh")
        self.fig.set_placeholder("Завантажте дані, щоб побачити аналіз")
        pan.add(self.fig, weight=4)
        right = ttk.Frame(pan)
        pan.add(right, weight=1)
        pan.bind("<Map>", lambda e: pan.after(60, lambda: pan.sashpos(0, int(pan.winfo_width() * 0.60))))
        ttk.Label(right, text="Ідентифікація моделі за даними", style="H2.TLabel").pack(anchor="w", padx=4, pady=(0, 6))
        box, self.text = scrolled_text(right, self.theme, height=20)
        box.pack(fill="both", expand=True)
        ttk.Label(right, text="Порівняння законів розподілу (обслуговування)", style="H2.TLabel").pack(anchor="w", padx=4, pady=(10, 4))
        self.fits = DataTable(right, self.theme, [("n", "Розподіл", 130), ("d", "D (KS)", 70), ("a", "AIC", 90)], height=4)
        self.fits.pack(fill="x")

    def show(self, data, an):
        self.fig.plot(lambda fig, C: plot_analysis(fig, C, data, an))
        parts = []
        for head, body in findings_text(data, an):
            parts += [(head + "\n", "h"), (body + "\n", "")]
        set_text(self.text, parts)
        rows = [(r["name"], f"{r['D']:.4f}", f"{r['aic']:.0f}") for _, r in an.fits.iterrows()]
        self.fits.set_rows(rows, ["best"] + [""] * (len(rows) - 1))

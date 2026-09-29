"""Вкладка «Результати»: вікно виводу результатів імітації (KPI, графіки, таблиці, висновок, експорт)."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..config import HOUR_LABELS, MONTHS_UA
from ..engine import SimResult
from ..export import KPI_TITLES, export_calls_csv, export_excel
from ..queueing import min_agents, profile_metrics
from .plots import plot_results
from .widgets import DataTable, FigureFrame, kpi_row, scrolled_text, set_text

# (ключ, назва, кількість знаків, одиниця)
KPI_FMT = {
    "offered_day": (0, ""), "served_day": (0, ""), "abandon_pct": (1, "%"), "wait_mean": (1, " с"),
    "waited_pct": (1, "%"), "sla_pct": (1, "%"), "wait_p95": (0, " с"), "wait_max": (0, " с"),
    "util_pct": (1, "%"), "q_mean": (2, ""), "q_max": (1, ""), "overtime_min": (1, " хв"),
    "wait_min_day": (0, " хв"), "wait_if_waited": (1, " с"),
}


class ResultsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        self.res: SimResult | None = None

        self.cards = kpi_row(self, self.theme, [
            ("sla", "SLA ВИКОНАНО"), ("wait", "СЕР. ОЧІКУВАННЯ"), ("p95", "P95 ОЧІКУВАННЯ"),
            ("util", "ЗАВАНТАЖЕННЯ"), ("queue", "МАКС. ЧЕРГА"), ("lost", "ВТРАЧЕНО ВИКЛИКІВ"),
            ("calls", "ОБСЛУГОВАНО / ДЕНЬ")])

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=16, pady=(4, 4))
        self.ref_var = tk.BooleanVar(value=True)
        self.erl_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Порівняти з фактом (журнал)", variable=self.ref_var,
                        command=self._replot).pack(side="left")
        ttk.Checkbutton(bar, text="Крива Erlang C", variable=self.erl_var,
                        command=self._replot).pack(side="left", padx=14)
        ttk.Label(bar, text="Цільовий SLA, %:").pack(side="left", padx=(14, 4))
        self.target_var = tk.DoubleVar(value=90.0)
        sp = ttk.Spinbox(bar, from_=50, to=99.9, increment=1, textvariable=self.target_var, width=6,
                         command=self._verdict)
        sp.pack(side="left")
        sp.bind("<Return>", lambda e: self._verdict())
        ttk.Button(bar, text="Зберегти сценарій для порівняння", style="Small.TButton",
                   command=self._snapshot).pack(side="right", padx=(6, 0))
        ttk.Button(bar, text="Експорт у CSV…", style="Small.TButton", command=self._csv).pack(side="right", padx=6)
        ttk.Button(bar, text="Експорт у Excel…", style="Small.TButton", command=self._excel).pack(side="right")

        self.nb = ttk.Notebook(self, style="Inner.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        self.fig = FigureFrame(self.nb, self.theme, figsize=(11, 6), save_name="rezultaty_symuliatsii")
        self.fig.set_placeholder("Запустіть симуляцію на вкладці «Модель» (F5) — тут з'являться результати")
        self.nb.add(self.fig, text="  Графіки  ")

        kp = ttk.Frame(self.nb)
        self.kpi_table = DataTable(kp, self.theme, [("k", "Показник", 280), ("m", "Середнє", 100), ("s", "Ст. відхил.", 100),
                                                    ("lo", "95% ЦІ від", 100), ("hi", "95% ЦІ до", 100)], height=16)
        self.kpi_table.pack(fill="both", expand=True, padx=6, pady=6)
        self.nb.add(kp, text="  Показники (KPI)  ")

        hp = ttk.Frame(self.nb)
        self.hour_table = DataTable(hp, self.theme, [("h", "Година", 90), ("c", "Викликів/день", 110), ("w", "Сер. очікування, с", 130),
                                                     ("s", "SLA, %", 90), ("q", "Чекали, %", 90)], height=16)
        self.hour_table.pack(fill="both", expand=True, padx=6, pady=6)
        self.nb.add(hp, text="  За годинами  ")

        vp = ttk.Frame(self.nb)
        box, self.verdict = scrolled_text(vp, self.theme, height=14)
        box.pack(fill="both", expand=True, padx=6, pady=6)
        self.nb.add(vp, text="  Висновок  ")

    # ------------------------------------------------------------ відображення
    def show(self, res: SimResult):
        self.res = res
        s = res.summary

        def ci(k, d=1, u=""):
            return f"95% ЦІ: {s[k]['lo']:.{d}f} – {s[k]['hi']:.{d}f}{u}"

        target = float(self.target_var.get())
        self.cards["sla"].set(f"{s['sla_pct']['mean']:.1f}%", ci("sla_pct", 1, "%"),
                              "good" if s["sla_pct"]["mean"] >= target else "bad")
        self.cards["wait"].set(f"{s['wait_mean']['mean']:.1f} с", ci("wait_mean", 1, " с"))
        self.cards["p95"].set(f"{s['wait_p95']['mean']:.0f} с", f"макс. за день ≈ {s['wait_max']['mean']:.0f} с")
        u = s["util_pct"]["mean"]
        self.cards["util"].set(f"{u:.0f}%", ci("util_pct", 1, "%"), "bad" if u > 92 else ("warn" if u > 85 else "good"))
        self.cards["queue"].set(f"{s['q_max']['mean']:.1f}", f"середня довжина {s['q_mean']['mean']:.2f}")
        ab = s["abandon_pct"]["mean"]
        self.cards["lost"].set(f"{ab:.1f}%", "клієнти втратили терпіння" if ab > 0 else "терпіння нескінченне",
                               "bad" if ab > 5 else ("warn" if ab > 0 else "good"))
        self.cards["calls"].set(f"{s['served_day']['mean']:.0f}", f"надійшло {s['offered_day']['mean']:.0f} за день")

        rows = []
        for key, title in KPI_TITLES.items():
            d, unit = KPI_FMT[key]
            v = s[key]
            rows.append((title, f"{v['mean']:.{d}f}", f"{v['std']:.{d}f}", f"{v['lo']:.{d}f}", f"{v['hi']:.{d}f}"))
        self.kpi_table.set_rows(rows)

        hr = res.hourly
        hrows, flags = [], []
        for _, r in hr.iterrows():
            hrows.append((HOUR_LABELS[int(r["hour"])], f"{r['calls_day']:.1f}", f"{r['wait_mean']:.1f}",
                          f"{r['sla_pct']:.1f}", f"{r['waited_pct']:.1f}"))
            flags.append("bad" if r["sla_pct"] < target else "")
        self.hour_table.set_rows(hrows, flags)
        self._replot()
        self._verdict()

    def _reference(self):
        d = self.app.data
        if d is None or not self.ref_var.get() or self.res is None:
            return None
        key = self.res.cfg.label
        if key == "custom":
            return None
        if key.startswith("month:"):
            m = int(key.split(":")[1])
            return dict(wait=d.subset(m)["wait_length"].to_numpy(), label=f"факт, {MONTHS_UA[m - 1].lower()}")
        return dict(wait=d.df["wait_length"].to_numpy(), label="факт, весь рік")

    def _replot(self):
        if self.res is None:
            return
        cfg = self.res.cfg
        erlang = None
        if self.erl_var.get():
            erlang = (cfg.effective_rates(), cfg.service_mean + cfg.acw_mean, cfg.capacity())
        ref = self._reference()
        self.fig.plot(lambda fig, C: plot_results(fig, C, self.res, ref, erlang))

    # ------------------------------------------------------------ висновок
    def _verdict(self):
        res = self.res
        if res is None:
            return
        try:
            target = float(self.target_var.get())
        except (tk.TclError, ValueError):
            return
        cfg, s = res.cfg, res.summary
        sla, util, wait = s["sla_pct"]["mean"], s["util_pct"]["mean"], s["wait_mean"]["mean"]
        parts = [("Загальна оцінка\n", "h")]
        ok = sla >= target
        parts.append((f"Частка викликів, обслугованих у межах SLA ({cfg.sla_seconds:.0f} с): {sla:.1f}% "
                      f"(95% ЦІ {s['sla_pct']['lo']:.1f}–{s['sla_pct']['hi']:.1f}%). ", ""))
        parts.append((("Цільовий рівень " if ok else "Цільовий рівень НЕ ") + f"{target:.0f}% досягається.\n", "good" if ok else "bad"))
        parts.append((f"Середнє очікування — {wait:.1f} с; 95% клієнтів чекають не більше {s['wait_p95']['mean']:.0f} с; "
                      f"у середньому {s['waited_pct']['mean']:.1f}% викликів потрапляє в чергу.\n", ""))
        parts.append(("Завантаження операторів\n", "h"))
        if util > 92:
            txt = "критично високе — система працює на межі стійкості, будь-який сплеск призводить до накопичення черги."
        elif util > 85:
            txt = "високе — запас потужності невеликий."
        elif util > 60:
            txt = "помірне, у робочому діапазоні."
        else:
            txt = "низьке — є резерв для скорочення штату."
        parts.append((f"{util:.0f}% — {txt}\n", ""))
        if s["overtime_min"]["mean"] > 1:
            parts.append((f"Після 18:00 у середньому ще {s['overtime_min']['mean']:.0f} хв триває обслуговування накопиченої черги.\n", "muted"))
        if s["abandon_pct"]["mean"] > 0:
            parts.append((f"Втрачено {s['abandon_pct']['mean']:.1f}% викликів через закінчення терпіння клієнтів.\n", "bad"))

        parts.append(("Рекомендація щодо штату (аналітично, Erlang C)\n", "h"))
        rates = cfg.effective_rates()
        svc = cfg.service_mean + cfg.acw_mean
        need = max(min_agents(float(r), svc, target / 100.0, cfg.sla_seconds) for r in rates)
        cur = max(cfg.capacity())
        if need > cur:
            parts.append((f"У пікову годину для SLA ≥ {target:.0f}% потрібно щонайменше {need} операторів (зараз {cur}). "
                          f"Рекомендовано збільшити штат або застосувати погодинний розклад (вкладка «Сценарії»).\n", "bad"))
        else:
            parts.append((f"Поточного штату ({cur}) достатньо для досягнення SLA ≥ {target:.0f}% у всі години "
                          f"(мінімум за Erlang C — {need}).\n", "good"))
        overall, _ = profile_metrics(rates, svc, cfg.capacity(), cfg.sla_seconds)
        if overall["stable"]:
            parts.append((f"Аналітична модель M/M/N дає SLA ≈ {overall['sla'] * 100:.1f}% та очікування ≈ {overall['wq']:.1f} с — "
                          f"для порівняння з імітацією.\n", "muted"))
        parts.append(("Параметри експерименту\n", "h"))
        parts.append((f"{cfg.replications} незалежних прогонів × {cfg.days} робочих днів; час виконання {res.elapsed:.1f} с; "
                      f"seed = {cfg.seed}.\n", "muted"))
        set_text(self.verdict, parts)

    # ------------------------------------------------------------ дії
    def _snapshot(self):
        if self.res is None:
            messagebox.showinfo("Порівняння", "Спершу запустіть симуляцію.")
            return
        self.app.tabs["compare"].add(self.res)
        self.app.status("Сценарій збережено для порівняння")

    def _excel(self):
        if self.res is None:
            messagebox.showinfo("Експорт", "Немає результатів — спершу запустіть симуляцію.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="rezultaty_symuliatsii.xlsx",
                                            filetypes=[("Excel", "*.xlsx")])
        if path:
            self.app.export_excel(path)

    def _csv(self):
        if self.res is None:
            messagebox.showinfo("Експорт", "Немає результатів — спершу запустіть симуляцію.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="zhurnal_symuliatsii.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            try:
                export_calls_csv(path, self.res)
                self.app.status(f"Збережено: {path}")
            except Exception as exc:
                messagebox.showerror("Експорт", str(exc))

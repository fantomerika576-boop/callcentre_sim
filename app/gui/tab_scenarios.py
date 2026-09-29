"""Вкладка «Сценарії»: підбір штату, стрес-тест, прогноз навантаження, погодинний розклад."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from ..config import HOUR_LABELS, MONTHS_UA
from ..engine import run_simulation
from ..experiments import forecast_load, schedule_plan, stress_grid, sweep_agents
from .plots import plot_forecast, plot_schedule, plot_stress, plot_sweep
from .widgets import DataTable, FigureFrame, Form, scrolled_text, set_text, spin


class _Panel(ttk.Frame):
    """Каркас підвкладки: ліворуч — параметри та висновок, праворуч — графік і таблиця."""

    title = ""
    hint = ""
    fig_name = "scenariy"

    def __init__(self, parent, app, table_cols, table_height=6):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(pan, width=310)
        pan.add(left, weight=0)
        right = ttk.Frame(pan)
        pan.add(right, weight=1)
        pan.bind("<Map>", lambda e: pan.after(60, lambda: pan.sashpos(0, 330)))
        ttk.Label(left, text=self.title, style="H2.TLabel").pack(anchor="w", padx=6, pady=(0, 2))
        ttk.Label(left, text=self.hint, style="Muted.TLabel", wraplength=290, justify="left").pack(anchor="w", padx=6, pady=(0, 6))
        self.form_box = ttk.Frame(left)
        self.form_box.pack(fill="x")
        self.form = Form(self.form_box)
        self.btn_box = ttk.Frame(left)
        self.btn_box.pack(fill="x", padx=6, pady=8)
        box, self.text = scrolled_text(left, self.theme, height=12)
        box.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        v = self.vpan = ttk.Panedwindow(right, orient="vertical")
        v.pack(fill="both", expand=True)
        self.fig = FigureFrame(v, self.theme, figsize=(9, 4.6), save_name=self.fig_name)
        self.fig.set_placeholder("Задайте параметри та натисніть кнопку запуску")
        v.add(self.fig, weight=4)
        self.table = DataTable(v, self.theme, table_cols, height=table_height)
        v.add(self.table, weight=1)

    def var(self, kind, value):
        return {"i": tk.IntVar, "d": tk.DoubleVar, "s": tk.StringVar}[kind](value=value)

    def model_cfg(self, **over):
        try:
            return self.app.tabs["model"].get_config(**over)
        except ValueError as exc:
            messagebox.showerror("Некоректні параметри моделі", str(exc))
            return None


# ------------------------------------------------------------------ 1. підбір кількості операторів
class SweepPanel(_Panel):
    title = "Підбір кількості операторів"
    hint = ("Для кожного варіанта штату виконується серія прогонів; обирається мінімальний штат, що досягає цільового SLA, "
            "та штат із мінімальною сукупною вартістю (оплата операторів + втрати від очікування + втрачені виклики).")
    fig_name = "pidbir_shtatu"

    def __init__(self, parent, app):
        super().__init__(parent, app, [("n", "Операторів", 80), ("u", "Завантаж., %", 90), ("w", "Очікування, с", 100), ("s", "SLA, %", 80),
                                       ("e", "SLA Erlang C, %", 105), ("p", "P95, с", 70), ("c", "Вартість/день, грн", 130)])
        self.lo, self.hi = self.var("i", 2), self.var("i", 9)
        self.c_ag, self.c_w, self.c_l = self.var("d", 250.0), self.var("d", 6.0), self.var("d", 400.0)
        self.target, self.reps = self.var("d", 90.0), self.var("i", 10)
        f, b = self.form, self.form_box
        f.add("Операторів від", spin(b, self.lo, 1, 60))
        f.add("до", spin(b, self.hi, 1, 60))
        f.add("Оплата оператора, грн/год", spin(b, self.c_ag, 0, 5000, 10))
        f.add("Втрати від очікування, грн/хв", spin(b, self.c_w, 0, 1000, 1))
        f.add("Втрачений виклик, грн", spin(b, self.c_l, 0, 10000, 50))
        f.add("Цільовий SLA, %", spin(b, self.target, 50, 99.9, 1))
        f.add("Прогонів на варіант", spin(b, self.reps, 2, 200))
        ttk.Button(self.btn_box, text="▶ Виконати підбір", style="Accent.TButton", command=self.run).pack(fill="x")

    def run(self):
        cfg = self.model_cfg()
        if cfg is None:
            return
        lo, hi = int(self.lo.get()), int(self.hi.get())
        if hi < lo or hi - lo > 30:
            messagebox.showerror("Підбір", "Діапазон має бути впорядкованим і не ширшим за 30 значень.")
            return
        vals = list(range(lo, hi + 1))
        tgt = float(self.target.get())
        args = (float(self.c_ag.get()), float(self.c_w.get()), float(self.c_l.get()), tgt, int(self.reps.get()))
        self.app.run_bg(lambda p, s: sweep_agents(cfg, vals, *args, p, s), lambda df: self._done(df, tgt), "Підбір штату…")

    def _done(self, df, tgt):
        self.app.sweep = df
        self.fig.plot(lambda fig, C: plot_sweep(fig, C, df, tgt))
        best = df["cost_total"].idxmin()
        rows, flags = [], []
        for i, r in df.iterrows():
            rows.append((int(r["agents"]), f"{r['util']:.0f}", f"{r['wait']:.1f}", f"{r['sla']:.1f}", f"{r['sla_erl']:.1f}",
                         f"{r['p95']:.0f}", f"{r['cost_total']:,.0f}".replace(",", " ")))
            flags.append("best" if i == best else ("" if r["meets"] else "bad"))
        self.table.set_rows(rows, flags)
        ok = df[df["meets"]]
        parts = [("Результат\n", "h")]
        if len(ok):
            n_ok = int(ok["agents"].min())
            parts.append((f"Мінімальний штат для SLA ≥ {tgt:.0f}%: {n_ok} операторів ", "good"))
            parts.append((f"(SLA {ok.iloc[0]['sla']:.1f}%, завантаження {ok.iloc[0]['util']:.0f}%).\n", ""))
        else:
            parts.append((f"У межах діапазону цільовий SLA {tgt:.0f}% не досягається — розширте діапазон.\n", "bad"))
        rb = df.loc[best]
        parts.append((f"Мінімальна сукупна вартість — {int(rb['agents'])} операторів: {rb['cost_total']:,.0f} грн/день "
                      f"(оператори {rb['cost_agents']:,.0f} + очікування {rb['cost_wait']:,.0f} + втрати {rb['cost_lost']:,.0f}).\n".replace(",", " "), ""))
        parts.append(("Рядок із виділенням у таблиці — економічно оптимальний варіант; червоні — не досягають цільового SLA.\n", "muted"))
        set_text(self.text, parts)


# ------------------------------------------------------------------ 2. стрес-тест
class StressPanel(_Panel):
    title = "Стрес-тест: штат × навантаження"
    hint = "Теплова карта показників при різній кількості операторів та множнику інтенсивності потоку (наприклад, сезонний пік, акція)."
    fig_name = "stres_test"

    def __init__(self, parent, app):
        super().__init__(parent, app, [("n", "Операторів", 90)], table_height=1)
        self.a_lo, self.a_hi = self.var("i", 3), self.var("i", 8)
        self.l_lo, self.l_hi, self.l_st = self.var("i", 60), self.var("i", 200), self.var("i", 20)
        self.reps, self.target = self.var("i", 5), self.var("d", 90.0)
        self.metric = self.var("s", "SLA, %")
        self.grid = None
        f, b = self.form, self.form_box
        f.add("Операторів від", spin(b, self.a_lo, 1, 60))
        f.add("до", spin(b, self.a_hi, 1, 60))
        f.add("Навантаження від, %", spin(b, self.l_lo, 20, 500, 10))
        f.add("до, %", spin(b, self.l_hi, 20, 500, 10))
        f.add("крок, %", spin(b, self.l_st, 5, 100, 5))
        f.add("Цільовий SLA, %", spin(b, self.target, 50, 99.9, 1))
        f.add("Прогонів у клітинці", spin(b, self.reps, 2, 50))
        cb = ttk.Combobox(b, textvariable=self.metric, state="readonly", width=24,
                          values=["SLA, %", "Сер. очікування, с", "Завантаження, %", "P95 очікування, с"])
        cb.bind("<<ComboboxSelected>>", lambda e: self._replot())
        f.add("Показник на карті", cb)
        ttk.Button(self.btn_box, text="▶ Побудувати карту", style="Accent.TButton", command=self.run).pack(fill="x")
        self.vpan.forget(self.table)

    def run(self):
        cfg = self.model_cfg()
        if cfg is None:
            return
        a = list(range(int(self.a_lo.get()), int(self.a_hi.get()) + 1))
        loads = [x / 100.0 for x in range(int(self.l_lo.get()), int(self.l_hi.get()) + 1, max(5, int(self.l_st.get())))]
        if len(a) < 1 or len(loads) < 2 or len(a) * len(loads) > 120:
            messagebox.showerror("Стрес-тест", "Сітка має містити від 2 до 120 клітинок — змініть діапазони.")
            return
        reps = int(self.reps.get())
        self.app.run_bg(lambda p, s: stress_grid(cfg, a, loads, reps, p, s), self._done, "Стрес-тест…")

    def _metric_key(self):
        return {"SLA, %": "sla", "Сер. очікування, с": "wait", "Завантаження, %": "util",
                "P95 очікування, с": "p95"}[self.metric.get()]

    def _replot(self):
        if self.grid is None:
            return
        g, key, tgt = self.grid, self._metric_key(), float(self.target.get())
        self.fig.plot(lambda fig, C: plot_stress(fig, C, g, key, tgt))

    def _done(self, grid):
        self.grid = grid
        self.app.stress = grid
        self._replot()
        tgt = float(self.target.get())
        parts = [("Мінімальний штат для SLA ≥ " + f"{tgt:.0f}%\n", "h")]
        for j, lf in enumerate(grid["loads"]):
            ok = [c for i, c in enumerate(grid["agents"]) if grid["sla"][i, j] >= tgt]
            parts.append((f"навантаження {lf * 100:.0f}%: ", "b"))
            parts.append((f"{min(ok)} операторів\n" if ok else "не вистачає в обраному діапазоні\n", "" if ok else "bad"))
        set_text(self.text, parts)


# ------------------------------------------------------------------ 3. прогноз
class ForecastPanel(_Panel):
    title = "Прогноз навантаження"
    hint = ("Лінійний тренд середньоденної кількості дзвінків за місяцями, прогнозний інтервал та розрахунок потрібного штату за формулою Erlang C. "
            "Показує, коли поточний штат перестає забезпечувати SLA.")
    fig_name = "prohnoz"

    def __init__(self, parent, app):
        super().__init__(parent, app, [("m", "Місяць", 90), ("c", "Викликів/день", 100), ("i", "Інтервал 95%", 130),
                                       ("r", "ρ при поточному штаті, %", 150), ("s", "SLA при поточному штаті, %", 160), ("n", "Потрібно операторів", 130)])
        self.months, self.agents, self.target = self.var("i", 6), self.var("i", 4), self.var("d", 90.0)
        f, b = self.form, self.form_box
        f.add("Горизонт прогнозу, міс.", spin(b, self.months, 1, 24))
        f.add("Поточний штат", spin(b, self.agents, 1, 60))
        f.add("Цільовий SLA, %", spin(b, self.target, 50, 99.9, 1))
        ttk.Button(self.btn_box, text="▶ Розрахувати прогноз", style="Accent.TButton", command=self.run).pack(fill="x")

    def on_data_loaded(self, data):
        self.agents.set(data.n_agents)

    def run(self):
        d = self.app.data
        if d is None:
            messagebox.showinfo("Прогноз", "Спершу завантажте журнал дзвінків.")
            return
        try:
            m = self.app.tabs["model"]
            fc = forecast_load(d, int(self.months.get()), int(self.agents.get()), float(self.target.get()) / 100.0,
                               service_mean=float(m.svc_var.get()) + float(m.acw_var.get()), sla_seconds=float(m.sla_var.get()))
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Прогноз", str(exc))
            return
        self.app.forecast = fc
        self.fig.plot(lambda fig, C: plot_forecast(fig, C, fc))
        t = fc.table
        rows, flags = [], []
        for _, r in t.iterrows():
            rows.append((r["label"], f"{r['calls_day']:.0f}", f"{r['lo']:.0f} – {r['hi']:.0f}", f"{r['rho']:.0f}", f"{r['sla_now']:.1f}", int(r["need"])))
            flags.append("bad" if r["sla_now"] < fc.target * 100 else "")
        self.table.set_rows(rows, flags)
        parts = [("Тренд\n", "h"),
                 (f"Інтенсивність зростає на {fc.slope:+.1f} викликів/день щомісяця (R² = {fc.r2:.2f}).\n", "")]
        parts.append(("Висновок\n", "h"))
        last = d.monthly_table().iloc[-1]
        if last["sla"] * 100 < fc.target * 100:
            parts.append((f"Уже в останньому місяці журналу SLA ({last['sla'] * 100:.1f}%) нижчий за ціль {fc.target * 100:.0f}%.\n", "bad"))
        if fc.saturation_month is None:
            parts.append((f"У межах прогнозу штат {fc.n_current} операторів забезпечує SLA ≥ {fc.target * 100:.0f}%.\n", "good"))
        else:
            k = fc.saturation_month
            row = t[t["x"] == k].iloc[0] if (t["x"] == k).any() else None
            if row is not None:
                parts.append((f"Штат {fc.n_current} операторів перестає забезпечувати SLA ≥ {fc.target * 100:.0f}% з місяця «{row['label']}».\n", "bad"))
            need = int(t["need"].max())
            parts.append((f"До кінця горизонту потрібно щонайменше {need} операторів.\n", ""))
        parts.append(("Прогноз екстраполює лінійний тренд, тому надійний лише на найближчі місяці; сезонність за один рік даних не оцінюється.\n", "muted"))
        set_text(self.text, parts)


# ------------------------------------------------------------------ 4. розклад
class SchedulePanel(_Panel):
    title = "Оптимальний погодинний розклад"
    hint = "Мінімальна кількість операторів у кожну годину доби для досягнення цільового SLA порівняно з рівномірним штатом."
    fig_name = "rozklad"

    def __init__(self, parent, app):
        super().__init__(parent, app, [("h", "Година", 80), ("l", "λ, викл/год", 90), ("n", "Розклад, операторів", 130),
                                       ("sp", "SLA (розклад), %", 120), ("f", "Рівномірний штат", 120), ("sf", "SLA (рівномірний), %", 140)])
        self.target = self.var("d", 90.0)
        self.plan = None
        self.f_ = self.form
        self.form.add("Цільовий SLA, %", spin(self.form_box, self.target, 50, 99.9, 1))
        ttk.Button(self.btn_box, text="▶ Розрахувати розклад", style="Accent.TButton", command=self.run).pack(fill="x")
        ttk.Button(self.btn_box, text="Перенести до моделі", command=self.apply).pack(fill="x", pady=(6, 0))
        ttk.Button(self.btn_box, text="Перевірити симуляцією", command=self.verify).pack(fill="x", pady=(6, 0))

    def run(self):
        cfg = self.model_cfg()
        if cfg is None:
            return
        tgt = float(self.target.get()) / 100.0
        self.plan = sc = schedule_plan(cfg, tgt)
        self.app.schedule = sc
        self.fig.plot(lambda fig, C: plot_schedule(fig, C, sc, tgt))
        rows = [(HOUR_LABELS[int(r["hour"])], f"{r['lam']:.1f}", int(r["need"]), f"{r['sla_plan']:.1f}", int(r["flat"]), f"{r['sla_flat']:.1f}")
                for _, r in sc.iterrows()]
        self.table.set_rows(rows, ["bad" if r["sla_flat"] < tgt * 100 else "" for _, r in sc.iterrows()])
        need_total, flat_total = int(sc["need"].sum()), int(sc["flat"].sum())
        diff = flat_total - need_total
        parts = [("Результат\n", "h"),
                 (f"Розклад: {'/'.join(str(int(x)) for x in sc['need'])} операторів по годинах (08–18).\n", "b"),
                 (f"Операторо-годин за день: {need_total} проти {flat_total} при рівномірному штаті ", "")]
        if diff > 0:
            parts.append((f"— економія {diff} оператор-год. ({diff / flat_total * 100:.0f}%).\n", "good"))
        elif diff < 0:
            parts.append((f"— потрібно на {-diff} оператор-год. більше, щоб підтримати SLA у пікові години.\n", "bad"))
        else:
            parts.append(("— різниці немає.\n", ""))
        if sc["need"].nunique() == 1:
            parts.append(("Інтенсивність потоку майже однакова протягом доби, тому оптимальний розклад рівномірний. "
                          "Ефект від погодинного планування зʼявляється при нерівномірному профілі λ(t); "
                          "натомість штат варто переглядати по місяцях (див. вкладку «Прогноз»).\n", "muted"))
        parts.append(("Червоні рядки — години, де рівномірний штат не досягає цільового SLA.\n", "muted"))
        set_text(self.text, parts)

    def apply(self):
        if self.plan is None:
            self.run()
        if self.plan is None:
            return
        self.app.tabs["model"].set_schedule([int(x) for x in self.plan["need"]])
        self.app.status("Розклад перенесено на вкладку «Модель»")

    def verify(self):
        if self.plan is None:
            self.run()
        if self.plan is None:
            return
        cfg = self.model_cfg(agents_by_hour=[int(x) for x in self.plan["need"]])
        if cfg is None:
            return
        m = self.app.tabs["model"]
        self.app.run_bg(lambda p, s: run_simulation(cfg, p, s), lambda res: m._done(cfg, res), "Перевірка розкладу симуляцією…")


# ------------------------------------------------------------------ контейнер
class ScenariosTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.nb = ttk.Notebook(self, style="Inner.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=10, pady=8)
        self.sweep = SweepPanel(self.nb, app)
        self.stress = StressPanel(self.nb, app)
        self.forecast = ForecastPanel(self.nb, app)
        self.schedule = SchedulePanel(self.nb, app)
        for w, t in ((self.sweep, "  Підбір штату  "), (self.stress, "  Стрес-тест  "),
                     (self.forecast, "  Прогноз  "), (self.schedule, "  Розклад  ")):
            self.nb.add(w, text=t)

    def on_data_loaded(self, data):
        self.forecast.on_data_loaded(data)

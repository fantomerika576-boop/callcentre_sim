"""Вкладка «Модель»: параметри, схема бізнес-процесу, швидка аналітична оцінка та запуск симуляції."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from ..config import MONTHS_UA, N_HOURS, OPEN_HOUR, SERVICE_DISTS
from ..engine import SimConfig, run_simulation
from ..queueing import min_agents, profile_metrics
from .plots import plot_process
from .widgets import FigureFrame, Form, ScrolledFrame, make_text, set_text, spin

PROFILE_ALL = "Весь рік (середнє за даними)"
PROFILE_CUSTOM = "Власна інтенсивність (рівномірна)"


class ModelTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        self._preview_job = None

        # ---- змінні
        self.profile_var = tk.StringVar(value=PROFILE_CUSTOM)
        self.load_var = tk.DoubleVar(value=100.0)
        self.lam_var = tk.DoubleVar(value=20.0)
        self.first_var = tk.BooleanVar(value=True)
        self.dist_var = tk.StringVar(value="Експоненційний")
        self.svc_var = tk.DoubleVar(value=300.0)
        self.cv_var = tk.DoubleVar(value=1.0)
        self.acw_var = tk.DoubleVar(value=0.0)
        self.agents_var = tk.IntVar(value=4)
        self.sched_var = tk.BooleanVar(value=False)
        self.sched_vars = [tk.IntVar(value=4) for _ in range(N_HOURS)]
        self.patience_var = tk.DoubleVar(value=0.0)
        self.sla_var = tk.DoubleVar(value=60.0)
        self.drop_var = tk.BooleanVar(value=True)
        self.days_var = tk.IntVar(value=22)
        self.reps_var = tk.IntVar(value=20)
        self.seed_var = tk.StringVar(value="42")

        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True, padx=10, pady=8)
        lc = ttk.Frame(pan)
        pan.add(lc, weight=0)
        btn_bar = ttk.Frame(lc)
        btn_bar.pack(side="bottom", fill="x")
        left = ScrolledFrame(lc, self.theme, width=440)
        left.pack(side="top", fill="both", expand=True)
        right = ttk.Frame(pan)
        pan.add(right, weight=1)
        self._build_left(left.inner, btn_bar)
        self._build_right(right)

        for v in (self.profile_var, self.load_var, self.lam_var, self.first_var, self.dist_var, self.svc_var,
                  self.cv_var, self.acw_var, self.agents_var, self.sched_var, self.patience_var, self.sla_var,
                  *self.sched_vars):
            v.trace_add("write", lambda *a: self._schedule_preview())
        self.agents_var.trace_add("write", lambda *a: self._sync_sched())
        self.profile_var.trace_add("write", lambda *a: self._toggle_states())
        self.dist_var.trace_add("write", lambda *a: self._toggle_states())
        self.sched_var.trace_add("write", lambda *a: self._toggle_states())
        self._toggle_states()
        self._schedule_preview()

    # ------------------------------------------------------------ побудова інтерфейсу
    def _group(self, parent, title):
        lf = ttk.LabelFrame(parent, text=f" {title} ")
        lf.pack(fill="x", padx=8, pady=6)
        inner = ttk.Frame(lf)
        inner.pack(fill="x", padx=4, pady=6)
        return Form(inner), inner

    def _build_left(self, root, btn_parent):
        f, b = self._group(root, "1. Вхідний потік викликів  λ(t)")
        self.profile_cb = ttk.Combobox(b, textvariable=self.profile_var, state="readonly", width=30,
                                       values=[PROFILE_CUSTOM])
        f.add("Профіль інтенсивності", self.profile_cb)
        self.lam_spin = spin(b, self.lam_var, 1, 500, 1)
        f.add("λ (власна), викл/год", self.lam_spin)
        sc = ttk.Frame(b)
        ttk.Scale(sc, from_=50, to=300, variable=self.load_var,
                  command=lambda v: self.load_var.set(round(float(v)))).pack(side="left", fill="x", expand=True)
        ttk.Label(sc, textvariable=self.load_var, width=5).pack(side="left")
        ttk.Label(sc, text="%").pack(side="left")
        f.add("Множник навантаження", sc)
        f.add_wide(ttk.Checkbutton(b, text="Перший дзвінок дня рівно о 08:00:00 (як у даних)", variable=self.first_var))

        f, b = self._group(root, "2. Обслуговування оператором")
        f.add("Розподіл тривалості", ttk.Combobox(b, textvariable=self.dist_var, state="readonly",
                                                   values=list(SERVICE_DISTS), width=24))
        f.add("Середня тривалість E[S], с", spin(b, self.svc_var, 1, 7200, 1))
        self.cv_spin = spin(b, self.cv_var, 0.05, 5, 0.05)
        f.add("Коеф. варіації CV", self.cv_spin)
        f.add("Постобробка ACW, с", spin(b, self.acw_var, 0, 1800, 5),
              "час, коли оператор недоступний після розмови (0 = немає)")

        f, b = self._group(root, "3. Ресурси та політика")
        f.add("Кількість операторів N", spin(b, self.agents_var, 1, 40, 1))
        f.add_wide(ttk.Checkbutton(b, text="Розклад операторів за годинами", variable=self.sched_var))
        grid = ttk.Frame(b)
        f.add_wide(grid)
        self.sched_spins = []
        for h in range(N_HOURS):
            cell = ttk.Frame(grid)
            cell.grid(row=h // 5, column=h % 5, padx=3, pady=2)
            ttk.Label(cell, text=f"{OPEN_HOUR + h}:00", style="Muted.TLabel").pack()
            sp = spin(cell, self.sched_vars[h], 0, 40, 1, width=4)
            sp.pack()
            self.sched_spins.append(sp)
        f.add("Терпіння клієнта, с", spin(b, self.patience_var, 0, 7200, 10),
              "середнє; 0 = клієнт чекає необмежено (як у даних)")
        f.add("Поріг SLA (очікування ≤), с", spin(b, self.sla_var, 1, 600, 5))
        f.add_wide(ttk.Checkbutton(b, text="Не враховувати незавершені до 18:00",
                                   variable=self.drop_var))

        f, b = self._group(root, "4. Параметри експерименту")
        f.add("Робочих днів у прогоні", spin(b, self.days_var, 1, 365, 1))
        f.add("Кількість прогонів", spin(b, self.reps_var, 1, 500, 1))
        f.add("Seed (порожньо = випадковий)", ttk.Entry(b, textvariable=self.seed_var, width=10))

        btns = ttk.Frame(btn_parent)
        btns.pack(fill="x", padx=8, pady=(8, 10))
        ttk.Button(btns, text="▶  Запустити симуляцію  (F5)", style="Accent.TButton",
                   command=self.run).pack(fill="x")
        row = ttk.Frame(btns)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Калібрувати за даними", command=self.calibrate).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Скинути", command=self.reset).pack(side="left", padx=(6, 0))

    def _build_right(self, root):
        ttk.Label(root, text="Схема бізнес-процесу «Обробка звернення клієнта»", style="H2.TLabel").pack(anchor="w", padx=4)
        self.diagram = FigureFrame(root, self.theme, figsize=(8, 3.2), save_name="skhema_protsesu", toolbar=False)
        self.diagram.pack(fill="x", padx=4, pady=(4, 8), ipady=24)
        ttk.Label(root, text="Швидка аналітична оцінка (Erlang C, M/M/N)", style="H2.TLabel").pack(anchor="w", padx=4)
        self.preview = make_text(root, self.theme, height=5)
        self.preview.pack(fill="x", padx=4, pady=(4, 8))
        ttk.Label(root, text="Журнал виконання", style="H2.TLabel").pack(anchor="w", padx=4)
        self.log = make_text(root, self.theme, height=8, mono=True)
        self.log.pack(fill="both", expand=True, padx=4, pady=(4, 0))

    # ------------------------------------------------------------ допоміжне
    def log_line(self, text: str, tag: str = ""):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag) if tag else self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_data_loaded(self, data):
        months = [f"{MONTHS_UA[m - 1]} (факт)" for m in data.months_present()]
        self.profile_cb.configure(values=[PROFILE_ALL] + months + [PROFILE_CUSTOM])
        self.calibrate(initial=True)

    def _toggle_states(self):
        custom = self.profile_var.get() == PROFILE_CUSTOM
        self.lam_spin.configure(state="normal" if custom else "disabled")
        cv_on = SERVICE_DISTS.get(self.dist_var.get(), "exp") in ("gamma", "lognorm")
        self.cv_spin.configure(state="normal" if cv_on else "disabled")
        for sp in self.sched_spins:
            sp.configure(state="normal" if self.sched_var.get() else "disabled")

    def _sync_sched(self):
        if not self.sched_var.get():
            try:
                n = int(self.agents_var.get())
            except (tk.TclError, ValueError):
                return
            for v in self.sched_vars:
                v.set(n)

    def set_schedule(self, plan: list[int]):
        self.sched_var.set(True)
        for v, n in zip(self.sched_vars, plan):
            v.set(int(n))

    def reset(self):
        self.load_var.set(100.0)
        self.first_var.set(True)
        self.dist_var.set("Експоненційний")
        self.acw_var.set(0.0)
        self.sched_var.set(False)
        self.patience_var.set(0.0)
        self.sla_var.set(60.0)
        self.drop_var.set(True)
        self.days_var.set(22)
        self.reps_var.set(20)
        self.seed_var.set("42")
        if self.app.data:
            self.calibrate(initial=True)
        else:
            self.agents_var.set(4)
            self.svc_var.set(300.0)
            self.cv_var.set(1.0)

    def calibrate(self, initial: bool = False):
        d = self.app.data
        if d is None:
            messagebox.showinfo("Калібрування", "Спершу завантажте журнал дзвінків.")
            return
        self.agents_var.set(d.n_agents)
        self.svc_var.set(round(d.service_mean, 1))
        self.cv_var.set(round(d.service_cv, 2))
        self.sla_var.set(d.sla_seconds)
        self.first_var.set(d.first_call_at_open)
        if initial:
            months = d.months_present()
            self.profile_var.set(f"{MONTHS_UA[months[-1] - 1]} (факт)")
            self.days_var.set(d.days_in(months[-1]))
        else:
            self.dist_var.set("Експоненційний" if 0.9 <= d.service_cv <= 1.1 else "Гамма (Ерланга)")
            self.log_line(f"Калібрування: N={d.n_agents}, E[S]={d.service_mean:.1f} с, CV={d.service_cv:.2f}, SLA={d.sla_seconds:.0f} с")

    # ------------------------------------------------------------ формування конфігурації
    def profile_key(self) -> str:
        p = self.profile_var.get()
        if p == PROFILE_ALL:
            return "all"
        if p == PROFILE_CUSTOM:
            return "custom"
        name = p.replace(" (факт)", "")
        return f"month:{MONTHS_UA.index(name) + 1}"

    def _rates(self):
        key = self.profile_key()
        d = self.app.data
        if key == "custom" or d is None:
            return [float(self.lam_var.get())] * N_HOURS
        month = None if key == "all" else int(key.split(":")[1])
        return list(d.hourly_rates(month, first_call=bool(self.first_var.get())))

    def get_config(self, **over) -> SimConfig:
        try:
            seed_txt = self.seed_var.get().strip()
            cfg = SimConfig(
                rates=self._rates(), load_factor=float(self.load_var.get()) / 100.0,
                agents=int(self.agents_var.get()),
                agents_by_hour=[int(v.get()) for v in self.sched_vars] if self.sched_var.get() else None,
                service_dist=SERVICE_DISTS[self.dist_var.get()], service_mean=float(self.svc_var.get()),
                service_cv=float(self.cv_var.get()),
                empirical=self.app.data.service_sample() if self.app.data else None,
                acw_mean=float(self.acw_var.get()), patience_mean=float(self.patience_var.get()),
                first_call_at_open=bool(self.first_var.get()), drop_unfinished=bool(self.drop_var.get()),
                sla_seconds=float(self.sla_var.get()), days=int(self.days_var.get()),
                replications=int(self.reps_var.get()), seed=int(seed_txt) if seed_txt else None,
                label=self.profile_key())
        except (tk.TclError, ValueError) as exc:
            raise ValueError("Перевірте параметри: усі поля мають містити коректні числа.") from exc
        if cfg.service_dist == "empirical" and cfg.empirical is None:
            raise ValueError("Емпіричний розподіл потребує завантажених даних.")
        if cfg.service_mean <= 0 or cfg.days < 1 or cfg.replications < 1:
            raise ValueError("Тривалість, кількість днів і прогонів мають бути додатними.")
        for k, v in over.items():
            setattr(cfg, k, v)
        return cfg

    # ------------------------------------------------------------ швидка оцінка
    def _schedule_preview(self):
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(150, self._update_preview)

    def _update_preview(self):
        self._preview_job = None
        try:
            cfg = self.get_config()
        except ValueError:
            return
        rates = cfg.effective_rates()
        svc = cfg.service_mean + cfg.acw_mean
        caps = cfg.capacity()
        overall, tab = profile_metrics(rates, svc, caps, cfg.sla_seconds)
        lam = float(rates.mean())
        a_avg = lam / 3600.0 * svc
        peak = int(np.argmax(rates))
        need = min_agents(float(rates.max()), svc, 0.9, cfg.sla_seconds)
        parts = [(f"λ̄ = {lam:.1f} викл/год  ·  {rates.sum():.0f} викликів/день  ·  навантаження a = λ·E[S] = {a_avg:.2f} Ерл\n", "b")]
        if overall["stable"]:
            rho = overall["rho"] * 100
            parts.append((f"Коеф. завантаження ρ = {rho:.0f}%   ·   P(очікування) = {overall['p_wait'] * 100:.1f}%   ·   "
                          f"сер. очікування ≈ {overall['wq']:.1f} с   ·   SLA ≈ {overall['sla'] * 100:.1f}%\n", "good" if overall["sla"] >= 0.9 else "bad"))
        else:
            parts.append(("Система нестійка (ρ ≥ 1): черга зростає необмежено — збільшіть штат або зменште навантаження.\n", "bad"))
        parts.append((f"Пікова година {OPEN_HOUR + peak}:00: для SLA ≥ 90% за Erlang C потрібно ≥ {need} операторів.\n", "muted"))
        if cfg.patience_mean > 0 or cfg.service_dist not in ("exp",):
            parts.append(("Примітка: оцінка Erlang C точна для експоненційного обслуговування без втрат; "
                          "для інших умов вона орієнтовна, точні значення дає симуляція.\n", "muted"))
        set_text(self.preview, parts)
        info = dict(lam=lam, calls_day=float(rates.sum()), agents=(cfg.agents if cfg.agents_by_hour is None else f"{min(caps)}–{max(caps)}"),
                    svc=cfg.service_mean,
                    dist=self.dist_var.get().split(" ")[0].lower() + " закон", acw=cfg.acw_mean,
                    patience="∞" if cfg.patience_mean <= 0 else f"{cfg.patience_mean:.0f} с", sla=cfg.sla_seconds)
        self.diagram.plot(lambda fig, C: plot_process(fig, C, info))

    # ------------------------------------------------------------ запуск
    def run(self):
        try:
            cfg = self.get_config()
        except ValueError as exc:
            messagebox.showerror("Некоректні параметри", str(exc))
            return
        n_calls = cfg.effective_rates().sum() * cfg.days * cfg.replications
        if n_calls > 3_000_000:
            if not messagebox.askyesno("Великий експеримент", f"Буде змодельовано ≈ {n_calls:,.0f} викликів. Продовжити?".replace(",", " ")):
                return
        self.log_line(f"▶ Старт: {cfg.replications} прогонів × {cfg.days} днів, N = "
                      f"{cfg.agents if cfg.agents_by_hour is None else 'розклад'}, "
                      f"≈ {cfg.effective_rates().sum():.0f} викликів/день", "b")
        self.app.run_bg(lambda p, s: run_simulation(cfg, p, s), lambda res: self._done(cfg, res),
                        "Виконується симуляція…")

    def _done(self, cfg, res):
        self.app.result, self.app.cfg = res, cfg
        s = res.summary
        self.log_line(f"✓ Готово за {res.elapsed:.1f} с. Змодельовано {int(res.days_total * s['offered_day']['mean']):,} викликів. "
                      f"SLA = {s['sla_pct']['mean']:.1f}%, сер. очікування = {s['wait_mean']['mean']:.1f} с, "
                      f"завантаження = {s['util_pct']['mean']:.0f}%".replace(",", " "), "good")
        self.app.tabs["results"].show(res)
        self.app.select("results")

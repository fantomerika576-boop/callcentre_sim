"""Вкладка «Валідація»: перевірка адекватності моделі — факт ↔ імітація ↔ аналітична модель."""
from __future__ import annotations

from tkinter import messagebox, ttk
import tkinter as tk

from ..experiments import ValidationResult, validate_model
from .plots import plot_validation
from .widgets import DataTable, FigureFrame, scrolled_text, set_text, spin

KPI_NAMES = {"calls_day": "Викликів за день", "wait": "Сер. очікування", "waited": "Частка тих, хто чекав",
             "sla": "SLA", "util": "Завантаження"}


class ValidationTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        self.result: ValidationResult | None = None

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=16, pady=(10, 6))
        ttk.Label(bar, text="Валідація моделі", style="H1.TLabel").pack(side="left")
        self.reps_var = tk.IntVar(value=15)
        ttk.Button(bar, text="▶ Виконати валідацію", style="Accent.TButton", command=self.run).pack(side="right")
        spin(bar, self.reps_var, 3, 100, 1, width=5).pack(side="right", padx=(4, 12))
        ttk.Label(bar, text="Прогонів на місяць:").pack(side="right")
        ttk.Label(self, style="Muted.TLabel", wraplength=1100, justify="left",
                  text="Для кожного місяця журналу модель запускається з відкаліброваними за даними параметрами (потік λ(t), кількість "
                       "операторів, середня тривалість розмови, поріг SLA); закон обслуговування та постобробка беруться з вкладки «Модель». Результати порівнюються з фактичними показниками та з "
                       "аналітичною моделлю Erlang C; перевіряється потрапляння факту в 95% прогнозний інтервал та збіг розподілів (критерій Колмогорова–Смирнова)."
                  ).pack(fill="x", padx=16, pady=(0, 6))

        pan = ttk.Panedwindow(self, orient="horizontal")
        pan.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.fig = FigureFrame(pan, self.theme, figsize=(9, 6), save_name="validatsiia_modeli")
        self.fig.set_placeholder("Натисніть «Виконати валідацію»")
        pan.add(self.fig, weight=4)
        right = ttk.Frame(pan)
        pan.add(right, weight=2)
        ttk.Label(right, text="Метрики точності", style="H2.TLabel").pack(anchor="w", padx=4, pady=(0, 4))
        self.metrics = DataTable(right, self.theme, [("k", "Показник", 150), ("mape", "MAPE, %", 70), ("cov", "У інтервалі", 90)], height=5)
        self.metrics.pack(fill="x")
        box, self.text = scrolled_text(right, self.theme, height=12)
        box.pack(fill="both", expand=True, pady=(8, 0))

    def run(self):
        data = self.app.data
        if data is None:
            messagebox.showinfo("Валідація", "Спершу завантажте журнал дзвінків.")
            return
        try:
            base = self.app.tabs["model"].get_config(
                agents=data.n_agents, agents_by_hour=None, load_factor=1.0, patience_mean=0.0,
                service_mean=data.service_mean, sla_seconds=data.sla_seconds,
                first_call_at_open=data.first_call_at_open)
            reps = int(self.reps_var.get())
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Некоректні параметри", str(exc))
            return
        self.app.run_bg(lambda p, s: validate_model(data, base, reps, p, s), self._done, "Валідація моделі…")

    def _done(self, v: ValidationResult):
        self.result = v
        self.app.validation = v
        self.fig.plot(lambda fig, C: plot_validation(fig, C, v))
        n = len(v.table)
        self.metrics.set_rows([(KPI_NAMES[k], f"{v.mape[k]:.1f}", f"{v.coverage[k]} із {n}") for k in KPI_NAMES])
        parts = [("Висновок про адекватність\n", "h")]
        tot_cov = sum(v.coverage.values()) / (n * len(v.coverage)) * 100
        good = tot_cov >= 85 and max(v.mape["sla"], v.mape["util"], v.mape["calls_day"]) < 10
        parts.append((f"Фактичні значення потрапляють у 95% інтервал імітації у {tot_cov:.0f}% випадків "
                      f"(за {n} місяцями × {len(v.coverage)} показників). ", ""))
        parts.append(("Модель визнається адекватною для цілей дослідження.\n" if good else
                      "Є суттєві відхилення — розгляньте уточнення параметрів.\n", "good" if good else "bad"))
        order = sorted(v.mape, key=v.mape.get)
        nm = lambda k: KPI_NAMES[k] if k == "sla" else KPI_NAMES[k].lower()
        best = ", ".join(f"{nm(k)} ({v.mape[k]:.1f}%)" for k in order[:3])
        worst = order[-1]
        parts.append((f"Найточніше відтворюються: {best}. Найбільша відносна похибка — {nm(worst)} "
                      f"({v.mape[worst]:.1f}%)" + (" — це малі величини (секунди) з великою природною мінливістю в межах місяця.\n"
                                                  if worst == "wait" else ".\n"), ""))
        parts.append(("Порівняння розподілів (Колмогоров–Смирнов)\n", "h"))
        dw, pw = v.ks["wait"]
        ds, ps = v.ks["service"]
        parts.append((f"Тривалість розмови: D = {ds:.4f}, p = {ps:.3f} — " +
                      ("розподіли статистично не відрізняються.\n" if ps > 0.05 else "розподіли відрізняються.\n"),
                      "good" if ps > 0.05 else "bad"))
        parts.append((f"Час очікування: D = {dw:.4f}, p = {pw:.4f} — " +
                      ("розподіли статистично не відрізняються.\n" if pw > 0.05 else
                       "статистично значуща, але мала за величиною різниця (велика вибірка ≈ 50 тис. викликів робить критерій дуже чутливим; "
                       "D < 0,02 означає практичну незначущість).\n"), "good" if pw > 0.05 else "muted"))
        parts.append(("Оцінка якості: MAPE < 10% — добре, 10–20% — прийнятно.\n", "muted"))
        set_text(self.text, parts)
        self.app.status("Валідацію завершено")

"""Вкладка «Анімація дня»: покадрове відтворення одного змодельованого робочого дня (оператори, черга, лічильники)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

from ..config import DAY_LEN, OPEN_HOUR
from ..engine import simulate_day
from .widgets import spin

SPEEDS = {"×30": 30, "×60": 60, "×120": 120, "×300": 300, "×600": 600, "×1200": 1200}
TICK_MS = 40


def _assign_agents(start: np.ndarray, svc: np.ndarray, acw: np.ndarray) -> np.ndarray:
    """Номер оператора для кожного виклику (найменший вільний у момент початку розмови)."""
    n = len(start)
    agent = np.full(n, -1, dtype=int)
    free_at: list[float] = []
    order = np.argsort(np.where(np.isnan(start), np.inf, start), kind="stable")
    for i in order:
        s = start[i]
        if np.isnan(s):
            continue
        k = next((j for j, f in enumerate(free_at) if f <= s + 1e-9), None)
        if k is None:
            free_at.append(0.0)
            k = len(free_at) - 1
        agent[i] = k
        free_at[k] = s + svc[i] + acw[i]
    return agent


class LiveTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.theme = app, app.theme
        self.tr = None
        self.agent = None
        self.t = 0.0
        self.playing = False
        self.job = None
        self.n_slots = 4

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=16, pady=(10, 4))
        ttk.Label(bar, text="Анімація робочого дня", style="H1.TLabel").pack(side="left")
        self.seed_var = tk.IntVar(value=7)
        self.speed_var = tk.StringVar(value="×300")
        self.play_btn = ttk.Button(bar, text="▶ Відтворити", style="Accent.TButton", command=self.toggle)
        self.play_btn.pack(side="right")
        ttk.Button(bar, text="Згенерувати день", command=self.generate).pack(side="right", padx=8)
        sp = ttk.Combobox(bar, textvariable=self.speed_var, values=list(SPEEDS), state="readonly", width=7)
        sp.pack(side="right")
        ttk.Label(bar, text="Швидкість:").pack(side="right", padx=(12, 4))
        spin(bar, self.seed_var, 0, 99999, 1, width=7).pack(side="right", padx=(4, 0))
        ttk.Label(bar, text="Seed дня:").pack(side="right")

        ttk.Label(self, style="Muted.TLabel", wraplength=1100, justify="left",
                  text="Показано один випадковий день за параметрами вкладки «Модель». Зелені блоки — оператори в розмові (смужка — "
                       "прогрес розмови), сірі — вільні, жовті — постобробка; кружечки праворуч — клієнти в черзі "
                       "(червоні — вже перевищили поріг SLA).").pack(fill="x", padx=16, pady=(0, 4))

        self.canvas = tk.Canvas(self, highlightthickness=1, height=380)
        self.canvas.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self.timeline = tk.Canvas(self, highlightthickness=1, height=96)
        self.timeline.pack(fill="x", padx=16, pady=(0, 4))
        self.scale = ttk.Scale(self, from_=0, to=DAY_LEN, orient="horizontal", command=self._on_scale)
        self.scale.pack(fill="x", padx=16, pady=(0, 10))
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.timeline.bind("<Configure>", lambda e: self.draw())
        self.timeline.bind("<Button-1>", self._click_timeline)
        self.theme.on_change(self.draw)
        self._scale_lock = False
        self.draw()

    # ------------------------------------------------------------ генерація
    def generate(self):
        try:
            cfg = self.app.tabs["model"].get_config(replications=1)
            rng = np.random.default_rng(int(self.seed_var.get()))
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Анімація", str(exc))
            return
        self.pause()
        self.cfg = cfg
        self.tr = simulate_day(cfg, rng)
        tr = self.tr
        self.agent = _assign_agents(tr.start, tr.svc, tr.acw)
        self.n_slots = max(max(cfg.capacity()), int(self.agent.max()) + 1 if self.agent.size else 1)
        # ряд довжини черги для мініграфіка
        grid = np.arange(0, DAY_LEN + 1, 30.0)
        arr, st, lo = tr.arr, tr.start, tr.lost_at
        self.grid = grid
        self.qlen = np.array([int(np.sum((arr <= t) & ~(st <= t) & ~(lo <= t))) for t in grid])
        self.t = 0.0
        self._sync_scale()
        self.draw()
        self.app.status(f"Згенеровано день: {len(arr)} викликів")

    # ------------------------------------------------------------ керування
    def toggle(self):
        if self.tr is None:
            self.generate()
            if self.tr is None:
                return
        if self.playing:
            self.pause()
        else:
            if self.t >= DAY_LEN:
                self.t = 0.0
            self.playing = True
            self.play_btn.configure(text="❚❚ Пауза")
            self._tick()

    def pause(self):
        self.playing = False
        self.play_btn.configure(text="▶ Відтворити")
        if self.job:
            self.after_cancel(self.job)
            self.job = None

    def _tick(self):
        if not self.playing:
            return
        self.t = min(DAY_LEN, self.t + SPEEDS.get(self.speed_var.get(), 300) * TICK_MS / 1000.0)
        self._sync_scale()
        self.draw()
        if self.t >= DAY_LEN:
            self.pause()
            return
        self.job = self.after(TICK_MS, self._tick)

    def _sync_scale(self):
        self._scale_lock = True
        self.scale.set(self.t)
        self._scale_lock = False

    def _on_scale(self, v):
        if self._scale_lock or self.tr is None:
            return
        self.t = float(v)
        self.draw()

    def _click_timeline(self, e):
        if self.tr is None:
            return
        w = max(self.timeline.winfo_width() - 20, 1)
        self.t = float(np.clip((e.x - 10) / w, 0, 1)) * DAY_LEN
        self._sync_scale()
        self.draw()

    # ------------------------------------------------------------ відмальовування
    def draw(self):
        C = self.theme.C
        cv, tl = self.canvas, self.timeline
        cv.configure(bg=C["card"], highlightbackground=C["border"])
        tl.configure(bg=C["card"], highlightbackground=C["border"])
        cv.delete("all")
        tl.delete("all")
        W, H = max(cv.winfo_width(), 400), max(cv.winfo_height(), 200)
        if self.tr is None:
            cv.create_text(W / 2, H / 2, text="Натисніть «Згенерувати день» або «Відтворити»", fill=C["muted"], font=(self.theme.family, 12))
            return
        tr, t, sla = self.tr, self.t, self.cfg.sla_seconds
        arr, st, svc, acw, lo = tr.arr, tr.start, tr.svc, tr.acw, tr.lost_at
        end_call, free = st + svc, st + svc + acw

        arrived = arr <= t
        waiting = arrived & ~(st <= t) & ~(lo <= t)
        talking = (st <= t) & (t < end_call)
        wrap = (end_call <= t) & (t < free)
        served = int(np.sum(end_call <= t))
        lost = int(np.sum(lo <= t))
        started = st <= t
        waits = (st - arr)[started]
        sla_now = float(np.mean(waits <= sla) * 100) if waits.size else 100.0
        wcur = t - arr[waiting]

        # ---- табло
        clock = OPEN_HOUR * 3600 + t
        hh, mm, ss = int(clock // 3600), int(clock % 3600 // 60), int(clock % 60)
        cv.create_text(20, 16, anchor="w", text=f"{hh:02d}:{mm:02d}:{ss:02d}", fill=C["fg"], font=(self.theme.mono, 22, "bold"))
        stats = [("Надійшло", int(arrived.sum()), C["accent"]), ("У черзі", int(waiting.sum()), C["warn"]),
                 ("Розмовляють", int(talking.sum()), C["good"]), ("Обслужено", served, C["info"]),
                 ("Втрачено", lost, C["bad"]), ("SLA (поточний)", f"{sla_now:.0f}%", C["good"] if sla_now >= 90 else C["bad"])]
        x0 = 190
        cw = (W - x0 - 20) / len(stats)
        for i, (lab, val, col) in enumerate(stats):
            x = x0 + i * cw
            cv.create_text(x, 8, anchor="nw", text=lab.upper(), fill=C["muted"], font=(self.theme.family, 8, "bold"))
            cv.create_text(x, 22, anchor="nw", text=str(val), fill=col, font=(self.theme.family, 18, "bold"))

        # ---- оператори
        top = 62
        n = self.n_slots
        cols = 2 if n > 6 else 1
        per = int(np.ceil(n / cols))
        aw = min(300, (W * 0.5 - 40) / cols)
        ah = min(46, (H - top - 20) / per - 6)
        cv.create_text(20, top - 4, anchor="sw", text="ОПЕРАТОРИ", fill=C["muted"], font=(self.theme.family, 8, "bold"))
        cap_now = self.cfg.capacity()[min(int(t // 3600), len(self.cfg.capacity()) - 1)]
        idx_t = np.flatnonzero(talking)
        idx_w = np.flatnonzero(wrap)
        for k in range(n):
            col, row = k // per, k % per
            x, y = 20 + col * (aw + 12), top + row * (ah + 6)
            active = k < cap_now
            fill, txt, prog = C["grid"], "вільний" if active else "поза зміною", None
            for i in idx_t:
                if self.agent[i] == k:
                    fill, txt, prog = C["good"], f"розмова {int(t - st[i]) // 60}:{int(t - st[i]) % 60:02d}", (t - st[i]) / svc[i]
            for i in idx_w:
                if self.agent[i] == k:
                    fill, txt = C["warn"], "постобробка"
            cv.create_rectangle(x, y, x + aw, y + ah, fill=fill, outline=C["border"], stipple="" if active else "gray50")
            cv.create_text(x + 10, y + ah / 2, anchor="w", text=f"Оператор {k + 1}", fill="#FFFFFF" if fill != C["grid"] else C["fg"],
                           font=(self.theme.family, 10, "bold"))
            cv.create_text(x + aw - 10, y + ah / 2 - (5 if prog is not None else 0), anchor="e", text=txt,
                           fill="#FFFFFF" if fill != C["grid"] else C["muted"], font=(self.theme.family, 9))
            if prog is not None:
                cv.create_rectangle(x + 6, y + ah - 8, x + aw - 6, y + ah - 4, fill="#064E3B", outline="")
                cv.create_rectangle(x + 6, y + ah - 8, x + 6 + (aw - 12) * min(prog, 1.0), y + ah - 4, fill="#FFFFFF", outline="")

        # ---- черга
        qx0 = 20 + cols * (aw + 12) + 30
        cv.create_text(qx0, top - 4, anchor="sw", text="ЧЕРГА (перший — ліворуч)", fill=C["muted"], font=(self.theme.family, 8, "bold"))
        cv.create_line(qx0 - 12, top, qx0 - 12, H - 20, fill=C["border"], dash=(3, 3))
        order = np.flatnonzero(waiting)
        order = order[np.argsort(arr[order])]
        r = 9
        per_row = max(1, int((W - qx0 - 20) // (2 * r + 4)))
        for j, i in enumerate(order[:per_row * 8]):
            cx = qx0 + r + (j % per_row) * (2 * r + 4)
            cy = top + r + 4 + (j // per_row) * (2 * r + 4)
            over = (t - arr[i]) > sla
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=C["bad"] if over else C["warn"], outline="")
        if len(order) > per_row * 8:
            cv.create_text(qx0, H - 14, anchor="w", text=f"… ще {len(order) - per_row * 8}", fill=C["muted"])
        if wcur.size:
            cv.create_text(W - 20, H - 12, anchor="e", text=f"найдовше очікування зараз: {wcur.max():.0f} с",
                           fill=C["bad"] if wcur.max() > sla else C["muted"], font=(self.theme.family, 9))

        # ---- мініграфік довжини черги
        tw, th = max(tl.winfo_width(), 400), max(tl.winfo_height(), 60)
        px0, px1, py0, py1 = 10, tw - 10, 8, th - 18
        qmax = max(int(self.qlen.max()), 1)
        pts = []
        for g, q in zip(self.grid, self.qlen):
            pts += [px0 + (px1 - px0) * g / DAY_LEN, py1 - (py1 - py0) * q / qmax]
        tl.create_polygon([px0, py1] + pts + [px1, py1], fill=C["grid"], outline="")
        tl.create_line(pts, fill=C["warn"], width=1.6)
        for h in range(0, 11, 2):
            x = px0 + (px1 - px0) * h / 10
            tl.create_text(x, th - 8, text=f"{OPEN_HOUR + h}:00", fill=C["muted"], font=(self.theme.family, 8),
                           anchor="w" if h == 0 else ("e" if h == 10 else "center"))
        tl.create_text(px0 + 4, py0, anchor="nw", text=f"довжина черги (макс. {qmax})", fill=C["muted"], font=(self.theme.family, 8))
        xc = px0 + (px1 - px0) * t / DAY_LEN
        tl.create_line(xc, py0, xc, py1, fill=C["accent"], width=2)

"""Рушій дискретно-подієвої імітаційної моделі контакт-центру.

Бізнес-процес «обробка звернення клієнта»:

    Надходження виклику ──► Черга (FIFO) ──► Оператор (обслуговування + постобробка) ──► Завершення
                               │                                                          │
                               └── клієнт втратив терпіння ──► Втрачений виклик           └── перевірка SLA

Календар подій (Future Event List):
    • потік надходжень — заздалегідь згенерований нестаціонарний пуассонівський потік;
    • пріоритетна черга heapq — завершення обслуговування, зміна розкладу, втрата терпіння.
На кожному кроці вибирається найближча подія; стан системи (зайняті оператори, довжина
черги) змінюється лише в моменти подій, а тривалості станів накопичуються для розрахунку
середніх (завантаження, середня довжина черги).
"""
from __future__ import annotations

import heapq
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from .config import BIN_SEC, DAY_LEN, N_BINS, N_HOURS

# типи подій у календарі (менше число — вищий пріоритет при однаковому часі)
EV_FREE, EV_CAP, EV_ABANDON, EV_ARRIVAL = 0, 1, 2, 3
# стан виклику
ST_WAIT, ST_SERVED, ST_LOST = 0, 1, 2


class Cancelled(Exception):
    """Користувач перервав виконання."""


@dataclass
class SimConfig:
    rates: Sequence[float] = field(default_factory=lambda: [20.0] * N_HOURS)   # λ(h), викл./год
    load_factor: float = 1.0                    # множник навантаження
    agents: int = 4                             # кількість операторів
    agents_by_hour: Optional[Sequence[int]] = None   # розклад (N_HOURS значень) або None
    service_dist: str = "exp"                   # exp | gamma | lognorm | empirical | const
    service_mean: float = 300.0                 # середня тривалість розмови, с
    service_cv: float = 1.0                     # коефіцієнт варіації (для gamma/lognorm)
    empirical: Optional[np.ndarray] = None      # вибірка для емпіричного розподілу
    acw_mean: float = 0.0                       # середня постобробка (After-Call Work), с
    patience_mean: float = 0.0                  # середнє терпіння клієнта, с (0 = нескінченне)
    first_call_at_open: bool = True             # перший дзвінок рівно о 08:00:00 (як у даних)
    drop_unfinished: bool = True                # не враховувати дзвінки, не завершені до закриття
    sla_seconds: float = 60.0
    days: int = 22                              # робочих днів в одному прогоні
    replications: int = 20                      # кількість незалежних прогонів
    seed: Optional[int] = 42
    keep_calls: bool = True
    label: str = ""

    def capacity(self) -> list[int]:
        if self.agents_by_hour is not None:
            caps = [max(0, int(x)) for x in self.agents_by_hour]
            if len(caps) != N_HOURS:
                raise ValueError("Розклад має містити 10 значень (по одному на годину).")
            return caps
        return [max(0, int(self.agents))] * N_HOURS

    def effective_rates(self) -> np.ndarray:
        return np.maximum(np.asarray(self.rates, dtype=float), 0.0) * float(self.load_factor)

    def describe(self) -> dict:
        r = self.effective_rates()
        return {
            "Операторів": "розклад " + "/".join(map(str, self.capacity())) if self.agents_by_hour is not None else self.agents,
            "Викликів за день (очікувано)": round(float(r.sum()), 1),
            "Розподіл обслуговування": self.service_dist,
            "Середнє обслуговування, с": round(self.service_mean, 1),
            "CV обслуговування": round(self.service_cv, 2),
            "Постобробка, с": self.acw_mean,
            "Терпіння клієнтів, с": self.patience_mean if self.patience_mean > 0 else "∞",
            "Множник навантаження": self.load_factor,
            "SLA, с": self.sla_seconds,
            "Днів у прогоні": self.days,
            "Прогонів": self.replications,
            "Seed": self.seed if self.seed is not None else "випадковий",
        }


# ------------------------------------------------------------------ генератори
def gen_arrivals(cfg: SimConfig, rng: np.random.Generator) -> np.ndarray:
    """Нестаціонарний пуассонівський потік: N_h ~ Poisson(λ_h), моменти — рівномірно в годині."""
    counts = rng.poisson(cfg.effective_rates())
    parts = [h * 3600.0 + rng.random(int(k)) * 3600.0 for h, k in enumerate(counts) if k > 0]
    arr = np.sort(np.concatenate(parts)) if parts else np.empty(0)
    if cfg.first_call_at_open:
        arr = np.concatenate(([0.0], arr))
    return arr


def draw_service(cfg: SimConfig, rng: np.random.Generator, n: int) -> np.ndarray:
    m = max(cfg.service_mean, 1e-6)
    d = cfg.service_dist
    if d == "exp":
        return rng.exponential(m, n)
    if d == "gamma":
        cv = max(cfg.service_cv, 1e-3)
        return rng.gamma(1.0 / cv ** 2, m * cv ** 2, n)
    if d == "lognorm":
        cv = max(cfg.service_cv, 1e-3)
        s2 = math.log(1.0 + cv ** 2)
        return rng.lognormal(math.log(m) - s2 / 2.0, math.sqrt(s2), n)
    if d == "empirical" and cfg.empirical is not None and len(cfg.empirical):
        smp = np.asarray(cfg.empirical, dtype=float)
        return rng.choice(smp, n) * (m / max(smp.mean(), 1e-9))
    if d == "const":
        return np.full(n, m)
    return rng.exponential(m, n)


# ------------------------------------------------------------------ один робочий день
@dataclass
class DayTrace:
    arr: np.ndarray
    svc: np.ndarray
    acw: np.ndarray
    start: np.ndarray        # момент початку розмови (NaN — виклик втрачено)
    lost_at: np.ndarray      # момент втрати (NaN — не втрачено)
    status: np.ndarray
    counted: np.ndarray      # чи входить виклик у статистику
    q_area: np.ndarray       # ∫ довжина_черги dt по інтервалах доби
    busy_area: np.ndarray    # ∫ зайняті_оператори dt
    cap_area: np.ndarray     # ∫ доступні_оператори dt
    max_q: int
    overtime: float          # скільки секунд після закриття ще тривала робота
    caps: list

    @property
    def end_call(self) -> np.ndarray:
        return self.start + self.svc

    @property
    def free_at(self) -> np.ndarray:
        return self.start + self.svc + self.acw

    @property
    def wait_rec(self) -> np.ndarray:
        """Час очікування, зафіксований з точністю до секунди (як у журналі)."""
        return np.floor(self.start) - np.floor(self.arr)


def simulate_day(cfg: SimConfig, rng: np.random.Generator) -> DayTrace:
    caps = cfg.capacity()
    arr = gen_arrivals(cfg, rng)
    n = int(arr.size)
    svc = draw_service(cfg, rng, n)
    acw = rng.exponential(cfg.acw_mean, n) if cfg.acw_mean > 0 else np.zeros(n)
    finite_pat = cfg.patience_mean > 0
    pat = rng.exponential(cfg.patience_mean, n).tolist() if finite_pat else None

    arr_l, svc_l, acw_l = arr.tolist(), svc.tolist(), acw.tolist()
    start_l = [-1.0] * n
    lost_l = [-1.0] * n
    status_l = [ST_WAIT] * n
    q_area = [0.0] * N_BINS
    busy_area = [0.0] * N_BINS
    cap_area = [0.0] * N_BINS

    heap: list = []
    for h in range(1, N_HOURS):
        if caps[h] != caps[h - 1]:
            heap.append((h * 3600.0, EV_CAP, h))
    heapq.heapify(heap)

    cap, busy, qlen, max_q = caps[0], 0, 0, 0
    queue: deque = deque()
    last_t, ai = 0.0, 0
    last_end = 0.0
    push, pop = heapq.heappush, heapq.heappop

    while True:
        if heap:
            if ai < n and arr_l[ai] < heap[0][0]:
                t, kind, idx = arr_l[ai], EV_ARRIVAL, ai
                ai += 1
            else:
                t, kind, idx = pop(heap)
        elif ai < n:
            t, kind, idx = arr_l[ai], EV_ARRIVAL, ai
            ai += 1
        else:
            break

        # накопичення часу в поточному стані (лише в межах робочого дня)
        if t > last_t:
            if last_t < DAY_LEN:
                te = t if t < DAY_LEN else DAY_LEN
                a = last_t
                while a < te:
                    b = int(a // BIN_SEC)
                    if b >= N_BINS:
                        break
                    e = (b + 1) * BIN_SEC
                    if e > te:
                        e = te
                    dt = e - a
                    q_area[b] += qlen * dt
                    busy_area[b] += busy * dt
                    cap_area[b] += cap * dt
                    a = e
            last_t = t

        if kind == EV_ARRIVAL:
            if busy < cap:
                busy += 1
                status_l[idx] = ST_SERVED
                start_l[idx] = t
                push(heap, (t + svc_l[idx] + acw_l[idx], EV_FREE, idx))
                if t + svc_l[idx] > last_end:
                    last_end = t + svc_l[idx]
            else:
                queue.append(idx)
                qlen += 1
                if qlen > max_q:
                    max_q = qlen
                if finite_pat:
                    push(heap, (t + pat[idx], EV_ABANDON, idx))
        elif kind == EV_ABANDON:
            if status_l[idx] == ST_WAIT:
                status_l[idx] = ST_LOST
                lost_l[idx] = t
                qlen -= 1
        else:                                   # EV_FREE або EV_CAP
            if kind == EV_FREE:
                busy -= 1
            else:
                cap = caps[idx]
            while busy < cap and qlen > 0:      # диспетчеризація черги
                j = queue.popleft()
                if status_l[j] != ST_WAIT:
                    continue
                qlen -= 1
                busy += 1
                status_l[j] = ST_SERVED
                start_l[j] = t
                push(heap, (t + svc_l[j] + acw_l[j], EV_FREE, j))
                if t + svc_l[j] > last_end:
                    last_end = t + svc_l[j]

    start = np.asarray(start_l)
    start[start < 0] = np.nan
    lost_at = np.asarray(lost_l)
    lost_at[lost_at < 0] = np.nan
    status = np.asarray(status_l, dtype=np.int8)
    if cfg.drop_unfinished:
        counted = (status == ST_LOST) | ((status == ST_SERVED) & (start + svc <= DAY_LEN))
    else:
        counted = np.ones(n, dtype=bool)
    return DayTrace(arr=arr, svc=svc, acw=acw, start=start, lost_at=lost_at, status=status,
                    counted=counted, q_area=np.asarray(q_area), busy_area=np.asarray(busy_area),
                    cap_area=np.asarray(cap_area), max_q=max_q,
                    overtime=max(0.0, last_end - DAY_LEN), caps=caps)


# ------------------------------------------------------------------ багаторазовий експеримент
@dataclass
class SimResult:
    cfg: SimConfig
    rep: pd.DataFrame                  # KPI за кожним прогоном
    summary: dict                      # KPI → {mean, std, lo, hi}
    hourly: pd.DataFrame               # показники за годинами
    q_bins: np.ndarray                 # (днів × N_BINS) середня довжина черги
    busy_bins: np.ndarray              # (днів × N_BINS) середня кількість зайнятих
    cap_bins: np.ndarray               # (днів × N_BINS) середня кількість доступних
    calls: Optional[pd.DataFrame]
    elapsed: float
    days_total: int

    def mean(self, key: str) -> float:
        return float(self.summary[key]["mean"])


KPI_KEYS = ["offered_day", "served_day", "abandon_pct", "wait_mean", "waited_pct", "sla_pct",
            "wait_p95", "wait_max", "util_pct", "q_mean", "q_max", "overtime_min",
            "wait_min_day", "wait_if_waited"]


def _ci(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=float)
    m = float(np.mean(values))
    if len(values) < 2:
        return dict(mean=m, std=0.0, lo=m, hi=m)
    s = float(np.std(values, ddof=1))
    half = float(stats.t.ppf(0.975, len(values) - 1) * s / math.sqrt(len(values)))
    return dict(mean=m, std=s, lo=m - half, hi=m + half)


def run_simulation(cfg: SimConfig, progress: Optional[Callable[[float, str], None]] = None,
                   should_stop: Optional[Callable[[], bool]] = None) -> SimResult:
    t0 = time.perf_counter()
    seeds = np.random.SeedSequence(cfg.seed).spawn(cfg.replications)
    sla = cfg.sla_seconds
    rep_rows = []
    hour_acc = np.zeros((4, N_HOURS))           # offered, wait_sum, ok, waited
    q_days, busy_days, cap_days = [], [], []
    call_parts = []

    for r, ss in enumerate(seeds):
        if should_stop and should_stop():
            raise Cancelled()
        rng = np.random.default_rng(ss)
        off = srv = lost = 0
        wsum = 0.0
        waited = ok = 0
        wait_if_sum = 0.0
        waits_all = []
        wmax_days, qmax_days, ot_days = [], [], []
        qa = ba = ca = 0.0
        for d in range(cfg.days):
            tr = simulate_day(cfg, rng)
            c = tr.counted
            served = c & (tr.status == ST_SERVED)
            lostc = c & (tr.status == ST_LOST)
            w = tr.wait_rec[served]
            hrs = np.minimum((tr.arr // 3600).astype(int), N_HOURS - 1)
            okm = w <= sla
            off += int(c.sum())
            srv += int(served.sum())
            lost += int(lostc.sum())
            wsum += float(w.sum())
            waited += int((w > 0).sum())
            wait_if_sum += float(w[w > 0].sum())
            ok += int(okm.sum())
            waits_all.append(w)
            wmax_days.append(float(w.max()) if w.size else 0.0)
            qmax_days.append(tr.max_q)
            ot_days.append(tr.overtime / 60.0)
            qa += tr.q_area.sum()
            ba += tr.busy_area.sum()
            ca += tr.cap_area.sum()
            hour_acc[0] += np.bincount(hrs[c], minlength=N_HOURS)[:N_HOURS]
            hour_acc[1] += np.bincount(hrs[served], weights=w, minlength=N_HOURS)[:N_HOURS]
            hour_acc[2] += np.bincount(hrs[served][okm], minlength=N_HOURS)[:N_HOURS]
            hour_acc[3] += np.bincount(hrs[served][w > 0], minlength=N_HOURS)[:N_HOURS]
            q_days.append(tr.q_area / BIN_SEC)
            busy_days.append(tr.busy_area / BIN_SEC)
            cap_days.append(tr.cap_area / BIN_SEC)
            if cfg.keep_calls:
                sel = c
                wait_full = np.where(tr.status == ST_SERVED, tr.wait_rec, tr.lost_at - tr.arr)
                call_parts.append(pd.DataFrame({
                    "rep": np.int16(r), "day": np.int16(d),
                    "arrival": tr.arr[sel].astype(np.float32),
                    "wait": wait_full[sel].astype(np.float32),
                    "service": tr.svc[sel].astype(np.float32),
                    "status": tr.status[sel]}))
        w_cat = np.concatenate(waits_all) if waits_all else np.empty(0)
        nd = cfg.days
        rep_rows.append(dict(
            rep=r + 1,
            offered_day=off / nd, served_day=srv / nd,
            abandon_pct=100.0 * lost / max(off, 1),
            wait_mean=wsum / max(srv, 1),
            waited_pct=100.0 * waited / max(off, 1),
            sla_pct=100.0 * ok / max(off, 1),
            wait_p95=float(np.percentile(w_cat, 95)) if w_cat.size else 0.0,
            wait_max=float(np.mean(wmax_days)),
            util_pct=100.0 * ba / ca if ca > 0 else 0.0,
            q_mean=qa / (nd * DAY_LEN),
            q_max=float(np.mean(qmax_days)),
            overtime_min=float(np.mean(ot_days)),
            wait_min_day=wsum / 60.0 / nd,
            wait_if_waited=wait_if_sum / max(waited, 1),
        ))
        if progress:
            progress((r + 1) / cfg.replications, f"Прогін {r + 1} із {cfg.replications}")

    rep = pd.DataFrame(rep_rows)
    summary = {k: _ci(rep[k].to_numpy()) for k in KPI_KEYS}
    hourly = pd.DataFrame({
        "hour": np.arange(N_HOURS),
        "calls_day": hour_acc[0] / (cfg.days * cfg.replications),
        "wait_mean": hour_acc[1] / np.maximum(hour_acc[0], 1),
        "sla_pct": 100.0 * hour_acc[2] / np.maximum(hour_acc[0], 1),
        "waited_pct": 100.0 * hour_acc[3] / np.maximum(hour_acc[0], 1),
    })
    calls = pd.concat(call_parts, ignore_index=True) if call_parts else None
    return SimResult(cfg=cfg, rep=rep, summary=summary, hourly=hourly,
                     q_bins=np.vstack(q_days), busy_bins=np.vstack(busy_days),
                     cap_bins=np.vstack(cap_days), calls=calls,
                     elapsed=time.perf_counter() - t0, days_total=cfg.days * cfg.replications)

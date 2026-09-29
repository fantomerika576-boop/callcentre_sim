"""Аналітична модель масового обслуговування M/M/c (формули Ерланга C).

Використовується для:
  • швидкої попередньої оцінки параметрів системи;
  • верифікації імітаційної моделі (порівняння «симуляція ↔ теорія»);
  • підбору мінімальної кількості операторів для заданого SLA.

Позначення: λ — інтенсивність потоку [викл/с], μ = 1/E[S], a = λ/μ — навантаження [Ерланг],
c — кількість операторів, ρ = a/c — коефіцієнт завантаження, T — поріг SLA [с].
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd

from .config import HOUR_LABELS, N_HOURS


def erlang_c(c: int, a: float) -> float:
    """Ймовірність очікування (формула Ерланга C) через стійку рекурсію Ерланга B."""
    if c <= 0:
        return 1.0
    if a <= 0:
        return 0.0
    if a >= c:
        return 1.0
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    return b / (1.0 - (a / c) * (1.0 - b))


def mmc(lam_per_hour: float, mean_service: float, c: int, sla: float = 60.0) -> dict:
    """Стаціонарні показники M/M/c."""
    lam = lam_per_hour / 3600.0
    a = lam * mean_service
    if lam <= 0:
        return dict(a=0.0, rho=0.0, p_wait=0.0, wq=0.0, wq_wait=0.0, sla=1.0, lq=0.0,
                    p95=0.0, stable=True)
    if c <= 0 or a >= c:
        return dict(a=a, rho=a / max(c, 1), p_wait=1.0, wq=math.inf, wq_wait=math.inf,
                    sla=0.0, lq=math.inf, p95=math.inf, stable=False)
    mu = 1.0 / mean_service
    C = erlang_c(c, a)
    d = c * mu - lam
    p95 = max(0.0, math.log(C / 0.05) / d) if C > 0.05 else 0.0
    return dict(a=a, rho=a / c, p_wait=C, wq=C / d, wq_wait=1.0 / d,
                sla=1.0 - C * math.exp(-d * sla), lq=lam * C / d, p95=p95, stable=True)


def _as_list(agents: int | Sequence[int]) -> list[int]:
    if isinstance(agents, (int, np.integer)):
        return [int(agents)] * N_HOURS
    return [int(x) for x in agents]


def profile_metrics(rates: Sequence[float], mean_service: float, agents: int | Sequence[int],
                    sla: float = 60.0) -> tuple[dict, pd.DataFrame]:
    """Погодинне наближення (квазістаціонарне) для нестаціонарного потоку.

    Повертає (зведені показники за день, таблиця за годинами).
    """
    caps = _as_list(agents)
    rows = []
    for h in range(N_HOURS):
        m = mmc(float(rates[h]), mean_service, caps[h], sla)
        rows.append(dict(hour=h, label=HOUR_LABELS[h], lam=float(rates[h]), agents=caps[h], **m))
    tab = pd.DataFrame(rows)
    lam = tab["lam"].to_numpy()
    tot = lam.sum()
    if tot <= 0:
        return dict(rho=0, p_wait=0, wq=0, sla=1, lq=0, calls_day=0), tab

    def wavg(col):
        v = tab[col].to_numpy(dtype=float)
        return float(np.sum(lam * v) / tot)

    overall = dict(
        rho=float(tab["a"].sum() / max(1, tab["agents"].sum())),
        p_wait=wavg("p_wait"), wq=wavg("wq"), sla=wavg("sla"),
        lq=float(tab["lq"].replace(np.inf, np.nan).mean()), calls_day=float(tot),
        stable=bool(tab["stable"].all()),
    )
    return overall, tab


def wait_cdf(t: np.ndarray, rates: Sequence[float], mean_service: float,
             agents: int | Sequence[int]) -> np.ndarray:
    """Теоретична функція розподілу часу очікування P(W ≤ t) для змішаного за годинами потоку."""
    caps = _as_list(agents)
    t = np.asarray(t, dtype=float)
    lam_tot = float(np.sum(rates))
    out = np.zeros_like(t)
    if lam_tot <= 0:
        return out + 1.0
    for h in range(N_HOURS):
        lam = rates[h] / 3600.0
        a = lam * mean_service
        w = rates[h] / lam_tot
        c = caps[h]
        if a >= c:
            continue
        C = erlang_c(c, a)
        d = c / mean_service - lam
        out += w * (1.0 - C * np.exp(-d * t))
    return out


def min_agents(lam_per_hour: float, mean_service: float, target: float, sla: float = 60.0,
               max_c: int = 80) -> int:
    """Мінімальна кількість операторів, за якої частка викликів із очікуванням ≤ sla ≥ target."""
    a = lam_per_hour / 3600.0 * mean_service
    c = max(1, int(math.floor(a)) + 1)
    while c < max_c:
        if mmc(lam_per_hour, mean_service, c, sla)["sla"] >= target:
            return c
        c += 1
    return max_c


def optimal_schedule(rates: Sequence[float], mean_service: float, target: float,
                     sla: float = 60.0, min_c: int = 1) -> list[int]:
    """Розклад: мінімальне число операторів у кожну годину для досягнення цільового SLA."""
    return [max(min_c, min_agents(float(r), mean_service, target, sla)) for r in rates]

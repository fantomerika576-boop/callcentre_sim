"""Експерименти над моделлю: валідація, підбір штату, стрес-тест, прогноз, розклад."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Optional

import numpy as np
import pandas as pd
from scipy import stats

from .config import DAY_LEN, MONTHS_UA, N_HOURS
from .data import CallData
from .engine import Cancelled, SimConfig, SimResult, run_simulation
from .queueing import min_agents, mmc, optimal_schedule, profile_metrics

Progress = Optional[Callable[[float, str], None]]
Stop = Optional[Callable[[], bool]]

HOURS_PER_DAY = DAY_LEN / 3600.0


def config_from_data(data: CallData, month: Optional[int], **kw) -> SimConfig:
    """Конфігурація моделі, відкалібрована за даними (потік, обслуговування, штат)."""
    base = dict(rates=data.hourly_rates(month), agents=data.n_agents,
                service_mean=data.service_mean, service_cv=data.service_cv,
                sla_seconds=data.sla_seconds, first_call_at_open=data.first_call_at_open,
                empirical=data.service_sample(), days=data.days_in(month) or 22)
    base.update(kw)
    return SimConfig(**base)


# ------------------------------------------------------------------ валідація
@dataclass
class ValidationResult:
    table: pd.DataFrame
    ks: dict
    mape: dict
    coverage: dict
    reps: int


def validate_model(data: CallData, base: SimConfig, reps: int = 15,
                   progress: Progress = None, should_stop: Stop = None) -> ValidationResult:
    """Порівняння: факт (журнал) ↔ імітація ↔ аналітична модель, по кожному місяцю."""
    rows = []
    sim_waits, sim_services = [], []
    months = data.months_present()
    for i, m in enumerate(months):
        if should_stop and should_stop():
            raise Cancelled()
        cfg = replace(base, rates=data.hourly_rates(m), days=data.days_in(m), replications=reps,
                      load_factor=1.0, agents_by_hour=None, keep_calls=True,
                      seed=None if base.seed is None else base.seed + m)
        res = run_simulation(cfg)
        k = data.kpis(m)
        erl, _ = profile_metrics(cfg.effective_rates(), cfg.service_mean + cfg.acw_mean,
                                 cfg.agents, cfg.sla_seconds)
        s = res.summary
        row = dict(month=m, name=MONTHS_UA[m - 1])
        pairs = [("calls_day", k["calls_per_day"], "offered_day", None),
                 ("wait", k["wait_mean"], "wait_mean", erl["wq"]),
                 ("waited", k["waited_share"] * 100, "waited_pct", erl["p_wait"] * 100),
                 ("sla", k["sla"] * 100, "sla_pct", erl["sla"] * 100),
                 ("util", k["util"] * 100, "util_pct", erl["rho"] * 100)]
        for key, act, skey, ev in pairs:
            row[f"{key}_act"] = act
            row[f"{key}_sim"] = s[skey]["mean"]
            row[f"{key}_lo"] = s[skey]["mean"] - 1.96 * s[skey]["std"]      # прогнозний інтервал
            row[f"{key}_hi"] = s[skey]["mean"] + 1.96 * s[skey]["std"]
            row[f"{key}_ci_lo"], row[f"{key}_ci_hi"] = s[skey]["lo"], s[skey]["hi"]
            row[f"{key}_erl"] = ev if ev is not None else np.nan
            row[f"{key}_ok"] = bool(row[f"{key}_lo"] <= act <= row[f"{key}_hi"])
        rows.append(row)
        c = res.calls
        sim_waits.append(c.loc[c["status"] == 1, "wait"].to_numpy()[:6000])
        sim_services.append(c["service"].to_numpy()[:6000])
        if progress:
            progress((i + 1) / len(months), f"Валідація: {MONTHS_UA[m - 1]}")
    tab = pd.DataFrame(rows)

    sw, ss = np.concatenate(sim_waits), np.concatenate(sim_services)
    aw = data.df["wait_length"].to_numpy(dtype=float)
    asv = data.df["service_length"].to_numpy(dtype=float)
    ks_w = stats.ks_2samp(sw, aw)
    ks_s = stats.ks_2samp(ss, asv)
    ks = dict(wait=(float(ks_w.statistic), float(ks_w.pvalue)),
              service=(float(ks_s.statistic), float(ks_s.pvalue)))
    mape, cover = {}, {}
    for key in ["calls_day", "wait", "waited", "sla", "util"]:
        act, sim = tab[f"{key}_act"].to_numpy(), tab[f"{key}_sim"].to_numpy()
        mape[key] = float(np.mean(np.abs(sim - act) / np.maximum(np.abs(act), 1e-9)) * 100)
        cover[key] = int(tab[f"{key}_ok"].sum())
    return ValidationResult(table=tab, ks=ks, mape=mape, coverage=cover, reps=reps)


# ------------------------------------------------------------------ підбір кількості операторів
def sweep_agents(cfg: SimConfig, values: list[int], cost_agent_hour: float, cost_wait_min: float,
                 cost_lost_call: float, sla_target: float, reps: int,
                 progress: Progress = None, should_stop: Stop = None) -> pd.DataFrame:
    rows = []
    for i, c in enumerate(values):
        if should_stop and should_stop():
            raise Cancelled()
        cc = replace(cfg, agents=c, agents_by_hour=None, replications=reps, keep_calls=False)
        res = run_simulation(cc)
        s = res.summary
        erl, _ = profile_metrics(cc.effective_rates(), cc.service_mean + cc.acw_mean, c, cc.sla_seconds)
        cost_ag = c * HOURS_PER_DAY * cost_agent_hour
        cost_w = s["wait_min_day"]["mean"] * cost_wait_min
        cost_l = s["abandon_pct"]["mean"] / 100 * s["offered_day"]["mean"] * cost_lost_call
        rows.append(dict(
            agents=c, util=s["util_pct"]["mean"], wait=s["wait_mean"]["mean"],
            waited=s["waited_pct"]["mean"], sla=s["sla_pct"]["mean"],
            sla_lo=s["sla_pct"]["lo"], sla_hi=s["sla_pct"]["hi"],
            sla_erl=erl["sla"] * 100 if erl["stable"] else 0.0,
            p95=s["wait_p95"]["mean"], qmax=s["q_max"]["mean"], lost=s["abandon_pct"]["mean"],
            cost_agents=cost_ag, cost_wait=cost_w, cost_lost=cost_l,
            cost_total=cost_ag + cost_w + cost_l,
            meets=s["sla_pct"]["mean"] >= sla_target))
        if progress:
            progress((i + 1) / len(values), f"Операторів: {c}")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ стрес-тест
def stress_grid(cfg: SimConfig, agent_values: list[int], load_values: list[float], reps: int,
                progress: Progress = None, should_stop: Stop = None) -> dict:
    shape = (len(agent_values), len(load_values))
    sla, wait, util, p95 = (np.zeros(shape) for _ in range(4))
    total = shape[0] * shape[1]
    k = 0
    for i, c in enumerate(agent_values):
        for j, lf in enumerate(load_values):
            if should_stop and should_stop():
                raise Cancelled()
            cc = replace(cfg, agents=c, agents_by_hour=None, load_factor=lf,
                         replications=reps, keep_calls=False)
            s = run_simulation(cc).summary
            sla[i, j], wait[i, j] = s["sla_pct"]["mean"], s["wait_mean"]["mean"]
            util[i, j], p95[i, j] = s["util_pct"]["mean"], s["wait_p95"]["mean"]
            k += 1
            if progress:
                progress(k / total, f"Клітинка {k} із {total}")
    return dict(agents=agent_values, loads=load_values, sla=sla, wait=wait, util=util, p95=p95)


# ------------------------------------------------------------------ прогноз
@dataclass
class Forecast:
    table: pd.DataFrame
    hist_x: np.ndarray
    hist_y: np.ndarray
    slope: float
    intercept: float
    r2: float
    saturation_month: Optional[int]
    n_current: int
    target: float


def forecast_load(data: CallData, months_ahead: int, agents: int, sla_target: float,
                  service_mean: Optional[float] = None, sla_seconds: float = 60.0) -> Forecast:
    """Лінійний тренд інтенсивності + аналітична оцінка потрібного штату (Erlang C)."""
    mon = data.monthly_table()
    x, y = mon["month"].to_numpy(dtype=float), mon["calls_day"].to_numpy(dtype=float)
    lr = stats.linregress(x, y)
    n = len(x)
    resid = y - (lr.intercept + lr.slope * x)
    s = math.sqrt(float(np.sum(resid ** 2)) / max(n - 2, 1))
    sxx = float(np.sum((x - x.mean()) ** 2))
    tcrit = stats.t.ppf(0.975, max(n - 2, 1))
    svc = service_mean or data.service_mean
    last_month = int(x.max())
    shape = data.hourly_rates(last_month)
    shape = shape / shape.sum()
    rows = []
    sat = None
    for k in range(1, months_ahead + 1):
        x0 = last_month + k
        pred = lr.intercept + lr.slope * x0
        half = tcrit * s * math.sqrt(1 + 1 / n + (x0 - x.mean()) ** 2 / sxx)
        rates = shape * pred
        overall, _ = profile_metrics(rates, svc, agents, sla_seconds)
        need = max(min_agents(float(r), svc, sla_target, sla_seconds) for r in rates)
        label_m = (x0 - 1) % 12 + 1
        year = 2021 + (x0 - 1) // 12
        rows.append(dict(k=k, x=x0, label=f"{MONTHS_UA[label_m - 1][:3]} {year}", calls_day=pred,
                         lo=pred - half, hi=pred + half,
                         sla_now=(overall["sla"] * 100 if overall["stable"] else 0.0),
                         rho=overall["rho"] * 100, need=need))
        if sat is None and overall["sla"] < sla_target:
            sat = x0
    return Forecast(table=pd.DataFrame(rows), hist_x=x, hist_y=y, slope=float(lr.slope),
                    intercept=float(lr.intercept), r2=float(lr.rvalue ** 2),
                    saturation_month=sat, n_current=agents, target=sla_target)


# ------------------------------------------------------------------ розклад по годинах
def schedule_plan(cfg: SimConfig, target: float) -> pd.DataFrame:
    """Мінімальна кількість операторів у кожну годину для досягнення цільового SLA."""
    rates = cfg.effective_rates()
    svc = cfg.service_mean + cfg.acw_mean
    need = optimal_schedule(rates, svc, target, cfg.sla_seconds)
    _, tab_plan = profile_metrics(rates, svc, need, cfg.sla_seconds)
    _, tab_flat = profile_metrics(rates, svc, cfg.agents, cfg.sla_seconds)
    out = pd.DataFrame({"hour": np.arange(N_HOURS), "label": tab_plan["label"], "lam": rates,
                        "need": need, "sla_plan": tab_plan["sla"] * 100,
                        "rho_plan": tab_plan["rho"] * 100,
                        "flat": cfg.agents, "sla_flat": tab_flat["sla"] * 100,
                        "rho_flat": tab_flat["rho"] * 100})
    return out

"""Побудова графіків (matplotlib). Кожна функція приймає (fig, C, …) та малює у поточній темі."""
from __future__ import annotations

import numpy as np
from matplotlib.patches import FancyBboxPatch, Rectangle
from scipy import stats

from ..config import HOUR_LABELS, MONTHS_UA_SHORT, N_HOURS, OPEN_HOUR
from ..queueing import wait_cdf


# ------------------------------------------------------------------ допоміжні
def style_ax(ax, C, title=None, xlabel=None, ylabel=None, grid="y"):
    ax.set_facecolor(C["card"])
    for name, sp in ax.spines.items():
        sp.set_color(C["border"])
        if name in ("top", "right"):
            sp.set_visible(False)
    ax.tick_params(colors=C["muted"], labelsize=8, length=3)
    if title:
        ax.set_title(title, color=C["fg"], fontsize=9.5, fontweight="bold", loc="left")
    if xlabel:
        ax.set_xlabel(xlabel, color=C["muted"], fontsize=8.5)
    if ylabel:
        ax.set_ylabel(ylabel, color=C["muted"], fontsize=8.5)
    if grid:
        ax.grid(True, axis=grid, color=C["grid"], linewidth=0.8)
        ax.set_axisbelow(True)


def legend(ax, C, loc="best", **kw):
    leg = ax.legend(frameon=False, fontsize=7.5, loc=loc, **kw)
    if leg:
        for t in leg.get_texts():
            t.set_color(C["fg"])
    return leg


def _twin(ax, C, ylabel=None, color=None):
    ax2 = ax.twinx()
    ax2.set_facecolor("none")
    for name, sp in ax2.spines.items():
        sp.set_color(C["border"])
        if name != "right":
            sp.set_visible(False)
    ax2.tick_params(colors=color or C["muted"], labelsize=8, length=3)
    if ylabel:
        ax2.set_ylabel(ylabel, color=color or C["muted"], fontsize=8.5)
    return ax2


def _clock_ticks(ax):
    ax.set_xlim(OPEN_HOUR, OPEN_HOUR + N_HOURS)
    ax.set_xticks(range(OPEN_HOUR, OPEN_HOUR + N_HOURS + 1, 1))
    ax.set_xticklabels([f"{h}:00" for h in range(OPEN_HOUR, OPEN_HOUR + N_HOURS + 1)])


def _heat(ax, C, mat, cmap, vmin=None, vmax=None, fmt="{:.0f}", xt=None, yt=None, fs=7):
    im = ax.imshow(mat, aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xticks(range(mat.shape[1]))
    ax.set_yticks(range(mat.shape[0]))
    if xt is not None:
        ax.set_xticklabels(xt)
    if yt is not None:
        ax.set_yticklabels(yt)
    ax.tick_params(colors=C["muted"], labelsize=8, length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    lo = np.nanmin(mat) if vmin is None else vmin
    hi = np.nanmax(mat) if vmax is None else vmax
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat[i, j]
            if np.isnan(v):
                continue
            frac = (v - lo) / (hi - lo + 1e-12)
            ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=fs,
                    color="#FFFFFF" if (frac > 0.62 or frac < 0.12) and cmap in ("YlGnBu", "Blues", "viridis") else "#111827")
    return im


# ------------------------------------------------------------------ 1. Аналіз історичних даних
def plot_analysis(fig, C, data, an):
    axs = fig.subplots(3, 2)
    ax = axs[0, 0]
    x = np.arange(N_HOURS)
    ax.bar(x, an.hourly, color=C["accent"], width=0.7)
    ax.axhline(an.hourly.mean(), color=C["warn"], ls="--", lw=1.2, label=f"середнє {an.hourly.mean():.1f}")
    ax.set_xticks(x)
    ax.set_xticklabels([str(OPEN_HOUR + h) for h in x])
    style_ax(ax, C, "Навантаження за годинами доби", "година початку", "викликів / день")
    legend(ax, C, "lower right")

    ax = axs[0, 1]
    mon = an.monthly
    ax.bar(mon["month"], mon["calls_day"], color=C["info"], width=0.7)
    slope, icp, r2 = an.trend
    xs = np.array([mon["month"].min(), mon["month"].max()])
    ax.plot(xs, icp + slope * xs, color=C["bad"], lw=2, label=f"тренд {slope:+.1f}/міс (R²={r2:.2f})")
    ax.set_xticks(mon["month"])
    ax.set_xticklabels([MONTHS_UA_SHORT[m - 1] for m in mon["month"]], fontsize=7)
    style_ax(ax, C, "Зростання навантаження протягом року", None, "викликів / день")
    legend(ax, C, "upper left")

    ax = axs[1, 0]
    svc = data.df["service_length"].to_numpy(dtype=float)
    grid = np.linspace(0, 2000, 300)
    ax.hist(svc, bins=np.arange(0, 2050, 50), density=True, color=C["accent"], alpha=0.55,
            label="дані")
    ax.plot(grid, stats.expon.pdf(grid, scale=svc.mean()), color=C["bad"], lw=2,
            label=f"Exp (1/μ={svc.mean():.0f} с)")
    ln = an.fits[an.fits["name"] == "Логнормальний"]
    if len(ln):
        ax.plot(grid, stats.lognorm.pdf(grid, *ln.iloc[0]["params"]), color=C["warn"], lw=1.6, ls="--",
                label="логнормальний")
    ax.set_xlim(0, 2000)
    style_ax(ax, C, "Тривалість обслуговування", "с", "щільність")
    legend(ax, C, "upper right")

    ax = axs[1, 1]
    ia = an.interarrival
    grid = np.linspace(0, 900, 300)
    ax.hist(ia, bins=np.arange(0, 920, 20), density=True, color=C["violet"], alpha=0.55, label="дані")
    ax.plot(grid, stats.expon.pdf(grid, scale=ia.mean()), color=C["bad"], lw=2,
            label=f"Exp (CV={an.ia_cv:.2f})")
    ax.set_xlim(0, 900)
    style_ax(ax, C, "Інтервали між викликами", "с", "щільність")
    legend(ax, C, "upper right")

    ax = axs[2, 0]
    cols = [C["good"] if v >= 0.90 else (C["warn"] if v >= 0.85 else C["bad"]) for v in mon["sla"]]
    ax.bar(mon["month"], mon["sla"] * 100, color=cols, width=0.7)
    ax.axhline(90, color=C["muted"], ls=":", lw=1.2)
    ax.set_ylim(70, 100)
    ax.set_xticks(mon["month"])
    ax.set_xticklabels([MONTHS_UA_SHORT[m - 1] for m in mon["month"]], fontsize=7)
    style_ax(ax, C, "SLA та середнє очікування за місяцями", None, "SLA, %")
    ax2 = _twin(ax, C, "очікування, с", C["violet"])
    ax2.plot(mon["month"], mon["wait_mean"], color=C["violet"], marker="o", ms=4, lw=2)

    ax = axs[2, 1]
    im = _heat(ax, C, an.heat, "YlGnBu", fmt="{:.0f}", xt=MONTHS_UA_SHORT, yt=[str(OPEN_HOUR + h) for h in range(N_HOURS)], fs=6.5)
    ax.set_title("Теплокарта: година × місяць (викл./день)", color=C["fg"], fontsize=9.5,
                 fontweight="bold", loc="left")
    ax.set_facecolor(C["card"])


# ------------------------------------------------------------------ 2. Схема бізнес-процесу
def plot_process(fig, C, info: dict):
    ax = fig.add_axes([0.005, 0.02, 0.99, 0.96])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 40)
    ax.axis("off")
    ax.set_facecolor(C["card"])
    y0, h, w = 15.5, 13, 17

    def node(xc, y, title, lines, color, dashed=False, fill=None, ww=w, hh=h):
        p = FancyBboxPatch((xc - ww / 2, y), ww, hh, boxstyle="round,pad=0.3,rounding_size=1.6",
                           fc=fill or C["canvas"], ec=color, lw=1.8, ls="--" if dashed else "-")
        ax.add_patch(p)
        ax.text(xc, y + hh - 3.0, title, ha="center", va="center", fontsize=9, fontweight="bold", color=C["fg"])
        for i, ln in enumerate(lines):
            ax.text(xc, y + hh - 6.6 - i * 2.9, ln, ha="center", va="center", fontsize=7.8, color=C["muted"])

    def arrow(x1, y1, x2, y2, color=None, rad=0.0, ls="-"):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=color or C["muted"], lw=1.6, ls=ls,
                                    connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0))

    xs = [9.5, 29.5, 50.5, 71.5, 91]
    node(xs[0], y0, "1. Надходження", [f"λ ≈ {info['lam']:.1f} викл/год", f"{info['calls_day']:.0f} викл/день", "пуассонівський потік"], C["accent"])
    node(xs[1], y0, "2. Черга", ["дисципліна FIFO", f"терпіння: {info['patience']}", "очікування клієнта"], C["warn"])
    node(xs[2], y0, f"3. Оператори (N = {info['agents']})", [f"E[S] = {info['svc']:.0f} с", info["dist"], "обслуговування"], C["good"], ww=19)
    node(xs[3], y0, "4. Постобробка", [f"ACW = {info['acw']:.0f} с", "оператор недоступний", "після розмови"], C["violet"])
    node(xs[4], y0, "5. Контроль SLA", [f"очікування ≤ {info['sla']:.0f} с", "фіксація KPI", "звернення закрито"], C["info"], ww=w)
    for a, b, wa, wb in [(0, 1, w, w), (1, 2, w, 19), (2, 3, 19, w), (3, 4, w, w)]:
        arrow(xs[a] + wa / 2 + 0.6, y0 + h / 2, xs[b] - wb / 2 - 0.6, y0 + h / 2)
    arrow(xs[0], y0 + h + 0.6, xs[2] - 3, y0 + h + 0.6, C["good"], rad=-0.28)
    ax.text((xs[0] + xs[2]) / 2 - 1, 38.2, "є вільний оператор — обслуговування без черги", ha="center",
            fontsize=7.8, color=C["good"], style="italic")
    lost_on = info["patience"] != "∞"
    node(xs[1], 1.2, "Втрачений виклик", ["клієнт поклав слухавку"], C["bad"] if lost_on else C["border"],
         dashed=True, ww=w + 3, hh=8.2)
    arrow(xs[1], y0 - 0.6, xs[1], 9.9, C["bad"] if lost_on else C["border"], ls="--")
    ax.text(xs[1] + 1.5, 12.7, "втрата терпіння", fontsize=7.3, color=C["bad"] if lost_on else C["muted"])
    ax.text(46, 5.2, "Час у системі = очікування + обслуговування + постобробка", ha="left", fontsize=8,
            color=C["muted"], style="italic")
    ax.text(46, 2.3, "Показники: SLA %, середнє очікування, завантаження, довжина черги, втрати",
            ha="left", fontsize=8, color=C["muted"], style="italic")


# ------------------------------------------------------------------ 3. Результати симуляції
def plot_results(fig, C, res, ref=None, erlang=None):
    """res — SimResult; ref — {'wait': array, 'label': str} (факт); erlang — (rates, svc, agents)."""
    cfg = res.cfg
    axs = fig.subplots(2, 3)
    calls = res.calls
    sla = cfg.sla_seconds

    served = calls[calls["status"] == 1]["wait"].to_numpy(dtype=float) if calls is not None else np.empty(0)
    tmax = float(np.percentile(served, 99.5)) if served.size else 300.0
    tmax = max(240.0, min(tmax, 900.0))

    ax = axs[0, 0]
    if served.size:
        wp = served[served > 0]
        bins = np.linspace(0, tmax, 31)
        wt = np.full(wp.size, 100.0 / served.size)
        ax.hist(wp, bins=bins, weights=wt, color=C["accent"], alpha=0.75, label="модель")
        if ref is not None:
            rw = np.asarray(ref["wait"], dtype=float)
            rp = rw[rw > 0]
            ax.hist(rp, bins=bins, weights=np.full(rp.size, 100.0 / rw.size), histtype="step",
                    color=C["bad"], lw=1.8, label=ref["label"])
        ax.axvline(sla, color=C["muted"], ls="--", lw=1.2)
        ax.text(sla, ax.get_ylim()[1] * 0.92, f" SLA {sla:.0f} с", color=C["muted"], fontsize=7.5)
        legend(ax, C, "upper right")
    style_ax(ax, C, "Розподіл часу очікування (лише хто чекав)", "очікування, с", "% усіх викликів")

    ax = axs[0, 1]
    if served.size:
        t = np.linspace(0, tmax, 400)
        ws = np.sort(served)
        ax.plot(t, np.searchsorted(ws, t, "right") / ws.size * 100, color=C["accent"], lw=2.2, label="модель")
        if ref is not None:
            rs = np.sort(np.asarray(ref["wait"], dtype=float))
            ax.plot(t, np.searchsorted(rs, t, "right") / rs.size * 100, color=C["bad"], lw=1.6, ls="--",
                    label=ref["label"])
        if erlang is not None:
            rates, svc, agents = erlang
            ax.plot(t, wait_cdf(t, rates, svc, agents) * 100, color=C["good"], lw=1.4, ls=":", label="Erlang C")
        ax.axvline(sla, color=C["muted"], ls="--", lw=1.2)
        ax.set_ylim(min(100, max(0, np.searchsorted(ws, 0, "right") / ws.size * 100 - 8)), 100.5)
        legend(ax, C, "lower right")
    style_ax(ax, C, "Емпірична функція розподілу P(W ≤ t)", "t, с", "%", grid="both")

    ax = axs[0, 2]
    x = OPEN_HOUR + (np.arange(res.q_bins.shape[1]) + 0.5) * 900 / 3600
    qm = res.q_bins.mean(axis=0)
    ax.fill_between(x, np.percentile(res.q_bins, 10, axis=0), np.percentile(res.q_bins, 90, axis=0),
                    color=C["warn"], alpha=0.25, label="10–90 перцентиль")
    ax.plot(x, qm, color=C["warn"], lw=2.2, label="середня")
    _clock_ticks(ax)
    ax.set_ylim(bottom=0)
    style_ax(ax, C, "Довжина черги протягом доби", "година", "клієнтів у черзі")
    ax.tick_params(axis="x", labelsize=7)
    legend(ax, C, "upper left")

    ax = axs[1, 0]
    busy, cap = res.busy_bins.mean(axis=0), res.cap_bins.mean(axis=0)
    ax.fill_between(x, 0, busy, color=C["good"], alpha=0.35)
    ax.plot(x, busy, color=C["good"], lw=2, label="зайнято (середнє)")
    ax.step(x, cap, where="mid", color=C["muted"], ls="--", lw=1.4, label="доступно")
    _clock_ticks(ax)
    ax.set_ylim(0, max(cap.max(), busy.max()) * 1.2 + 0.5)
    style_ax(ax, C, "Завантаження операторів протягом доби", "година", "оператори")
    ax.tick_params(axis="x", labelsize=7)
    legend(ax, C, "lower right")

    ax = axs[1, 1]
    rep = res.rep
    ax.plot(rep["rep"], rep["sla_pct"], color=C["accent"], marker="o", ms=4, lw=1.4, label="SLA за прогонами")
    s = res.summary["sla_pct"]
    ax.axhline(s["mean"], color=C["bad"], lw=1.6, label=f"середнє {s['mean']:.1f}%")
    ax.axhspan(s["lo"], s["hi"], color=C["bad"], alpha=0.15, label="95% ЦІ середнього")
    style_ax(ax, C, "Стабільність SLA між прогонами", "номер прогону", "SLA, %", grid="both")
    legend(ax, C, "best")

    ax = axs[1, 2]
    hr = res.hourly
    ax.bar(hr["hour"], hr["wait_mean"], color=C["violet"], alpha=0.85, width=0.7)
    ax.set_xticks(range(N_HOURS))
    ax.set_xticklabels([str(OPEN_HOUR + h) for h in range(N_HOURS)])
    style_ax(ax, C, "Очікування та SLA за годинами", "година початку", "сер. очікування, с")
    ax2 = _twin(ax, C, "SLA, %", C["good"])
    ax2.plot(hr["hour"], hr["sla_pct"], color=C["good"], marker="o", ms=4, lw=2)
    lo = max(0, min(hr["sla_pct"].min() - 5, 90))
    ax2.set_ylim(lo, 100.5)


# ------------------------------------------------------------------ 4. Валідація
def plot_validation(fig, C, v):
    t = v.table
    x = t["month"].to_numpy()
    axs = fig.subplots(2, 2)
    xt = [MONTHS_UA_SHORT[m - 1] for m in x]

    def series(ax, key, title, ylabel):
        ax.fill_between(x, t[f"{key}_lo"], t[f"{key}_hi"], color=C["accent"], alpha=0.18,
                        label="прогнозний інтервал моделі 95%")
        ax.plot(x, t[f"{key}_sim"], color=C["accent"], lw=2, marker="o", ms=4, label="імітація")
        ax.plot(x, t[f"{key}_act"], color=C["bad"], lw=0, marker="D", ms=6, label="факт (журнал)")
        if t[f"{key}_erl"].notna().any():
            ax.plot(x, t[f"{key}_erl"], color=C["good"], lw=1.5, ls="--", label="Erlang C")
        ax.set_xticks(x)
        ax.set_xticklabels(xt, fontsize=7)
        style_ax(ax, C, title, None, ylabel)

    series(axs[0, 0], "wait", "Середнє очікування за місяцями", "с")
    legend(axs[0, 0], C, "upper left")
    series(axs[0, 1], "sla", "SLA за місяцями", "%")

    ax = axs[1, 0]
    a, s = t["wait_act"].to_numpy(), t["wait_sim"].to_numpy()
    lim = max(a.max(), s.max()) * 1.08
    ax.plot([0, lim], [0, lim], color=C["muted"], ls="--", lw=1.2, label="ідеальний збіг")
    ax.errorbar(a, s, yerr=[s - t["wait_lo"].to_numpy(), t["wait_hi"].to_numpy() - s], fmt="o",
                color=C["accent"], ecolor=C["grid"], capsize=2, ms=5, label="місяці")
    r = np.corrcoef(a, s)[0, 1] if len(a) > 2 else 1.0
    ax.text(0.04, 0.9, f"r = {r:.3f}", transform=ax.transAxes, color=C["fg"], fontsize=9, fontweight="bold")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    style_ax(ax, C, "Середнє очікування: факт ↔ модель", "факт, с", "модель, с", grid="both")
    legend(ax, C, "lower right")

    ax = axs[1, 1]
    keys = [("calls_day", "викл./день"), ("waited", "% чекали"), ("sla", "SLA"), ("util", "завант."),
            ("wait", "сер. оч.")]
    mat = np.array([(t[f"{k}_sim"] - t[f"{k}_act"]) / np.maximum(t[f"{k}_act"], 1e-9) * 100 for k, _ in keys])
    im = ax.imshow(mat, aspect="auto", cmap="RdYlGn_r", vmin=-30, vmax=30)
    ax.set_xticks(range(len(x)))
    ax.set_xticklabels(xt, fontsize=7)
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels([n for _, n in keys], fontsize=8)
    ax.tick_params(colors=C["muted"], length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            ax.text(j, i, f"{mat[i, j]:+.1f}", ha="center", va="center", fontsize=6.5, color="#111827")
    ax.set_title("Відхилення моделі від факту, %", color=C["fg"], fontsize=9.5, fontweight="bold", loc="left")


# ------------------------------------------------------------------ 5. Сценарії
def plot_sweep(fig, C, df, target):
    axs = fig.subplots(1, 2)
    x = df["agents"].to_numpy()
    ax = axs[0]
    ax.errorbar(x, df["sla"], yerr=[df["sla"] - df["sla_lo"], df["sla_hi"] - df["sla"]], color=C["accent"],
                lw=2, marker="o", ms=5, capsize=3, label="SLA (імітація, 95% ЦІ)")
    ax.plot(x, df["sla_erl"], color=C["good"], ls="--", lw=1.5, marker="s", ms=3, label="SLA (Erlang C)")
    ax.axhline(target, color=C["bad"], ls=":", lw=1.5, label=f"ціль {target:.0f}%")
    ok = df[df["meets"]]
    if len(ok):
        n_ok = int(ok["agents"].min())
        ax.axvline(n_ok, color=C["bad"], alpha=0.35, lw=6)
        ax.text(n_ok, 4, f" мін. N = {n_ok}", color=C["bad"], fontsize=9, fontweight="bold")
    ax.set_xticks(x)
    ax.set_ylim(0, 103)
    style_ax(ax, C, "SLA та завантаження залежно від кількості операторів", "кількість операторів", "SLA, %")
    ax2 = _twin(ax, C, "завантаження, %", C["warn"])
    ax2.plot(x, df["util"], color=C["warn"], lw=1.8, marker="^", ms=4, label="завантаження")
    ax2.set_ylim(0, 105)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    leg = ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=7.5, loc="center right")
    for tt in leg.get_texts():
        tt.set_color(C["fg"])

    ax = axs[1]
    stable = df["cost_total"] < df["cost_total"].min() * 6 + 1
    ax.bar(x, df["cost_agents"], color=C["accent"], width=0.6, label="оплата операторів")
    ax.bar(x, df["cost_wait"], bottom=df["cost_agents"], color=C["warn"], width=0.6, label="очікування клієнтів")
    ax.bar(x, df["cost_lost"], bottom=df["cost_agents"] + df["cost_wait"], color=C["bad"], width=0.6,
           label="втрачені виклики")
    best = df.loc[df["cost_total"].idxmin()]
    ax.plot([best["agents"]], [best["cost_total"]], marker="*", ms=16, color=C["good"], ls="none",
            label=f"мін. вартість (N={int(best['agents'])})")
    top = df.loc[stable, "cost_total"].max() * 1.25 if stable.any() else None
    if top:
        ax.set_ylim(0, top)
    ax.set_xticks(x)
    style_ax(ax, C, "Добова вартість", "кількість операторів", "грн / день")
    legend(ax, C, "upper center", ncol=2)


def plot_stress(fig, C, grid, metric, target):
    ax = fig.add_subplot(1, 1, 1)
    mat = {"sla": grid["sla"], "wait": grid["wait"], "util": grid["util"], "p95": grid["p95"]}[metric]
    title = {"sla": "SLA, % (жирна рамка — ціль виконано)", "wait": "Середнє очікування, с",
             "util": "Завантаження операторів, %", "p95": "95-й перцентиль очікування, с"}[metric]
    cmap = {"sla": "RdYlGn", "wait": "YlOrRd", "util": "Blues", "p95": "YlOrRd"}[metric]
    vmin, vmax = (0, 100) if metric in ("sla", "util") else (0, None)
    if metric == "wait":
        vmax = float(np.percentile(mat, 90)) + 1
    if metric == "p95":
        vmax = float(np.percentile(mat, 90)) + 1
    xt = [f"{int(round(v * 100))}%" for v in grid["loads"]]
    im = _heat(ax, C, mat, cmap, vmin, vmax, "{:.0f}", xt, [str(a) for a in grid["agents"]], fs=9)
    if metric == "sla":
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                if mat[i, j] >= target:
                    ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec=C["fg"], lw=2.2))
    ax.set_xlabel("множник навантаження (100% = поточний потік)", color=C["muted"], fontsize=9)
    ax.set_ylabel("кількість операторів", color=C["muted"], fontsize=9)
    ax.set_title(title, color=C["fg"], fontsize=10.5, fontweight="bold", loc="left")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.ax.tick_params(colors=C["muted"], labelsize=8)
    cb.outline.set_visible(False)


def plot_forecast(fig, C, fc):
    axs = fig.subplots(1, 2)
    t = fc.table
    ax = axs[0]
    ax.plot(fc.hist_x, fc.hist_y, color=C["accent"], marker="o", ms=5, lw=0, label="факт (місяці)")
    xs = np.concatenate([fc.hist_x, t["x"].to_numpy()])
    ax.plot(xs, fc.intercept + fc.slope * xs, color=C["bad"], lw=1.6, label=f"тренд {fc.slope:+.1f}/міс, R²={fc.r2:.2f}")
    ax.fill_between(t["x"], t["lo"], t["hi"], color=C["warn"], alpha=0.25, label="прогноз, 95% інтервал")
    ax.plot(t["x"], t["calls_day"], color=C["warn"], marker="D", ms=5, lw=0)
    ticks = list(range(1, int(t["x"].max()) + 1))
    ax.set_xticks(ticks)
    ax.set_xticklabels([MONTHS_UA_SHORT[(k - 1) % 12] for k in ticks], fontsize=7)
    style_ax(ax, C, "Прогноз інтенсивності потоку", None, "викликів / день")
    legend(ax, C, "upper left")

    ax = axs[1]
    labels = list(t["label"])
    xi = np.arange(len(t))
    cols = [C["good"] if n <= fc.n_current else C["bad"] for n in t["need"]]
    ax.bar(xi, t["need"], color=cols, width=0.55, alpha=0.9)
    for i, n in enumerate(t["need"]):
        ax.text(i, n + 0.08, str(int(n)), ha="center", color=C["fg"], fontsize=9, fontweight="bold")
    ax.axhline(fc.n_current, color=C["muted"], ls="--", lw=1.3, label=f"зараз {fc.n_current} операторів")
    ax.set_xticks(xi)
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylim(0, max(t["need"].max(), fc.n_current) + 2)
    style_ax(ax, C, f"Потрібно операторів для SLA ≥ {fc.target * 100:.0f}%", None, "операторів")
    ax2 = _twin(ax, C, "SLA при поточному штаті, %", C["violet"])
    ax2.plot(xi, t["sla_now"], color=C["violet"], marker="o", ms=4, lw=2, label="SLA зараз")
    ax2.axhline(fc.target * 100, color=C["bad"], ls=":", lw=1.3)
    ax2.set_ylim(0, 102)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    leg = ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=7.5, loc="lower left")
    for tt in leg.get_texts():
        tt.set_color(C["fg"])


def plot_schedule(fig, C, sc, target):
    axs = fig.subplots(1, 2)
    x = sc["hour"].to_numpy()
    xl = [str(OPEN_HOUR + h) for h in x]
    ax = axs[0]
    ax.bar(x, sc["need"], color=C["accent"], width=0.6, alpha=0.9, label="потрібно операторів")
    for h, n in zip(x, sc["need"]):
        ax.text(h, n + 0.07, str(int(n)), ha="center", color=C["fg"], fontsize=9, fontweight="bold")
    ax.step(x, sc["flat"], where="mid", color=C["muted"], ls="--", lw=1.6, label=f"постійний штат ({int(sc['flat'].iloc[0])})")
    ax.set_xticks(x)
    ax.set_xticklabels(xl)
    ax.set_ylim(0, max(sc["need"].max(), sc["flat"].max()) + 2)
    style_ax(ax, C, "Розклад операторів за годинами", "година початку", "операторів")
    ax2 = _twin(ax, C, "λ, викликів/год", C["warn"])
    ax2.plot(x, sc["lam"], color=C["warn"], marker="o", ms=4, lw=2, label="λ(h)")
    ax2.set_ylim(0, sc["lam"].max() * 1.3 + 1)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    leg = ax.legend(h1 + h2, l1 + l2, frameon=False, fontsize=7.5, loc="upper left", ncol=3)
    for tt in leg.get_texts():
        tt.set_color(C["fg"])

    ax = axs[1]
    ax.plot(x, sc["sla_plan"], color=C["good"], marker="o", ms=5, lw=2.2, label="за розкладом")
    ax.plot(x, sc["sla_flat"], color=C["bad"], marker="s", ms=4, lw=1.6, ls="--", label="постійний штат")
    ax.axhline(target * 100, color=C["muted"], ls=":", lw=1.3, label=f"ціль {target * 100:.0f}%")
    ax.set_xticks(x)
    ax.set_xticklabels(xl)
    ax.set_ylim(max(0, min(sc["sla_flat"].min(), sc["sla_plan"].min()) - 8), 101)
    style_ax(ax, C, "SLA за годинами (Erlang C)", "година початку", "SLA, %", grid="both")
    legend(ax, C, "lower right")

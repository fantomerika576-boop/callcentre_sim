"""Завантаження журналу дзвінків та статистичний аналіз історичних даних.

Ці функції відповідають етапу «збір і аналіз вхідних даних / ідентифікація моделі»:
з журналу визначаються інтенсивність потоку викликів, закон розподілу тривалості
обслуговування, кількість операторів та фактичні показники якості (SLA).
"""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .config import DAY_LEN, MONTHS_UA, N_HOURS, OPEN_HOUR

REQUIRED_COLUMNS = ["call_id", "date", "daily_caller", "call_started", "call_answered",
                    "call_ended", "wait_length", "service_length", "meets_standard"]


# ---------------------------------------------------------------- читання файлу
def _time_to_seconds(series: pd.Series) -> np.ndarray:
    """Перетворює час доби ('8:02:42 AM' або '08:02:42') у секунди від опівночі."""
    last_error = None
    for fmt in ("%I:%M:%S %p", "%H:%M:%S", "%I:%M %p", "%H:%M"):
        try:
            dt = pd.to_datetime(series, format=fmt)
        except (ValueError, TypeError) as exc:
            last_error = exc
            continue
        return (dt.dt.hour * 3600 + dt.dt.minute * 60 + dt.dt.second).to_numpy(dtype=float)
    raise ValueError(f"Не вдалося розпізнати формат часу: {last_error}")


def read_raw_csv(path: str) -> tuple[pd.DataFrame, str]:
    """Читає CSV або ZIP-архів із одним CSV-файлом."""
    path = str(path)
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist()
                     if n.lower().endswith(".csv") and not n.startswith("__MACOSX")]
            if not names:
                raise ValueError("В архіві не знайдено CSV-файлу.")
            with zf.open(names[0]) as fh:
                return pd.read_csv(fh), names[0]
    return pd.read_csv(path), os.path.basename(path)


def estimate_agents(df: pd.DataFrame) -> int:
    """Кількість операторів = максимум одночасно активних розмов (метод розгортки)."""
    day_idx = (df["date"] - df["date"].min()).dt.days.to_numpy(dtype=float)
    base = day_idx * 100000.0
    n = len(df)
    times = np.concatenate([base + df["ans_s"].to_numpy(), base + df["end_s"].to_numpy()])
    delta = np.concatenate([np.ones(n), -np.ones(n)])
    order = np.lexsort((delta, times))          # спершу час, потім завершення (-1) перед початком (+1)
    return int(np.cumsum(delta[order]).max())


# ---------------------------------------------------------------- клас даних
class CallData:
    """Оброблений журнал дзвінків + допоміжні статистичні методи."""

    def __init__(self, raw: pd.DataFrame, source: str = ""):
        missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
        if missing:
            raise ValueError("У файлі відсутні обов'язкові стовпці: " + ", ".join(missing))
        df = raw.copy()
        df["date"] = pd.to_datetime(df["date"])
        open_s = OPEN_HOUR * 3600
        df["arr_s"] = _time_to_seconds(df["call_started"]) - open_s     # надходження, с від 08:00
        df["ans_s"] = _time_to_seconds(df["call_answered"]) - open_s    # початок розмови
        df["end_s"] = _time_to_seconds(df["call_ended"]) - open_s       # завершення
        df["month"] = df["date"].dt.month
        df["weekday"] = df["date"].dt.dayofweek
        df["hour"] = np.clip((df["arr_s"] // 3600).astype(int), 0, N_HOURS - 1)
        if df["meets_standard"].dtype != bool:
            df["meets_standard"] = (df["meets_standard"].astype(str).str.strip().str.upper()
                                    .isin(["TRUE", "1", "YES", "T", "ТАК"]))
        df = df.sort_values(["date", "arr_s", "call_id"]).reset_index(drop=True)
        self.df = df
        self.source = source
        self.n_days = int(df["date"].nunique())
        self.days_by_month = df.groupby("month")["date"].nunique().to_dict()
        ok_waits = df.loc[df["meets_standard"], "wait_length"]
        self.sla_seconds = float(ok_waits.max()) if len(ok_waits) else 60.0
        self.n_agents = estimate_agents(df)
        self.service_mean = float(df["service_length"].mean())
        self.service_cv = float(df["service_length"].std() / self.service_mean)
        first = df.groupby("date")["arr_s"].min()
        self.first_call_at_open = bool((first == 0).mean() > 0.95)

    # ------------------------------------------------------------ вибірки
    def subset(self, month: int | None = None) -> pd.DataFrame:
        return self.df if month is None else self.df[self.df["month"] == month]

    def days_in(self, month: int | None = None) -> int:
        return self.n_days if month is None else int(self.days_by_month.get(month, 0))

    def months_present(self) -> list[int]:
        return sorted(self.days_by_month)

    # ------------------------------------------------------------ показники
    def kpis(self, month: int | None = None) -> dict:
        d = self.subset(month)
        nd = max(1, d["date"].nunique())
        w, s = d["wait_length"], d["service_length"]
        waited = w[w > 0]
        return dict(
            calls=len(d), days=nd, calls_per_day=len(d) / nd,
            wait_mean=float(w.mean()), wait_median=float(w.median()),
            wait_p95=float(w.quantile(0.95)), wait_max=float(w.max()),
            waited_share=float((w > 0).mean()),
            waited_mean=float(waited.mean()) if len(waited) else 0.0,
            sla=float(d["meets_standard"].mean()),
            service_mean=float(s.mean()), service_median=float(s.median()),
            service_cv=float(s.std() / s.mean()),
            util=float(s.sum() / (self.n_agents * DAY_LEN * nd)),
        )

    def hourly_calls_per_day(self, month: int | None = None) -> np.ndarray:
        d = self.subset(month)
        nd = max(1, d["date"].nunique())
        return np.bincount(d["hour"].to_numpy(), minlength=N_HOURS)[:N_HOURS] / nd

    def hourly_rates(self, month: int | None = None, first_call: bool = True,
                     censor: bool = True) -> np.ndarray:
        """Оцінка інтенсивності потоку λ(h) [дзвінків/год] для кожної години зміни.

        Виправлення двох артефактів журналу:
        • перший дзвінок кожного дня фіксується рівно о 08:00:00 (не є частиною пуассонівського потоку);
        • дзвінки, що не завершились до 18:00, у журнал не потрапляють (цензурування праворуч),
          тому лічильник останньої години ділиться на ймовірність «встигнути завершитись».
        """
        d = self.subset(month)
        nd = max(1, d["date"].nunique())
        cnt = np.bincount(d["hour"].to_numpy(), minlength=N_HOURS)[:N_HOURS].astype(float)
        if first_call and self.first_call_at_open:
            cnt[0] -= nd
        if censor:
            m = max(self.service_mean, 1.0)
            survive = 1.0 - (m / 3600.0) * (1.0 - np.exp(-3600.0 / m))
            cnt[-1] /= survive
        return cnt / nd

    def monthly_table(self) -> pd.DataFrame:
        rows = []
        for m in self.months_present():
            k = self.kpis(m)
            rows.append(dict(month=m, name=MONTHS_UA[m - 1], days=k["days"], calls=k["calls"],
                             calls_day=k["calls_per_day"], wait_mean=k["wait_mean"],
                             waited_share=k["waited_share"], sla=k["sla"],
                             service_mean=k["service_mean"], util=k["util"]))
        return pd.DataFrame(rows)

    def heatmap(self) -> np.ndarray:
        """Матриця «година × місяць»: середня кількість викликів за день."""
        out = np.zeros((N_HOURS, 12))
        for m in self.months_present():
            out[:, m - 1] = self.hourly_calls_per_day(m)
        return out

    def interarrival(self) -> np.ndarray:
        d = self.df
        diff = d.groupby("date")["arr_s"].diff().dropna().to_numpy()
        return diff

    def day_dates(self, month: int | None = None) -> list[str]:
        d = self.subset(month)
        return [x.strftime("%Y-%m-%d") for x in sorted(d["date"].unique())]

    def day_frame(self, date: str) -> pd.DataFrame:
        return self.df[self.df["date"] == pd.Timestamp(date)]

    def service_sample(self, max_n: int = 30000) -> np.ndarray:
        s = self.df["service_length"].to_numpy(dtype=float)
        if len(s) > max_n:
            s = np.random.default_rng(1).choice(s, max_n, replace=False)
        return s


# ---------------------------------------------------------------- повний аналіз
@dataclass
class Analysis:
    kpis: dict
    monthly: pd.DataFrame
    hourly: np.ndarray
    heat: np.ndarray
    fits: pd.DataFrame
    interarrival: np.ndarray
    ia_cv: float
    ia_ks: float
    trend: tuple            # (slope, intercept, r2)
    n_agents: int
    best_fit: str


def analyze(data: CallData) -> Analysis:
    """Ідентифікація закону розподілу обслуговування та перевірка пуассонівського потоку."""
    svc = data.df["service_length"].to_numpy(dtype=float)
    svc = svc[svc > 0]
    rows = []
    for label, dist in [("Експоненційний", stats.expon), ("Гамма", stats.gamma),
                        ("Логнормальний", stats.lognorm), ("Вейбулла", stats.weibull_min)]:
        params = dist.fit(svc, floc=0)
        ks = stats.kstest(svc, dist.name, args=params)
        ll = float(np.sum(dist.logpdf(svc, *params)))
        k = len(params) - 1                     # loc зафіксовано
        rows.append(dict(name=label, D=float(ks.statistic), loglik=ll,
                         aic=2 * k - 2 * ll, params=params))
    fits = pd.DataFrame(rows).sort_values("aic").reset_index(drop=True)

    ia = data.interarrival()
    ia_pos = ia[ia > 0]
    ia_cv = float(ia.std() / ia.mean())
    ia_ks = float(stats.kstest(ia_pos, "expon", args=(0, ia_pos.mean())).statistic)

    mon = data.monthly_table()
    lr = stats.linregress(mon["month"], mon["calls_day"])
    return Analysis(kpis=data.kpis(), monthly=mon, hourly=data.hourly_calls_per_day(),
                    heat=data.heatmap(), fits=fits, interarrival=ia, ia_cv=ia_cv,
                    ia_ks=ia_ks, trend=(float(lr.slope), float(lr.intercept), float(lr.rvalue ** 2)),
                    n_agents=data.n_agents, best_fit=str(fits.iloc[0]["name"]))


def findings_text(data: CallData, an: Analysis) -> list[tuple[str, str]]:
    """Текстові висновки для панелі «Ідентифікація моделі»."""
    k = an.kpis
    slope, _, r2 = an.trend
    exp_row = an.fits[an.fits["name"] == "Експоненційний"].iloc[0]
    out = [
        ("Набір даних",
         f"{k['calls']:,} викликів за {k['days']} робочих днів "
         f"({data.df['date'].min():%d.%m.%Y} – {data.df['date'].max():%d.%m.%Y}).".replace(",", " ")),
        ("Кількість операторів",
         f"Максимум одночасних розмов = {an.n_agents}. Отже, у моделі N = {an.n_agents} "
         f"однакових операторів; черга одна, дисципліна — FIFO."),
        ("Потік викликів",
         f"Коефіцієнт варіації інтервалів між дзвінками CV = {an.ia_cv:.3f} (для пуассонівського потоку ≈ 1), "
         f"відхилення від експоненційного закону D = {an.ia_ks:.3f}. Потік вважається пуассонівським "
         f"з нестаціонарною інтенсивністю λ(t)."),
        ("Динаміка навантаження",
         f"Інтенсивність зростає протягом року: у середньому {slope:+.1f} викл./день щодоби щомісяця "
         f"(лінійний тренд, R² = {r2:.2f}). Це джерело зростання черги та падіння SLA."),
        ("Обслуговування",
         f"Середня тривалість розмови {k['service_mean']:.1f} с, CV = {k['service_cv']:.2f}. "
         f"Найкраще за AIC: «{an.best_fit}»; експоненційний закон має D = {exp_row['D']:.4f} "
         f"(розбіжність із гамма-розподілом мінімальна, форма ≈ 1)."),
        ("Якість (SLA)",
         f"Стандарт: очікування ≤ {data.sla_seconds:.0f} с. Виконано {k['sla'] * 100:.1f}% викликів; "
         f"чекали в черзі {k['waited_share'] * 100:.1f}%, середнє очікування {k['wait_mean']:.1f} с "
         f"(для тих, хто чекав, — {k['waited_mean']:.0f} с)."),
        ("Особливості журналу",
         "• Перший дзвінок кожного дня зафіксований рівно о 08:00:00.\n"
         "• Дзвінки, що не завершилися до 18:00, відсутні (цензурування) — модель це враховує.\n"
         "• Відмов (кинутих слухавок) у журналі немає, тому терпіння клієнтів за замовчуванням нескінченне."),
    ]
    return out

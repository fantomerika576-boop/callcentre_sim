"""Експорт результатів у Excel та CSV."""
from __future__ import annotations

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .engine import SimResult

KPI_TITLES = {
    "offered_day": "Викликів за день", "served_day": "Обслужено за день",
    "abandon_pct": "Втрачені виклики, %", "wait_mean": "Середнє очікування, с",
    "waited_pct": "Частка тих, хто чекав, %", "sla_pct": "SLA виконано, %",
    "wait_p95": "95-й перцентиль очікування, с", "wait_max": "Макс. очікування за день, с",
    "util_pct": "Завантаження операторів, %", "q_mean": "Середня довжина черги",
    "q_max": "Макс. довжина черги за день", "overtime_min": "Понаднормово, хв/день",
    "wait_min_day": "Сумарне очікування, клієнто-хв/день",
    "wait_if_waited": "Очікування тих, хто чекав, с",
}


def _style(ws, df: pd.DataFrame):
    head_fill = PatternFill("solid", fgColor="2563EB")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, col in enumerate(df.columns, start=1):
        width = max(len(str(col)), *(len(str(v)) for v in df[col].head(200))) + 3
        ws.column_dimensions[get_column_letter(i)].width = min(max(width, 10), 48)
    ws.freeze_panes = "A2"


def kpi_table(res: SimResult) -> pd.DataFrame:
    rows = []
    for key, title in KPI_TITLES.items():
        s = res.summary[key]
        rows.append({"Показник": title, "Середнє": round(s["mean"], 3), "Ст. відхилення": round(s["std"], 3),
                     "95% ЦІ (нижня)": round(s["lo"], 3), "95% ЦІ (верхня)": round(s["hi"], 3)})
    return pd.DataFrame(rows)


def export_excel(path: str, cfg, result: SimResult | None, validation=None, sweep=None,
                 forecast=None, schedule=None, max_call_rows: int = 100000) -> None:
    sheets: dict[str, pd.DataFrame] = {}
    if cfg is not None:
        sheets["Параметри"] = pd.DataFrame(list(cfg.describe().items()), columns=["Параметр", "Значення"])
    if result is not None:
        sheets["KPI"] = kpi_table(result)
        rep = result.rep.rename(columns=KPI_TITLES).rename(columns={"rep": "Прогін"})
        sheets["По прогонах"] = rep.round(3)
        hr = result.hourly.rename(columns={
            "hour": "Година (0=08:00)", "calls_day": "Викликів/день", "wait_mean": "Сер. очікування, с",
            "sla_pct": "SLA, %", "waited_pct": "Чекали, %"}).round(3)
        sheets["За годинами"] = hr
        if result.calls is not None:
            sheets["Виклики"] = result.calls.head(max_call_rows).rename(columns={
                "rep": "Прогін", "day": "День", "arrival": "Надходження, с від 08:00",
                "wait": "Очікування, с", "service": "Обслуговування, с", "status": "Статус (1 — обслужено, 2 — втрачено)"})
    if validation is not None:
        sheets["Валідація"] = validation.table.round(3)
    if sweep is not None:
        sheets["Підбір операторів"] = sweep.round(3)
    if forecast is not None:
        sheets["Прогноз"] = forecast.table.round(2)
    if schedule is not None:
        sheets["Розклад"] = schedule.round(2)
    if not sheets:
        raise ValueError("Немає даних для експорту — спочатку запустіть симуляцію.")
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            _style(xw.sheets[name[:31]], df)


def export_calls_csv(path: str, result: SimResult) -> None:
    if result.calls is None:
        raise ValueError("Журнал викликів не зберігався (keep_calls=False).")
    result.calls.to_csv(path, index=False, encoding="utf-8-sig")

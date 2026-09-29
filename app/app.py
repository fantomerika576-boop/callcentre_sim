"""Головне вікно застосунку: вкладки, тема, фонове виконання обчислень, меню, рядок стану."""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import traceback
import warnings
from tkinter import filedialog, messagebox, ttk

from .config import APP_TITLE
from .data import CallData, analyze, read_raw_csv
from .engine import Cancelled
from .export import export_excel
from .gui.tab_compare import CompareTab
from .gui.tab_data import AnalysisTab, DataTab
from .gui.tab_help import HelpTab
from .gui.tab_live import LiveTab
from .gui.tab_model import ModelTab
from .gui.tab_results import ResultsTab
from .gui.tab_scenarios import ScenariosTab
from .gui.tab_validation import ValidationTab
from .gui.theme import ThemeManager

warnings.filterwarnings("ignore", message=".*layoutgrids.*")

DEFAULT_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "simulated_call_centre.csv")


class BusyDialog(tk.Toplevel):
    """Модальне вікно з індикатором виконання та кнопкою «Скасувати»."""

    def __init__(self, app, title: str, on_cancel):
        super().__init__(app)
        self.title("Виконання")
        self.resizable(False, False)
        self.transient(app)
        self.on_cancel = on_cancel
        C = app.theme.C
        self.configure(bg=C["bg"])
        box = ttk.Frame(self, padding=20)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=title, style="H2.TLabel").pack(anchor="w")
        self.msg = ttk.Label(box, text="Підготовка…", style="Muted.TLabel", width=46)
        self.msg.pack(anchor="w", pady=(6, 8))
        self.bar = ttk.Progressbar(box, mode="determinate", maximum=100, length=380)
        self.bar.pack(fill="x")
        self.btn = ttk.Button(box, text="Скасувати", style="Danger.TButton", command=self.cancel)
        self.btn.pack(anchor="e", pady=(12, 0))
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_reqwidth()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()

    def update_progress(self, frac: float, text: str):
        self.bar["value"] = max(0.0, min(1.0, frac)) * 100
        self.msg.configure(text=text)

    def cancel(self):
        self.btn.configure(state="disabled", text="Зупинка…")
        self.on_cancel()


class App(tk.Tk):
    def __init__(self, data_path: str | None = DEFAULT_DATA):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1440x900")
        self.minsize(1180, 720)
        self.theme = ThemeManager(self)
        self.theme.apply("light")

        # спільний стан
        self.data: CallData | None = None
        self.analysis = None
        self.result = None
        self.cfg = None
        self.validation = self.sweep = self.stress = self.forecast = self.schedule = None
        self.tabs: dict[str, ttk.Frame] = {}
        self._busy: BusyDialog | None = None
        self._stop = threading.Event()
        self._q: queue.Queue = queue.Queue()

        self._build_header()
        self._build_status()
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        spec = [("data", "Дані", DataTab), ("analysis", "Аналіз даних", AnalysisTab), ("model", "Модель", ModelTab),
                ("results", "Результати", ResultsTab), ("validation", "Валідація", ValidationTab),
                ("scenarios", "Сценарії", ScenariosTab), ("compare", "Порівняння", CompareTab),
                ("live", "Анімація дня", LiveTab), ("help", "Довідка", HelpTab)]
        for key, title, cls in spec:
            tab = cls(self.nb, self)
            self.tabs[key] = tab
            self.nb.add(tab, text=f"  {title}  ")

        self._build_menu()
        self.bind("<F5>", lambda e: self.tabs["model"].run())
        self.bind("<Control-o>", lambda e: self.open_dialog())
        self.bind("<Control-e>", lambda e: self.tabs["results"]._excel())
        self.bind("<Control-t>", lambda e: self.toggle_theme())
        self.status("Готово до роботи")
        if data_path and os.path.exists(data_path):
            self.after(200, lambda: self.load_path(data_path))

    # ------------------------------------------------------------ інтерфейс
    def _build_header(self):
        h = ttk.Frame(self, style="Header.TFrame")
        h.pack(fill="x", padx=8, pady=8)
        left = ttk.Frame(h, style="Header.TFrame")
        left.pack(side="left", padx=14, pady=8)
        ttk.Label(left, text="Імітаційне моделювання контакт-центру", style="Header.TLabel").pack(anchor="w")
        ttk.Label(left, text="Бізнес-процеси сервіс-орієнтованої інформаційної системи · дискретно-подієва модель M(t)/G/N",
                  style="HeaderSub.TLabel").pack(anchor="w")
        right = ttk.Frame(h, style="Header.TFrame")
        right.pack(side="right", padx=14)
        ttk.Button(right, text="Тема ◐", style="Small.TButton", command=self.toggle_theme).pack(side="right", padx=(8, 0))
        ttk.Button(right, text="Відкрити дані…", style="Small.TButton", command=self.open_dialog).pack(side="right")

    def _build_status(self):
        sb = ttk.Frame(self, style="Status.TFrame")
        sb.pack(side="bottom", fill="x")
        self.status_lbl = ttk.Label(sb, text="", style="Status.TLabel")
        self.status_lbl.pack(side="left", padx=12, pady=4)

    def _build_menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Відкрити журнал (CSV / ZIP)…", accelerator="Ctrl+O", command=self.open_dialog)
        f.add_command(label="Експорт результатів у Excel…", accelerator="Ctrl+E", command=self.tabs["results"]._excel)
        f.add_separator()
        f.add_command(label="Вихід", command=self.destroy)
        m.add_cascade(label="Файл", menu=f)
        r = tk.Menu(m, tearoff=0)
        r.add_command(label="Запустити симуляцію", accelerator="F5", command=self.tabs["model"].run)
        r.add_command(label="Калібрувати модель за даними", command=self.tabs["model"].calibrate)
        m.add_cascade(label="Симуляція", menu=r)
        v = tk.Menu(m, tearoff=0)
        v.add_command(label="Світла / темна тема", accelerator="Ctrl+T", command=self.toggle_theme)
        m.add_cascade(label="Вигляд", menu=v)
        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="Довідка", command=lambda: self.select("help"))
        m.add_cascade(label="Довідка", menu=hm)
        self.configure(menu=m)

    def toggle_theme(self):
        self.theme.toggle()
        self.status("Тему змінено: " + ("темна" if self.theme.name == "dark" else "світла"))

    def status(self, text: str):
        self.status_lbl.configure(text=text)

    def select(self, key: str):
        self.nb.select(self.tabs[key])

    # ------------------------------------------------------------ дані
    def open_dialog(self):
        path = filedialog.askopenfilename(title="Журнал дзвінків", filetypes=[("CSV або ZIP", "*.csv *.zip"), ("Усі файли", "*.*")])
        if path:
            self.load_path(path)

    def load_path(self, path: str):
        def work(progress, should_stop):
            progress(0.15, "Читання файлу…")
            raw, source = read_raw_csv(path)
            progress(0.45, "Обробка журналу…")
            data = CallData(raw, source)
            progress(0.75, "Статистичний аналіз (підгонка розподілів)…")
            return data, analyze(data)

        self.run_bg(work, self._loaded, "Завантаження даних…")

    def _loaded(self, res):
        data, an = res
        self.data, self.analysis = data, an
        self.tabs["data"].show(data)
        self.tabs["analysis"].show(data, an)
        self.tabs["model"].on_data_loaded(data)
        self.tabs["scenarios"].on_data_loaded(data)
        self.status(f"Завантажено {len(data.df):,} викликів за {data.n_days} робочих днів · оцінка кількості операторів: {data.n_agents}".replace(",", " "))

    # ------------------------------------------------------------ фонове виконання
    def run_bg(self, fn, on_done, title="Виконання…"):
        """Виконує fn(progress, should_stop) у потоці; on_done(result) викликається в потоці інтерфейсу."""
        if self._busy is not None:
            return
        self._stop.clear()
        self._busy = BusyDialog(self, title, self._stop.set)

        def progress(frac, text=""):
            self._q.put(("p", frac, text))

        def worker():
            try:
                self._q.put(("ok", fn(progress, self._stop.is_set)))
            except Cancelled:
                self._q.put(("cancel", None))
            except BaseException as exc:                     # noqa: BLE001 — показуємо користувачу будь-яку помилку
                traceback.print_exc()
                self._q.put(("err", exc))

        threading.Thread(target=worker, daemon=True).start()
        self.after(40, lambda: self._poll(on_done))

    def _poll(self, on_done):
        last = None
        try:
            while True:
                msg = self._q.get_nowait()
                if msg[0] == "p":
                    last = msg
                    continue
                self._finish()
                kind, payload = msg
                if kind == "ok":
                    try:
                        on_done(payload)
                    except Exception as exc:                 # noqa: BLE001
                        traceback.print_exc()
                        messagebox.showerror("Помилка", f"{type(exc).__name__}: {exc}")
                elif kind == "cancel":
                    self.status("Виконання перервано користувачем")
                else:
                    messagebox.showerror("Помилка", f"{type(payload).__name__}: {payload}")
                return
        except queue.Empty:
            pass
        if last and self._busy:
            self._busy.update_progress(last[1], last[2])
        self.after(40, lambda: self._poll(on_done))

    def _finish(self):
        if self._busy is not None:
            self._busy.grab_release()
            self._busy.destroy()
            self._busy = None

    # ------------------------------------------------------------ експорт
    def export_excel(self, path: str):
        try:
            export_excel(path, self.cfg, self.result, self.validation, self.sweep, self.forecast, self.schedule)
            self.status(f"Збережено: {path}")
            messagebox.showinfo("Експорт", f"Результати збережено:\n{path}")
        except Exception as exc:                             # noqa: BLE001
            messagebox.showerror("Експорт", str(exc))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else DEFAULT_DATA
    App(path).mainloop()

"""Повторно використовувані віджети: KPI-картки, рамка з графіком, таблиця, прокручувана область."""
from __future__ import annotations

import tkinter as tk
import traceback
from tkinter import filedialog, ttk
from typing import Callable, Optional

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

matplotlib.rcParams["font.family"] = "DejaVu Sans"
matplotlib.rcParams["axes.unicode_minus"] = False


# ------------------------------------------------------------------ KPI-картка
class KpiCard(ttk.Frame):
    """Картка показника: заголовок, велике значення, підпис і кольорова смужка зліва."""

    def __init__(self, parent, theme, title: str, accent: str = "accent"):
        super().__init__(parent, style="Card.TFrame")
        self.theme = theme
        self.accent_key = accent
        self.strip = tk.Frame(self, width=5, bd=0, highlightthickness=0)
        self.strip.pack(side="left", fill="y")
        body = ttk.Frame(self, style="Plain.TFrame")
        body.pack(side="left", fill="both", expand=True, padx=(10, 8), pady=8)
        self.title = ttk.Label(body, text=title, style="CardTitle.TLabel")
        self.title.pack(anchor="w")
        self.value = ttk.Label(body, text="—", style="CardValue.TLabel")
        self.value.pack(anchor="w")
        self.sub = ttk.Label(body, text=" ", style="CardMuted.TLabel")
        self.sub.pack(anchor="w")
        self._apply()
        theme.on_change(self._apply)

    def _apply(self):
        try:
            self.strip.configure(bg=self.theme.C[self.accent_key])
        except tk.TclError:
            pass

    def set(self, value: str, sub: str = " ", accent: Optional[str] = None):
        self.value.configure(text=value)
        self.sub.configure(text=sub or " ")
        if accent:
            self.accent_key = accent
            self._apply()


def kpi_row(parent, theme, specs: list[tuple[str, str]], columns: Optional[int] = None) -> dict[str, KpiCard]:
    """Створює ряд карток. specs = [(ключ, заголовок), …] → {ключ: KpiCard}."""
    frame = ttk.Frame(parent)
    frame.pack(fill="x", padx=12, pady=(10, 4))
    cards = {}
    cols = columns or len(specs)
    for i, (key, title) in enumerate(specs):
        card = KpiCard(frame, theme, title, accent=["accent", "info", "good", "warn", "violet", "bad"][i % 6])
        card.grid(row=i // cols, column=i % cols, sticky="nsew", padx=4, pady=4)
        cards[key] = card
    for c in range(cols):
        frame.columnconfigure(c, weight=1, uniform="kpi")
    return cards


# ------------------------------------------------------------------ графік matplotlib
class FigureFrame(ttk.Frame):
    """Рамка з полотном matplotlib. Функція-відмальовувач fn(fig, C) перемальовується при зміні теми."""

    def __init__(self, parent, theme, figsize=(8, 5), save_name="chart", toolbar=True):
        super().__init__(parent, style="Card.TFrame")
        self.theme = theme
        self.save_name = save_name
        self.fig = Figure(figsize=figsize, dpi=100, layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(highlightthickness=0, bd=0)
        self.widget.pack(fill="both", expand=True, padx=1, pady=1)
        if toolbar:
            bar = ttk.Frame(self, style="Plain.TFrame")
            bar.pack(fill="x", side="bottom")
            ttk.Button(bar, text="Зберегти PNG", style="Small.TButton",
                       command=self.save_png).pack(side="right", padx=6, pady=3)
        self._plotter: Optional[Callable] = None
        self._placeholder = "Немає даних"
        theme.on_change(self.redraw)
        self.redraw()

    def set_placeholder(self, text: str):
        self._placeholder = text
        if self._plotter is None:
            self.redraw()

    def plot(self, fn: Callable):
        self._plotter = fn
        self.redraw()

    def clear(self):
        self._plotter = None
        self.redraw()

    def redraw(self):
        C = self.theme.C
        self.fig.clear()
        self.fig.set_facecolor(C["card"])
        self.widget.configure(bg=C["card"])
        if self._plotter is None:
            self.fig.text(0.5, 0.5, self._placeholder, ha="center", va="center",
                          color=C["muted"], fontsize=11, wrap=True)
        else:
            try:
                self._plotter(self.fig, C)
            except Exception:                      # не даємо помилці графіка зламати весь інтерфейс
                traceback.print_exc()
                self.fig.clear()
                self.fig.text(0.5, 0.5, "Не вдалося побудувати графік", ha="center", color=C["bad"])
        self.canvas.draw_idle()

    def save_png(self):
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"{self.save_name}.png",
                                            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")])
        if path:
            self.fig.savefig(path, dpi=200, facecolor=self.fig.get_facecolor())


# ------------------------------------------------------------------ таблиця
class DataTable(ttk.Frame):
    def __init__(self, parent, theme, columns: list[tuple[str, str, int]], height=10, stretch=True):
        super().__init__(parent)
        self.theme = theme
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings", height=height)
        for cid, head, width in columns:
            self.tree.heading(cid, text=head)
            self.tree.column(cid, width=width, minwidth=50, anchor="center", stretch=stretch)
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._tags()
        theme.on_change(self._tags)

    def _tags(self):
        C = self.theme.C
        self.tree.tag_configure("odd", background=C["card"])
        self.tree.tag_configure("even", background=C["hover"])
        self.tree.tag_configure("bad", foreground=C["bad"])
        self.tree.tag_configure("good", foreground=C["good"])
        self.tree.tag_configure("best", background=C["accent_soft"], foreground=C["fg"])

    def set_rows(self, rows: list[tuple], flags: Optional[list[str]] = None):
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(rows):
            tags = ["even" if i % 2 else "odd"]
            if flags and flags[i]:
                tags = [flags[i]]
            self.tree.insert("", "end", values=row, tags=tags)


# ------------------------------------------------------------------ прокручувана область
class ScrolledFrame(ttk.Frame):
    def __init__(self, parent, theme, width=380):
        super().__init__(parent)
        self.theme = theme
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, width=width)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        self._apply()
        theme.on_change(self._apply)

    def _apply(self):
        self.canvas.configure(bg=self.theme.C["bg"])

    def _bind_wheel(self, _):
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

    def _unbind_wheel(self, _):
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(ev)

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units")


# ------------------------------------------------------------------ текстова панель
def make_text(parent, theme, height=10, wrap="word", mono=False) -> tk.Text:
    t = tk.Text(parent, height=height, wrap=wrap, relief="flat", bd=0, highlightthickness=1,
                padx=10, pady=8, cursor="arrow", state="disabled")

    def apply():
        C = theme.C
        t.configure(bg=C["card"], fg=C["fg"], insertbackground=C["fg"], highlightbackground=C["border"],
                    highlightcolor=C["border"], selectbackground=C["accent"],
                    font=(theme.mono if mono else theme.family, 10))
        t.tag_configure("h", foreground=C["accent"], font=(theme.family, 10, "bold"), spacing1=8)
        t.tag_configure("good", foreground=C["good"], font=(theme.family, 10, "bold"))
        t.tag_configure("bad", foreground=C["bad"], font=(theme.family, 10, "bold"))
        t.tag_configure("muted", foreground=C["muted"])
        t.tag_configure("b", font=(theme.family, 10, "bold"))

    apply()
    theme.on_change(apply)
    return t


def scrolled_text(parent, theme, height=10, mono=False):
    """Текстова панель із вертикальною прокруткою; повертає (рамка, Text). Рамку розміщує викликач."""
    box = ttk.Frame(parent)
    t = make_text(box, theme, height=height, mono=mono)
    sb = ttk.Scrollbar(box, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    t.pack(side="left", fill="both", expand=True)
    return box, t


def set_text(t: tk.Text, parts: list[tuple[str, str]]):
    """parts = [(текст, тег), …] — тег '' для звичайного тексту."""
    t.configure(state="normal")
    t.delete("1.0", "end")
    for text, tag in parts:
        t.insert("end", text, tag) if tag else t.insert("end", text)
    t.configure(state="disabled")


# ------------------------------------------------------------------ форма параметрів
class Form:
    """Допоміжний конструктор рядків «мітка — віджет» у grid."""

    def __init__(self, parent, label_width=None):
        self.parent = parent
        self.row = 0
        parent.columnconfigure(1, weight=1)

    def add(self, label: str, widget: tk.Widget, hint: str = ""):
        lab = ttk.Label(self.parent, text=label)
        lab.grid(row=self.row, column=0, sticky="w", padx=(8, 8), pady=3)
        widget.grid(row=self.row, column=1, sticky="ew", padx=(0, 8), pady=3)
        if hint:
            ttk.Label(self.parent, text=hint, style="Muted.TLabel", font=("TkDefaultFont", 8)).grid(
                row=self.row + 1, column=0, columnspan=2, sticky="w", padx=8)
            self.row += 1
        self.row += 1
        return lab

    def add_wide(self, widget: tk.Widget, pady=3):
        widget.grid(row=self.row, column=0, columnspan=2, sticky="ew", padx=8, pady=pady)
        self.row += 1


def spin(parent, var, lo, hi, step=1, width=8, fmt=None):
    kw = dict(from_=lo, to=hi, increment=step, textvariable=var, width=width)
    if fmt:
        kw["format"] = fmt
    return ttk.Spinbox(parent, **kw)

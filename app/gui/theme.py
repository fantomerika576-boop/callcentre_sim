"""Кольорові теми (світла / темна) для ttk-віджетів та графіків matplotlib."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

PALETTES = {
    "light": dict(
        bg="#F1F5F9", card="#FFFFFF", tab="#E2E8F0", fg="#0F172A", muted="#64748B",
        border="#CBD5E1", grid="#E2E8F0", hover="#EEF2F7",
        accent="#2563EB", accent_hover="#1D4ED8", accent_soft="#DBEAFE",
        good="#059669", warn="#D97706", bad="#DC2626", info="#0891B2", violet="#7C3AED",
        disabled="#94A3B8", canvas="#F8FAFC"),
    "dark": dict(
        bg="#0B1220", card="#141E33", tab="#0F1A2E", fg="#E5E7EB", muted="#94A3B8",
        border="#2B3A55", grid="#26334D", hover="#1C2946",
        accent="#3B82F6", accent_hover="#60A5FA", accent_soft="#1E3A8A",
        good="#34D399", warn="#FBBF24", bad="#F87171", info="#22D3EE", violet="#A78BFA",
        disabled="#475569", canvas="#0F1A2E"),
}

SERIES = ["#2563EB", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#06B6D4"]


class ThemeManager:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.name = "light"
        self.listeners: list = []
        fams = set(tkfont.families(root))
        self.family = next((f for f in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Noto Sans",
                                        "DejaVu Sans", "Arial") if f in fams), "TkDefaultFont")
        self.mono = next((f for f in ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier New")
                          if f in fams), "TkFixedFont")

    @property
    def C(self) -> dict:
        return PALETTES[self.name]

    def font(self, size=10, weight="normal"):
        return (self.family, size, weight)

    def toggle(self):
        self.apply("dark" if self.name == "light" else "light")

    def apply(self, name: str):
        self.name = name
        C, f = self.C, self.family
        st = ttk.Style(self.root)
        st.theme_use("clam")
        self.root.configure(bg=C["bg"])
        st.configure(".", background=C["bg"], foreground=C["fg"], font=(f, 10),
                     fieldbackground=C["card"], bordercolor=C["border"], lightcolor=C["bg"],
                     darkcolor=C["bg"], troughcolor=C["grid"], focuscolor=C["accent"],
                     selectbackground=C["accent"], selectforeground="#FFFFFF")
        st.configure("TFrame", background=C["bg"])
        st.configure("Card.TFrame", background=C["card"], bordercolor=C["border"], relief="solid",
                     borderwidth=1)
        st.configure("Plain.TFrame", background=C["card"])
        st.configure("TLabel", background=C["bg"], foreground=C["fg"])
        st.configure("Card.TLabel", background=C["card"], foreground=C["fg"])
        st.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"])
        st.configure("CardMuted.TLabel", background=C["card"], foreground=C["muted"], font=(f, 9))
        st.configure("CardTitle.TLabel", background=C["card"], foreground=C["muted"],
                     font=(f, 9, "bold"))
        st.configure("CardValue.TLabel", background=C["card"], foreground=C["fg"], font=(f, 19, "bold"))
        st.configure("H1.TLabel", background=C["bg"], foreground=C["fg"], font=(f, 15, "bold"))
        st.configure("H2.TLabel", background=C["bg"], foreground=C["accent"], font=(f, 11, "bold"))
        st.configure("Header.TFrame", background=C["card"])
        st.configure("Header.TLabel", background=C["card"], foreground=C["fg"], font=(f, 13, "bold"))
        st.configure("HeaderSub.TLabel", background=C["card"], foreground=C["muted"], font=(f, 9))
        st.configure("Status.TFrame", background=C["card"])
        st.configure("Status.TLabel", background=C["card"], foreground=C["muted"])
        st.configure("Good.TLabel", background=C["bg"], foreground=C["good"], font=(f, 10, "bold"))
        st.configure("Bad.TLabel", background=C["bg"], foreground=C["bad"], font=(f, 10, "bold"))

        st.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(10, 8, 10, 0))
        st.configure("TNotebook.Tab", padding=(16, 9), background=C["tab"], foreground=C["muted"],
                     font=(f, 10, "bold"), borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", C["card"]), ("active", C["hover"])],
               foreground=[("selected", C["accent"]), ("active", C["fg"])])
        st.configure("Inner.TNotebook", background=C["bg"], borderwidth=0, tabmargins=(4, 4, 4, 0))
        st.configure("Inner.TNotebook.Tab", padding=(12, 6), font=(f, 9, "bold"))

        st.configure("TButton", padding=(12, 6), background=C["card"], foreground=C["fg"],
                     bordercolor=C["border"], relief="flat", font=(f, 10))
        st.map("TButton", background=[("active", C["hover"]), ("disabled", C["bg"])],
               foreground=[("disabled", C["disabled"])], bordercolor=[("focus", C["accent"])])
        st.configure("Accent.TButton", padding=(16, 8), background=C["accent"], foreground="#FFFFFF",
                     bordercolor=C["accent"], font=(f, 10, "bold"))
        st.map("Accent.TButton", background=[("active", C["accent_hover"]), ("disabled", C["disabled"])],
               foreground=[("disabled", "#E2E8F0")])
        st.configure("Danger.TButton", padding=(10, 5), background=C["bad"], foreground="#FFFFFF",
                     bordercolor=C["bad"])
        st.map("Danger.TButton", background=[("disabled", C["disabled"])])
        st.configure("Small.TButton", padding=(8, 3), font=(f, 9))
        st.configure("Toolbutton", padding=(8, 4), background=C["bg"])

        for w in ("TEntry", "TSpinbox", "TCombobox"):
            st.configure(w, fieldbackground=C["card"], foreground=C["fg"], bordercolor=C["border"],
                         insertcolor=C["fg"], padding=4, arrowcolor=C["muted"], background=C["card"])
        st.map("TCombobox", fieldbackground=[("readonly", C["card"])],
               foreground=[("readonly", C["fg"]), ("disabled", C["disabled"])],
               selectbackground=[("readonly", C["card"])], selectforeground=[("readonly", C["fg"])])
        st.map("TSpinbox", foreground=[("disabled", C["disabled"])],
               fieldbackground=[("disabled", C["bg"])])
        st.map("TEntry", fieldbackground=[("disabled", C["bg"])])
        self.root.option_add("*TCombobox*Listbox.background", C["card"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.root.option_add("*TCombobox*Listbox.font", (f, 10))

        st.configure("TCheckbutton", background=C["bg"], foreground=C["fg"], indicatorcolor=C["card"],
                     indicatorbackground=C["card"])
        st.map("TCheckbutton", indicatorcolor=[("selected", C["accent"])],
               background=[("active", C["bg"])])
        st.configure("TRadiobutton", background=C["bg"], foreground=C["fg"])
        st.map("TRadiobutton", indicatorcolor=[("selected", C["accent"])], background=[("active", C["bg"])])
        st.configure("TLabelframe", background=C["bg"], bordercolor=C["border"], relief="solid")
        st.configure("TLabelframe.Label", background=C["bg"], foreground=C["accent"], font=(f, 10, "bold"))
        st.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor=C["grid"],
                     bordercolor=C["grid"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=8)
        st.configure("Horizontal.TScale", background=C["bg"], troughcolor=C["grid"])
        st.configure("TSeparator", background=C["border"])

        st.configure("Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["fg"],
                     rowheight=25, borderwidth=0, font=(f, 10))
        st.configure("Treeview.Heading", background=C["tab"], foreground=C["fg"], font=(f, 10, "bold"),
                     relief="flat", padding=(6, 6))
        st.map("Treeview", background=[("selected", C["accent"])], foreground=[("selected", "#FFFFFF")])
        st.map("Treeview.Heading", background=[("active", C["hover"])])
        for orient in ("Vertical", "Horizontal"):
            st.configure(f"{orient}.TScrollbar", background=C["tab"], troughcolor=C["bg"],
                         bordercolor=C["bg"], arrowcolor=C["muted"], relief="flat")
            st.map(f"{orient}.TScrollbar", background=[("active", C["border"])])

        for cb in list(self.listeners):
            try:
                cb()
            except tk.TclError:
                self.listeners.remove(cb)

    def on_change(self, cb):
        self.listeners.append(cb)

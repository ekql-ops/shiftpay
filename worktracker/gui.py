"""Work Tracker desktop app."""
import calendar
import sys
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import font as tkfont

from . import core
from .core import (
    DAY_KEYS,
    DAY_NAMES,
    breakdown,
    day_pay,
    default_hours,
    entry_kind,
    fmt_hours,
    money,
    rate_for,
    sick_pay_for,
)

APP_ID = "WorkTracker.App"

# ── palette ───────────────────────────────────────────────────────────────
BG        = "#0a0b10"
SURFACE   = "#141620"
RAISED    = "#1c1f2b"
BORDER    = "#262a38"
FG        = "#f4f5fa"
MUTED     = "#7b8095"
DIM       = "#4a4f61"

GREEN     = "#3ddc91"
GREEN_BG  = "#153528"
AMBER     = "#ffc766"
AMBER_BG  = "#392e14"
BLUE      = "#6c9fff"
BLUE_BG   = "#17233f"
RED       = "#ff7a8f"
GREY_BG   = "#1b1e28"
PAYDAY    = "#c79bff"
PAYDAY_BG = "#261c3d"
BENEFIT   = "#4fd6e8"
BENEFIT_BG = "#12323a"

FONT = "Segoe UI"

KIND_STYLE = {
    "work":       (GREEN_BG, GREEN),
    "sick":       (AMBER_BG, AMBER),
    "adjustment": (BLUE_BG, BLUE),
    "off":        (GREY_BG, DIM),
    None:         ("#101320", "#3a3f4f"),
}


def resource_path(name):
    """Find bundled files whether running as a script or a packaged .exe."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / name
    return Path(__file__).resolve().parent.parent / "assets" / name


def claim_taskbar_identity():
    """Running as a script, Windows files the window under python.exe, so
    claim our own id. The packaged .exe already has its own identity, and
    overriding it there stops a pinned shortcut matching the window."""
    if getattr(sys, "frozen", False):
        return
    try:
        import ctypes  # noqa: PLC0415 — Windows-only, kept out of the import block
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass            # not Windows, or the shell API is unavailable


def round_rect(cnv, x1, y1, x2, y2, r, **kw):
    r = min(r, abs(x2 - x1) / 2, abs(y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cnv.create_polygon(pts, smooth=True, **kw)


# ── widgets ───────────────────────────────────────────────────────────────
class RButton(tk.Canvas):
    """Rounded button with hover and press feedback."""

    def __init__(self, parent, text, command, width=150, height=46, radius=None,
                 fill=RAISED, hover=None, fg=FG, font=None, outline="", bg=None):
        super().__init__(parent, width=width, height=height,
                         bg=bg or parent["bg"], highlightthickness=0, cursor="hand2")
        self.command, self.fill, self.fg = command, fill, fg
        self.hover = hover or fill
        self.outline = outline
        self.font = font or tkfont.Font(family=FONT, size=11, weight="bold")
        self.w, self.h = width, height
        self.radius = radius if radius is not None else height / 2
        self.text_str = text          # must precede the first draw
        self._draw(self.fill)
        self.bind("<Enter>", lambda e: self._draw(self.hover))
        self.bind("<Leave>", lambda e: self._draw(self.fill))
        self.bind("<ButtonPress-1>", lambda e: self._draw(self.hover, inset=1))
        self.bind("<ButtonRelease-1>", self._release)

    def _draw(self, fill, inset=0):
        self.delete("all")
        round_rect(self, 1 + inset, 1 + inset, self.w - 1 - inset, self.h - 1 - inset,
                   self.radius, fill=fill, outline=self.outline, width=1.3)
        self.create_text(self.w / 2, self.h / 2, text=self.text_str,
                         fill=self.fg, font=self.font)

    def _release(self, _):
        self._draw(self.hover)
        self.command()


class Segmented(tk.Canvas):
    def __init__(self, parent, options, command, width=250, height=36):
        super().__init__(parent, width=width, height=height, bg=parent["bg"],
                         highlightthickness=0, cursor="hand2")
        self.options, self.command = options, command
        self.w, self.h = width, height
        self.active = 0
        self.font = tkfont.Font(family=FONT, size=10, weight="bold")
        self._draw()
        self.bind("<Button-1>", self._click)

    def _draw(self):
        self.delete("all")
        round_rect(self, 0, 0, self.w, self.h, self.h / 2, fill=SURFACE,
                   outline=BORDER, width=1)
        seg = self.w / len(self.options)
        round_rect(self, self.active * seg + 3, 3, (self.active + 1) * seg - 3,
                   self.h - 3, (self.h - 6) / 2, fill=RAISED, outline="")
        for i, label in enumerate(self.options):
            self.create_text(seg * (i + 0.5), self.h / 2, text=label,
                             fill=FG if i == self.active else MUTED, font=self.font)

    def _click(self, ev):
        idx = max(0, min(int(ev.x // (self.w / len(self.options))), len(self.options) - 1))
        self.select(idx)

    def select(self, idx, notify=True):
        """Switch tab programmatically as well as by click."""
        if idx == self.active:
            return
        self.active = idx
        self._draw()
        if notify:
            self.command(idx)


class ProgressBar(tk.Canvas):
    def __init__(self, parent, width=320, height=6, bg=None):
        super().__init__(parent, width=width, height=height,
                         bg=bg or parent["bg"], highlightthickness=0)
        self.w, self.h = width, height
        self.set(0)

    def set(self, frac):
        frac = max(0.0, min(1.0, frac))
        self.delete("all")
        round_rect(self, 0, 0, self.w, self.h, self.h / 2, fill="#20232f", outline="")
        if frac > 0:
            round_rect(self, 0, 0, max(self.h, self.w * frac), self.h,
                       self.h / 2, fill=BLUE, outline="")


class CalendarGrid(tk.Canvas):
    """Month view: one tile per day, tinted by what's logged. Click to edit."""

    CELL_W, CELL_H, GAP, TOP = 46, 42, 5, 26

    def __init__(self, parent, app):
        w = self.CELL_W * 7 + self.GAP * 6
        super().__init__(parent, width=w, height=self.TOP, bg=SURFACE, highlightthickness=0)
        self.app = app
        self.month = date.today().replace(day=1)
        self.cells = {}
        self.font_day = tkfont.Font(family=FONT, size=10)
        self.font_hdr = tkfont.Font(family=FONT, size=9, weight="bold")
        self.font_tiny = tkfont.Font(family=FONT, size=7)
        self.bind("<Button-1>", self._click)

    def shift(self, months):
        m = self.month.month + months
        self.month = date(self.month.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
        self.redraw()

    def redraw(self):
        self.delete("all")
        self.cells.clear()
        weeks = calendar.Calendar().monthdatescalendar(self.month.year, self.month.month)
        self.configure(height=self.TOP + (self.CELL_H + self.GAP) * len(weeks))
        for i, name in enumerate("MTWTFSS"):
            self.create_text(i * (self.CELL_W + self.GAP) + self.CELL_W / 2, 10,
                             text=name, fill=DIM, font=self.font_hdr)

        data = self.app.data
        today = date.today()
        entries = data["entries"]
        paydays = core.paydays_between(data, weeks[0][0], weeks[-1][-1])
        benefits = set(core.benefit_dates_between(data, weeks[0][0], weeks[-1][-1]))

        for week, days in enumerate(weeks):
            for col, d in enumerate(days):
                if d.month != self.month.month:
                    continue
                x = col * (self.CELL_W + self.GAP)
                y = self.TOP + week * (self.CELL_H + self.GAP)
                e = entries.get(d.isoformat())
                kind = entry_kind(e) if e else None
                fill, text_col = KIND_STYLE[kind]
                is_payday, is_benefit = d in paydays, d in benefits
                if kind is None:
                    if is_payday:
                        fill, text_col = PAYDAY_BG, PAYDAY
                    elif is_benefit:
                        fill, text_col = BENEFIT_BG, BENEFIT

                outline, width = "", 1
                if is_payday:
                    outline, width = PAYDAY, 1.6
                elif is_benefit and kind is None:
                    outline, width = BENEFIT, 1.6
                if d == today:
                    outline, width = BLUE, 1.6

                round_rect(self, x, y, x + self.CELL_W, y + self.CELL_H, 10,
                           fill=fill, outline=outline, width=width)
                self.create_text(x + self.CELL_W / 2, y + self.CELL_H / 2 - 5,
                                 text=str(d.day), fill=text_col, font=self.font_day)
                if is_benefit:
                    # a benefit day can also be a work day, so flag it with a dot
                    cx, cy = x + self.CELL_W - 8, y + 8
                    self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=BENEFIT, outline="")

                # what the day earned wins the label; the dot carries the benefit
                label, colour = None, text_col
                if is_payday:
                    start, end = paydays[d]
                    due = breakdown(data, start, end)["total"]
                    label, colour = (f"£{due:.0f}" if due else "payday"), PAYDAY
                elif e and e["amount"]:
                    label = f"{e['amount']:.0f}"
                elif is_benefit:
                    amt = data.get("benefit_amount")
                    label, colour = (f"£{amt:.0f}" if amt else data.get("benefit_name", "benefit")), BENEFIT
                if label:
                    self.create_text(x + self.CELL_W / 2, y + self.CELL_H / 2 + 9,
                                     text=label, fill=colour, font=self.font_tiny)
                self.cells[(col, week)] = d

    def _click(self, ev):
        col = int(ev.x // (self.CELL_W + self.GAP))
        week = int((ev.y - self.TOP) // (self.CELL_H + self.GAP))
        d = self.cells.get((col, week))
        if d:
            self.app.open_day_editor(d)


class Popup(tk.Toplevel):
    def __init__(self, master, title, w=340, h=400):
        super().__init__(master, bg=BG)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        try:
            self.iconbitmap(str(resource_path("icon.ico")))
        except tk.TclError:
            pass        # icon missing or unsupported platform; not worth failing over
        master.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 20)}")
        self.body = tk.Frame(self, bg=SURFACE)
        self.body.pack(fill="both", expand=True, padx=12, pady=12)


def entry_box(parent, width=8, value="", font=None):
    e = tk.Entry(parent, font=font or tkfont.Font(family=FONT, size=10),
                 width=width, bg=RAISED, fg=FG, insertbackground=FG,
                 relief="flat", justify="center", bd=5)
    if value != "":
        e.insert(0, str(value))
    return e


# ── the app ───────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Work Tracker")
        self.geometry("470x750")
        self.configure(bg=BG)
        self.resizable(False, False)
        try:
            self.iconbitmap(str(resource_path("icon.ico")))
        except tk.TclError:
            pass        # icon missing or unsupported platform; not worth failing over

        self.data = core.load()
        self.queue, self.idx = [], 0

        self.f_h1    = tkfont.Font(family=FONT, size=19, weight="bold")
        self.f_h2    = tkfont.Font(family=FONT, size=13, weight="bold")
        self.f_body  = tkfont.Font(family=FONT, size=11)
        self.f_small = tkfont.Font(family=FONT, size=9)
        self.f_btn   = tkfont.Font(family=FONT, size=11, weight="bold")
        self.f_money = tkfont.Font(family=FONT, size=34, weight="bold")
        self.f_chip  = tkfont.Font(family=FONT, size=9, weight="bold")

        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True, padx=16, pady=14)

        head = tk.Frame(root, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text="Work Tracker", font=self.f_h2, bg=BG, fg=FG).pack(side="left")
        tk.Button(head, text="⚙", font=self.f_h2, bg=BG, fg=MUTED, activebackground=BG,
                  activeforeground=FG, relief="flat", bd=0, cursor="hand2",
                  command=self.open_settings).pack(side="right", padx=(8, 0))
        self.period_chip = tk.Label(head, text="", font=self.f_small, bg=BG, fg=MUTED)
        self.period_chip.pack(side="right")

        self.summary = tk.Frame(root, bg=SURFACE)
        self.summary.pack(fill="x", pady=(12, 0))
        pad = tk.Frame(self.summary, bg=SURFACE)
        pad.pack(fill="x", padx=18, pady=16)
        tk.Label(pad, text="THIS PAY PERIOD", font=self.f_chip, bg=SURFACE, fg=DIM).pack(anchor="w")
        self.total_lbl = tk.Label(pad, text="", font=self.f_money, bg=SURFACE, fg=FG)
        self.total_lbl.pack(anchor="w", pady=(2, 0))
        self.chips = tk.Frame(pad, bg=SURFACE)
        self.chips.pack(anchor="w", pady=(4, 12))
        self.progress = ProgressBar(pad, width=398, height=6, bg=SURFACE)
        self.progress.pack(anchor="w")
        self.period_lbl = tk.Label(pad, text="", font=self.f_small, bg=SURFACE, fg=MUTED)
        self.period_lbl.pack(anchor="w", pady=(7, 0))
        self.benefit_lbl = tk.Label(pad, text="", font=self.f_small, bg=SURFACE, fg=BENEFIT)
        self.benefit_lbl.pack(anchor="w", pady=(3, 0))

        self.tabs = Segmented(root, ["Today", "Calendar"], self.switch_view,
                              width=438, height=34)
        self.tabs.pack(pady=(14, 0))
        self.view = tk.Frame(root, bg=SURFACE)
        self.view.pack(fill="both", expand=True, pady=(12, 0))
        self.today_view = tk.Frame(self.view, bg=SURFACE)
        self.cal_view = tk.Frame(self.view, bg=SURFACE)
        self._build_today()
        self._build_calendar()

        self.after(60, self.first_run_check)

    # ── views ─────────────────────────────────────────────────────────────
    def _build_today(self):
        v = self.today_view
        self.q_icon = tk.Label(v, text="", font=tkfont.Font(family=FONT, size=28),
                               bg=SURFACE, fg=BLUE)
        self.q_icon.pack(pady=(26, 2))
        self.q_head = tk.Label(v, text="", font=self.f_h1, bg=SURFACE, fg=FG,
                               wraplength=400, justify="center")
        self.q_head.pack()
        self.q_date = tk.Label(v, text="", font=self.f_chip, bg=SURFACE, fg=BLUE)
        self.q_date.pack(pady=(7, 0))
        self.q_sub = tk.Label(v, text="", font=self.f_body, bg=SURFACE, fg=MUTED)
        self.q_sub.pack(pady=(6, 0))

        self.q_btns = tk.Frame(v, bg=SURFACE)
        RButton(self.q_btns, "Worked", lambda: self.answer("work"), width=130, height=48,
                fill=GREEN, hover="#33c982", fg="#06251a", font=self.f_btn,
                bg=SURFACE).grid(row=0, column=0, padx=4)
        RButton(self.q_btns, "Sick", lambda: self.answer("sick"), width=95, height=48,
                fill=SURFACE, hover=RAISED, fg=AMBER, font=self.f_btn,
                outline=BORDER, bg=SURFACE).grid(row=0, column=1, padx=4)
        RButton(self.q_btns, "Off", lambda: self.answer("off"), width=95, height=48,
                fill=SURFACE, hover=RAISED, fg=RED, font=self.f_btn,
                outline=BORDER, bg=SURFACE).grid(row=0, column=2, padx=4)
        self.q_btns.pack(pady=(22, 0))

        self.q_link = tk.Button(v, text="worked different hours?", font=self.f_small,
                                bg=SURFACE, fg=MUTED, activeforeground=BLUE,
                                activebackground=SURFACE, relief="flat", bd=0,
                                cursor="hand2", command=self.open_other_hours)
        self.q_link.pack(pady=(14, 0))
        self.q_remaining = tk.Label(v, text="", font=self.f_small, bg=SURFACE, fg=DIM)
        self.q_remaining.pack(pady=(16, 0))

    def _build_calendar(self):
        v = self.cal_view
        nav = tk.Frame(v, bg=SURFACE)
        nav.pack(fill="x", pady=(14, 8), padx=16)
        tk.Button(nav, text="‹", font=self.f_h2, bg=SURFACE, fg=MUTED,
                  activebackground=SURFACE, activeforeground=FG, relief="flat", bd=0,
                  cursor="hand2", command=lambda: self.shift_month(-1)).pack(side="left")
        self.month_lbl = tk.Label(nav, text="", font=self.f_h2, bg=SURFACE, fg=FG)
        self.month_lbl.pack(side="left", expand=True)
        tk.Button(nav, text="›", font=self.f_h2, bg=SURFACE, fg=MUTED,
                  activebackground=SURFACE, activeforeground=FG, relief="flat", bd=0,
                  cursor="hand2", command=lambda: self.shift_month(1)).pack(side="right")

        self.grid_widget = CalendarGrid(v, self)
        self.grid_widget.pack(pady=(0, 6))
        self.legend = tk.Frame(v, bg=SURFACE)
        self.legend.pack(pady=(2, 0))
        tk.Label(v, text="tap any day to change it", font=self.f_small,
                 bg=SURFACE, fg=DIM).pack(pady=(8, 0))

    def rebuild_legend(self):
        for w in self.legend.winfo_children():
            w.destroy()
        items = [("worked", GREEN), ("sick", AMBER), ("off", DIM),
                 ("extra", BLUE), ("payday", PAYDAY)]
        if self.data.get("benefit_anchor"):
            items.append((self.data.get("benefit_name") or "benefit", BENEFIT))
        for label, col in items:
            item = tk.Frame(self.legend, bg=SURFACE)
            item.pack(side="left", padx=6)
            tk.Label(item, text="●", font=self.f_small, bg=SURFACE, fg=col).pack(side="left")
            tk.Label(item, text=label, font=self.f_small, bg=SURFACE,
                     fg=MUTED).pack(side="left", padx=(3, 0))

    def switch_view(self, idx):
        self.today_view.pack_forget()
        self.cal_view.pack_forget()
        if idx == 0:
            self.today_view.pack(fill="both", expand=True)
        else:
            self.grid_widget.redraw()
            self.cal_view.pack(fill="both", expand=True)

    def shift_month(self, n):
        self.grid_widget.shift(n)
        self.month_lbl.config(text=self.grid_widget.month.strftime("%B %Y"))

    # ── state ─────────────────────────────────────────────────────────────
    def first_run_check(self):
        if not core.is_configured(self.data):
            self.open_settings(first_run=True)
        else:
            self.refresh()

    def refresh(self):
        if not core.is_configured(self.data):
            return
        core.auto_skip_non_workdays(self.data)
        self.queue = core.pending_dates(self.data)
        self.idx = 0
        self.rebuild_legend()
        self.month_lbl.config(text=self.grid_widget.month.strftime("%B %Y"))
        self.switch_view(self.tabs.active)
        self.update_summary()
        self.show_question()

    def update_summary(self):
        period = core.current_pay_period(self.data)
        if not period:
            return
        start, end, payday = period
        b = breakdown(self.data, start, end)
        self.total_lbl.config(text=money(b["total"]))

        for w in self.chips.winfo_children():
            w.destroy()
        parts = [("work", b["work"], GREEN)]
        if b["sick"]:
            parts.append(("sick pay", b["sick"], AMBER))
        if b["adjustment"]:
            parts.append(("extra", b["adjustment"], BLUE))
        for label, amount, col in parts:
            chip = tk.Frame(self.chips, bg=SURFACE)
            chip.pack(side="left", padx=(0, 12))
            tk.Label(chip, text="●", font=self.f_small, bg=SURFACE, fg=col).pack(side="left")
            tk.Label(chip, text=f"{label} {money(amount)}", font=self.f_small,
                     bg=SURFACE, fg=MUTED).pack(side="left", padx=(3, 0))

        today = date.today()
        self.progress.set(((today - start).days + 1) / core.PAY_PERIOD_DAYS)
        left = (payday - today).days
        self.period_lbl.config(
            text=f"{b['days_worked']} days worked · {fmt_hours(b['hours'])}"
                 f"   ·   paid {payday.strftime('%a %d %b')}"
                 f"{f' · {left} days away' if left > 0 else ''}")
        self.period_chip.config(text=f"{start.strftime('%d %b')} – {end.strftime('%d %b')}")

        nxt = core.next_benefit(self.data)
        if nxt:
            days = (nxt - today).days
            amt = self.data.get("benefit_amount")
            name = self.data.get("benefit_name") or "benefit"
            self.benefit_lbl.config(
                text=f"● next {name} · {nxt.strftime('%a %d %b')} · "
                     f"{'today' if days == 0 else f'{days} days away'}"
                     + (f" · {money(amt)}" if amt else ""))
        else:
            self.benefit_lbl.config(text="")

    def show_question(self):
        if self.idx >= len(self.queue):
            self.q_icon.config(text="✓", fg=GREEN)
            self.q_head.config(text="All caught up")
            self.q_date.config(text="")
            self.q_sub.config(text="Nothing left to log today")
            self.q_btns.pack_forget()
            self.q_link.pack_forget()
            self.q_remaining.config(text="")
            return
        d = self.queue[self.idx]
        today = date.today()
        self.q_icon.config(text="🗓", fg=BLUE)
        self.q_head.config(text=f"Did you work {d.strftime('%A %d %B')}?")
        if d == today:
            when = "TODAY"
        elif d == today - timedelta(days=1):
            when = f"YESTERDAY  ·  {d.isoformat()}"
        else:
            when = f"{(today - d).days} DAYS AGO  ·  {d.isoformat()}"
        self.q_date.config(text=when)
        sick = sick_pay_for(d, self.data)
        self.q_sub.config(
            text=f"{fmt_hours(default_hours(self.data))} × {money(rate_for(d, self.data))}"
                 f" = {money(day_pay(d, self.data))}"
                 + (f"   ·   sick = {money(sick)}" if sick else ""))
        self.q_btns.pack(pady=(22, 0))
        self.q_link.pack(pady=(14, 0))
        remaining = len(self.queue) - self.idx - 1
        self.q_remaining.config(
            text=f"{remaining} more day{'s' if remaining != 1 else ''} to go" if remaining else "")

    def answer(self, kind, hours=None):
        self.write_day(self.queue[self.idx], kind, hours)
        self.idx += 1
        self.show_question()
        self.update_summary()

    def write_day(self, d, kind, hours=None, amount=None, note=None):
        self.data["entries"][d.isoformat()] = core.make_entry(
            d, kind, self.data, hours=hours, amount=amount, note=note)
        core.save(self.data)

    # ── settings ──────────────────────────────────────────────────────────
    def open_settings(self, first_run=False):
        win = Popup(self, "Set up Work Tracker" if first_run else "Settings", w=420, h=770)
        b = win.body
        d = self.data

        tk.Label(b, text="Setup" if first_run else "Settings", font=self.f_h2,
                 bg=SURFACE, fg=FG).pack(pady=(14, 2))
        tk.Label(b, text="Leave a day blank if you don't work it",
                 font=self.f_small, bg=SURFACE, fg=MUTED).pack(pady=(0, 10))

        fields = {}

        def section(title):
            tk.Label(b, text=title, font=self.f_chip, bg=SURFACE,
                     fg=DIM).pack(anchor="w", padx=22, pady=(10, 4))

        def row(parent, label, key, value, width=8, suffix=""):
            r = tk.Frame(parent, bg=SURFACE)
            r.pack(fill="x", padx=22, pady=2)
            tk.Label(r, text=label, font=self.f_small, bg=SURFACE, fg=MUTED,
                     width=15, anchor="w").pack(side="left")
            e = entry_box(r, width=width, value="" if value is None else value)
            e.pack(side="left")
            if suffix:
                tk.Label(r, text=suffix, font=self.f_small, bg=SURFACE,
                         fg=DIM).pack(side="left", padx=(6, 0))
            fields[key] = e

        section("HOURLY RATE PER DAY  (£)")
        # two columns, so seven days don't push the Save button off a small screen
        grid = tk.Frame(b, bg=SURFACE)
        grid.pack(fill="x", padx=22)
        for i, (key, name) in enumerate(zip(DAY_KEYS, DAY_NAMES, strict=True)):
            cell = tk.Frame(grid, bg=SURFACE)
            cell.grid(row=i % 4, column=i // 4, sticky="w", pady=2, padx=(0, 10))
            tk.Label(cell, text=name[:3], font=self.f_small, bg=SURFACE, fg=MUTED,
                     width=4, anchor="w").pack(side="left")
            e = entry_box(cell, width=7,
                          value="" if d["rates"].get(key) is None else d["rates"][key])
            e.pack(side="left")
            fields[f"rate_{key}"] = e

        section("SHIFT")
        row(b, "Hours per day", "hours", d.get("hours_per_day") or "", suffix="hours")
        row(b, "Sick pay per day", "ssp", d.get("ssp_daily") or "", suffix="£")

        section("PAY CYCLE  (4-weekly)")
        row(b, "Period end date", "anchor", d.get("period_end_anchor") or "",
            width=12, suffix="YYYY-MM-DD")
        row(b, "Paid N days later", "offset", d.get("payday_offset_days", 0), suffix="days")

        section("BENEFIT PAYMENT  (optional)")
        row(b, "Name", "bname", d.get("benefit_name") or "", width=10)
        row(b, "Next payment", "banchor", d.get("benefit_anchor") or "",
            width=12, suffix="YYYY-MM-DD")
        row(b, "Amount", "bamount", d.get("benefit_amount") or "", suffix="£")
        row(b, "Every", "binterval", d.get("benefit_interval_days", 28), suffix="days")

        err = tk.Label(b, text="", font=self.f_small, bg=SURFACE, fg=RED, wraplength=340)
        err.pack(pady=(10, 0))

        def num(key, required=False, integer=False):
            raw = fields[key].get().strip().replace("£", "")
            if not raw:
                if required:
                    raise ValueError(f"{key} is required")
                return None
            return int(float(raw)) if integer else float(raw)

        def save():
            try:
                rates = {k: num(f"rate_{k}") for k in DAY_KEYS}
                if not any(rates.values()):
                    err.config(text="Set an hourly rate for at least one day")
                    return
                hours = num("hours")
                if not hours:
                    err.config(text="Hours per day is required")
                    return
                anchor_raw = fields["anchor"].get().strip()
                if not anchor_raw:
                    err.config(text="Period end date is required — "
                                    "the last day of a pay period on a payslip")
                    return
                anchor = date.fromisoformat(anchor_raw)
                benefit_raw = fields["banchor"].get().strip()
                benefit = date.fromisoformat(benefit_raw).isoformat() if benefit_raw else None
            except ValueError as exc:
                err.config(text=f"Check your entries — dates are YYYY-MM-DD ({exc})")
                return

            d["rates"] = rates
            d["hours_per_day"] = hours
            d["ssp_daily"] = num("ssp") or 0.0
            d["period_end_anchor"] = anchor.isoformat()
            d["payday_offset_days"] = num("offset", integer=True) or 0
            d["benefit_name"] = fields["bname"].get().strip() or "benefit"
            d["benefit_anchor"] = benefit
            d["benefit_amount"] = num("bamount")
            d["benefit_interval_days"] = num("binterval", integer=True) or 28
            core.save(d)
            win.destroy()
            self.refresh()

        RButton(b, "Save", save, width=130, height=42, fill=GREEN, hover="#33c982",
                fg="#06251a", font=self.f_btn, bg=SURFACE).pack(pady=12)
        if first_run:
            win.protocol("WM_DELETE_WINDOW", self.destroy)
        else:
            tk.Button(b, text="Cancel", font=self.f_small, bg=SURFACE, fg=MUTED,
                      activeforeground=FG, activebackground=SURFACE, relief="flat",
                      bd=0, cursor="hand2", command=win.destroy).pack()

    # ── day editor ────────────────────────────────────────────────────────
    def open_day_editor(self, d):
        win = Popup(self, d.strftime("%d %b %Y"), w=330, h=400)
        b = win.body
        existing = self.data["entries"].get(d.isoformat())

        tk.Label(b, text=d.strftime("%A"), font=self.f_small, bg=SURFACE,
                 fg=MUTED).pack(pady=(18, 0))
        tk.Label(b, text=d.strftime("%d %B %Y"), font=self.f_h2, bg=SURFACE, fg=FG).pack()
        state_lbl = tk.Label(b, text="", font=self.f_body, bg=SURFACE, fg=MUTED)
        state_lbl.pack(pady=(10, 0))

        def describe():
            e = self.data["entries"].get(d.isoformat())
            if not e:
                return "not logged yet"
            k = entry_kind(e)
            if k == "work":
                return f"worked {fmt_hours(e.get('hours', 0))} · {money(e['amount'])}"
            if k == "sick":
                return f"off sick · {money(e['amount'])}"
            if k == "adjustment":
                return f"extra · {money(e['amount'])}"
            return "day off"

        state_lbl.config(text=describe())

        hrow = tk.Frame(b, bg=SURFACE)
        hrow.pack(pady=(14, 4))
        tk.Label(hrow, text="hours", font=self.f_small, bg=SURFACE,
                 fg=MUTED).pack(side="left", padx=(0, 6))
        he = entry_box(hrow, width=6,
                       value=f"{(existing or {}).get('hours') or default_hours(self.data):g}")
        he.pack(side="left")

        rate = rate_for(d, self.data)
        hint = tk.Label(b, text="", font=self.f_small, bg=SURFACE, fg=DIM)
        hint.pack(pady=(6, 0))

        def update_hint(*_):
            try:
                h = float(he.get().strip())
            except ValueError:
                hint.config(text="enter hours, e.g. 2.5")
                return
            hint.config(text="not a working day" if rate is None
                        else f"{fmt_hours(h)} × {money(rate)} = {money(round(h * rate, 2))}")

        he.bind("<KeyRelease>", update_hint)
        update_hint()

        def apply(kind):
            h = None
            if kind == "work":
                if rate is None:
                    hint.config(text="no rate set for this weekday — see Settings")
                    return
                try:
                    h = float(he.get().strip())
                except ValueError:
                    hint.config(text="enter hours, e.g. 2.5")
                    return
            self.write_day(d, kind, h)
            state_lbl.config(text=describe(), fg=GREEN)
            self.grid_widget.redraw()
            self.update_summary()
            self.queue = core.pending_dates(self.data)
            self.idx = 0
            self.show_question()

        btns = tk.Frame(b, bg=SURFACE)
        btns.pack(pady=(16, 0))
        RButton(btns, "Worked", lambda: apply("work"), width=94, height=42, fill=GREEN,
                hover="#33c982", fg="#06251a", font=self.f_btn,
                bg=SURFACE).grid(row=0, column=0, padx=3)
        RButton(btns, "Sick", lambda: apply("sick"), width=72, height=42, fill=SURFACE,
                hover=RAISED, fg=AMBER, font=self.f_btn, outline=BORDER,
                bg=SURFACE).grid(row=0, column=1, padx=3)
        RButton(btns, "Off", lambda: apply("off"), width=72, height=42, fill=SURFACE,
                hover=RAISED, fg=RED, font=self.f_btn, outline=BORDER,
                bg=SURFACE).grid(row=0, column=2, padx=3)

        def clear():
            self.data["entries"].pop(d.isoformat(), None)
            core.save(self.data)
            state_lbl.config(text="not logged yet", fg=MUTED)
            self.grid_widget.redraw()
            self.update_summary()

        tk.Button(b, text="clear this day", font=self.f_small, bg=SURFACE, fg=DIM,
                  activeforeground=RED, activebackground=SURFACE, relief="flat", bd=0,
                  cursor="hand2", command=clear).pack(pady=(14, 0))
        tk.Button(b, text="Done", font=self.f_small, bg=SURFACE, fg=BLUE,
                  activeforeground=BLUE, activebackground=SURFACE, relief="flat", bd=0,
                  cursor="hand2", command=win.destroy).pack(pady=(6, 0))

    def open_other_hours(self):
        if self.idx >= len(self.queue):
            return
        d = self.queue[self.idx]
        win = Popup(self, "Different hours", w=300, h=270)
        b = win.body
        rate = rate_for(d, self.data)
        tk.Label(b, text=d.strftime("%A %d %B"), font=self.f_h2,
                 bg=SURFACE, fg=FG).pack(pady=(24, 12))
        e = entry_box(b, width=8, value=f"{default_hours(self.data):g}",
                      font=self.f_body)
        e.pack()
        prev = tk.Label(b, text="", font=self.f_small, bg=SURFACE, fg=MUTED)
        prev.pack(pady=(10, 0))

        def upd(*_):
            try:
                h = float(e.get().strip())
            except ValueError:
                prev.config(text="enter hours, e.g. 2.5")
                return
            prev.config(text=f"{fmt_hours(h)} × {money(rate)} = {money(round(h * rate, 2))}")

        e.bind("<KeyRelease>", upd)
        upd()

        def go():
            try:
                h = float(e.get().strip())
            except ValueError:
                return
            win.destroy()
            self.answer("work", hours=h)

        RButton(b, "Log it", go, width=120, height=42, fill=GREEN, hover="#33c982",
                fg="#06251a", font=self.f_btn, bg=SURFACE).pack(pady=18)
        e.focus()


def main():
    claim_taskbar_identity()
    App().mainloop()


if __name__ == "__main__":
    main()

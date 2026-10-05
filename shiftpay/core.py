"""Data model for ShiftPay.

Everything that is specific to one person's job — hourly rates, which days
they work, sick pay, when the employer's pay period ends — lives in the data
file, never in the code. A fresh install starts with nothing configured and
asks on first run.
"""
import json
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

APP_NAME = "ShiftPay"
DATA_FILENAME = "work_data.json"

PAY_PERIOD_DAYS = 28
LOOKBACK_DAYS = 60          # how far back the catch-up queue looks
DEFAULT_PAYDAY_OFFSET = 0   # payday lands this many days after the period ends
DEFAULT_HOURS = 0.0
DEFAULT_PIP_INTERVAL = 28

# Monday-first, matching date.weekday()
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]


def default_data():
    return {
        "rates": {k: None for k in DAY_KEYS},   # None = not a working day
        "hours_per_day": DEFAULT_HOURS,
        "ssp_daily": 0.0,
        "period_end_anchor": None,              # a known pay-period END date
        "payday_offset_days": DEFAULT_PAYDAY_OFFSET,
        # Optional recurring benefit payment, shown on the calendar only and
        # never counted as earnings.
        "benefit_name": "Benefit",
        "benefit_anchor": None,
        "benefit_interval_days": DEFAULT_PIP_INTERVAL,
        "benefit_amount": None,
        "entries": {},
    }


LEGACY_APP_NAME = "WorkTracker"     # the app was called this before v1.1


def data_dir():
    """Per-user storage, so the packaged app and the scripts share one file
    and rebuilding or reinstalling never touches it."""
    override = os.environ.get("SHIFTPAY_HOME")
    if override:
        d = Path(override)
    else:
        base = (os.environ.get("APPDATA")
                or os.environ.get("XDG_DATA_HOME")
                or str(Path.home()))
        d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_file():
    """The data file, carrying across anything left under the old app name."""
    path = data_dir() / DATA_FILENAME
    if not path.exists() and not os.environ.get("SHIFTPAY_HOME"):
        base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
        if base:
            legacy = Path(base) / LEGACY_APP_NAME / DATA_FILENAME
            if legacy.exists():
                shutil.copy2(legacy, path)
    return path


# ── load / save ───────────────────────────────────────────────────────────
def _migrate(data):
    """Bring older data files up to the current schema. Each step is additive
    so no amount is ever recalculated behind the user's back."""
    # single flat rate -> per-weekday rates
    if "rate" in data:
        old = data.pop("rate")
        data["rates"] = {k: old for k in DAY_KEYS[:6]} | {"sun": None}

    rates = data.get("rates") or {}
    # mon_fri/sat/sun grouping -> one rate per weekday
    if "mon_fri" in rates:
        weekday = rates.get("mon_fri")
        data["rates"] = {
            "mon": weekday, "tue": weekday, "wed": weekday,
            "thu": weekday, "fri": weekday,
            "sat": rates.get("sat"), "sun": rates.get("sun"),
        }
    for key in DAY_KEYS:
        data.setdefault("rates", {}).setdefault(key, None)

    # PIP keys were once pip_*; they are now the generic benefit_*. The old
    # schema had no name field because PIP was hardcoded, so keep that label
    # rather than silently renaming someone's payment to "Benefit".
    if any(k in data for k in ("pip_anchor", "pip_interval_days", "pip_amount")):
        data.setdefault("benefit_name", "PIP")
    for old_key, new_key in (("pip_anchor", "benefit_anchor"),
                             ("pip_interval_days", "benefit_interval_days"),
                             ("pip_amount", "benefit_amount")):
        if old_key in data:
            data.setdefault(new_key, data.pop(old_key))

    defaults = default_data()
    for key, value in defaults.items():
        data.setdefault(key, value)

    # entries predating hour tracking stored a day's pay without its hours
    for e in data["entries"].values():
        e.setdefault("hours", 0 if not e.get("worked", True) else data["hours_per_day"])
    return data


def load():
    path = data_file()
    if not path.exists():
        legacy = Path(__file__).resolve().parent.parent / DATA_FILENAME
        if legacy.exists():
            shutil.copy2(legacy, path)
        else:
            return default_data()
    with open(path, encoding="utf-8") as f:
        return _migrate(json.load(f))


def save(data):
    path = data_file()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)            # atomic, so a crash mid-write can't truncate


def is_configured(data):
    return any(v for v in data["rates"].values()) and bool(data.get("period_end_anchor"))


# ── money and days ────────────────────────────────────────────────────────
def money(n):
    return f"£{n:,.2f}"


def fmt_hours(h):
    return f"{h:g}h"


def rate_key_for(d):
    return DAY_KEYS[d.weekday()]


def rate_for(d, data):
    """Hourly rate for that weekday, or None if it isn't a working day."""
    return data["rates"].get(rate_key_for(d))


def works_on(d, data):
    return bool(rate_for(d, data))


def default_hours(data):
    return data.get("hours_per_day", DEFAULT_HOURS)


def day_pay(d, data, hours=None):
    rate = rate_for(d, data)
    if rate is None:
        return None
    h = default_hours(data) if hours is None else hours
    return round(h * rate, 2)


def ssp_daily(data):
    return data.get("ssp_daily") or 0.0


def sick_pay_for(d, data):
    """Sick pay is only payable on qualifying days — the days you'd work."""
    return ssp_daily(data) if works_on(d, data) else 0.0


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ── entries ───────────────────────────────────────────────────────────────
def entry_kind(e):
    """One of 'work', 'sick', 'adjustment', 'off'."""
    if e.get("adjustment"):
        return "adjustment"
    if e.get("sick"):
        return "sick"
    if e.get("worked", True):
        return "work"
    return "off"


def make_entry(d, kind, data, hours=None, amount=None, note=None):
    if kind == "work":
        h = default_hours(data) if hours is None else hours
        return {"amount": day_pay(d, data, h) if amount is None else amount,
                "hours": h, "note": note or "", "worked": True}
    if kind == "sick":
        return {"amount": sick_pay_for(d, data) if amount is None else amount,
                "hours": 0, "note": note or "off sick", "worked": False, "sick": True}
    if kind == "adjustment":
        return {"amount": amount or 0.0, "hours": 0,
                "note": note or "adjustment", "worked": False, "adjustment": True}
    return {"amount": 0, "hours": 0, "note": note or "day off", "worked": False}


def tracking_start(data):
    """Earliest date still worth asking about: the first day ever logged,
    capped to a sane window so the catch-up queue can't explode."""
    today = date.today()
    if not data["entries"]:
        return today
    earliest = min(date.fromisoformat(d) for d in data["entries"])
    return max(earliest, today - timedelta(days=LOOKBACK_DAYS))


def pending_dates(data):
    """Every unanswered working day between the start of tracking and today.

    Scans the whole window rather than only dates after the last entry, so a
    day left unanswered — app closed mid-catch-up, or a gap left by skipping a
    non-working day — is picked up again instead of being lost.
    """
    entries = data["entries"]
    return [d for d in daterange(tracking_start(data), date.today())
            if d.isoformat() not in entries and works_on(d, data)]


def auto_skip_non_workdays(data):
    """Silently record non-working days so they never need asking about."""
    if not data["entries"]:
        return False
    changed = False
    for d in daterange(tracking_start(data), date.today()):
        if d.isoformat() not in data["entries"] and not works_on(d, data):
            data["entries"][d.isoformat()] = {
                "amount": 0, "hours": 0, "note": "not a work day", "worked": False}
            changed = True
    if changed:
        save(data)
    return changed


# ── pay periods ───────────────────────────────────────────────────────────
def pay_period_for(d, data):
    """The (start, end, payday) of the period a given date falls in.

    Periods are anchored on a known period END date. The payslip lands
    `payday_offset_days` after the period closes, so the payday for the period
    you're working now can be well after the period itself ends.
    """
    if not data.get("period_end_anchor"):
        return None
    end = date.fromisoformat(data["period_end_anchor"])
    offset = data.get("payday_offset_days", DEFAULT_PAYDAY_OFFSET)
    while end < d:
        end += timedelta(days=PAY_PERIOD_DAYS)
    while end - timedelta(days=PAY_PERIOD_DAYS) >= d:
        end -= timedelta(days=PAY_PERIOD_DAYS)
    return (end - timedelta(days=PAY_PERIOD_DAYS - 1), end,
            end + timedelta(days=offset))


def current_pay_period(data, today=None):
    return pay_period_for(today or date.today(), data)


def paydays_between(data, first, last):
    """{payday: (period_start, period_end)} for every payday in the range."""
    if not data.get("period_end_anchor"):
        return {}
    anchor = date.fromisoformat(data["period_end_anchor"])
    offset = data.get("payday_offset_days", DEFAULT_PAYDAY_OFFSET)
    out = {}
    p = anchor + timedelta(days=offset)
    while p > first:
        p -= timedelta(days=PAY_PERIOD_DAYS)
    while p <= last:
        if p >= first:
            end = p - timedelta(days=offset)
            out[p] = (end - timedelta(days=PAY_PERIOD_DAYS - 1), end)
        p += timedelta(days=PAY_PERIOD_DAYS)
    return out


# ── benefit payments (calendar only, never counted as pay) ────────────────
def benefit_dates_between(data, first, last):
    if not data.get("benefit_anchor"):
        return []
    step = data.get("benefit_interval_days", DEFAULT_PIP_INTERVAL)
    d = date.fromisoformat(data["benefit_anchor"])
    while d > first:
        d -= timedelta(days=step)
    out = []
    while d <= last:
        if d >= first:
            out.append(d)
        d += timedelta(days=step)
    return out


def next_benefit(data, today=None):
    if not data.get("benefit_anchor"):
        return None
    step = data.get("benefit_interval_days", DEFAULT_PIP_INTERVAL)
    today = today or date.today()
    d = date.fromisoformat(data["benefit_anchor"])
    while d < today:
        d += timedelta(days=step)
    while d - timedelta(days=step) >= today:
        d -= timedelta(days=step)
    return d


# ── reporting ─────────────────────────────────────────────────────────────
def breakdown(data, start=None, end=None):
    """Totals by kind over a date range, or everything if no range is given."""
    out = {"work": 0.0, "sick": 0.0, "adjustment": 0.0, "hours": 0.0,
           "days_worked": 0, "days_sick": 0, "days_off": 0}
    for d_iso, e in data["entries"].items():
        d = date.fromisoformat(d_iso)
        if (start and d < start) or (end and d > end):
            continue
        kind = entry_kind(e)
        if kind == "work":
            out["work"] += e["amount"]
            out["hours"] += e.get("hours", 0)
            out["days_worked"] += 1
        elif kind == "sick":
            out["sick"] += e["amount"]
            out["days_sick"] += 1
        elif kind == "adjustment":
            out["adjustment"] += e["amount"]
        else:
            out["days_off"] += 1
    out["total"] = out["work"] + out["sick"] + out["adjustment"]
    return out

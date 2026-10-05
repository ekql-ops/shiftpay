#!/usr/bin/env python3
"""Command-line interface for Work Tracker.

Everything the desktop app does, scriptable. Useful for bulk edits — logging
a fortnight of sickness, re-pricing history after a pay rise — and for
checking figures without opening a window.
"""
import argparse
import sys
from datetime import date, timedelta

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
)


# ── settings ──────────────────────────────────────────────────────────────
def cmd_rate(args, data):
    if args.day is None:
        for key, name in zip(DAY_KEYS, DAY_NAMES, strict=True):
            r = data["rates"].get(key)
            print(f"  {name:<10} {money(r) + '/hr' if r else '—'}")
        return
    key = args.day[:3].lower()
    if key not in DAY_KEYS:
        print(f"Unknown day '{args.day}'. Use mon/tue/wed/thu/fri/sat/sun.")
        sys.exit(1)
    data["rates"][key] = None if args.amount is None or args.amount <= 0 else args.amount
    core.save(data)
    r = data["rates"][key]
    print(f"{DAY_NAMES[DAY_KEYS.index(key)]}: " + (f"{money(r)}/hr" if r else "not a working day"))


def cmd_hours(args, data):
    if args.amount is None:
        print(f"Standard day: {fmt_hours(default_hours(data))}")
        return
    data["hours_per_day"] = args.amount
    core.save(data)
    print(f"Standard day set to {fmt_hours(args.amount)}")


def cmd_ssp(args, data):
    if args.amount is None:
        print(f"Sick pay per qualifying day: {money(core.ssp_daily(data))}")
        return
    data["ssp_daily"] = args.amount
    core.save(data)
    print(f"Sick pay set to {money(args.amount)} per qualifying day")


def cmd_payday(args, data):
    if args.date:
        data["period_end_anchor"] = date.fromisoformat(args.date).isoformat()
    if args.offset is not None:
        data["payday_offset_days"] = args.offset
    if args.date or args.offset is not None:
        core.save(data)
    period = core.current_pay_period(data)
    if not period:
        print("No pay period set. Use: work payday YYYY-MM-DD (a period END date)")
        return
    start, end, payday = period
    print(f"Period {start.isoformat()} to {end.isoformat()}, paid {payday.isoformat()}")
    print(f"(payday falls {data.get('payday_offset_days', 0)} days after the period ends)")


def cmd_benefit(args, data):
    """A recurring benefit payment: calendar and reminders only, never pay."""
    if args.date:
        data["benefit_anchor"] = date.fromisoformat(args.date).isoformat()
    if args.amount is not None:
        data["benefit_amount"] = args.amount
    if args.every is not None:
        data["benefit_interval_days"] = args.every
    if args.name:
        data["benefit_name"] = args.name
    if any(v is not None for v in (args.date, args.amount, args.every, args.name)):
        core.save(data)

    nxt = core.next_benefit(data)
    if not nxt:
        print("No benefit payment set. Use: work benefit 2026-10-29 --amount 428")
        return
    step = data.get("benefit_interval_days", 28)
    name = data.get("benefit_name") or "benefit"
    amt = data.get("benefit_amount")
    print(f"{name} every {step} days" + (f", {money(amt)} each" if amt else ""))
    d = nxt
    for _ in range(4):
        print(f"  {d.strftime('%A %d %B %Y')}")
        d += timedelta(days=step)


# ── logging ───────────────────────────────────────────────────────────────
def parse_date(s):
    return date.today().isoformat() if s is None else date.fromisoformat(s).isoformat()


def already_logged(data, d_iso, force):
    existing = data["entries"].get(d_iso)
    if not existing or force:
        return False
    kind = entry_kind(existing)
    desc = {"work": f"{fmt_hours(existing.get('hours', 0))} = {money(existing['amount'])}",
            "sick": f"off sick, {money(existing['amount'])}",
            "adjustment": f"extra {money(existing['amount'])}"}.get(kind, "day off")
    print(f"{d_iso} is already registered ({desc}). Use --force to change it.")
    return True


def _write(data, d, kind, **kw):
    data["entries"][d.isoformat()] = core.make_entry(d, kind, data, **kw)


def cmd_log(args, data):
    d_iso = parse_date(args.date)
    if already_logged(data, d_iso, args.force):
        sys.exit(1)
    d = date.fromisoformat(d_iso)
    if rate_for(d, data) is None and args.amount is None:
        print(f"{DAY_NAMES[d.weekday()]} has no rate set. Use: work rate {DAY_KEYS[d.weekday()]} N")
        sys.exit(1)
    hours = args.hours if args.hours is not None else default_hours(data)
    _write(data, d, "work", hours=hours, amount=args.amount, note=args.note)
    core.save(data)
    print(f"Logged {d_iso}: {fmt_hours(hours)} = {money(data['entries'][d_iso]['amount'])}")


def cmd_off(args, data):
    d_iso = parse_date(args.date)
    if already_logged(data, d_iso, args.force):
        sys.exit(1)
    _write(data, date.fromisoformat(d_iso), "off", note=args.note)
    core.save(data)
    print(f"Logged {d_iso}: day off (no pay)")


def cmd_sick(args, data):
    start = date.fromisoformat(parse_date(args.date))
    end = date.fromisoformat(args.until) if args.until else start
    if end < start:
        print("End date is before the start date.")
        sys.exit(1)
    clashes = [d.isoformat() for d in core.daterange(start, end)
               if d.isoformat() in data["entries"]]
    if clashes and not args.force:
        print(f"{len(clashes)} day(s) in that range are already registered "
              f"({clashes[0]}{'...' if len(clashes) > 1 else ''}). Use --force to overwrite.")
        sys.exit(1)

    total, qualifying = 0.0, 0
    for d in core.daterange(start, end):
        _write(data, d, "sick", note=args.note)
        pay = data["entries"][d.isoformat()]["amount"]
        total += pay
        qualifying += 1 if pay else 0
    core.save(data)
    span = start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
    print(f"Logged sick: {span}")
    print(f"{qualifying} qualifying day(s) x {money(core.ssp_daily(data))} = {money(total)}")


def cmd_adjust(args, data):
    d_iso = parse_date(args.date)
    if already_logged(data, d_iso, args.force):
        sys.exit(1)
    _write(data, date.fromisoformat(d_iso), "adjustment",
           amount=args.amount, note=args.note)
    core.save(data)
    print(f"Logged {d_iso}: extra {money(args.amount)} ({args.note or 'adjustment'})")


def cmd_remove(args, data):
    d = parse_date(args.date)
    if d in data["entries"]:
        del data["entries"][d]
        core.save(data)
        print(f"Removed entry for {d}")
    else:
        print(f"No entry found for {d}")


# ── reporting ─────────────────────────────────────────────────────────────
TAGS = {"work": "WORK", "sick": "SICK", "adjustment": "EXTRA", "off": "OFF "}


def _filtered(data, month=None):
    items = sorted(data["entries"].items())
    return [(d, e) for d, e in items if d.startswith(month)] if month else items


def cmd_list(args, data):
    items = _filtered(data, args.month)
    if not items:
        print("No entries found.")
        return
    for d, e in items:
        kind = entry_kind(e)
        hrs = f"{fmt_hours(e.get('hours', 0)):>5}" if kind == "work" else "     "
        note = f"  - {e['note']}" if e.get("note") else ""
        print(f"{d}  [{TAGS[kind]}] {hrs}  {money(e['amount'])}{note}")


def cmd_total(args, data):
    b = breakdown({"entries": dict(_filtered(data, args.month))})
    scope = f"for {args.month}" if args.month else "overall"
    extra = f" + extra {money(b['adjustment'])}" if b["adjustment"] else ""
    print(f"Total {scope}: {money(b['total'])}   "
          f"(work {money(b['work'])} + sick {money(b['sick'])}{extra})")
    print(f"Worked: {b['days_worked']} days / {fmt_hours(b['hours'])}"
          f"  |  Sick: {b['days_sick']}  |  Off: {b['days_off']}")


def cmd_period(args, data):
    period = core.current_pay_period(data)
    if not period:
        print("No pay period set. Use: work payday YYYY-MM-DD (a period END date)")
        return
    start, end, payday = period
    b = breakdown(data, start, end)
    print(f"Current pay period: {start.isoformat()} to {end.isoformat()}")
    print(f"  work   {money(b['work']):>10}   ({b['days_worked']} days / {fmt_hours(b['hours'])})")
    print(f"  sick   {money(b['sick']):>10}   ({b['days_sick']} days)")
    if b["adjustment"]:
        print(f"  extra  {money(b['adjustment']):>10}")
    print(f"  TOTAL  {money(b['total']):>10}")
    print(f"Paid on: {payday.strftime('%A %d %B %Y')}")


def cmd_forecast(args, data):
    """Project earnings to a date, grouped by the payday each period lands on."""
    today = date.today()
    end = date.fromisoformat(args.until)
    if end < today:
        print("Forecast end date is in the past.")
        sys.exit(1)

    periods = {}

    def bucket(d):
        p = core.pay_period_for(d, data)
        if not p:
            return None
        return periods.setdefault(p[2], {"start": p[0], "end": p[1], "work": 0.0,
                                         "sick": 0.0, "extra": 0.0, "projected": 0.0})

    for d_iso, e in data["entries"].items():
        b = bucket(date.fromisoformat(d_iso))
        if b is None:
            continue
        kind = entry_kind(e)
        if kind in ("sick", "work"):
            b[kind] += e["amount"]
        elif kind == "adjustment":
            b["extra"] += e["amount"]

    projected = 0
    assume_sick = args.assume == "sick"
    # starts at today: if today isn't logged yet it still counts toward the forecast
    for d in core.daterange(today, end):
        if d.isoformat() in data["entries"] or not core.works_on(d, data):
            continue
        pay = core.sick_pay_for(d, data) if assume_sick else day_pay(d, data)
        if not pay:
            continue
        b = bucket(d)
        if b is not None:
            b["projected"] += pay
            projected += 1

    print(f"Forecast to {end.strftime('%a %d %b %Y')}, assuming {args.assume} throughout")
    print(f"({projected} projected days)\n")
    grand = 0.0
    for payday in sorted(periods):
        b = periods[payday]
        subtotal = b["work"] + b["sick"] + b["extra"] + b["projected"]
        if not subtotal:
            continue
        grand += subtotal
        print(f"Paid {payday.strftime('%a %d %b %Y')}  (period "
              f"{b['start'].strftime('%d %b')}-{b['end'].strftime('%d %b')})")
        for label, key in (("work logged", "work"), ("sick logged", "sick"),
                           ("extra", "extra"), ("projected", "projected")):
            if b[key]:
                print(f"    {label:<16} {money(b[key])}")
        print(f"    {'total':<16} {money(subtotal)}\n")
    print(f"Total across all paydays: {money(grand)}")


def cmd_recalc(args, data):
    """Re-price every logged day at the current rates. Also overwrites any
    per-day --amount overrides."""
    changed = []
    for d_iso, e in sorted(data["entries"].items()):
        d = date.fromisoformat(d_iso)
        before = e["amount"]
        kind = entry_kind(e)
        if kind == "work":
            e["amount"] = day_pay(d, data, e.get("hours", default_hours(data))) or 0.0
        elif kind == "sick":
            e["amount"] = core.sick_pay_for(d, data)
        if e["amount"] != before:
            changed.append((d_iso, before, e["amount"]))
    core.save(data)
    if not changed:
        print("Everything already matches the current rates.")
        return
    for d_iso, before, after in changed:
        print(f"{d_iso}: {money(before)} -> {money(after)}")
    print(f"{len(changed)} day(s) updated, net {money(sum(a - b for _, b, a in changed))}")


def cmd_where(args, data):
    print(core.data_file())


# ── wiring ────────────────────────────────────────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(prog="work", description="Work Tracker — pay and attendance")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(func=fn)
        return sp

    sp = add("rate", cmd_rate, "Show, set or clear a weekday's hourly rate")
    sp.add_argument("day", nargs="?", help="mon/tue/wed/thu/fri/sat/sun")
    sp.add_argument("amount", nargs="?", type=float, help="0 or omitted clears the day")

    sp = add("hours", cmd_hours, "View or set the standard hours per day")
    sp.add_argument("amount", nargs="?", type=float)

    sp = add("ssp", cmd_ssp, "View or set sick pay per qualifying day")
    sp.add_argument("amount", nargs="?", type=float)

    sp = add("payday", cmd_payday, "Set the pay-period anchor and payday offset")
    sp.add_argument("date", nargs="?", help="A known pay-period END date")
    sp.add_argument("--offset", type=int, help="Days between period end and payday")

    sp = add("benefit", cmd_benefit, "Set a recurring benefit payment (not counted as pay)")
    sp.add_argument("date", nargs="?")
    sp.add_argument("--amount", type=float)
    sp.add_argument("--every", type=int)
    sp.add_argument("--name")

    sp = add("log", cmd_log, "Log a day as worked")
    sp.add_argument("date", nargs="?")
    sp.add_argument("--hours", type=float)
    sp.add_argument("--amount", type=float)
    sp.add_argument("--note")
    sp.add_argument("--force", action="store_true")

    sp = add("off", cmd_off, "Log a day as unpaid / not worked")
    sp.add_argument("date", nargs="?")
    sp.add_argument("--note")
    sp.add_argument("--force", action="store_true")

    sp = add("sick", cmd_sick, "Log a day or range off sick")
    sp.add_argument("date", nargs="?")
    sp.add_argument("--until")
    sp.add_argument("--note")
    sp.add_argument("--force", action="store_true")

    sp = add("adjust", cmd_adjust, "Record a one-off amount (back pay, bonus, correction)")
    sp.add_argument("date")
    sp.add_argument("amount", type=float)
    sp.add_argument("--note")
    sp.add_argument("--force", action="store_true")

    sp = add("remove", cmd_remove, "Remove an entry")
    sp.add_argument("date")

    sp = add("list", cmd_list, "List logged entries")
    sp.add_argument("--month", help="YYYY-MM")

    sp = add("total", cmd_total, "Show totals")
    sp.add_argument("--month", help="YYYY-MM")

    add("period", cmd_period, "Current pay-period breakdown and payday")

    sp = add("forecast", cmd_forecast, "Project earnings by payday")
    sp.add_argument("--until", required=True)
    sp.add_argument("--assume", choices=["sick", "work"], default="sick")

    add("recalc", cmd_recalc, "Re-price all logged days at current rates")
    add("where", cmd_where, "Print the path to the data file")
    return p


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = build_parser().parse_args(argv)
    args.func(args, core.load())


if __name__ == "__main__":
    main()

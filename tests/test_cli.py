"""Tests for the command-line interface.

Each test drives the real argument parser and asserts on what landed in the
data file, so the wiring between commands and the model is covered too.
"""
from datetime import date

import pytest

from shiftpay import cli, core


def _pin_today(pinned):
    """A date subclass with today() pinned, so date-relative output is stable."""
    class Fixed(date):
        @classmethod
        def today(cls):
            return pinned
    return Fixed


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTPAY_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def configured():
    d = core.default_data()
    d["rates"] = {"mon": 12.71, "tue": 12.71, "wed": 12.71, "thu": 12.71,
                  "fri": 12.71, "sat": 13.10, "sun": None}
    d["hours_per_day"] = 2.5
    d["ssp_daily"] = 20.5417
    d["period_end_anchor"] = "2026-09-13"
    d["payday_offset_days"] = 10
    core.save(d)
    return d


def run(*argv):
    cli.main(list(argv))


# ── settings ──────────────────────────────────────────────────────────────
def test_rate_sets_a_single_weekday(configured):
    run("rate", "mon", "15.00")
    assert core.load()["rates"]["mon"] == 15.00


def test_rate_zero_clears_the_day(configured):
    run("rate", "sat", "0")
    assert core.load()["rates"]["sat"] is None


def test_rate_accepts_full_day_names(configured):
    run("rate", "saturday", "14.00")
    assert core.load()["rates"]["sat"] == 14.00


def test_rate_rejects_an_unknown_day(configured):
    with pytest.raises(SystemExit):
        run("rate", "funday", "10")


def test_hours_and_ssp_persist(configured):
    run("hours", "4")
    run("ssp", "25.50")
    d = core.load()
    assert d["hours_per_day"] == 4
    assert d["ssp_daily"] == 25.50


def test_payday_sets_anchor_and_offset(configured):
    run("payday", "2026-09-13", "--offset", "7")
    d = core.load()
    assert d["period_end_anchor"] == "2026-09-13"
    assert d["payday_offset_days"] == 7


# ── logging ───────────────────────────────────────────────────────────────
def test_log_uses_the_weekday_rate(configured):
    run("log", "2026-09-22")                     # Tuesday
    assert core.load()["entries"]["2026-09-22"]["amount"] == 31.78


def test_log_uses_the_saturday_rate(configured):
    run("log", "2026-09-26")                     # Saturday
    assert core.load()["entries"]["2026-09-26"]["amount"] == 32.75


def test_log_accepts_an_hours_override(configured):
    run("log", "2026-09-22", "--hours", "5")
    e = core.load()["entries"]["2026-09-22"]
    assert e["hours"] == 5
    assert e["amount"] == round(5 * 12.71, 2)


def test_log_refuses_a_non_working_day(configured):
    with pytest.raises(SystemExit):
        run("log", "2026-09-27")                 # Sunday, no rate


def test_log_refuses_to_overwrite_without_force(configured):
    run("log", "2026-09-22")
    with pytest.raises(SystemExit):
        run("log", "2026-09-22")


def test_force_overwrites_an_existing_day(configured):
    run("log", "2026-09-22")
    run("sick", "2026-09-22", "--force")
    assert core.entry_kind(core.load()["entries"]["2026-09-22"]) == "sick"


def test_sick_range_covers_every_day(configured):
    run("sick", "2026-09-14", "--until", "2026-09-21")
    entries = core.load()["entries"]
    assert len(entries) == 8
    # 7 qualifying days paid, the Sunday in the range pays nothing
    assert sum(1 for e in entries.values() if e["amount"]) == 7
    assert entries["2026-09-20"]["amount"] == 0


def test_adjust_records_a_one_off_amount(configured):
    run("adjust", "2026-10-11", "184.88", "--note", "back pay")
    e = core.load()["entries"]["2026-10-11"]
    assert e["amount"] == 184.88
    assert core.entry_kind(e) == "adjustment"


def test_remove_deletes_an_entry(configured):
    run("log", "2026-09-22")
    run("remove", "2026-09-22")
    assert "2026-09-22" not in core.load()["entries"]


# ── reporting ─────────────────────────────────────────────────────────────
def test_period_totals_work_sick_and_extra(configured, capsys, monkeypatch):
    # `period` reports whichever period contains today, so today must be pinned
    # or this passes only while the real clock sits inside the test's period.
    monkeypatch.setattr(core, "date", _pin_today(date(2026, 10, 5)))
    run("log", "2026-09-22")
    run("sick", "2026-09-23")
    run("adjust", "2026-10-11", "100")
    run("period")
    out = capsys.readouterr().out
    assert "£31.78" in out and "£20.54" in out and "£100.00" in out
    assert "£152.32" in out


def test_total_month_filter(configured, capsys):
    run("log", "2026-09-22")
    run("log", "2026-10-01")
    run("total", "--month", "2026-10")
    assert "1 days" in capsys.readouterr().out


def test_recalc_reprices_after_a_rate_change(configured, capsys):
    run("log", "2026-09-22")
    run("rate", "tue", "20.00")
    run("recalc")
    assert core.load()["entries"]["2026-09-22"]["amount"] == 50.00
    assert "->" in capsys.readouterr().out


def test_recalc_is_a_no_op_when_nothing_changed(configured, capsys):
    run("log", "2026-09-22")
    run("recalc")
    assert "already matches" in capsys.readouterr().out


def test_benefit_is_listed_but_never_counted_as_pay(configured, capsys):
    run("benefit", "2026-10-29", "--amount", "428", "--name", "PIP")
    run("period")
    out = capsys.readouterr().out
    assert "£428.00" not in out.split("Current pay period")[-1]
    assert core.breakdown(core.load())["total"] == 0


def test_where_prints_the_data_path(configured, capsys):
    run("where")
    assert "work_data.json" in capsys.readouterr().out

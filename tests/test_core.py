"""Tests for the data model.

Every test runs against a temporary data directory via the WORKTRACKER_HOME
environment variable, so the suite never touches a real install.
"""
import json
from datetime import date

import pytest

from worktracker import core


def _FixedDate(pinned):
    """A date subclass whose today() is pinned, so date-relative logic is testable."""
    class Fixed(date):
        @classmethod
        def today(cls):
            return pinned
    return Fixed


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKTRACKER_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def data():
    d = core.default_data()
    d["rates"] = {"mon": 12.71, "tue": 12.71, "wed": 12.71, "thu": 12.71,
                  "fri": 12.71, "sat": 13.10, "sun": None}
    d["hours_per_day"] = 2.5
    d["ssp_daily"] = 20.5417
    d["period_end_anchor"] = "2026-09-13"   # a Sunday
    d["payday_offset_days"] = 10
    return d


# ── storage ───────────────────────────────────────────────────────────────
def test_fresh_install_has_nothing_configured():
    d = core.load()
    assert not core.is_configured(d)
    assert d["entries"] == {}
    assert all(v is None for v in d["rates"].values())


def test_save_then_load_roundtrips(data):
    data["entries"]["2026-09-22"] = {"amount": 31.78, "hours": 2.5,
                                     "note": "", "worked": True}
    core.save(data)
    assert core.load()["entries"]["2026-09-22"]["amount"] == 31.78


def test_save_is_atomic_and_leaves_no_temp_file(data, isolated_home):
    core.save(data)
    assert core.data_file().exists()
    assert not list(isolated_home.glob("*.tmp"))


def test_save_does_not_truncate_on_rewrite(data):
    core.save(data)
    first = core.data_file().read_text(encoding="utf-8")
    core.save(core.load())
    assert json.loads(core.data_file().read_text(encoding="utf-8")) == json.loads(first)


# ── migration ─────────────────────────────────────────────────────────────
def test_migrates_single_flat_rate():
    d = core._migrate({"rate": 10.0, "entries": {}})
    assert d["rates"]["mon"] == 10.0
    assert d["rates"]["sat"] == 10.0
    assert d["rates"]["sun"] is None


def test_migrates_grouped_weekday_rates():
    d = core._migrate({"rates": {"mon_fri": 12.71, "sat": 13.10, "sun": None},
                       "entries": {}})
    assert [d["rates"][k] for k in ("mon", "tue", "wed", "thu", "fri")] == [12.71] * 5
    assert d["rates"]["sat"] == 13.10
    assert d["rates"]["sun"] is None


def test_migrates_pip_keys_to_benefit_keys():
    d = core._migrate({"pip_anchor": "2026-10-29", "pip_amount": 428.0,
                       "pip_interval_days": 28, "entries": {}})
    assert d["benefit_anchor"] == "2026-10-29"
    assert d["benefit_amount"] == 428.0
    assert d["benefit_interval_days"] == 28


def test_migration_preserves_logged_amounts():
    """Migration must never silently re-price history."""
    d = core._migrate({"rates": {"mon_fri": 12.71, "sat": 13.10},
                       "entries": {"2026-09-22": {"amount": 99.99, "worked": True}}})
    assert d["entries"]["2026-09-22"]["amount"] == 99.99


# ── rates and pay ─────────────────────────────────────────────────────────
def test_weekday_and_saturday_rates_differ(data):
    assert core.rate_for(date(2026, 9, 22), data) == 12.71   # Tuesday
    assert core.rate_for(date(2026, 9, 26), data) == 13.10   # Saturday


def test_sunday_is_not_a_working_day(data):
    assert core.rate_for(date(2026, 9, 27), data) is None
    assert not core.works_on(date(2026, 9, 27), data)
    assert core.day_pay(date(2026, 9, 27), data) is None


def test_day_pay_is_hours_times_rate(data):
    assert core.day_pay(date(2026, 9, 22), data) == 31.78    # 2.5 x 12.71
    assert core.day_pay(date(2026, 9, 26), data) == 32.75    # 2.5 x 13.10


def test_day_pay_accepts_an_hours_override(data):
    assert core.day_pay(date(2026, 9, 22), data, hours=4) == round(4 * 12.71, 2)


def test_sick_pay_only_on_qualifying_days(data):
    assert core.sick_pay_for(date(2026, 9, 22), data) == 20.5417
    assert core.sick_pay_for(date(2026, 9, 27), data) == 0.0   # Sunday


def test_any_shift_pattern_is_supported():
    """A Sunday-only worker must work exactly as well as a Mon-Sat one."""
    d = core.default_data()
    d["rates"]["sun"] = 20.0
    d["hours_per_day"] = 8
    assert core.works_on(date(2026, 9, 27), d)
    assert not core.works_on(date(2026, 9, 28), d)
    assert core.day_pay(date(2026, 9, 27), d) == 160.0


# ── pay periods ───────────────────────────────────────────────────────────
def test_period_runs_four_weeks_to_the_anchor(data):
    start, end, payday = core.pay_period_for(date(2026, 10, 5), data)
    assert (start, end) == (date(2026, 9, 14), date(2026, 10, 11))
    assert (end - start).days + 1 == core.PAY_PERIOD_DAYS


def test_payday_falls_after_the_period_ends(data):
    _, end, payday = core.pay_period_for(date(2026, 10, 5), data)
    assert payday == date(2026, 10, 21)
    assert (payday - end).days == 10


def test_the_anchor_date_belongs_to_its_own_period(data):
    _, end, _ = core.pay_period_for(date(2026, 9, 13), data)
    assert end == date(2026, 9, 13)


def test_day_after_a_period_end_starts_the_next_one(data):
    start, end, payday = core.pay_period_for(date(2026, 10, 12), data)
    assert (start, end, payday) == (date(2026, 10, 12), date(2026, 11, 8), date(2026, 11, 18))


def test_periods_before_the_anchor_work_too(data):
    # 10 Aug sits a full period earlier than the 13 Sep anchor
    start, end, payday = core.pay_period_for(date(2026, 8, 10), data)
    assert (start, end) == (date(2026, 7, 20), date(2026, 8, 16))
    assert payday == date(2026, 8, 26)


def test_paydays_between_finds_each_payday(data):
    found = core.paydays_between(data, date(2026, 10, 1), date(2026, 11, 30))
    assert sorted(found) == [date(2026, 10, 21), date(2026, 11, 18)]


def test_payday_maps_back_to_the_period_it_pays(data):
    found = core.paydays_between(data, date(2026, 10, 1), date(2026, 10, 31))
    assert found[date(2026, 10, 21)] == (date(2026, 9, 14), date(2026, 10, 11))


def test_no_period_without_an_anchor():
    assert core.pay_period_for(date(2026, 10, 5), core.default_data()) is None


# ── the catch-up queue ────────────────────────────────────────────────────
def test_pending_skips_non_working_days(data, monkeypatch):
    data["entries"]["2026-09-22"] = core.make_entry(date(2026, 9, 22), "work", data)
    monkeypatch.setattr(core, "date", _FixedDate(date(2026, 9, 28)))
    pending = core.pending_dates(data)
    assert date(2026, 9, 27) not in pending          # Sunday
    assert date(2026, 9, 23) in pending


def test_pending_finds_gaps_not_just_recent_days(data, monkeypatch):
    """A day left unanswered mid-catch-up must come back, not vanish."""
    for iso in ("2026-09-22", "2026-09-25"):
        data["entries"][iso] = core.make_entry(date.fromisoformat(iso), "work", data)
    monkeypatch.setattr(core, "date", _FixedDate(date(2026, 9, 25)))
    assert date(2026, 9, 23) in core.pending_dates(data)
    assert date(2026, 9, 24) in core.pending_dates(data)


def test_pending_is_empty_when_everything_is_logged(data, monkeypatch):
    for iso in ("2026-09-22", "2026-09-23"):
        data["entries"][iso] = core.make_entry(date.fromisoformat(iso), "work", data)
    monkeypatch.setattr(core, "date", _FixedDate(date(2026, 9, 23)))
    assert core.pending_dates(data) == []


def test_lookback_is_bounded(data, monkeypatch):
    data["entries"]["2020-01-01"] = core.make_entry(date(2020, 1, 1), "work", data)
    monkeypatch.setattr(core, "date", _FixedDate(date(2026, 9, 25)))
    assert core.tracking_start(data) == date(2026, 9, 25) - core.timedelta(days=core.LOOKBACK_DAYS)


# ── entries and totals ────────────────────────────────────────────────────
def test_entry_kinds_round_trip(data):
    d = date(2026, 9, 22)
    assert core.entry_kind(core.make_entry(d, "work", data)) == "work"
    assert core.entry_kind(core.make_entry(d, "sick", data)) == "sick"
    assert core.entry_kind(core.make_entry(d, "off", data)) == "off"
    assert core.entry_kind(core.make_entry(d, "adjustment", data, amount=10)) == "adjustment"


def test_breakdown_separates_work_sick_and_extra(data):
    data["entries"] = {
        "2026-09-22": core.make_entry(date(2026, 9, 22), "work", data),
        "2026-09-23": core.make_entry(date(2026, 9, 23), "sick", data),
        "2026-09-24": core.make_entry(date(2026, 9, 24), "off", data),
        "2026-09-25": core.make_entry(date(2026, 9, 25), "adjustment", data, amount=100.0),
    }
    b = core.breakdown(data)
    assert b["work"] == 31.78
    assert b["sick"] == 20.5417
    assert b["adjustment"] == 100.0
    assert b["days_worked"] == 1 and b["days_sick"] == 1 and b["days_off"] == 1
    assert b["total"] == pytest.approx(152.32, abs=0.01)


def test_breakdown_respects_the_date_range(data):
    data["entries"] = {
        "2026-09-22": core.make_entry(date(2026, 9, 22), "work", data),
        "2026-10-22": core.make_entry(date(2026, 10, 22), "work", data),
    }
    b = core.breakdown(data, date(2026, 9, 1), date(2026, 9, 30))
    assert b["days_worked"] == 1


def test_days_off_do_not_add_pay(data):
    data["entries"]["2026-09-24"] = core.make_entry(date(2026, 9, 24), "off", data)
    assert core.breakdown(data)["total"] == 0


# ── benefit payments ──────────────────────────────────────────────────────
def test_benefit_recurs_on_the_interval(data):
    data["benefit_anchor"] = "2026-10-29"
    found = core.benefit_dates_between(data, date(2026, 10, 1), date(2026, 12, 1))
    assert date(2026, 10, 29) in found
    assert date(2026, 11, 26) in found
    assert all(d.weekday() == 3 for d in found)      # every one a Thursday


def test_benefit_dates_extend_backwards_from_the_anchor(data):
    data["benefit_anchor"] = "2026-10-29"
    found = core.benefit_dates_between(data, date(2026, 9, 1), date(2026, 10, 28))
    assert date(2026, 10, 1) in found


def test_next_benefit_is_the_upcoming_one(data, monkeypatch):
    data["benefit_anchor"] = "2026-10-29"
    monkeypatch.setattr(core, "date", _FixedDate(date(2026, 10, 5)))
    assert core.next_benefit(data) == date(2026, 10, 29)


def test_benefit_never_counts_as_earnings(data):
    """A benefit is calendar-only. It must not reach any pay total."""
    data["benefit_anchor"] = "2026-10-29"
    data["benefit_amount"] = 428.0
    assert core.breakdown(data)["total"] == 0



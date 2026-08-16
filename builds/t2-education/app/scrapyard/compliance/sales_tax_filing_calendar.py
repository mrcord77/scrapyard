"""
sales_tax_filing_calendar — remittance due-date calendar per registered state.

### PART-META-JSON
{
  "name": "sales_tax_filing_calendar",
  "layer": "compliance",
  "purpose": "Once you are registered and collecting sales tax, generate the per-state remittance filing calendar (frequency, period, due date) so returns are filed on time and collected tax is actually remitted — never sitting uncollected-and-unremitted, which is a liability, not an oversight.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "A list of registrations {state, frequency, [due_day]} and a target year; optionally 'today' to compute what's upcoming/overdue.",
  "outputs": "Sorted FilingEvent rows (state, frequency, period label, period_end, due_date) for the year, plus upcoming() and overdue() views.",
  "files_created": [],
  "security_notes": "NOT TAX ADVICE. Filing frequencies are ASSIGNED by each state (often based on tax volume) and due days vary and change — the bundled due days are a common-case default that MUST be replaced with the date on your state notice. A wrong due date here can still incur a penalty. Validate all external input.",
  "ai_usage": "Build registrations from sales_tax_nexus 'register_now' + each state's assigned frequency, call build_calendar(regs, year), then upcoming(cal, today) for the next filings to action.",
  "example": "from scrapyard.compliance.sales_tax_filing_calendar import build_calendar, Registration; cal = build_calendar([Registration('CA','quarterly'), Registration('WA','monthly')], 2026)",
  "import_path": "scrapyard.compliance.sales_tax_filing_calendar"
}
### END-PART-META
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

STATUS = "core"

# How many filing periods per year, per frequency.
FREQUENCIES = {"monthly": 12, "quarterly": 4, "semiannual": 2, "annual": 1}

# Common default remittance due day of the month AFTER the period ends. MANY
# states use the 20th; some the last day, the 25th, or the 15th. This is a
# DEFAULT ONLY — override per state from your registration notice.
DEFAULT_DUE_DAY = 20
STATE_DUE_DAY: Dict[str, int] = {
    # A few well-known differences (verify against your notice):
    "FL": 19, "ME": 15, "MI": 20, "NY": 20, "TX": 20, "CA": 31,  # CA quarterly: last day
    "AZ": 20, "WA": 25, "CO": 20, "IL": 20,
}


@dataclass
class Registration:
    state: str
    frequency: str            # one of FREQUENCIES
    due_day: Optional[int] = None  # override the state/default due day


@dataclass
class FilingEvent:
    state: str
    frequency: str
    period: str               # human label, e.g. "2026-Q1" or "2026-03"
    period_end: date
    due_date: date


def _clamp_day(year: int, month: int, day: int) -> date:
    """Return date(year, month, day) but clamp day to the month's last day."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _period_ends(frequency: str, year: int) -> List["tuple[str, date]"]:
    freq = frequency.lower()
    if freq not in FREQUENCIES:
        raise ValueError(f"unknown frequency {frequency!r}; expected one of {sorted(FREQUENCIES)}")
    ends: List[tuple[str, date]] = []
    if freq == "monthly":
        for m in range(1, 13):
            ends.append((f"{year}-{m:02d}", _clamp_day(year, m, 31)))
    elif freq == "quarterly":
        for q, m in enumerate((3, 6, 9, 12), start=1):
            ends.append((f"{year}-Q{q}", _clamp_day(year, m, 31)))
    elif freq == "semiannual":
        ends.append((f"{year}-H1", _clamp_day(year, 6, 31)))
        ends.append((f"{year}-H2", _clamp_day(year, 12, 31)))
    else:  # annual
        ends.append((f"{year}", _clamp_day(year, 12, 31)))
    return ends


def _due_date(state: str, period_end: date, due_day: int) -> date:
    """Returns due in the month AFTER the period ends, on due_day (clamped)."""
    m = period_end.month + 1
    y = period_end.year + (1 if m > 12 else 0)
    m = 1 if m > 12 else m
    return _clamp_day(y, m, due_day)


def build_calendar(registrations: List[Registration], year: int) -> List[FilingEvent]:
    """Generate every remittance filing event for the year, sorted by due date."""
    events: List[FilingEvent] = []
    for reg in registrations:
        st = reg.state.upper()
        due_day = reg.due_day or STATE_DUE_DAY.get(st, DEFAULT_DUE_DAY)
        for label, pend in _period_ends(reg.frequency, year):
            events.append(FilingEvent(st, reg.frequency.lower(), label, pend,
                                      _due_date(st, pend, due_day)))
    events.sort(key=lambda e: (e.due_date, e.state))
    return events


def upcoming(calendar_events: List[FilingEvent], today: date,
             within_days: int = 30) -> List[FilingEvent]:
    """Filings due from `today` through the next `within_days` days."""
    horizon = today + timedelta(days=within_days)
    return [e for e in calendar_events if today <= e.due_date <= horizon]


def overdue(calendar_events: List[FilingEvent], today: date) -> List[FilingEvent]:
    """Filings whose due date has already passed (relative to `today`)."""
    return [e for e in calendar_events if e.due_date < today]


def _selftest() -> None:
    regs = [Registration("CA", "quarterly"), Registration("WA", "monthly"),
            Registration("TX", "annual")]
    cal = build_calendar(regs, 2026)
    # 4 CA + 12 WA + 1 TX = 17 events
    assert len(cal) == 17, len(cal)
    assert cal == sorted(cal, key=lambda e: (e.due_date, e.state)), "must be sorted"

    ca = [e for e in cal if e.state == "CA"]
    assert len(ca) == 4 and ca[0].period == "2026-Q1"
    # Q1 ends 2026-03-31, CA due day 31 -> due 2026-04-30 (April has 30 days, clamped)
    assert ca[0].period_end == date(2026, 3, 31)
    assert ca[0].due_date == date(2026, 4, 30), ca[0].due_date

    wa = [e for e in cal if e.state == "WA"]
    assert len(wa) == 12
    # Jan period ends 2026-01-31, WA due day 25 -> 2026-02-25
    jan = next(e for e in wa if e.period == "2026-01")
    assert jan.due_date == date(2026, 2, 25), jan.due_date
    # December period due in the FOLLOWING year
    dec = next(e for e in wa if e.period == "2026-12")
    assert dec.due_date.year == 2027 and dec.due_date.month == 1

    tx = [e for e in cal if e.state == "TX"]
    assert len(tx) == 1 and tx[0].due_date == date(2027, 1, 20)

    up = upcoming(cal, date(2026, 4, 1), within_days=30)
    assert all(date(2026, 4, 1) <= e.due_date <= date(2026, 5, 1) for e in up)
    od = overdue(cal, date(2026, 4, 1))
    assert all(e.due_date < date(2026, 4, 1) for e in od)

    # override due day + bad frequency
    c2 = build_calendar([Registration("NV", "monthly", due_day=15)], 2026)
    assert c2[0].due_date.day == 15
    try:
        build_calendar([Registration("NV", "weekly")], 2026)
        assert False, "should reject unknown frequency"
    except ValueError:
        pass


if __name__ == "__main__":
    _selftest()
    print("sales_tax_filing_calendar selftest OK")

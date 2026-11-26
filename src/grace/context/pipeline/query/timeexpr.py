"""Time phrases of a read task -> absolute valid-time windows (plan 3.3, 5.3; T023).

The planner never writes a relative date into a query. It names the phrase of the task ("in May
2023", "one year ago", "in the last week"), and `resolve_window` turns it into an absolute
half-open interval [start, end) of `xsd:date` values. The planner then filters the start of the
valid time of one claim pattern on that interval:

    FILTER(start(?c) >= "<start>"^^date) FILTER(start(?c) < "<end>"^^date)

A phrase that depends on the time of reading (`relative=True`) is resolved against the reference
date of the read (the read's `asked_at`, else the date of the last visible message) at compile
time, and the query is marked temporary: it answers this read and is never stored as a view,
because its meaning would change without any write (plan 3.3).

Supported phrases (case-insensitive; a leading "in", "during", "on" or "of" is ignored):

Absolute (not relative):

- `2023`: the calendar year; `May 2023`, `December, 2023`: the calendar month;
- `5 May 2023`, `May 5, 2023`, `2023-05-05`: the day.

Relative (resolved against the reference date):

- `today`, `yesterday`: the day;
- `this week` / `this month` / `this year`: the calendar period holding the reference date
  (weeks start on Monday); `last week` / `last month` / `last year`: the previous one;
- `the last N days/weeks/months/years`, `the past ...` (N a digit or a number word, default 1):
  trailing, [reference - N units, reference + 1 day);
- `N days/weeks/months/years ago`, `a year ago`: centred, [reference - N units - u/2,
  reference - N units + u/2) with u one unit; for days, the single day.

Vague phrases such as "recently" or "lately" have no window; the planner expresses them as the
most recently stated claim (`LATEST BY version`), and `resolve_window` refuses them.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import re
from dataclasses import dataclass


class TimeExpressionError(ValueError):
    """The phrase is not one of the supported forms, or no reference date is available."""


@dataclass(frozen=True)
class Window:
    """[start, end) as xsd:date lexical forms; `relative` when it depends on the reference."""

    phrase: str
    start: str
    end: str
    relative: bool


MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
           "a few": 3, "few": 3, "a couple of": 2, "couple of": 2, "several": 3}
UNITS = ("day", "week", "month", "year")
VAGUE = ("recently", "lately", "recent", "the other day", "a while ago", "some time ago")

_NUM = r"(?P<n>\d+|" + "|".join(sorted((re.escape(k) for k in NUMBERS), key=len,
                                       reverse=True)) + r")"
_UNIT = r"(?P<unit>day|week|month|year)s?"
_LEAD = re.compile(r"^(?:in|during|on|of|within|from)\s+")


def _date(text: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(text[:10])
    except ValueError as exc:
        raise TimeExpressionError(f"reference date {text!r} is not an ISO date") from exc


def _add_months(d: _dt.date, months: int) -> _dt.date:
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    day = min(d.day, calendar.monthrange(year, month + 1)[1])
    return _dt.date(year, month + 1, day)


def _shift(d: _dt.date, unit: str, n: float) -> _dt.date:
    if unit == "day":
        return d + _dt.timedelta(days=round(n))
    if unit == "week":
        return d + _dt.timedelta(days=round(7 * n))
    months = n * (12 if unit == "year" else 1)
    whole = int(months)
    out = _add_months(d, whole)
    if months != whole:  # half a month: 15 days
        out += _dt.timedelta(days=round((months - whole) * 30))
    return out


def _period(d: _dt.date, unit: str) -> tuple[_dt.date, _dt.date]:
    if unit == "day":
        return d, d + _dt.timedelta(days=1)
    if unit == "week":
        start = d - _dt.timedelta(days=d.weekday())
        return start, start + _dt.timedelta(days=7)
    if unit == "month":
        start = d.replace(day=1)
        return start, _add_months(start, 1)
    start = d.replace(month=1, day=1)
    return start, start.replace(year=start.year + 1)


def _number(text: str) -> int:
    return int(text) if text.isdigit() else NUMBERS[text]


def _window(phrase: str, start: _dt.date, end: _dt.date, relative: bool) -> Window:
    return Window(phrase, start.isoformat(), end.isoformat(), relative)


def resolve_window(phrase: str, reference: str | None = None) -> Window:
    """The absolute window of `phrase`; `reference` (ISO date) anchors relative phrases."""
    if not isinstance(phrase, str) or not phrase.strip():
        raise TimeExpressionError("empty time phrase")
    text = re.sub(r"\s+", " ", phrase.strip().lower().rstrip("?.!")).replace(",", "")
    text = _LEAD.sub("", text)
    if text.startswith("the ") and not re.match(r"the (last|past) ", text):
        text = text[4:]
    if any(text == v or text.endswith(" " + v) for v in VAGUE):
        raise TimeExpressionError(f"{phrase!r} is vague and has no window; use the latest state "
                                  "by valid time instead")

    # absolute forms
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
        d = _dt.date(*map(int, m.groups()))
        return _window(phrase, d, d + _dt.timedelta(days=1), False)
    if m := re.fullmatch(r"(\d{4})-(\d{2})", text):
        d = _dt.date(int(m[1]), int(m[2]), 1)
        return _window(phrase, d, _add_months(d, 1), False)
    if m := re.fullmatch(r"(\d{4})", text):
        d = _dt.date(int(m[1]), 1, 1)
        return _window(phrase, d, d.replace(year=d.year + 1), False)
    if (m := re.fullmatch(r"([a-z]+) (\d{4})", text)) and m[1] in MONTHS:
        d = _dt.date(int(m[2]), MONTHS[m[1]], 1)
        return _window(phrase, d, _add_months(d, 1), False)
    day = (re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]+) (\d{4})", text)
           or re.fullmatch(r"([a-z]+) (\d{1,2})(?:st|nd|rd|th)? (\d{4})", text))
    if day:
        a, b, year = day.groups()
        dd, month = (a, b) if a.isdigit() else (b, a)
        if month in MONTHS:
            try:
                d = _dt.date(int(year), MONTHS[month], int(dd))
            except ValueError as exc:
                raise TimeExpressionError(f"{phrase!r} is not a valid date") from exc
            return _window(phrase, d, d + _dt.timedelta(days=1), False)

    # relative forms
    relative = (text in ("today", "yesterday")
                or re.fullmatch(r"(this|last) (day|week|month|year)", text)
                or re.fullmatch(rf"(?:the )?(?:last|past) (?:{_NUM} )?{_UNIT}", text)
                or re.fullmatch(rf"{_NUM} {_UNIT} ago", text))
    if not relative:
        raise TimeExpressionError(f"unsupported time phrase {phrase!r}")
    if reference is None:
        raise TimeExpressionError(f"{phrase!r} is relative and the read has no reference date")
    ref = _date(reference)
    if text == "today":
        return _window(phrase, *_period(ref, "day"), True)
    if text == "yesterday":
        return _window(phrase, *_period(ref - _dt.timedelta(days=1), "day"), True)
    if m := re.fullmatch(r"(this|last) (day|week|month|year)", text):
        start, end = _period(ref, m[2])
        if m[1] == "last":
            start, end = _period(_shift(start, m[2], -1), m[2])
        return _window(phrase, start, end, True)
    if m := re.fullmatch(rf"(?:the )?(?:last|past) (?:{_NUM} )?{_UNIT}", text):
        n = _number(m["n"]) if m["n"] else 1
        return _window(phrase, _shift(ref, m["unit"], -n), ref + _dt.timedelta(days=1), True)
    m = re.fullmatch(rf"{_NUM} {_UNIT} ago", text)
    n, unit = _number(m["n"]), m["unit"]
    centre = _shift(ref, unit, -n)
    if unit == "day":
        return _window(phrase, centre, centre + _dt.timedelta(days=1), True)
    return _window(phrase, _shift(centre, unit, -0.5), _shift(centre, unit, 0.5), True)

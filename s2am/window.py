"""The 30-day window a pack built today stays valid in.

SyncExtPack binds each pack to a fixed window (upstream builder/utils.py
getMagicNum). Windows start at fixed moments, not when the pack is built, so a
pack built just before a boundary is only good for hours.
"""
from __future__ import annotations

from datetime import datetime, timedelta

WINDOW_SECONDS = 60 * 60 * 24 * 30
DEFAULT_MARGIN = timedelta(days=2)
# Right after a rollover, an APIM clock that runs behind is still in the old window.
DEFAULT_LEAD = timedelta(hours=12)


def bucket(moment: datetime) -> int:
    """Upstream getMagicNum, for a timezone-aware moment."""
    return int(moment.timestamp() / WINDOW_SECONDS - 0.48)


def valid_thru(now: datetime) -> datetime:
    """Last second of the window that contains ``now``."""
    current, step, moment = bucket(now), timedelta(hours=1), now
    while bucket(moment + step) == current:
        moment += step
    while bucket(moment + timedelta(seconds=1)) == current:
        moment += timedelta(seconds=1)
    return moment


def valid_from(now: datetime) -> datetime:
    """First second of the window that contains ``now``."""
    current, step, moment = bucket(now), timedelta(hours=1), now
    while bucket(moment - step) == current:
        moment -= step
    while bucket(moment - timedelta(seconds=1)) == current:
        moment -= timedelta(seconds=1)
    return moment


def check(now: datetime, margin: timedelta = DEFAULT_MARGIN,
          lead: timedelta = DEFAULT_LEAD) -> tuple[bool, datetime]:
    """(safe to build, window end).

    Unsafe when the window closes within ``margin`` or opened less than ``lead`` ago.
    """
    end = valid_thru(now)
    return end - now >= margin and now - valid_from(now) >= lead, end

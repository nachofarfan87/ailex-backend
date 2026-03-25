"""
AILEX — Business day arithmetic (V1: weekends only, no holidays).
"""

from datetime import date, timedelta


def add_business_days(start: date, days: int) -> date:
    """
    Add N business days (Monday–Friday) to a start date, skipping weekends.

    Limitation: does NOT skip official holidays or judicial non-working days.
    Callers must warn users that the result must be verified against the
    official judicial calendar of the applicable jurisdiction.
    """
    if days <= 0:
        return start
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0=Mon … 4=Fri
            added += 1
    return current

"""
AILEX - Helper central para timestamps UTC.

Reemplaza datetime.utcnow() (deprecated en Python 3.12+) con una
alternativa consistente que devuelve naive UTC datetimes para
mantener compatibilidad con los Column(DateTime) existentes.

Uso:
    from app.services.utc import utc_now
    now = utc_now()  # naive datetime en UTC
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Devuelve un naive datetime en UTC sin usar datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone, tzinfo
from zoneinfo import ZoneInfo, available_timezones

from flask import current_app


def get_app_timezone_name() -> str:
    return str(current_app.config.get("APP_TIMEZONE") or "UTC").strip() or "UTC"


def get_app_timezone() -> tzinfo:
    name = get_app_timezone_name()
    try:
        return ZoneInfo(name)
    except Exception:
        # En Windows / Python 3.13 puede faltar la base IANA (tzdata).
        # Fallback seguro: UTC built-in.
        return dt_timezone.utc


def list_timezones() -> list[str]:
    # devuelve lista IANA. Puede ser grande, pero es lo pedido.
    try:
        return sorted(available_timezones())
    except Exception:
        return ["UTC"]


def to_local(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    # En DB guardamos "naive" en UTC (datetime.utcnow). Convertimos desde UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(get_app_timezone())


def format_dt(dt: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    loc = to_local(dt)
    return loc.strftime(fmt) if loc else ""

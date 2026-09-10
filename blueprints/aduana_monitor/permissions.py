# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta

from . import settings


class PermissionDenied(Exception):
    pass


def is_active(user):
    return bool(user and user.get("status") == "ACTIVE")


def assert_can_query(user):
    if not is_active(user):
        raise PermissionDenied("Tu cuenta todavía no está activa.")
    if not bool(user.get("can_query")):
        raise PermissionDenied("Tu cuenta no tiene permiso de consulta manual.")


def assert_can_monitor(user):
    if not is_active(user):
        raise PermissionDenied("Tu cuenta todavía no está activa.")
    if not bool(user.get("can_monitor")):
        raise PermissionDenied("Tu cuenta no tiene permiso de monitoreo.")


def assert_can_add_rut(user, existing_distinct_ruts, rut):
    assert_can_monitor(user)
    if user.get("role") == "OWNER":
        return
    if rut not in set(existing_distinct_ruts):
        max_ruts = max(1, int(user.get("max_ruts") or settings.DEFAULT_MAX_RUTS))
        if len(set(existing_distinct_ruts)) >= max_ruts:
            raise PermissionDenied(f"Ya alcanzaste tu límite de {max_ruts} RUT(s).")


def _first_day_n_months_before(today, months_before):
    month_index = (today.year * 12 + today.month - 1) - months_before
    year, zero_month = divmod(month_index, 12)
    return date(year, zero_month + 1, 1)


def calendar_month_range(months):
    today = date.today()
    return _first_day_n_months_before(today, max(1, months) - 1), today


def range_options_for(user):
    level = user.get("permission_level")
    if level == settings.OWNER_PERMISSION:
        raise PermissionDenied("OWNER usa selección libre de años.")
    if level not in settings.PERMISSION_LEVELS:
        raise PermissionDenied("Nivel de permiso inválido.")

    max_months = {"MONTH": 1, "THREE_MONTHS": 3, "YEAR": 12}[level]
    today = date.today()
    options = [("7d", "Últimos 7 días", today - timedelta(days=6), today)]
    if max_months >= 1:
        start, end = calendar_month_range(1)
        options.append(("1m", "Mes actual", start, end))
    if max_months >= 3:
        start, end = calendar_month_range(3)
        options.append(("3m", "Últimos 3 meses", start, end))
    if max_months >= 12:
        start, end = calendar_month_range(12)
        options.append(("12m", "Últimos 12 meses", start, end))
    return options


def available_years_for(user):
    if user.get("role") != "OWNER" or user.get("permission_level") != settings.OWNER_PERMISSION:
        raise PermissionDenied("Solo OWNER puede elegir años libremente.")
    current = date.today().year
    return list(range(current, settings.UNLIMITED_START_YEAR - 1, -1))

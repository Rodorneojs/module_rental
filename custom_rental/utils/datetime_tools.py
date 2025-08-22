
# -*- coding: utf-8 -*-
from datetime import datetime, date, time
import pytz
import re

def normalize_tz_name(tz_name):
    """Normalize weird Etc/GMT names and typos to valid pytz tz names."""
    if not tz_name:
        return "UTC"
    name = str(tz_name).strip()
    if name.lower().startswith("etc/"):
        name = "Etc/" + name[4:]
    elif name.lower().startswith("etc-"):
        name = "Etc/" + name[4:]
    m = (re.search(r"(?i)^Etc/GMT\s*([+-])\s*(\d+)$", name)
         or re.search(r"(?i)^GMT\s*([+-])\s*(\d+)$", name)
         or re.search(r"(?i)^Etc[-/ ]GMT\s*([+-])\s*(\d+)$", name))
    if m:
        sign, num = m.groups()
        inv = "+" if sign == "-" else "-"
        name = f"Etc/GMT{inv}{num}"
    try:
        pytz.timezone(name)
        return name
    except Exception:
        return "UTC"

def time_selection(step=30):
    """Return HH:MM selections for Odoo Selection fields."""
    vals = []
    for h in range(24):
        for m in range(0, 60, step):
            s = f"{h:02d}:{m:02d}"
            vals.append((s, s))
    return vals

def hm_to_minutes(hhmm):
    if not hhmm:
        return None
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def parse_hhmm(hhmm):
    hh, mm = [int(x) for x in (hhmm or "00:00").split(":")]
    return time(hh, mm, 0)

def to_utc_naive(date_obj, hhmm, user_tzname):
    """Combine date + hhmm as local time, return naive UTC datetime."""
    hh, mm = [int(x) for x in (hhmm or "00:00").split(":")]
    local_dt = datetime(date_obj.year, date_obj.month, date_obj.day, hh, mm, 0)
    tz = pytz.timezone(normalize_tz_name(user_tzname))
    try:
        aware = tz.localize(local_dt, is_dst=None)
    except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
        aware = tz.localize(local_dt, is_dst=False)
    return aware.astimezone(pytz.UTC).replace(tzinfo=None)

def to_user_tz(dt, user_tzname):
    tz = pytz.timezone(normalize_tz_name(user_tzname))
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(tz)

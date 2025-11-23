# data_provider.py
"""
Henter og normaliserer data: events, weather, tommekalender.
Leser konfig fra miljøvariabler:
  - API_KEY_GOOGLE
  - CALENDAR_ID
  - MOVAR_API_TOKEN
  - MOVAR_BASE
  - LAT, LON
  - KOMMUNENR (valgfri, default 3103)
  - MOVAR_GATENAVN, MOVAR_HUSNR (valgfri)

Kjør som skript for rask feilsøking:
  python data_provider.py
"""
import os
import requests
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Oslo")
except Exception:
    TZ = None

from dotenv import load_dotenv
load_dotenv()

# --- Konfig fra miljøvariabler (fallbacks for enkel testing) ---
API_KEY_GOOGLE = os.environ.get("API_KEY_GOOGLE", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "3fssuka2am16b2jt44h4fl2o4g@group.calendar.google.com")

# Optional separate calendar id for public holidays (fallback to the official Norway holidays calendar)
HOLIDAYS_CALENDAR_ID = os.environ.get(
    "HOLIDAYS_CALENDAR_ID",
    "no.norwegian%23holiday@group.v.calendar.google.com"
)
MOVAR_API_TOKEN = os.environ.get("MOVAR_API_TOKEN", "")
MOVAR_BASE = os.environ.get("MOVAR_BASE", "https://mdt-proxy.movar.no/api")
LAT = float(os.environ.get("LAT", "59.4376"))
LON = float(os.environ.get("LON", "10.6432"))
KOMMUNENR = os.environ.get("KOMMUNENR", "3103")
MOVAR_GATENAVN = os.environ.get("MOVAR_GATENAVN", "Dokkveien")
MOVAR_HUSNR = os.environ.get("MOVAR_HUSNR", "19")

# Hvor mange dager vi viser standard
DEFAULT_DAYS = int(os.environ.get("DEFAULT_DAYS", "14"))

# Try to import mapping helpers (non-fatal)
def parse_locationforecast_timeseries(timeseries):
    """
    Convert Locationforecast 'properties.timeseries' into a simple hourly list:
    [{'time': ISO, 'temp': float, 'precip': float, 'symbol_code': str, 'condition': str}, ...]
    """
    out = []
    for item in (timeseries or []):
        t = item.get("time") or item.get("validTime") or None

        # instant details (air temp etc.)
        inst = item.get("data", {}).get("instant", {}).get("details", {}) if item.get("data") else item.get("data", {}).get("instant", {}).get("details", {})
        temp = None
        if inst:
            temp = inst.get("air_temperature") or inst.get("airTemperature") or inst.get("temperature") or inst.get("temp")

        # Prefer next_1_hours (1-hour period) fields if present, else next_6_hours, else next_12_hours
        precip = None
        symbol_code = None
        for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
            period = item.get("data", {}).get(key) if item.get("data") else item.get(key)
            if period:
                # precipitation amount often under period['details']['precipitation_amount'] or period['details']['precipitation']
                det = period.get("details", {}) or {}
                precip = det.get("precipitation_amount") or det.get("precipitation") or det.get("precipitation_amount_mm") or precip
                # symbol code sometimes under period['summary']['symbol_code'] or period['summary']['symbol']
                summary = period.get("summary") or {}
                symbol_code = summary.get("symbol_code") or summary.get("symbol") or symbol_code
                # if we found a 1-hour block, prefer it and break
                if key == "next_1_hours":
                    break

        # Fallbacks: try top-level summary if period missing
        if not symbol_code:
            top_summary = item.get("data", {}).get("summary", {}) if item.get("data") else item.get("summary", {})
            symbol_code = top_summary.get("symbol_code") or top_summary.get("symbol") or symbol_code

        # normalize precip and temp types
        try:
            precip = float(precip) if precip is not None else 0.0
        except Exception:
            precip = 0.0
        try:
            temp = float(temp) if temp is not None else None
        except Exception:
            temp = None

        # condition: map symbol_code into a friendly word
        cond = None
        if symbol_code:
            sc = symbol_code.lower()
            # common symbol name hints: 'clearsky', 'fair', 'partlycloudy', 'cloudy', 'rain', 'lightrain', 'heavyrain', 'snow', 'sleet', 'thunder'
            if "clear" in sc or "clearsky" in sc:
                cond = "Klarvær"
            elif "fair" in sc or "partly" in sc or "partlycloudy" in sc:
                cond = "Delvis skyet"
            elif "cloud" in sc or "overcast" in sc:
                cond = "Skyet"
            elif "rain" in sc or "shower" in sc or "drizzle" in sc:
                cond = "Regn"
            elif "snow" in sc or "snowshow" in sc:
                cond = "Snø"
            elif "sleet" in sc:
                cond = "Sludd"
            elif "thunder" in sc or "tstorm" in sc:
                cond = "Torden"
            else:
                cond = symbol_code
        else:
            # if no symbol_code available, fallback: guess from precip/temp
            if precip >= 2.5:
                cond = "Regn" if (temp is None or temp > 1.5) else "Snø"
            elif temp is not None and temp <= -1.5:
                cond = "Skyet"
            else:
                cond = "Delvis skyet"

        out.append({
            "time": t,
            "temp": temp,
            "precip": precip,
            "symbol_code": symbol_code,
            "condition": cond
        })
    return out


try:
    import mappings as mappings_module
    # expose common helpers if present
    mapping_info_for_event = getattr(mappings_module, "mapping_info_for_event", None)
    EVENT_MAPPINGS = getattr(mappings_module, "EVENT_MAPPINGS", None)
    color_to_rgb = getattr(mappings_module, "color_to_rgb", None)
except Exception:
    mappings_module = None
    mapping_info_for_event = None
    color_to_rgb = None
    EVENT_MAPPINGS = None

# Avoid duplicate zoneinfo block - we've already set TZ above, but keep a warning if not set
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    if TZ is None:
        TZ = _ZoneInfo("Europe/Oslo")
except Exception:
    if TZ is None:
        TZ = None
        print("[WARN] zoneinfo.ZoneInfo('Europe/Oslo') unavailable: falling back to system local time")


def now_local():
    """
    Return an AWARE datetime in Europe/Oslo if possible,
    otherwise a naive datetime in the system local time (with warning above).
    """
    if TZ:
        return datetime.now(TZ)
    return datetime.now()


def date_string_for_offset(day_index=0):
    d = now_local().date() + timedelta(days=day_index)
    return d.strftime("%Y-%m-%d")


# --------------------------------------------------------------------
# Lightweight apply_event_mapping shim
# --------------------------------------------------------------------
# This file no longer contains the heavy apply_event_mapping implementation.
# Instead we prefer mappings.apply_event_mapping when available. If it's not
# present, we build a conservative structure from mapping_info_for_event.
from PIL import ImageColor
import re
import importlib


def _safe_rgb_from_mapping_entry(entry):
    """Try to build an (r,g,b) tuple from mapping entry or None."""
    if not entry or not isinstance(entry, dict):
        return None
    for k in ("color_rgb", "tag_color_rgb", "icon_color_rgb"):
        if entry.get(k) is not None:
            try:
                v = entry.get(k)
                return (int(v[0]), int(v[1]), int(v[2]))
            except Exception:
                pass
    for k in ("color", "tag_color_name", "icon_color_name", "color_name"):
        if entry.get(k):
            try:
                rgb = ImageColor.getrgb(str(entry.get(k)))
                return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            except Exception:
                pass
    return None


def apply_event_mapping(summary: str):
    """
    Small shim that returns a dict with keys used by the rest of data_provider:
      - display_text, tag_text, tag_color_name, tag_color_rgb,
        icon, icon_size, icon_color_name, icon_color_rgb, mode, filtered_out, original_name, tags
    Behavior:
      - If mappings.apply_event_mapping exists, call and return its result (defensive).
      - Else if mapping_info_for_event exists, call it and convert the single mapping into the expected structure.
      - Else return a conservative structure (no changes).
    """
    original = (summary or "").strip()
    out = {
        "display_text": original,
        "tag_text": None,
        "tag_color_name": None,
        "tag_color_rgb": None,
        "icon": None,
        "icon_size": None,
        "icon_color_name": "",
        "icon_color_rgb": None,
        "mode": None,
        "filtered_out": False,
        "original_name": original,
        "tags": [],
    }

    # 1) Prefer a mapping implementation in mappings module if it exists.
    try:
        if mappings_module and hasattr(mappings_module, "apply_event_mapping") and callable(getattr(mappings_module, "apply_event_mapping")):
            try:
                res = mappings_module.apply_event_mapping(original)
                # Expect res to be a dict in the expected shape; be defensive
                if isinstance(res, dict):
                    # copy-over known keys
                    for k in out.keys():
                        if k in res:
                            out[k] = res.get(k)
                    # merge tags if present
                    if res.get("tags") and isinstance(res.get("tags"), list):
                        out["tags"] = res.get("tags")
                    return out
            except Exception:
                # fallthrough to mapping_info_for_event conversion
                pass
    except Exception:
        pass

    # 2) Fallback: use mapping_info_for_event and convert to structure
    try:
        if mapping_info_for_event and callable(mapping_info_for_event):
            info = mapping_info_for_event(original)
            if not info:
                return out
            # info is expected to be a dict with keys like:
            # 'replacement', 'mode', 'icon', 'size_px', 'color', 'color_rgb', 'remaining_text', 'match_span'
            mode = (info.get("mode") or "") or None
            replacement = (info.get("replacement") or "").strip()
            icon = info.get("icon")
            size_px = info.get("size_px")
            color_name = info.get("color") or ""
            color_rgb = info.get("color_rgb") if info.get("color_rgb") is not None else None
            remaining_text = (info.get("remaining_text") or "").strip()

            # default behavior: if mode begins with "add_" do not change display_text
            display = original
            filtered_out = False

            if mode and mode.startswith("replace_"):
                # try to use match_span to remove matched slice
                match_span = info.get("match_span")
                if isinstance(match_span, (list, tuple)) and len(match_span) >= 2:
                    try:
                        s_idx = int(match_span[0])
                        e_idx = int(match_span[1])
                        s_idx = max(0, min(len(original), s_idx))
                        e_idx = max(0, min(len(original), e_idx))
                        if e_idx > s_idx:
                            display = (original[:s_idx] + original[e_idx:]).strip()
                    except Exception:
                        # fallback: remove first literal occurrence of replacement/remaining_text
                        if replacement and replacement in original:
                            display = original.replace(replacement, "", 1).strip()
                        elif remaining_text and remaining_text in original:
                            display = original.replace(remaining_text, "", 1).strip()
                else:
                    if replacement and replacement in original:
                        display = original.replace(replacement, "", 1).strip()
                    elif remaining_text and remaining_text in original:
                        display = original.replace(remaining_text, "", 1).strip()
                    else:
                        # attempt to remove case-insensitive token
                        if replacement:
                            idx = original.lower().find(replacement.lower())
                            if idx >= 0:
                                display = (original[:idx] + original[idx+len(replacement):]).strip()

            # Build tag info if replacement visible text exists
            tags = []
            tag_text = None
            tag_color_name = None
            tag_color_rgb = None
            if replacement:
                tag_text = replacement
                # try rgb from info
                if color_rgb is not None:
                    try:
                        tag_color_rgb = (int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]))
                    except Exception:
                        tag_color_rgb = None
                elif color_name:
                    tag_color_name = color_name
                    try:
                        tag_color_rgb = ImageColor.getrgb(color_name)
                        tag_color_rgb = (int(tag_color_rgb[0]), int(tag_color_rgb[1]), int(tag_color_rgb[2]))
                    except Exception:
                        tag_color_rgb = None
                tag_entry = {"text": tag_text}
                if tag_color_rgb is not None:
                    tag_entry["color_rgb"] = tag_color_rgb
                elif tag_color_name:
                    tag_entry["color_name"] = tag_color_name
                tags.append(tag_entry)

            # icon color fallback handling
            icon_color_rgb = None
            if color_rgb is not None:
                try:
                    icon_color_rgb = (int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]))
                except Exception:
                    icon_color_rgb = None
            elif color_name:
                try:
                    tmp = ImageColor.getrgb(color_name)
                    icon_color_rgb = (int(tmp[0]), int(tmp[1]), int(tmp[2]))
                except Exception:
                    icon_color_rgb = None

            # If replace mode removed all text and no tags, mark filtered_out
            if (not display or display.strip() == "") and not tag_text:
                filtered_out = True

            out.update({
                "display_text": display,
                "tag_text": tag_text,
                "tag_color_name": tag_color_name,
                "tag_color_rgb": tag_color_rgb,
                "icon": icon,
                "icon_size": int(size_px) if size_px else None,
                "icon_color_name": color_name or "",
                "icon_color_rgb": icon_color_rgb,
                "mode": mode,
                "filtered_out": filtered_out,
                "original_name": original,
                "tags": tags,
            })
            return out
    except Exception:
        # any failure here -> return conservative default out
        return out

    # 3) No mapping available -> return conservative default
    return out


# --------------------------------------------------------------------
# Tommekalender integration
# --------------------------------------------------------------------
def fetch_fraction_names(session=None):
    session = session or requests.Session()
    url = f"{MOVAR_BASE}/Fraksjoner"
    headers = {"Kommunenr": KOMMUNENR, "Accept": "application/json", "User-Agent": "InkyFrameCalendar/1.0"}
    params = {"apitoken": MOVAR_API_TOKEN} if MOVAR_API_TOKEN else {}
    try:
        r = session.get(url, headers=headers, params=params, timeout=10, verify=True)
        if r.status_code == 200:
            data = r.json()
            return {int(item.get("id", -1)): item.get("navn", "") for item in data}
        else:
            if r.status_code == 401:
                try_headers = headers.copy()
                try_headers["apitoken"] = MOVAR_API_TOKEN
                r2 = session.get(url, headers=try_headers, timeout=10, verify=True)
                print("[fetch_fraction_names] retry with apitoken header status:", r2.status_code)
            return {}
    except Exception as ex:
        print("[fetch_fraction_names] exception:", ex)
        return {}


def fetch_tommekalender_events(fraction_names, days=DEFAULT_DAYS, session=None, gatenavn=None, husnr=None):
    session = session or requests.Session()
    gatenavn = gatenavn or MOVAR_GATENAVN
    husnr = husnr or MOVAR_HUSNR
    url = f"{MOVAR_BASE}/Tommekalender"
    headers = {"Kommunenr": KOMMUNENR, "Accept": "application/json", "User-Agent": "InkyFrameCalendar/1.0"}
    params = {"gatenavn": gatenavn, "husnr": husnr}
    if MOVAR_API_TOKEN:
        params["apitoken"] = MOVAR_API_TOKEN
    events = []
    try:
        r = session.get(url, headers=headers, params=params, timeout=10, verify=True)
        if r.status_code != 200:
            if r.status_code == 401 and MOVAR_API_TOKEN:
                try_headers = headers.copy()
                try_headers["apitoken"] = MOVAR_API_TOKEN
                r2 = session.get(url, headers=try_headers, params={"gatenavn": gatenavn, "husnr": husnr}, timeout=10, verify=True)
            return events
        data = r.json()
        allowed = {date_string_for_offset(i) for i in range(days)}
        for item in data:
            try:
                fid = int(item.get("fraksjonId", -1))
            except Exception:
                fid = -1
            dates = item.get("tommedatoer", []) or []
            for d_iso in dates:
                if not d_iso:
                    continue
                date_part = d_iso[:10]
                if date_part in allowed:
                    raw_name = "Movar: " + fraction_names.get(fid, "Ukjent")
                    mapped = apply_event_mapping(raw_name)
                    if mapped.get("filtered_out"):
                        continue
                    ev = {
                        "date": date_part,
                        "name": mapped.get("display_text") or "",
                        "display_text": mapped.get("display_text"),
                        "tag_text": mapped.get("tag_text"),
                        "tag_color_name": mapped.get("tag_color_name"),
                        "tag_color_rgb": mapped.get("tag_color_rgb"),
                        "time": "",
                        "icon": mapped.get("icon"),
                        "icon_size": mapped.get("icon_size"),
                        "icon_color_name": mapped.get("icon_color_name"),
                        "icon_color_rgb": mapped.get("icon_color_rgb"),
                        "icon_mode": mapped.get("mode"),
                        "original_name": raw_name,
                    }
                    if not any(e['date'] == ev['date'] and e['name'] == ev['name'] for e in events):
                        events.append(ev)
    except Exception as ex:
        print("[fetch_tommekalender_events] exception:", ex)
    return events


# --------------------------------------------------------------------
# Google Calendar integration
# --------------------------------------------------------------------
def _ensure_aware(dt):
    """
    Return a tz-aware datetime in UTC.
    - If dt has tzinfo: convert to UTC.
    - If dt is naive: assume it's in TZ (Europe/Oslo) if TZ available, otherwise assume system local time and convert to UTC.
    """
    if dt.tzinfo is None:
        if TZ:
            dt = dt.replace(tzinfo=TZ)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_google_calendar_events(days=DEFAULT_DAYS, session=None):
    session = session or requests.Session()
    today_local = now_local().date()

    if TZ:
        start_local_dt = datetime(year=today_local.year, month=today_local.month, day=today_local.day,
                                  hour=0, minute=0, second=0, microsecond=0, tzinfo=TZ)
    else:
        start_local_dt = datetime.combine(today_local, datetime.min.time())  # naive
    start_utc = _ensure_aware(start_local_dt)
    end_utc = start_utc + timedelta(days=days)

    def iso_z(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    timeMin = iso_z(start_utc)
    timeMax = iso_z(end_utc)
    url = (
        f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events"
        f"?timeMin={timeMin}&timeMax={timeMax}&singleEvents=true&fields=items(summary,start,end)&orderBy=startTime&key={API_KEY_GOOGLE}"
    )

    events = []
    try:
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            for it in items:
                summary = (it.get("summary") or "").strip()
                if not summary:
                    continue
                # Skip titles that are only a token that would be filtered out by mapping
                if summary and mapping_info_for_event:
                    try:
                        mcheck = mapping_info_for_event(summary)
                        if mcheck and mcheck.get("remaining_text", "").strip() == "" and (mcheck.get("mode") in ("replace_icon", "replace_text", "replace_all")):
                            applied = apply_event_mapping(summary)
                            if applied.get("filtered_out"):
                                continue
                    except Exception:
                        pass

                start = it.get("start", {})
                end = it.get("end", {})
                if "date" in start:  # heldags-event
                    sdate = start["date"]
                    edate = end.get("date", sdate)
                    try:
                        sdt = datetime.strptime(sdate, "%Y-%m-%d").date()
                        edt = datetime.strptime(edate, "%Y-%m-%d").date()
                    except Exception:
                        sdt = None
                        edt = None

                    try:
                        query_start_date = start_local_dt.date()
                    except Exception:
                        query_start_date = now_local().date()

                    if sdt is None or edt is None:
                        date_str = sdate
                        try:
                            if datetime.strptime(date_str, "%Y-%m-%d").date() < query_start_date:
                                continue
                        except Exception:
                            pass
                        mapped = apply_event_mapping(summary)
                        if mapped.get("filtered_out"):
                            continue
                        ev = {
                            "date": date_str,
                            "name": mapped.get("display_text") or "",
                            "display_text": mapped.get("display_text"),
                            "tag_text": mapped.get("tag_text"),
                            "tag_color_name": mapped.get("tag_color_name"),
                            "tag_color_rgb": mapped.get("tag_color_rgb"),
                            "time": "",
                            "icon": mapped.get("icon"),
                            "icon_size": mapped.get("icon_size"),
                            "icon_color_name": mapped.get("icon_color_name"),
                            "icon_color_rgb": mapped.get("icon_color_rgb"),
                            "icon_mode": mapped.get("mode"),
                            "original_name": summary,
                        }
                        if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                            events.append(ev)
                    else:
                        last_day = edt - timedelta(days=1)
                        day = max(sdt, query_start_date)
                        while day <= last_day:
                            date_str = day.strftime("%Y-%m-%d")
                            mapped = apply_event_mapping(summary)
                            if mapped.get("filtered_out"):
                                day += timedelta(days=1)
                                continue
                            ev = {
                                "date": date_str,
                                "name": mapped.get("display_text") or "",
                                "display_text": mapped.get("display_text"),
                                "tag_text": mapped.get("tag_text"),
                                "tag_color_name": mapped.get("tag_color_name"),
                                "tag_color_rgb": mapped.get("tag_color_rgb"),
                                "time": "",
                                "icon": mapped.get("icon"),
                                "icon_size": mapped.get("icon_size"),
                                "icon_color_name": mapped.get("icon_color_name"),
                                "icon_color_rgb": mapped.get("icon_color_rgb"),
                                "icon_mode": mapped.get("mode"),
                                "original_name": summary,
                            }
                            if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                                events.append(ev)
                            day += timedelta(days=1)
                elif "dateTime" in start:
                    dt_start_raw = start.get("dateTime")
                    dt_end_raw = end.get("dateTime") or dt_start_raw

                    dt_core_start = dt_start_raw[:19]
                    dt_core_end = dt_end_raw[:19]
                    try:
                        dt_start = datetime.strptime(dt_core_start, "%Y-%m-%dT%H:%M:%S")
                        dt_end = datetime.strptime(dt_core_end, "%Y-%m-%dT%H:%M:%S")
                    except Exception:
                        try:
                            dt = datetime.strptime(dt_core_start, "%Y-%m-%dT%H:%M:%S")
                            date_str = dt.strftime("%Y-%m-%d")
                            time_str = dt.strftime("%H:%M")
                            mapped = apply_event_mapping(summary)
                            if mapped.get("filtered_out"):
                                continue
                            ev = {
                                "date": date_str,
                                "name": mapped.get("display_text") or "",
                                "display_text": mapped.get("display_text"),
                                "tag_text": mapped.get("tag_text"),
                                "tag_color_name": mapped.get("tag_color_name"),
                                "tag_color_rgb": mapped.get("tag_color_rgb"),
                                "time": time_str,
                                "icon": mapped.get("icon"),
                                "icon_size": mapped.get("icon_size"),
                                "icon_color_name": mapped.get("icon_color_name"),
                                "icon_color_rgb": mapped.get("icon_color_rgb"),
                                "icon_mode": mapped.get("mode"),
                                "original_name": summary,
                            }
                            if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                                events.append(ev)
                        except Exception:
                            pass
                        continue

                    sdt = dt_start.date()
                    edt = dt_end.date()
                    include_end = (dt_end.time() != datetime.min.time())
                    last_day = edt if include_end else (edt - timedelta(days=1))

                    try:
                        query_start_date = start_local_dt.date()
                    except Exception:
                        query_start_date = now_local().date()

                    day = max(sdt, query_start_date)
                    while day <= last_day:
                        date_str = day.strftime("%Y-%m-%d")
                        mapped = apply_event_mapping(summary)
                        if mapped.get("filtered_out"):
                            day += timedelta(days=1)
                            continue

                        time_str = dt_start.strftime("%H:%M") if day == sdt else ""

                        ev = {
                            "date": date_str,
                            "name": mapped.get("display_text") or "",
                            "display_text": mapped.get("display_text"),
                            "tag_text": mapped.get("tag_text"),
                            "tag_color_name": mapped.get("tag_color_name"),
                            "tag_color_rgb": mapped.get("tag_color_rgb"),
                            "time": time_str,
                            "icon": mapped.get("icon"),
                            "icon_size": mapped.get("icon_size"),
                            "icon_color_name": mapped.get("icon_color_name"),
                            "icon_color_rgb": mapped.get("icon_color_rgb"),
                            "icon_mode": mapped.get("mode"),
                            "original_name": summary,
                        }
                        if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                            events.append(ev)
                        day += timedelta(days=1)
    except Exception as ex:
        print("[fetch_google_calendar_events] exception:", ex)
    events.sort(key=lambda e: (e['date'], e.get('time', '')))
    return events


# --------------------------------------------------------------------
# Weather provider integration
# --------------------------------------------------------------------
try:
    from weather_provider import get_forecast_json, debug_print  # may raise
except Exception:
    def get_forecast_json(*args, **kwargs):
        return {}
    def debug_print(*args, **kwargs):
        pass


def fetch_weather_from_provider(lat=LAT, lon=LON, days=DEFAULT_DAYS):
    try:
        forecast = get_forecast_json(lat=lat, lon=lon, days=days, user_agent="InkyFrameCalendar/1.0 (contact: youremail@example.com)", keep_debug_hourly=True)
        weather_list = []
        for day in forecast.get("daily", []):
            weather_list.append({
                "date": day.get("date"),
                "condition": day.get("symbol"),
                "temp_max": day.get("temp_max"),
                "temp_min": day.get("temp_min"),
                "precip": day.get("precip"),
                "wind_max": day.get("wind_max"),
                "wind_dir_deg": day.get("wind_dir_deg"),
                "source": day.get("source")
            })
        hourly_today = forecast.get("hourly_today", [])
        return weather_list, hourly_today, forecast.get("meta", {})
    except Exception as ex:
        return [], [], {}


# --------------------------------------------------------------------
# Tag enrichment helpers (new) and initial_fetch_all wiring
# --------------------------------------------------------------------
def _color_from_mapping_entry(entry):
    """
    Try to return an (r,g,b) tuple from a mapping entry (dict), or None.
    """
    if not entry or not isinstance(entry, dict):
        return None
    for k in ("color_rgb", "tag_color_rgb", "icon_color_rgb"):
        if entry.get(k) is not None:
            try:
                v = entry.get(k)
                return (int(v[0]), int(v[1]), int(v[2]))
            except Exception:
                pass
    for k in ("color", "tag_color_name", "icon_color_name", "color_name"):
        if entry.get(k):
            try:
                rgb = ImageColor.getrgb(str(entry.get(k)))
                return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            except Exception:
                pass
    for k, v in entry.items():
        try:
            if str(k).lower().endswith("color") and v:
                rgb = ImageColor.getrgb(str(v))
                return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        except Exception:
            pass
    return None


def _split_tag_text_into_tokens(raw):
    """
    Heuristic splitting: commas first; else capitalized words.
    """
    if not raw:
        return []
    s = str(raw).strip()
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if parts:
        return parts
    caps = re.findall(r"\b[A-ZÆØÅ][a-zæøåA-ZÆØÅ\-\']+\b", s)
    if caps:
        return caps
    return []


def _build_lookup_from_EVENT_MAPPINGS(event_mappings_obj):
    """
    Convert EVENT_MAPPINGS (list or dict) -> simple lookup dict by common keys
    """
    lookup = {}
    if not event_mappings_obj:
        return lookup
    try:
        if isinstance(event_mappings_obj, dict):
            for k, v in event_mappings_obj.items():
                key = str(k).strip()
                if key:
                    lookup[key] = v
                if isinstance(v, dict):
                    for candidate in ("replacement", "token", "keyword", "name"):
                        val = v.get(candidate)
                        if val:
                            lookup[str(val).strip()] = v
        elif isinstance(event_mappings_obj, (list, tuple)):
            for v in event_mappings_obj:
                if not isinstance(v, dict):
                    continue
                for candidate in ("replacement", "token", "keyword", "name"):
                    val = v.get(candidate)
                    if val:
                        lookup[str(val).strip()] = v
    except Exception:
        pass
    return lookup


def enrich_events_with_tags(events, EVENT_MAPPINGS=None, prefer_mapping_module=True):
    """
    Return a copy of events where each event has ev['tags'] = [{'text':.., 'color_rgb':(...)}...]
    Behavior:
      - If event already has ev['tags'], normalize and keep them.
      - Prefer structured tags returned by mapping_func(ev_name) (if present).
      - If not present, prefer explicit ev['tag_text'] split by commas.
      - FALLBACK (conservative): scan words/tokens in event name and only accept a token
        as a tag if it matches a key in EVENT_MAPPINGS lookup or mapping_info_for_event(token)
        returns structured info with a color/tag. This avoids creating tags for arbitrary
        capitalized names (which caused Geir/Wiggen/Restavfall).
    """
    import importlib
    mapping_func = None
    try:
        m = importlib.import_module("mappings")
        if hasattr(m, "apply_event_mapping") and callable(getattr(m, "apply_event_mapping")):
            mapping_func = getattr(m, "apply_event_mapping")
    except Exception:
        mapping_func = None

    lookup = {}
    if EVENT_MAPPINGS:
        lookup = _build_lookup_from_EVENT_MAPPINGS(EVENT_MAPPINGS)

    enriched = []
    for ev in events:
        ev_copy = dict(ev)

        # 1) If ev already has structured tags, normalize them and keep
        if ev_copy.get("tags"):
            try:
                norm = []
                for t in ev_copy.get("tags"):
                    if not isinstance(t, dict):
                        continue
                    te = {"text": str(t.get("text") or "").strip()}
                    if t.get("color_rgb") is not None:
                        try:
                            te["color_rgb"] = (int(t["color_rgb"][0]), int(t["color_rgb"][1]), int(t["color_rgb"][2]))
                        except Exception:
                            pass
                    elif t.get("color_name"):
                        try:
                            rgb = ImageColor.getrgb(str(t.get("color_name")))
                            te["color_rgb"] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
                        except Exception:
                            pass
                    norm.append(te)
                if norm:
                    ev_copy["tags"] = norm
                enriched.append(ev_copy)
                continue
            except Exception:
                pass

        # 2) Try mapping_func for full summary first (may return structured tags)
        try:
            if mapping_func and prefer_mapping_module:
                mapped = mapping_func(ev_copy.get("name") or ev_copy.get("display_text") or "")
                if isinstance(mapped, dict) and mapped.get("tags"):
                    out_tags = []
                    for t in mapped.get("tags"):
                        if not isinstance(t, dict):
                            continue
                        te = {"text": str(t.get("text") or "").strip()}
                        if t.get("color_rgb") is not None:
                            try:
                                te["color_rgb"] = (int(t["color_rgb"][0]), int(t["color_rgb"][1]), int(t["color_rgb"][2]))
                            except Exception:
                                pass
                        elif t.get("color_name"):
                            try:
                                rgb = ImageColor.getrgb(str(t.get("color_name")))
                                te["color_rgb"] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
                            except Exception:
                                pass
                        out_tags.append(te)
                    if out_tags:
                        ev_copy["tags"] = out_tags
                        enriched.append(ev_copy)
                        continue
        except Exception:
            pass

        # 3) If explicit tag_text exists, split by commas and honor legacy color if given
        raw = ev_copy.get("tag_text") or ev_copy.get("tag") or ""
        parts = _split_tag_text_into_tokens(raw)

        tags_out = []
        legacy_rgb = None
        legacy_name = ev_copy.get("tag_color_name")
        if ev_copy.get("tag_color_rgb") is not None:
            try:
                legacy_rgb = (int(ev_copy["tag_color_rgb"][0]), int(ev_copy["tag_color_rgb"][1]), int(ev_copy["tag_color_rgb"][2]))
            except Exception:
                legacy_rgb = None

        if parts:
            for p in parts:
                if not p:
                    continue
                color_rgb = None
                # lookup in EVENT_MAPPINGS-derived lookup
                entry = lookup.get(p) or lookup.get(p.strip())
                if entry:
                    color_rgb = _color_from_mapping_entry(entry)
                # mapping_func on token as fallback
                if color_rgb is None and mapping_func:
                    try:
                        info = mapping_func(p)
                        if isinstance(info, dict):
                            color_rgb = _color_from_mapping_entry(info)
                            if color_rgb is None and info.get("tags"):
                                try:
                                    t0 = info.get("tags")[0]
                                    color_rgb = _color_from_mapping_entry(t0) or color_rgb
                                except Exception:
                                    pass
                    except Exception:
                        pass
                # final fallback legacy
                if color_rgb is None and legacy_rgb is not None:
                    color_rgb = legacy_rgb
                elif color_rgb is None and legacy_name:
                    try:
                        color_rgb = ImageColor.getrgb(str(legacy_name))
                    except Exception:
                        color_rgb = None

                tag_entry = {"text": str(p).strip()}
                if color_rgb is not None:
                    try:
                        tag_entry["color_rgb"] = (int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2]))
                    except Exception:
                        pass
                tags_out.append(tag_entry)
            if tags_out:
                ev_copy["tags"] = tags_out
                enriched.append(ev_copy)
                continue

        # 4) CONSERVATIVE FALLBACK: scan tokens in name but only accept them
        #    if they are present in EVENT_MAPPINGS lookup or mapping_info_for_event(token)
        #    returns something useful. This prevents creating tags for arbitrary capitalized tokens.
        name_source = ev_copy.get("name") or ev_copy.get("original_name") or ""
        tokens = [t.strip() for t in re.split(r"[,\s\-\:]+", str(name_source)) if t.strip()]
        found = []
        for t in tokens:
            if not t:
                continue
            # only consider short tokens (avoid long fragments)
            if len(t) > 30 or len(t) < 2:
                continue
            # check direct lookup (case-insensitive)
            entry = lookup.get(t) or lookup.get(t.lower()) or lookup.get(t.capitalize())
            color_rgb = None
            if entry:
                color_rgb = _color_from_mapping_entry(entry)
            # else ask mapping_func for the token (if available)
            if color_rgb is None and mapping_func:
                try:
                    info = mapping_func(t)
                    if isinstance(info, dict):
                        # accept if mapping returns a replacement/tag or color
                        color_rgb = _color_from_mapping_entry(info)
                        # if mapping contains tags with colors, accept first
                        if color_rgb is None and info.get("tags"):
                            try:
                                t0 = info.get("tags")[0]
                                color_rgb = _color_from_mapping_entry(t0) or color_rgb
                            except Exception:
                                pass
                        # only accept token if info suggests it's a tag/replacement (avoid noise)
                        if not (info.get("replacement") or info.get("mode") or info.get("tags") or info.get("color") or info.get("color_rgb")):
                            color_rgb = None
                except Exception:
                    pass
            if color_rgb is not None:
                found.append((t, color_rgb))

        if found:
            out_tags = []
            for t, c in found:
                te = {"text": str(t)}
                try:
                    te["color_rgb"] = (int(c[0]), int(c[1]), int(c[2]))
                except Exception:
                    pass
                out_tags.append(te)
            ev_copy["tags"] = out_tags
        # else: do not add noisy capitalized-word tags

        enriched.append(ev_copy)

    return enriched
# --------------------------------------------------------------------
# initial_fetch_all (wired to call enrichment)
# --------------------------------------------------------------------
def initial_fetch_all(days=DEFAULT_DAYS, session=None, gatenavn=None, husnr=None):
    import json
    import os
    from datetime import datetime

    s = session or requests.Session()
    try:
        # fetch initial data
        fractions = fetch_fraction_names(session=s)
        tomme = fetch_tommekalender_events(fractions, days=days, session=s, gatenavn=gatenavn, husnr=husnr)
        gcal = fetch_google_calendar_events(days=days, session=s)

        
        # fetch public holidays (Norway calendar by default)
        holidays = []
        try:
            holidays = fetch_google_holiday_events(calendar_id=HOLIDAYS_CALENDAR_ID, days=days, session=s)
        except Exception:
            holidays = []
# fetch weather: (weather, hourly, meta) expected from your provider function
        weather, hourly, meta = fetch_weather_from_provider(lat=LAT, lon=LON, days=days)

        # --- Ensure hourly entries include 'condition' and 'precip' for renderer ---
        try:
            # Normalize keys and fill missing fields so renderer can map icons
            hourly = hourly or []
            for h in hourly:
                # ensure precip is present (many providers use precip_mm or precipitation)
                if h.get("precip") is None:
                    if h.get("precip_mm") is not None:
                        h["precip"] = h.get("precip_mm")
                    elif h.get("precipitation") is not None:
                        h["precip"] = h.get("precipitation")
                    else:
                        h["precip"] = 0.0

                # ensure temperature field is normalized
                if h.get("temp") is None:
                    if h.get("temperature") is not None:
                        h["temp"] = h.get("temperature")
                    elif h.get("air_temperature") is not None:
                        h["temp"] = h.get("air_temperature")

                # ensure there's a condition string; try matching daily summary first
                if not h.get("condition"):
                    # try find the day summary for this hour (match by date prefix YYYY-MM-DD)
                    t = h.get("time") or h.get("dt") or h.get("datetime")
                    date_str = None
                    if isinstance(t, str) and len(t) >= 10:
                        date_str = t[:10]
                    elif isinstance(t, (int, float)):
                        # if time is hour index or epoch, we don't try to match day summary
                        date_str = None

                    day_entry = None
                    if date_str and weather:
                        for d in weather:
                            if d.get("date") == date_str:
                                day_entry = d
                                break
                    if day_entry and (day_entry.get("condition") or day_entry.get("symbol")):
                        # prefer daily textual condition if available
                        h["condition"] = day_entry.get("condition") or day_entry.get("symbol")
                    else:
                        # fallback heuristic: if temp exists and <= 0 -> 'Skyet' (or 'Snø' if heavy precip)
                        tval = h.get("temp")
                        pval = h.get("precip", 0.0) or 0.0
                        if pval >= 2.5:
                            # heavy precip — guess rain or snow depending on temp
                            h["condition"] = "Regn" if (tval is None or tval > 1.5) else "Snø"
                        else:
                            if tval is None:
                                h["condition"] = "Skyet"
                            else:
                                # use a slightly more descriptive guess
                                if tval <= -1.5:
                                    h["condition"] = "Skyet"
                                elif tval <= 0.5:
                                    h["condition"] = "Delvis skyet"
                                else:
                                    h["condition"] = "Klarvær"
        except Exception:
            # don't break the whole fetch if something odd happens here
            pass

        # merge events (tommekalender + gcal)
        events = []
        for e in gcal + tomme + holidays:
            if not any(x['date'] == e['date'] and x['name'] == e['name'] and x.get('time', '') == e.get('time', '') for x in events):
                events.append(e)
        events.sort(key=lambda e: (e['date'], e.get('time', '')))

        # ---- ENRICH events with structured tags (so renderer can color per-tag) ----
        try:
            # prefer EVENT_MAPPINGS from mappings module if available
            em = EVENT_MAPPINGS if 'EVENT_MAPPINGS' in globals() else None
            events = enrich_events_with_tags(events, EVENT_MAPPINGS=em, prefer_mapping_module=True)
        except Exception:
            # fail gracefully: keep original events
            pass

        # DEBUG: dump first weather entry for debugging and produce hourly preview + period picks
        try:
            if weather:
                print("[DEBUG weather sample] first weather entry:", weather[0])
            else:
                print("[DEBUG weather sample] weather list empty")
            print("[DEBUG hourly_today sample] len:", len(hourly))
        except Exception:
            print("[DEBUG] failed to print weather debug")

        # --- Additional debug: write hourly payload and print a readable summary + rep-per-period ---
        try:
            # write debug file next to this module
            module_dir = os.path.dirname(__file__)
            debug_path = os.path.join(module_dir, "debug_hourly.json")
            try:
                with open(debug_path, "w", encoding="utf-8") as fh:
                    json.dump(hourly, fh, ensure_ascii=False, indent=2)
                print(f"[DEBUG] Saved debug hourly to: {debug_path}")
            except Exception as ex:
                print("[DEBUG] failed to write debug_hourly.json:", ex)

            # compact preview of first 24 entries
            try:
                print("[DEBUG hourly entries preview] (index, time, cond, temp, precip)")
                for i, h in enumerate((hourly or [])[:24]):
                    t = h.get("time") or h.get("dt") or h.get("datetime") or h.get("hour") or "<no-time>"
                    cond = h.get("condition") or h.get("symbol") or h.get("weather") or ""
                    temp = h.get("temp") or h.get("temperature") or None
                    precip = h.get("precip") if h.get("precip") is not None else h.get("precip_mm", None)
                    print(f"  {i:02d}: {t} | {cond!r:30} | temp={str(temp):>6} | precip={str(precip)}")
            except Exception as ex:
                print("[DEBUG] failed to print hourly summary:", ex)

            # quick representative selection check (simple heuristics)
            try:
                def _norm_cond_key(cond):
                    if not cond:
                        return "cloud"
                    c = str(cond).lower()
                    if "rain" in c or "regn" in c or "byge" in c:
                        return "rain"
                    if "snow" in c or "snø" in c:
                        return "snow"
                    if "sun" in c or "klar" in c:
                        return "sun"
                    if "thun" in c or "lyn" in c:
                        return "thunder"
                    if "fog" in c or "tåke" in c:
                        return "fog"
                    if "cloud" in c or "sky" in c or "skyet" in c:
                        return "cloud"
                    return "cloud"

                def _choose_for_period(hours):
                    if not hours:
                        return None
                    rank = {"sun":0, "cloud":1, "rain":2, "snow":3, "thunder":4}
                    best = None
                    best_rank = -1
                    for hh in hours:
                        key = _norm_cond_key(hh.get("condition") or hh.get("symbol") or hh.get("weather"))
                        r = rank.get(key, 1)
                        precip = hh.get("precip") or hh.get("precip_mm") or 0.0
                        if best is None or (r > best_rank) or (r == best_rank and (precip or 0) > (best.get("precip") or 0)):
                            best_rank = r
                            best = {"hour": hh, "key": key, "precip": precip}
                    return best

                # naive split by hour-of-day; fallback to index-based distribution if no proper time field
                periods = {"morning":[], "lunch":[], "day":[], "evening":[]}
                for idx, hh in enumerate(hourly or []):
                    t = hh.get("time")
                    hour = None
                    if isinstance(t, str):
                        try:
                            hour = int(datetime.fromisoformat(t.replace("Z", "+00:00")).hour)
                        except Exception:
                            hour = None
                    elif isinstance(t, (int, float)):
                        try:
                            hour = int(t)
                        except Exception:
                            hour = None
                    if hour is None:
                        # distribute by index along 24h
                        pos = idx % 24
                        hour = pos

                    if 6 <= hour <= 10:
                        periods["morning"].append(hh)
                    elif 11 <= hour <= 13:
                        periods["lunch"].append(hh)
                    elif 14 <= hour <= 17:
                        periods["day"].append(hh)
                    else:
                        periods["evening"].append(hh)

                for name in ("morning","lunch","day","evening"):
                    rep = _choose_for_period(periods[name])
                    if rep:
                        hh = rep["hour"]
                        t = hh.get("time") or hh.get("dt") or "<no-time>"
                        print(f"[DEBUG chosen] {name:7} -> {t} {rep['key']} precip={rep['precip']}")
                    else:
                        print(f"[DEBUG chosen] {name:7} -> <no data>")
            except Exception as ex:
                print("[DEBUG] rep selection failed:", ex)

        except Exception as ex:
            print("[DEBUG] hourly debug block failed:", ex)

        return {"events": events, "weather": weather, "hourly_today": hourly, "meta": meta}

    finally:
        if session is None:
            s.close()


# --------------------------------------------------------------------
# debug main
# --------------------------------------------------------------------
if __name__ == "__main__":
    out = initial_fetch_all(days=14)
    print("Events count:", len(out.get("events", [])))
    for e in out.get("events", [])[:100]:
        print(e)

    print("\nDetailed debug preview (first 40):")
    for e in out.get("events", [])[:40]:
        print("----")
        print("date:", e.get("date"))
        print("name:", e.get("name"))
        print("display_text:", repr(e.get("display_text")))
        print("tag_text:", repr(e.get("tag_text")))
        print("tag_color_name:", repr(e.get("tag_color_name")))
        print("tag_color_rgb:", repr(e.get("tag_color_rgb")))
        print("tags:", repr(e.get("tags")))
        print("icon:", repr(e.get("icon")))
        print("icon_color_name:", repr(e.get("icon_color_name")))
        print("icon_color_rgb:", repr(e.get("icon_color_rgb")))


def fetch_google_holiday_events(calendar_id=None, days=DEFAULT_DAYS, session=None):
    """
    Fetch public-holiday (all-day) events from a given Google Calendar ID.
    Returns list of normalized event dicts similar to fetch_google_calendar_events().
    These events have:
      - time: "" (all-day)
      - tag_text: "Offentlig Fridag:"  (so mapping layer can pick up icon/color)
    """
    import requests
    from datetime import datetime, timedelta

    session = session or requests.Session()
    cal_id = calendar_id or HOLIDAYS_CALENDAR_ID
    # ensure '#' is URL encoded for use in URL
    encoded_cal_id = cal_id.replace("#", "%23")

    today_local = now_local().date()
    if TZ:
        start_local_dt = datetime(year=today_local.year, month=today_local.month, day=today_local.day,
                                  hour=0, minute=0, second=0, microsecond=0, tzinfo=TZ)
    else:
        start_local_dt = datetime.combine(today_local, datetime.min.time())
    start_utc = _ensure_aware(start_local_dt)
    end_utc = start_utc + timedelta(days=days)

    def iso_z(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    timeMin = iso_z(start_utc)
    timeMax = iso_z(end_utc)
    url = (
        f"https://www.googleapis.com/calendar/v3/calendars/{encoded_cal_id}/events"
        f"?timeMin={timeMin}&timeMax={timeMax}&singleEvents=true&fields=items(summary,start,end)&orderBy=startTime&key={API_KEY_GOOGLE}"
    )

    holidays = []
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        items = data.get("items", [])
        # query_start_date used to skip past multi-day events that start earlier
        try:
            query_start_date = start_local_dt.date()
        except Exception:
            query_start_date = now_local().date()

        for it in items:
            summary = (it.get("summary") or "").strip()
            if not summary:
                continue
            start = it.get("start", {})
            end = it.get("end", {})

            # Prefer all-day date events; but if dateTime present, treat defensively.
            if "date" in start:
                sdate = start["date"]
                edate = end.get("date", sdate)
                try:
                    sdt = datetime.strptime(sdate, "%Y-%m-%d").date()
                    edt = datetime.strptime(edate, "%Y-%m-%d").date()
                except Exception:
                    sdt = None
                    edt = None

                # If parsing failed, include if not obviously out-of-range
                if sdt is None or edt is None:
                    date_str = sdate
                    try:
                        if datetime.strptime(date_str, "%Y-%m-%d").date() < query_start_date:
                            continue
                    except Exception:
                        pass
                    ev = {
                        "date": date_str,
                        "name": summary,
                        "display_text": summary,
                        "tag_text": "Offentlig Fridag:",
                        "tag_color_name": None,
                        "tag_color_rgb": None,
                        "time": "",
                        "icon": None,
                        "icon_size": None,
                        "icon_color_name": None,
                        "icon_color_rgb": None,
                        "icon_mode": None,
                        "original_name": summary,
                    }
                    if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in holidays):
                        holidays.append(ev)
                else:
                    # Google calendar all-day events use exclusive end date, so last_day = edt - 1
                    last_day = edt - timedelta(days=1)
                    day = max(sdt, query_start_date)
                    while day <= last_day:
                        date_str = day.strftime("%Y-%m-%d")
                        ev = {
                            "date": date_str,
                            "name": summary,
                            "display_text": summary,
                            "tag_text": "Offentlig Fridag:",
                            "tag_color_name": None,
                            "tag_color_rgb": None,
                            "time": "",
                            "icon": None,
                            "icon_size": None,
                            "icon_color_name": None,
                            "icon_color_rgb": None,
                            "icon_mode": None,
                            "original_name": summary,
                        }
                        if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in holidays):
                            holidays.append(ev)
                        day += timedelta(days=1)
            elif "dateTime" in start:
                # Uncommon for a holiday calendar, but handle gracefully:
                try:
                    dt_start = start.get("dateTime") or ""
                    date_str = dt_start[:10]
                except Exception:
                    date_str = None
                if date_str:
                    ev = {
                        "date": date_str,
                        "name": summary,
                        "display_text": summary,
                        "tag_text": "Offentlig Fridag:",
                        "tag_color_name": None,
                        "tag_color_rgb": None,
                        "time": "",
                        "icon": None,
                        "icon_size": None,
                        "icon_color_name": None,
                        "icon_color_rgb": None,
                        "icon_mode": None,
                        "original_name": summary,
                    }
                    if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in holidays):
                        holidays.append(ev)
        holidays.sort(key=lambda e: (e['date'], e.get('time', '')))
        return holidays
    except Exception as ex:
        print("[fetch_google_holiday_events] exception:", ex)
        return []

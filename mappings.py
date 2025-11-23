"""
mappings.py (CSV-only + local cache + fallback)

Order of attempts when loading mappings:
  1) Published CSV URL (env GS_CSV_URL) OR explicit url argument
  2) Local valid cache (event_mappings_cache.json by default)
  3) Embedded fallback list

Environment variables:
  GS_CSV_URL           -> published CSV URL (optional)
  GS_CACHE_PATH        -> cache path (default: "event_mappings_cache.json")
  GS_CACHE_TTL_SECONDS -> how long cache is valid in seconds (default: 3600)
  MAPPINGS_DEBUG=1     -> print summary on import

Notes:
- CSV must have headers: keyword, icon, replacement, mode, color, match_type, size_px
- You can call reload_event_mappings(url="...") to force-load from a specific URL (handy on Windows)
"""

from typing import Optional, Dict, Any, List, Tuple
import re
import os
import time
import json

# requests is required for CSV mode; fail early with a clear message if missing
try:
    import requests
except Exception as e:
    requests = None  # we'll raise a clear error if CSV fetch is attempted

# --- Colors and small helpers ----------------------------------------
INKY_COLORS = {
    "black":  (0, 0, 0),
    "white":  (255, 255, 255),
    "red":    (255, 0, 0),
    "yellow": (255, 255, 0),
    "green":  (0, 128, 0),
    "blue":   (0, 0, 255),
    "orange": (255, 128, 0),
}

def color_to_rgb(name: Optional[str]):
    if not name:
        return None
    k = str(name).strip().lower()
    if k in INKY_COLORS:
        return INKY_COLORS[k]
    try:
        if k.startswith("#") and (len(k) == 7 or len(k) == 4):
            if len(k) == 4:
                r = int(k[1]*2, 16)
                g = int(k[2]*2, 16)
                b = int(k[3]*2, 16)
                return (r, g, b)
            r = int(k[1:3], 16)
            g = int(k[3:5], 16)
            b = int(k[5:7], 16)
            return (r, g, b)
        if k.startswith("rgb"):
            nums = re.findall(r"[-]?\d+", k)
            if len(nums) >= 3:
                return (int(nums[0]), int(nums[1]), int(nums[2]))
    except Exception:
        pass
    return None

DEFAULT_WEATHER_MAP = {
    "sol": "sun",
    "klart": "sun",
    "cloud": "cloud",
    "regn": "cloud-rain",
    "rain": "cloud-rain",
    "snø": "cloud-snow",
    "snow": "cloud-snow",
    "vind": "wind",
    "torden": "cloud-lightning",
}

def weather_to_icon(symbol: Optional[str]) -> Optional[str]:
    if not symbol:
        return None
    k = str(symbol).strip().lower()
    if k in DEFAULT_WEATHER_MAP:
        return DEFAULT_WEATHER_MAP[k]
    for s, icon in DEFAULT_WEATHER_MAP.items():
        if s in k:
            return icon
    return None

# --- Embedded fallback mappings --------------------------------------
FALLBACK_EVENT_MAPPINGS = [
    { "keyword": "Middag:", "icon": "coffee", "replacement": "", "mode": "replace_icon",
      "color": "RED", "match_type": "contains", "size_px": 18 },
    { "keyword": "movar:", "icon": "trash-2", "replacement": "", "mode": "replace_icon",
      "color": "RED", "match_type": "contains", "size_px": 18 },
    { "keyword": "ferie:", "icon": "flag", "replacement": "ferie", "mode": "replace_all",
      "color": "", "match_type": "contains", "size_px": 18 },
    { "keyword": "husk:", "icon": "bell", "replacement": "husk", "mode": "replace_icon",
      "color": "RED", "match_type": "contains", "size_px": 18 },
    { "keyword": "bursdag:", "icon": "cake", "replacement": "bursdag", "mode": "replace_all",
      "color": "", "match_type": "contains", "size_px": 18 },
    { "keyword": "r.i.p:", "icon": "grave-stone", "replacement": "", "mode": "replace_icon",
      "color": "", "match_type": "contains", "size_px": 18 },
    { "keyword": "G16 IK", "icon": "soccer", "replacement": "Peter", "mode": "replace_all",
      "color": "BLUE", "match_type": "contains", "size_px": 18 },
    { "keyword": "oslo", "icon": "city", "replacement": "", "mode": "add_icon",
      "color": "", "match_type": "contains", "size_px": 18 },
    { "keyword": "amalie", "icon": "", "replacement": "Amalie", "mode": "replace_text",
      "color": "YELLOW", "match_type": "contains", "size_px": 18 },
    { "keyword": "sigrid", "icon": "", "replacement": "Sigrid", "mode": "replace_text",
      "color": "GREEN", "match_type": "contains", "size_px": 18 },
    { "keyword": "peter", "icon": "", "replacement": "Peter", "mode": "replace_text",
      "color": "BLACK", "match_type": "contains", "size_px": 18 },
    { "keyword": "ingun", "icon": "", "replacement": "Ingun", "mode": "replace_text",
      "color": "RED", "match_type": "contains", "size_px": 18 },
    { "keyword": "christian", "icon": "", "replacement": "Christian", "mode": "replace_text",
      "color": "BLACK", "match_type": "contains", "size_px": 18 },
    { "keyword": "G16", "icon": "soccer", "replacement": "Peter", "mode": "replace_all",
      "color": "BLUE", "match_type": "contains", "size_px": 18 },
    { "keyword": "leire", "icon": "palette", "replacement": "", "mode": "add_icon",
      "color": "YELLOW", "match_type": "contains", "size_px": 18 },
    { "keyword": "skole", "icon": "school", "replacement": "", "mode": "add_icon",
      "color": "", "match_type": "contains", "size_px": 18 },
    { "keyword": "istrening", "icon": "skate", "replacement": "Amalie", "mode": "add_all",
      "color": "YELLOW", "match_type": "contains", "size_px": 18 },
]

# --- Config via env ---------------------------------------------------
GS_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTYL3NSfO_r0l9HItyeakQjkqC00XVTgoXrmHgGcSS3HAT_cGGkPmCMibmVKizL33m585mmlHVV0rOV/pub?output=csv"
GS_CACHE_PATH = os.environ.get("GS_CACHE_PATH", "event_mappings_cache.json")
GS_CACHE_TTL_SECONDS = int(os.environ.get("GS_CACHE_TTL_SECONDS", "3600"))

EVENT_MAPPINGS: List[Dict[str, Any]] = []
EVENT_MAPPINGS_LOADED_AT: Optional[float] = None
EVENT_MAPPINGS_SOURCE: str = "fallback"

# --- Normalizer -------------------------------------------------------
def _normalize_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        keyword = str(row.get("keyword", "") or "").strip()
        if not keyword:
            return None
        icon = str(row.get("icon", "") or "").strip()
        replacement = str(row.get("replacement", "") or "").strip()
        mode = str(row.get("mode", "replace_icon") or "replace_icon").strip()
        color = str(row.get("color", "") or "").strip()
        match_type = str(row.get("match_type", "contains") or "contains").strip()
        size_px_raw = str(row.get("size_px", "18") or "18").strip()
        try:
            size_px = int(size_px_raw)
        except Exception:
            size_px = 18

        if mode not in {"replace_icon", "replace_text", "replace_all", "add_icon", "add_all"}:
            mode = "replace_icon"
        if match_type not in {"contains", "prefix", "exact", "startswith", "endswith", "regex"}:
            match_type = "contains"

        return {
            "keyword": keyword,
            "icon": icon,
            "replacement": replacement,
            "mode": mode,
            "color": color,
            "match_type": match_type,
            "size_px": size_px,
        }
    except Exception:
        return None

# --- CSV fetcher (published sheet) -----------------------------------
def fetch_mappings_from_csv_url(url: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch the published CSV; normalize and return mapping dicts.
    Raises RuntimeError with helpful message if requests is missing or url empty.
    """
    if not url:
        url = GS_CSV_URL
    if not url:
        raise RuntimeError("No CSV URL provided. Set GS_CSV_URL env var or pass url to reload_event_mappings(url=...)")

    if requests is None:
        raise RuntimeError("Python package 'requests' is not installed. Run: pip install requests")

    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    content = resp.content.decode("utf-8")
    # parse CSV into dict rows
    import csv, io
    reader = csv.DictReader(io.StringIO(content))
    out = []
    for r in reader:
        nr = _normalize_row(r)
        if nr:
            out.append(nr)
    return out

# --- Cache helpers ----------------------------------------------------
def save_cache(mappings: List[Dict[str, Any]]):
    try:
        with open(GS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"meta": {"fetched_at": int(time.time())}, "mappings": mappings}, f, ensure_ascii=False, indent=2)
    except Exception:
        # non-fatal
        pass

def load_cache_if_valid() -> Optional[List[Dict[str, Any]]]:
    if not os.path.exists(GS_CACHE_PATH):
        return None
    try:
        with open(GS_CACHE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        fetched_at = payload.get("meta", {}).get("fetched_at", 0)
        if time.time() - fetched_at > GS_CACHE_TTL_SECONDS:
            return None
        rows = payload.get("mappings", [])
        out = []
        for r in rows:
            nr = _normalize_row(r)
            if nr:
                out.append(nr)
        return out
    except Exception:
        return None

# --- Main loader -----------------------------------------------------
def _load_event_mappings(force_refresh: bool = False, csv_url: Optional[str] = None) -> Tuple[List[Dict[str, Any]], str]:
    """
    Order of attempts:
      1) CSV published (if csv_url param provided or GS_CSV_URL set)
      2) cache (if valid and not force_refresh)
      3) fallback
    Returns (mappings, source)
    """
    # 1) try CSV (explicit url preferred)
    url_to_try = csv_url or GS_CSV_URL or ""
    if url_to_try and not force_refresh:
        try:
            mappings = fetch_mappings_from_csv_url(url_to_try)
            if mappings:
                save_cache(mappings)
                return mappings, "csv"
            # empty result -> continue to cache/fallback
        except Exception as e:
            # don't raise here — return to cache/fallback but print a helpful message
            print(f"[mappings] CSV fetch error: {e}")

    # 2) try cache
    if not force_refresh:
        cached = load_cache_if_valid()
        if cached:
            return cached, "cache"

    # 3) fallback
    return [dict(m) for m in FALLBACK_EVENT_MAPPINGS], "fallback"

def reload_event_mappings(force_refresh: bool = False, url: Optional[str] = None):
    """
    Public reload function.
    - url: optional CSV url to load from immediately (overrides GS_CSV_URL).
    - force_refresh: bypass cache (if True).
    """
    global EVENT_MAPPINGS, EVENT_MAPPINGS_LOADED_AT, EVENT_MAPPINGS_SOURCE
    EVENT_MAPPINGS, EVENT_MAPPINGS_SOURCE = _load_event_mappings(force_refresh=force_refresh, csv_url=url)
    EVENT_MAPPINGS_LOADED_AT = time.time()
    print(f"[mappings] Loaded {len(EVENT_MAPPINGS)} mappings from {EVENT_MAPPINGS_SOURCE}")

# convenience test helper (call from REPL)
def test_fetch_csv(url: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch and return parsed rows from the CSV (does not change EVENT_MAPPINGS or cache).
    Useful for quick debugging.
    """
    return fetch_mappings_from_csv_url(url)

# initial load on import (uses env GS_CSV_URL by default)
try:
    reload_event_mappings()
except Exception as e:
    EVENT_MAPPINGS = [dict(m) for m in FALLBACK_EVENT_MAPPINGS]
    EVENT_MAPPINGS_SOURCE = "fallback"
    EVENT_MAPPINGS_LOADED_AT = time.time()
    print(f"[mappings] init failed, using fallback: {e}")

# --- matching helpers (unchanged) ------------------------------------
def _match_text(text: str, keyword: str, match_type: str) -> Optional[re.Match]:
    text = text or ""
    keyword = (keyword or "").strip()
    if not keyword:
        return None
    mt = (match_type or "prefix").strip().lower()
    if mt in ("prefix", "startswith"):
        pattern = r"^\s*" + re.escape(keyword) + r"(?::|\b)?\s*"
        return re.match(pattern, text, flags=re.IGNORECASE)
    if mt == "exact":
        pattern = r"^\s*" + re.escape(keyword) + r"\s*$"
        return re.match(pattern, text, flags=re.IGNORECASE)
    if mt == "regex":
        try:
            return re.search(keyword, text, flags=re.IGNORECASE)
        except re.error:
            return re.search(re.escape(keyword), text, flags=re.IGNORECASE)
    if mt == "endswith":
        pattern = re.escape(keyword) + r"\s*$"
        return re.search(pattern, text, flags=re.IGNORECASE)
    # contains
    pattern = re.escape(keyword)
    return re.search(pattern, text, flags=re.IGNORECASE)

def mapping_info_for_event(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    tstr = str(text)
    for m in EVENT_MAPPINGS:
        kw = m.get("keyword", "")
        match_type = m.get("match_type", "prefix")
        mm = _match_text(tstr, kw, match_type)
        if mm:
            start, end = mm.span()
            remaining = (tstr[:start] + tstr[end:]).strip()
            replacement_text = m.get("replacement") or ""
            mode = (m.get("mode") or "").strip() or None
            icon = m.get("icon") or None
            size_px = int(m.get("size_px") or 18)
            color_name = (m.get("color") or "").strip()
            color_rgb = color_to_rgb(color_name) if color_name else None
            return {
                "icon": icon,
                "replacement": replacement_text,
                "mode": mode,
                "color": color_name,
                "color_rgb": color_rgb,
                "size_px": size_px,
                "remaining_text": remaining,
                "match_span": (start, end),
            }
    return None

# export helper
def export_mappings_as_table() -> List[Dict[str, Any]]:
    rows = []
    for m in EVENT_MAPPINGS:
        rows.append({
            "keyword": m.get("keyword", ""),
            "icon": m.get("icon", ""),
            "replacement": m.get("replacement", ""),
            "mode": m.get("mode", ""),
            "color": m.get("color", ""),
            "match_type": m.get("match_type", ""),
            "size_px": m.get("size_px", 18),
        })
    return rows

# In mappings.py - add this function (one canonical copy)
import re
from PIL import ImageColor

def apply_event_mapping(summary: str):
    """
    Simple, deterministic mapping application.

    Rules:
      - Iterate EVENT_MAPPINGS in order.
      - For each mapping, check if mapping['keyword'] (literal) is contained in the
        current working text (case-insensitive).
      - If mode starts with 'add_' -> collect icon/tag/color but DO NOT modify text.
      - If mode starts with 'replace_' -> remove matched token from the working text:
          - 'replace_text' / 'replace_icon' -> remove first occurrence (case-insensitive)
          - 'replace_all' -> remove all occurrences (case-insensitive)
      - Build structured out dict with per-tag colors where possible.
    """
    original = (summary or "").strip()
    out = {
        "display_text": original,
        "tag_text": None,
        "tag_color_name": None,
        "tag_color_rgb": None,
        "icon": None,
        "icon_size": None,
        "icon_color_name": None,
        "icon_color_rgb": None,
        "mode": None,
        "filtered_out": False,
        "original_name": original,
        "tags": [],
    }
    if not original:
        return out

    # EVENT_MAPPINGS must be available in this module (list of dicts)
    try:
        mappings_list = EVENT_MAPPINGS
    except Exception:
        mappings_list = []

    working = original
    collected_tags = []           # list of {"text":..., "color_name":..., "color_rgb":...}
    first_icon = None
    first_icon_size = None
    first_icon_color_name = None
    first_icon_color_rgb = None
    applied_any = False
    chosen_mode = None

    for m in mappings_list:
        try:
            kw = (m.get("keyword") or "").strip()
            if not kw:
                continue
            mode = (m.get("mode") or "").strip() or None
            icon = m.get("icon") or None
            replacement = (m.get("replacement") or "").strip() or ""
            color_name = m.get("color") or None
            color_rgb_raw = m.get("color_rgb") if m.get("color_rgb") is not None else None
            size_px = m.get("size_px") or None

            # canonicalize color rgb if present as list
            color_rgb = None
            if isinstance(color_rgb_raw, (list, tuple)) and len(color_rgb_raw) >= 3:
                try:
                    color_rgb = (int(color_rgb_raw[0]), int(color_rgb_raw[1]), int(color_rgb_raw[2]))
                except Exception:
                    color_rgb = None
            # fallback: if color_name present, will resolve later via ImageColor.getrgb/color_to_rgb
        except Exception:
            continue

        # case-insensitive contains test
        if kw.lower() not in working.lower():
            # keyword not present in current working text -> skip
            continue

        # record icon as first seen
        if first_icon is None and icon:
            first_icon = icon
            first_icon_size = int(size_px) if size_px else None
            first_icon_color_name = color_name or None
            first_icon_color_rgb = color_rgb

        # collect replacement/tag if present (replacement means a tag string to show)
        if replacement:
            tag_entry = {"text": replacement}
            if color_rgb is not None:
                tag_entry["color_rgb"] = color_rgb
            elif color_name:
                tag_entry["color_name"] = color_name
            collected_tags.append(tag_entry)

        # Decide action on the working text
        if mode is None:
            continue

        mode_l = mode.lower()

        if mode_l.startswith("add_"):
            # add_* modes must NOT modify the text (just collect info)
            applied_any = True
            chosen_mode = chosen_mode or mode_l
            continue

        # For replace_* modes we remove the matched literal (case-insensitive).
        # Use escaped literal and re with IGNORECASE for safety.
        try:
            esc = re.escape(kw)
            if mode_l == "replace_all":
                new_working = re.sub(esc, "", working, flags=re.IGNORECASE)
            else:
                # replace_text and replace_icon -> remove first occurrence only
                new_working = re.sub(esc, "", working, count=1, flags=re.IGNORECASE)
        except re.error:
            # fallback to simple case-insensitive literal removal
            low = working.lower()
            idx = low.find(kw.lower())
            if idx >= 0:
                new_working = working[:idx] + working[idx + len(kw):]
            else:
                new_working = working

        if new_working != working:
            working = new_working.strip()
            applied_any = True
            chosen_mode = chosen_mode or mode_l
        else:
            # If nothing changed, still mark applied if mode was replace_all (maybe kw equals casing?)
            if mode_l == "replace_all":
                applied_any = True
                chosen_mode = chosen_mode or mode_l

    # Build output
    out["display_text"] = working.strip()
    out["icon"] = first_icon
    out["icon_size"] = first_icon_size
    out["icon_color_name"] = first_icon_color_name
    out["icon_color_rgb"] = first_icon_color_rgb
    out["mode"] = chosen_mode

    # Build tags list deduped in order (preserve per-tag colors)
    tags_out = []
    seen = set()
    for t in collected_tags:
        txt = (t.get("text") or "").strip()
        if not txt or txt in seen:
            continue
        seen.add(txt)
        tag_obj = {"text": txt}
        if t.get("color_rgb") is not None:
            try:
                tag_obj["color_rgb"] = tuple(int(x) for x in t["color_rgb"])
            except Exception:
                tag_obj.pop("color_rgb", None)
        elif t.get("color_name"):
            # attempt to convert name to rgb for convenience
            try:
                rgb = None
                # prefer module helper if available
                if "color_to_rgb" in globals() and callable(color_to_rgb):
                    try:
                        rgb = color_to_rgb(t.get("color_name"))
                    except Exception:
                        rgb = None
                if rgb is None:
                    rgb = ImageColor.getrgb(t.get("color_name"))
                tag_obj["color_rgb"] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            except Exception:
                tag_obj["color_name"] = t.get("color_name")
        tags_out.append(tag_obj)

    out["tags"] = tags_out

    # legacy joined tag_text
    if tags_out:
        out["tag_text"] = ", ".join([t["text"] for t in tags_out])
        # pick first color as legacy tag_color_*
        first = tags_out[0]
        if first.get("color_rgb") is not None:
            out["tag_color_rgb"] = tuple(first["color_rgb"])
        elif first.get("color_name"):
            out["tag_color_name"] = first["color_name"]

    # filtered_out if nothing remains and no tags
    if (not out["display_text"] or out["display_text"].strip() == "") and not out.get("tag_text"):
        out["filtered_out"] = True

    return out


# debug summary
def _print_summary():
    print("=== mappings.py summary ===")
    print(f"Mappings source: {EVENT_MAPPINGS_SOURCE}")
    if EVENT_MAPPINGS_LOADED_AT:
        print("Loaded at:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(EVENT_MAPPINGS_LOADED_AT)))
    print(f"Mappings count: {len(EVENT_MAPPINGS)}")
    for i, m in enumerate(EVENT_MAPPINGS[:20]):
        print(f" {i+1:2d}. {m.get('keyword')!r} -> icon={m.get('icon')!r} mode={m.get('mode')!r}")
    print("===========================")

if os.environ.get("MAPPINGS_DEBUG", "") == "1":
    _print_summary()

__all__ = [
    "EVENT_MAPPINGS",
    "EVENT_MAPPINGS_SOURCE",
    "EVENT_MAPPINGS_LOADED_AT",
    "reload_event_mappings",
    "test_fetch_csv",
    "mapping_info_for_event",
    "color_to_rgb",
    "weather_to_icon",
    "export_mappings_as_table",
]


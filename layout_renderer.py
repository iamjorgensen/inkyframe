
def _ensure_opaque(c):
    """Normalize color tuple or hex to (r,g,b,a)"""
    if c is None:
        return (0,0,0,255)
    if isinstance(c, str):
        s = c.strip()
        if s.startswith('#') and len(s) in (7,4):
            if len(s)==7:
                r=int(s[1:3],16); g=int(s[3:5],16); b=int(s[5:7],16)
            else:
                r=int(s[1]*2,16); g=int(s[2]*2,16); b=int(s[3]*2,16)
            return (r,g,b,255)
        return (0,0,0,255)
    if isinstance(c, (list,tuple)):
        if len(c)>=4:
            return (int(c[0]),int(c[1]),int(c[2]),int(c[3]))
        else:
            return (int(c[0]),int(c[1]),int(c[2]),255)
    return (0,0,0,255)

# layout_renderer.py
"""
Renderer for Inky Frame Calendar Project.

- Normalizes color inputs (names/tuples/ints).
- Tints header/weather icons to header_text_color so they read on colored headers.
- Optionally tints event icons per-event using event['color'] when opts["tint_event_icons"]=True.
- Reserves fixed icon slot so times align.
- Robust ellipsize/text metrics, dotted separators, auto-sized boxes.
- Supports multi-line event titles (configurable max_event_lines; default 2).
- Per-tag color support (expects event['tags'] = [{"text","color_rgb"/"color_name"},...]).
"""
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageColor
import os
import re
from typing import List, Tuple, Union, Dict
from datetime import datetime
from mappings import mapping_info_for_event, color_to_rgb
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")

DEFAULT_FONT = os.path.join(FONTS_DIR, "Roboto-Bold.ttf")
DEFAULT_BOLD_FONT = os.path.join(FONTS_DIR, "Roboto-Bold.ttf")

ICON_NAME_MAP = {
    "clearsky_day": "sun",
    "clearsky_night": "moon",
    "fair_day": "sun",
    "fair_night": "moon",
    "partlycloudy_day": "cloud-sun",
    "partlycloudy_night": "cloud-moon",
    "cloudy": "cloud",
    "rain": "cloud-rain",
    "lightrain": "cloud-rain",
    "heavyrain": "cloud-rain",
    "rainshowers_day": "cloud-rain",
    "rainshowers_night": "cloud-rain",
    "snow": "cloud-snow",
    "heavysnow": "cloud-snow",
    "sleet": "cloud-snow",
    "lightsleet": "cloud-snow",
    "snowshowers_day": "cloud-snow",
    "snowshowers_night": "cloud-snow",
    "thunderstorm": "cloud-lightning",
    "rainandthunder": "cloud-lightning",
    "fog": "cloud",
    "wind": "wind",
}

# ---------------- Weather period helpers -----------------------------------
def _symbol_code_to_icon_key(symbol_code: str):
    """Map MET/yr symbol_code into our ICON_NAME_MAP keys or friendly icon names."""
    if not symbol_code:
        return None
    sc = symbol_code.lower()
    # normalize common suffixes like _day/_night
    if sc.endswith("_day") or sc.endswith("_night"):
        base = sc.rsplit("_", 1)[0]
    else:
        base = sc
    # direct map if present
    if base in ICON_NAME_MAP:
        return ICON_NAME_MAP[base]
    # try full symbol_code map
    if symbol_code in ICON_NAME_MAP:
        return ICON_NAME_MAP[symbol_code]
    # heuristics
    if "clear" in sc or "clearsky" in sc:
        return "sun"
    if "partlycloud" in sc or "partly" in sc:
        return "cloud-sun"
    if "cloud" in sc or "overcast" in sc:
        return "cloud"
    if "rain" in sc or "drizzle" in sc or "showers" in sc:
        return "cloud-rain"
    if "snow" in sc or "snowshow" in sc:
        return "cloud-snow"
    if "sleet" in sc:
        return "cloud-snow"
    if "thunder" in sc or "tstorm" in sc:
        return "cloud-lightning"
    if "fog" in sc or "mist" in sc:
        return "cloud"
    return None


def split_hours_to_periods(hourly_list):
    """Split hourly_list into 4 periods: morning (06-10), lunch (11-13), day (14-17), evening (18-23)."""
    from datetime import datetime
    periods = {"morning": [], "lunch": [], "day": [], "evening": []}
    for h in (hourly_list or []):
        t = h.get("time") or h.get("dt") or h.get("datetime")
        hour = None
        if isinstance(t, str):
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                hour = dt.hour
            except Exception:
                hour = None
        elif isinstance(t, (int, float)):
            try:
                hour = int(t) % 24
            except Exception:
                hour = None
        if hour is None:
            # fallback: distribute by index
            idx = (hourly_list or []).index(h) % 24
            hour = idx
        if 6 <= hour <= 10:
            periods["morning"].append(h)
        elif 11 <= hour <= 13:
            periods["lunch"].append(h)
        elif 14 <= hour <= 17:
            periods["day"].append(h)
        else:
            periods["evening"].append(h)
    return periods


def choose_representative_for_period(hourly_entries: list):
    """Choose representative icon and temp for a list of hourly entries."""
    if not hourly_entries:
        return {"icon_key": "cloud", "label": "", "temp": None, "source_hour": None}
    candidates = []
    for h in hourly_entries:
        sym = h.get("symbol_code") or h.get("symbol") or h.get("condition") or ""
        precip = h.get("precip") or h.get("precip_mm") or 0.0
        try:
            precip = float(precip or 0.0)
        except Exception:
            precip = 0.0
        icon_key = _symbol_code_to_icon_key(sym) or (_symbol_code_to_icon_key(h.get("condition")) if isinstance(h.get("condition"), str) else None) or "cloud"
        # severity: simple numeric score
        sev = 0
        if "heavy" in str(sym) or precip >= 2.5:
            sev = 5
        elif "rain" in str(sym) or precip > 0.1:
            sev = 3
        elif "snow" in str(sym):
            sev = 4
        elif "cloud" in str(sym) or "sky" in str(sym) or (not sym and precip == 0):
            sev = 1
        else:
            sev = 1
        temp = h.get("temp") or h.get("temperature") or None
        candidates.append({"severity": sev, "precip": precip, "icon_key": icon_key, "temp": temp, "hour": h})
    candidates.sort(key=lambda c: (c["severity"], c["precip"], (c["temp"] if c["temp"] is not None else -9999)), reverse=True)
    best = candidates[0]
    label = f"{int(round(best['temp']))}°" if best["temp"] is not None else ""
    return {"icon_key": best["icon_key"], "label": label, "temp": best["temp"], "source_hour": best["hour"]}


def draw_period_weather_row(image: Image.Image, x: int, y: int, width: int, hourly_list: list,
                            icon_manager=None, icon_size=20, gap=8, font_small=None):
    """Draw four period icons (Morn/Noon/Day/Eve) within (x,y,width). Returns bottom y used."""
    draw = ImageDraw.Draw(image)
    per = split_hours_to_periods(hourly_list)
    order = [("morning", "Morn"), ("lunch", "Noon"), ("day", "Day"), ("evening", "Eve")]
    total = len(order)
    slot_w = (width - (total - 1) * gap) // total
    for i, (key, label_text) in enumerate(order):
        slot_x0 = x + i * (slot_w + gap)
        slot_cx = slot_x0 + slot_w // 2
        entries = per.get(key, [])
        rep = choose_representative_for_period(entries)
        icon_key = rep.get("icon_key", "cloud")
        temp_label = rep.get("label", "")
        # attempt to load icon
        icon_im = _load_icon_image(icon_key, icon_size, icon_manager=icon_manager)
        if icon_im is None:
            # try to use mapped ICON_NAME_MAP values
            icon_im = _load_icon_image(icon_key, icon_manager=icon_manager, size=icon_size) if False else None
        if icon_im:
            iw, ih = icon_im.size
            icon_x = slot_cx - iw // 2
            icon_y = y
            try:
                image.paste(icon_im, (icon_x, icon_y), icon_im if icon_im.mode == 'RGBA' else None)
            except Exception:
                image.paste(icon_im, (icon_x, icon_y))
        else:
            # fallback: draw small circle and text
            try:
                draw.ellipse([slot_cx - icon_size//2, y, slot_cx + icon_size//2, y + icon_size], outline=(0,0,0), width=1)
            except Exception:
                pass
        # draw temp label under icon
        if font_small is None:
            try:
                font_small = ImageFont.truetype(DEFAULT_FONT, 10)
            except Exception:
                font_small = ImageFont.load_default()
        tw, th = _measure_text(draw, temp_label, font_small)
        draw.text((slot_cx - tw//2, y + icon_size + 1), temp_label, font=font_small, fill=(0,0,0))
    used_h = icon_size + 1 + (font_small.size if hasattr(font_small, "size") else 10)
    return y + used_h

# ---------------- End Weather helpers --------------------------------------



# ---------------- Helpers ----------------------------------------------------

def _measure_box_height_for_date(events: list,
                                box_header_height: int,
                                event_vspacing: int,
                                min_icon_padding: int,
                                draw: 'ImageDraw.ImageDraw',
                                font,
                                small_font,
                                inner_w: int,
                                event_icon_slot: int,
                                icon_gap: int,
                                top_padding: int = 6,
                                bottom_padding: int = 6,
                                min_box_height: int = 24,
                                max_event_lines: int = 3) -> int:
    """
    Compute total box height required to render a date's events.

    Calls _measure_row_height for each event and sums header + paddings.
    Defensive: if measuring a row raises, fall back to a conservative single-line height.
    """
    total = box_header_height + top_padding + bottom_padding

    if not events:
        return max(min_box_height, total)

    for ev in events:
        try:
            h = _measure_row_height(ev,
                                    event_vspacing,
                                    min_icon_padding,
                                    draw,
                                    font,
                                    small_font,
                                    inner_w,
                                    event_icon_slot,
                                    icon_gap,
                                    max_event_lines)
        except Exception:
            # conservative fallback if measurement fails for any event
            fallback_text_h = getattr(font, "size", 12)
            h = max(event_vspacing, fallback_text_h + min_icon_padding)
        total += h

    return max(min_box_height, total)

def _measure_text(draw, text, font):
    """Return (width, height) for text using textbbox, with sensible fallbacks."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        try:
            return font.getsize(text)
        except Exception:
            return (len(text) * (getattr(font, 'size', 10) // 2), getattr(font, 'size', 10))


def _deg_to_cardinal(deg: float) -> str:
    """
    Convert degrees (0-360) to a short cardinal (N, NE, E, SE, S, SW, W, NW).
    Returns empty string if deg is None/invalid.
    """
    if deg is None:
        return ""
    try:
        d = float(deg) % 360
    except Exception:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = int((d + 22.5) // 45) % 8
    return dirs[ix]


def _ensure_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(DEFAULT_FONT, size)
        except Exception:
            return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if text is None:
        text = ""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        pass
    try:
        w, _ = _measure_text(draw, text, font=font)
        return w
    except Exception:
        pass
    try:
        w, _ = font.getsize(text)
        return w
    except Exception:
        size = getattr(font, "size", 12)
        return int(len(text) * size * 0.6)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int):
    if text is None:
        text = ""
    if _text_width(draw, text, font) <= max_width:
        return text
    ell = "…"
    t = text
    while t:
        t = t[:-1]
        if _text_width(draw, t + ell, font) <= max_width:
            return t + ell
    return ell


def _load_icon_image(icon_name: str, size: int, icon_manager=None):
    """Load icon by name. Try map -> icon_manager -> assets/icons. Return RGBA or None."""
    if not icon_name:
        return None
    icon_try = ICON_NAME_MAP.get(icon_name, icon_name)
    # try icon_manager
    if icon_manager is not None:
        try:
            if hasattr(icon_manager, "get_icon_image"):
                im = icon_manager.get_icon_image(icon_try, size)
                if isinstance(im, Image.Image):
                    return im.convert("RGBA")
            if hasattr(icon_manager, "render_icon"):
                im = icon_manager.render_icon(icon_try, size)
                if isinstance(im, Image.Image):
                    return im.convert("RGBA")
        except Exception:
            pass
    # try files
    png_path = os.path.join(ICONS_DIR, f"{icon_try}.png")
    if not os.path.isfile(png_path):
        png_path2 = os.path.join(ICONS_DIR, f"{icon_name}.png")
        if os.path.isfile(png_path2):
            png_path = png_path2
        else:
            return None
    try:
        im = Image.open(png_path).convert("RGBA")
        w, h = im.size
        if h != size:
            new_w = max(1, int(w * (size / float(h))))
            im = im.resize((new_w, size), Image.Resampling.LANCZOS)
        return im
    except Exception:
        return None


def _normalize_color_input(col):
    """
    Accept color as:
    - None -> (0,0,0)
    - int -> greyscale
    - tuple/list -> first 3 items
    - string -> ImageColor.getrgb
    Returns (r,g,b)
    """
    try:
        if col is None:
            return (0, 0, 0)
        if isinstance(col, int):
            c = max(0, min(255, col))
            return (c, c, c)
        if isinstance(col, (tuple, list)):
            return (col[0], col[1], col[2])
        if isinstance(col, str):
            return ImageColor.getrgb(col)
    except Exception:
        pass
    return (0, 0, 0)


def _tint_icon_to_color(icon_im: Image.Image, color) -> Image.Image:
    """
    Tint icon_im to color (r,g,b) or color-name. preserve alpha.
    Use for header/weather icons or event icons when tint_event_icons enabled.
    """
    if icon_im is None:
        return None
    try:
        icon = icon_im.convert("RGBA")
        r, g, b = _normalize_color_input(color)
        solid = Image.new("RGBA", icon.size, (r, g, b, 255))
        alpha = icon.split()[3]
        solid.putalpha(alpha)
        return solid
    except Exception:
        return icon_im


def _resize_to_height_and_pad(icon_im: Image.Image, height: int, pad_square: bool = True) -> Image.Image:
    """
    Resize to given height preserving aspect; optionally pad to square (height x height).
    """
    if icon_im is None:
        return None
    try:
        im = icon_im.convert("RGBA")
        w, h = im.size
        if h != height:
            new_w = max(1, int(w * (height / float(h))))
            im = im.resize((new_w, height), Image.Resampling.LANCZOS)
        if pad_square and im.size[0] != height:
            out = Image.new("RGBA", (height, height), (0, 0, 0, 0))
            ox = (height - im.size[0]) // 2
            out.paste(im, (ox, 0), im)
            return out
        return im
    except Exception:
        return icon_im


def _normalize_bg(bg: Union[int, Tuple, list, str]) -> Tuple[int, int, int, int]:
    # extend support for strings via ImageColor.getrgb
    try:
        if isinstance(bg, (tuple, list)):
            if len(bg) == 3:
                return (bg[0], bg[1], bg[2], 255)
            if len(bg) == 4:
                return tuple(bg)
        if isinstance(bg, int):
            return (bg, bg, bg, 255)
        if isinstance(bg, str):
            rgb = ImageColor.getrgb(bg)
            return (rgb[0], rgb[1], rgb[2], 255)
    except Exception:
        pass
    return (255, 255, 255, 255)


def _luminance_from_color(col: Union[int, Tuple, list, str]) -> float:
    try:
        if isinstance(col, int):
            return col / 255.0
        if isinstance(col, (tuple, list)):
            r = col[0] / 255.0
            g = col[1] / 255.0
            b = col[2] / 255.0
            return 0.299 * r + 0.587 * g + 0.114 * b
        if isinstance(col, str):
            rgb = ImageColor.getrgb(col)
            r = rgb[0] / 255.0
            g = rgb[1] / 255.0
            b = rgb[2] / 255.0
            return 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        pass
    return 1.0


def _group_events_by_date(events: List[dict]) -> Dict[str, List[dict]]:
    groups = {}
    for ev in events:
        d = ev.get("date", "unknown")
        groups.setdefault(d, []).append(ev)
    return groups


# ---------------- Text wrapping helper ---------------------------------------

def _wrap_text_to_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
                        max_width: int, max_lines: int) -> List[str]:
    """
    Greedy wrap text into at most max_lines lines to fit within max_width.
    Returns list of lines (may be shorter than max_lines). If text is empty -> [].
    """
    if not text:
        return []
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip() if cur else w
        if _text_width(draw, candidate, font) <= max_width:
            cur = candidate
        else:
            # commit current line
            if cur:
                lines.append(cur)
            else:
                # single long word: break it into pieces
                s = w
                piece = ""
                for ch in s:
                    if _text_width(draw, piece + ch, font) <= max_width:
                        piece += ch
                    else:
                        if piece:
                            lines.append(piece)
                        piece = ch
                if piece:
                    lines.append(piece)
            cur = ""
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # if we exceeded max_lines via splitting, truncate last line with ellipsis
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines:
        # ensure last line fits; if not, ellipsize it
        if _text_width(draw, lines[-1], font) > max_width:
            lines[-1] = _ellipsize(draw, lines[-1], font, max_width)
    return lines


# ---------- Tag-drawing helper (IMPROVED) ----------------------------------

def _relative_luminance(rgb):
    # rgb is (r,g,b) 0..255
    def _lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(l1, l2):
    a = max(l1, l2)
    b = min(l1, l2)
    return (a + 0.05) / (b + 0.05)



def _fg_for_bg(rgb):
    """
    Choose white or black for text on top of rgb background.
    Prefer white for darker/saturated backgrounds (so red tags get white text).
    """
    try:
        if rgb is None:
            return (0, 0, 0)
        # accept tuples, hex strings, or color names already normalized elsewhere
        if isinstance(rgb, str):
            # try hex like "#rrggbb"
            s = rgb.strip()
            if s.startswith("#") and len(s) in (7, 4):
                if len(s) == 7:
                    r = int(s[1:3], 16); g = int(s[3:5], 16); b = int(s[5:7], 16)
                else:
                    r = int(s[1]*2, 16); g = int(s[2]*2, 16); b = int(s[3]*2, 16)
                bg = (r, g, b)
            else:
                # unknown string, fall back
                return (0,0,0)
        else:
            bg = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        def rl(c):
            v = c / 255.0
            return v/12.92 if v <= 0.03928 else ((v+0.055)/1.055) ** 2.4
        l_bg = 0.2126*rl(bg[0]) + 0.7152*rl(bg[1]) + 0.0722*rl(bg[2])
        # prefer white for darker or saturated colors (like pure red)
        if l_bg < 0.45:
            return (255,255,255)
        # fallback to contrast ratio
        def contrast(l1,l2):
            L1 = max(l1,l2); L2 = min(l1,l2)
            return (L1+0.05)/(L2+0.05)
        l_white = 1.0
        l_black = 0.0
        cr_white = contrast(l_bg, l_white)
        cr_black = contrast(l_bg, l_black)
        return (255,255,255) if cr_white >= cr_black else (0,0,0)
    except Exception:
        return (0,0,0)


def draw_event_tags(draw: ImageDraw.ImageDraw, start_x: int, top_y: int, ev: dict,
                    tag_font: ImageFont.ImageFont, padding_x: int = 8, padding_y: int = 3, gap: int = 8,
                    max_x: int = None):
    """
    Draw tags (chips) for an event dict `ev`.
    - Prefers ev["tags"] if present: list of {"text", "color_rgb"/"color_name"}.
    - Legacy fallback: if ev['tag_text'] exists, split *only* by commas.
    - Returns x position after last drawn chip.
    """
    x = start_x

    tags = ev.get("tags") or []
    # Legacy fallback: split comma-joined tag_text into multiple tags (trim whitespace)
    if not tags and ev.get("tag_text"):
        raw = (ev.get("tag_text") or "").strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            legacy_rgb = ev.get("tag_color_rgb")
            legacy_name = ev.get("tag_color_name")
            tags = [{"text": p, "color_rgb": legacy_rgb, "color_name": legacy_name} for p in parts]

    for tag in tags:
        text = (tag.get("text") or "").strip()
        if not text:
            continue

        # determine bg color rgb (normalized)
        bg = None
        if tag.get("color_rgb") is not None:
            try:
                bg = tuple(tag["color_rgb"])
            except Exception:
                bg = None

        elif tag.get("color_name"):

            try:

                bg = _normalize_color_input(tag["color_name"])

            except Exception:

                bg = None


        if bg is None:
# fallback: try event color fields, then grey
            ev_color = None
            if ev.get("tag_color_rgb") is not None:
                ev_color = tuple(ev.get("tag_color_rgb"))
            elif ev.get("tag_color_name"):
                try:
                    ev_color = _normalize_color_input(ev.get("tag_color_name"))
                except Exception:
                    ev_color = None
            elif ev.get("color") is not None:
                ev_color = _normalize_color_input(ev.get("color"))
            if ev_color is not None:
                bg = ev_color
            else:
                bg = (200, 200, 200)

        # precise text bbox measurement (handles baseline offsets)
        try:
            bbox = draw.textbbox((0, 0), text, font=tag_font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            baseline_top = bbox[1]
        except Exception:
            text_w, text_h = _measure_text(draw, text, font=tag_font)
            baseline_top = 0

        chip_w = text_w + padding_x * 2
        chip_h = text_h + padding_y * 2
        chip_h = max(chip_h, (tag_font.size if hasattr(tag_font, "size") else 12) + 2)

        # overflow check
        if max_x is not None and (x + chip_w) > max_x:
            break

        left = x
        top = top_y
        right = x + chip_w
        bottom = top + chip_h
        radius = int(chip_h / 2)

        try:
            draw.rounded_rectangle([(left, top), (right, bottom)], radius=radius, fill=bg)
        except Exception:
            draw.rectangle([(left, top), (right, bottom)], fill=bg)

        fg = _fg_for_bg(bg)

        # compute exact text position using baseline/top correction
        text_x = left + padding_x
        text_y = top + (chip_h - text_h) // 2 - baseline_top
        draw.text((text_x, text_y), text, font=tag_font, fill=fg)

        x = right + gap

    return x


# ---------------- Measurement helpers ---------------------------------------

def _measure_row_height(event: dict,
                        nominal_vspacing: int,
                        min_icon_padding: int,
                        draw: ImageDraw.ImageDraw,
                        font: ImageFont.ImageFont,
                        small_font: ImageFont.ImageFont,
                        inner_text_width: int,
                        event_icon_slot: int,
                        icon_gap: int,
                        max_event_lines: int) -> int:
    """
    Compute the vertical space required for one event row, aligned with render_events_section logic.
    This function is tag-aware and reserves horizontal space for chips on the first line before wrapping.

    - inner_text_width: width available for the text area (box inner width minus left padding)
    - Returns an integer row height (pixels).
    """
    # requested icon size (fallback sensible minimum)
    requested_icon_size = event.get("icon_size") or event.get("icon_size_px") or max(12, event_icon_slot - 4)

    # baseline row height (icon height + a minimum padding)
    base_row = max(nominal_vspacing, requested_icon_size + min_icon_padding)

    # time width (if event shows a time, reserve space)
    time = event.get("time") or ""
    time_w = _text_width(draw, time, small_font) if time else 0

    # compute how much horizontal space is left for text after icon slot and optional time
    left_reserved = event_icon_slot + icon_gap + (time_w + 6 if time_w else 0)
    text_avail = max(8, inner_text_width - left_reserved)

    # primary name text used for wrapping
    name = (event.get("display_text") or event.get("name") or "") or ""

    # Build tags list (try event['tags'] first; fall back to legacy tag_text parsing)
    tags_for_measure = event.get("tags") or []
    tag_text = event.get("tag_text") or event.get("tag") or None
    if not tags_for_measure and tag_text:
        rawt = (tag_text or "").strip()
        parts = [p.strip() for p in rawt.split(",") if p.strip()]
        if not parts:
            # fallback heuristic: capture capitalized words as separate tags
            caps = re.findall(r"\b[A-ZÆØÅ][a-zæøåA-ZÆØÅ\-']+\b", rawt)
            if len(caps) >= 2:
                parts = caps
        if parts:
            legacy_rgb = event.get("tag_color_rgb")
            legacy_name = event.get("tag_color_name")
            tags_for_measure = [{"text": p, "color_rgb": legacy_rgb, "color_name": legacy_name} for p in parts]

    # chip geometry heuristics (must match render_event_tags behavior)
    tag_padding_x = 8
    tag_padding_y = 3
    tag_gap = 8

    # measure total chip width we might want to reserve on the first line
    tag_total_w = 0
    tag_count = 0
    for t in tags_for_measure:
        txt = (t.get("text") or "").strip()
        if not txt:
            continue
        try:
            bbox = draw.textbbox((0, 0), txt, font=small_font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = _text_width(draw, txt, small_font)
        chip_w = tw + tag_padding_x * 2
        # don't reserve more than half the text_avail for tags (heuristic)
        if tag_total_w + chip_w + (tag_gap if tag_count > 0 else 0) > text_avail // 2:
            break
        if tag_count > 0:
            tag_total_w += tag_gap
        tag_total_w += chip_w
        tag_count += 1

    # clamp reserved width to half the available text area (safety)
    if tag_total_w > text_avail // 2:
        tag_total_w = text_avail // 2

    reserved_for_tags = tag_total_w + (6 if tag_total_w > 0 else 0)

    # Now simulate first-line + remaining-lines wrapping.
    name_max_width = max(8, text_avail - reserved_for_tags)
    words = (name or "").split()
    first_line = ""
    rest_text = ""

    for idx_w, w in enumerate(words):
        cand = (first_line + " " + w).strip() if first_line else w
        if _text_width(draw, cand, font) <= name_max_width:
            first_line = cand
        else:
            rest_text = " ".join(words[idx_w:])
            break

    if not first_line and words:
        first_line = _ellipsize(draw, words[0], font, name_max_width)
        rest_text = " ".join(words[1:]) if len(words) > 1 else ""

    # subsequent lines can use the full text_avail (tags only reserve first line)
    remaining_lines = []
    if rest_text:
        remaining_lines = _wrap_text_to_lines(draw, rest_text, font, max(8, text_avail), max(0, max_event_lines - 1))

    lines = [first_line] + remaining_lines
    if not lines:
        lines = [""]

    # measure per-line heights robustly using textbbox (fallback to font.size)
    line_heights = []
    for ln in lines:
        try:
            bbox = draw.textbbox((0, 0), ln if ln else "X", font=font)
            line_h = bbox[3] - bbox[1]
        except Exception:
            line_h = getattr(font, "size", 12)
        line_heights.append(line_h)

    # spacing between wrapped lines (match renderer's spacing heuristic)
    spacing_px = max(2, int((line_heights[0] if line_heights else getattr(font, "size", 12)) * 0.12))

    total_text_h = sum(line_heights)
    if len(line_heights) > 1:
        total_text_h += spacing_px * (len(line_heights) - 1)

    # estimate chip height for vertical accommodation
    try:
        chip_bbox = draw.textbbox((0, 0), "X", font=small_font)
        chip_text_h = chip_bbox[3] - chip_bbox[1]
    except Exception:
        chip_text_h = getattr(small_font, "size", 12)
    chip_h_est = max(10, chip_text_h + (tag_padding_y * 2))

    # final row height must accommodate icon baseline, text block, and chips with min padding
    needed_row = max(base_row, total_text_h + min_icon_padding, chip_h_est + min_icon_padding)

    return int(needed_row)

# ----------------- Rendering -------------------------------------------------

# Defensive import for apply_event_mapping (optional)
apply_event_mapping = None
try:
    from mappings import apply_event_mapping  # try direct import first
except Exception:
    try:
        import mappings as _m
        apply_event_mapping = getattr(_m, "apply_event_mapping", None)
    except Exception:
        apply_event_mapping = None


def _gather_weather_values(entry: dict):
    """Return tuple (icon_name, temp_text, precip_text, wind_text)."""
    icon_keys = ("icon", "icon_name", "symbol", "weather_icon", "main")
    temp_min_keys = ("temp_min", "min_temp", "tmin", "low", "temp_low", "min")
    temp_max_keys = ("temp_max", "max_temp", "tmax", "high", "temp_high", "max")
    temp_keys = ("temp", "temperature", "temp_c", "temp_celsius")
    precip_keys = ("rain_mm", "precip_mm", "precip", "rain", "rain_amount", "precipitation")
    wind_keys_ms = ("wind_m_s", "wind_ms", "wind_speed", "wind", "wind_max")
    wind_keys_kph = ("wind_kph", "wind_kmh", "wind_kph_value", "wind_kmh_value")

    icon = next((entry.get(k) for k in icon_keys if entry.get(k) is not None), None)

    tmin = next((entry.get(k) for k in temp_min_keys if entry.get(k) is not None), None)
    tmax = next((entry.get(k) for k in temp_max_keys if entry.get(k) is not None), None)
    if tmin is None and tmax is None:
        t = next((entry.get(k) for k in temp_keys if entry.get(k) is not None), None)
        temp_text = f"{t}°C" if t is not None else None
    else:
        try:
            temp_text = f"{int(tmin)}°/{int(tmax)}°" if (tmin is not None and tmax is not None) else None
        except Exception:
            if tmin is not None and tmax is not None:
                temp_text = f"{tmin}°/{tmax}°"
            else:
                temp_text = None

    precip = next((entry.get(k) for k in precip_keys if entry.get(k) is not None), None)
    if precip is not None:
        try:
            precip_mm = float(precip)
            precip_text = f"{precip_mm:.1f} mm"
        except Exception:
            try:
                num = float("".join(ch for ch in str(precip) if (ch.isdigit() or ch in ".-")))
                precip_text = f"{num:.1f} mm"
            except Exception:
                precip_text = str(precip)
    else:
        precip_text = None

    wind_val = None
    wind_text = None

    def _parse_number_from_string(v):
        if v is None:
            return None, None
        if isinstance(v, (int, float)):
            return float(v), None
        s = str(v).strip().lower()
        if "km/h" in s or "kph" in s or "kmh" in s:
            try:
                num = float("".join(ch for ch in s if (ch.isdigit() or ch in ".-")))
                return num, "kph"
            except Exception:
                return None, None
        if "m/s" in s or "mps" in s:
            try:
                num = float("".join(ch for ch in s if (ch.isdigit() or ch in ".-")))
                return num, "m/s"
            except Exception:
                return None, None
        try:
            return float(s), None
        except Exception:
            return None, None

    for k in wind_keys_ms:
        if k in entry and entry.get(k) is not None:
            val, unit = _parse_number_from_string(entry.get(k))
            if val is not None:
                if unit == "kph":
                    wind_val = val * 0.277778
                else:
                    wind_val = val
                break

    if wind_val is None:
        for k in wind_keys_kph:
            if k in entry and entry.get(k) is not None:
                val, unit = _parse_number_from_string(entry.get(k))
                if val is not None:
                    wind_val = val * 0.277778
                    break

    if wind_val is None and "wind" in entry and entry.get("wind") is not None:
        val, unit = _parse_number_from_string(entry.get("wind"))
        if val is not None:
            if unit == "kph":
                wind_val = val * 0.277778
            else:
                wind_val = val

    if wind_val is not None:
        try:
            wind_text = f"{wind_val:.1f} m/s"
        except Exception:
            wind_text = str(wind_val)

    return icon, temp_text, precip_text, wind_text

def render_events_section(image: Image.Image, x: int, y: int, width: int, events: List[dict],
                        font: ImageFont.ImageFont, small_font: ImageFont.ImageFont = None, tag_font: ImageFont.ImageFont = None,
                        icon_manager=None, event_vspacing: int = 14, icon_gap: int = 6,
                        text_color=0, dotted_line=False, dot_color=None, dot_gap=3,
                        min_icon_padding: int = 4, icon_pad_square: bool = True,
                        event_icon_slot: int = 20, tint_event_icons: bool = True,
                        max_event_lines: int = 2):
    """
    Draw events vertically and return new cursor_y below last drawn line.

    Parameters mirror measurement helpers so measured heights and rendered heights match.
    """
    draw = ImageDraw.Draw(image)
    cursor_y = y
    if small_font is None:
        try:
            small_font = ImageFont.truetype(DEFAULT_FONT, max(10, getattr(font, "size", 12) - 2))
        except Exception:
            small_font = font
    if tag_font is None:
        try:
            tag_font = small_font
        except Exception:
            tag_font = font

    body_rgb = _normalize_color_input(text_color)
    dot_rgb = _normalize_color_input(dot_color) if dot_color is not None else (0, 0, 0)
    fallback_col = globals().get("box_outline_rgb", (0, 0, 0))

    for i, ev in enumerate(events):
        name = ev.get("display_text") or ev.get("name") or ""
        time = ev.get("time") or ""
        icon_name = ev.get("icon")
        requested_icon_size = ev.get("icon_size") or ev.get("icon_size_px") or max(12, event_icon_slot - 4)

        # event color (supports multiple keys)
        ev_color_rgb = None
        if ev.get("icon_color_rgb") is not None:
            try:
                ev_color_rgb = tuple(ev.get("icon_color_rgb"))
            except Exception:
                ev_color_rgb = ev.get("icon_color_rgb")
        elif ev.get("icon_color_name") is not None:
            try:
                ev_color_rgb = _normalize_color_input(ev.get("icon_color_name"))
            except Exception:
                ev_color_rgb = None
        elif ev.get("color") is not None:
            ev_color_rgb = _normalize_color_input(ev.get("color"))

        # legacy tag color fallback
        tag_text = ev.get("tag_text") or ev.get("tag") or None
        tag_color_rgb = None
        if ev.get("tag_color_rgb") is not None:
            try:
                tag_color_rgb = tuple(ev.get("tag_color_rgb"))
            except Exception:
                tag_color_rgb = ev.get("tag_color_rgb")
        elif ev.get("tag_color_name") is not None:
            try:
                tag_color_rgb = _normalize_color_input(ev.get("tag_color_name"))
            except Exception:
                tag_color_rgb = None
        if tag_color_rgb is None:
            tag_color_rgb = ev_color_rgb

        # baseline row height (icon + padding)
        line_height = max(event_vspacing, requested_icon_size + min_icon_padding)

        # icon display sizing
        icon_display_h = max(10, int(line_height * 0.80))
        if icon_display_h > requested_icon_size:
            icon_display_h = requested_icon_size

        # left reserved icon slot; text starts after that (+ icon_gap)
        text_x = x + event_icon_slot + icon_gap

        # draw icon (center in slot; vertically centered to the row center)
        if icon_name:
            icon_im = _load_icon_image(icon_name, icon_display_h, icon_manager=icon_manager)
            if icon_im:
                icon_prepared = _resize_to_height_and_pad(icon_im, icon_display_h, pad_square=icon_pad_square)
                # Force event icons to be drawn in black regardless of per-event color mapping.
                try:
                    icon_to_draw = _tint_icon_to_color(icon_prepared, (0, 0, 0))
                except Exception:
                    icon_to_draw = icon_prepared
                iw, ih = icon_to_draw.size
                slot_x = x + max(0, (event_icon_slot - iw) // 2)
                # vertical center aligned to canonical row center (we compute canonical row later,
                # but approximate here with current cursor + half nominal line_height)
                text_center_y = cursor_y + line_height // 2
                icon_y = text_center_y - ih // 2
                image.paste(icon_to_draw, (slot_x, icon_y), icon_to_draw)
            else:
                ph_r = min(6, max(3, event_icon_slot // 4))
                ph_cx = x + event_icon_slot // 2
                ph_cy = cursor_y + line_height // 2
                fill_col = (0, 0, 0)
                draw.ellipse([ph_cx - ph_r, ph_cy - ph_r, ph_cx + ph_r, ph_cy + ph_r],
                            fill=fill_col, outline=None)

        # draw time (baseline top at cursor_y)
        name_x = text_x
        if time:
            time_w = _text_width(draw, time, small_font)
            draw.text((x + event_icon_slot + icon_gap, cursor_y), time, font=small_font, fill=body_rgb)
            name_x = x + event_icon_slot + icon_gap + time_w + 6

        # compute available width for name before placing tags after it
        max_text_width = width - (name_x - x) - 8  # small safety margin
        if max_text_width < 8:
            cursor_y += line_height
            continue

        # ----------------- MEASURE TAGS to reserve first-line space -----------------
        tags_for_measure = ev.get("tags") or []
        if not tags_for_measure and tag_text:
            rawt = (tag_text or "").strip()
            parts = [p.strip() for p in rawt.split(",") if p.strip()]
            if not parts:
                caps = re.findall(r"\b[A-ZÆØÅ][a-zæøåA-ZÆØÅ\-']+\b", rawt)
                if len(caps) >= 2:
                    parts = caps
            if parts:
                legacy_rgb = ev.get("tag_color_rgb")
                legacy_name = ev.get("tag_color_name")
                tags_for_measure = [{"text": p, "color_rgb": legacy_rgb, "color_name": legacy_name} for p in parts]

        # compute pixel width of chips we prefer to show on the first line
        tag_padding_x = 8
        tag_padding_y = 3
        tag_gap = 8
        tag_total_w = 0
        tag_count = 0
        for t in tags_for_measure:
            txt = (t.get("text") or "").strip()
            if not txt:
                continue
            try:
                bbox = draw.textbbox((0, 0), txt, font=small_font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = _text_width(draw, txt, small_font)
            chip_w = tw + tag_padding_x * 2
            if tag_total_w + chip_w + (tag_gap if tag_count > 0 else 0) > max_text_width // 2:
                break
            if tag_count > 0:
                tag_total_w += tag_gap
            tag_total_w += chip_w
            tag_count += 1

        if tag_total_w > max_text_width // 2:
            tag_total_w = max_text_width // 2

        reserved_for_tags = tag_total_w + (6 if tag_total_w > 0 else 0)

        # ----------------- BUILD FIRST LINE + REMAINING LINES --------------------
        name_max_width = max(8, max_text_width - reserved_for_tags)
        words = (name or "").split()
        first_line = ""
        rest_text = ""
        for idx_w, w in enumerate(words):
            cand = (first_line + " " + w).strip() if first_line else w
            if _text_width(draw, cand, font) <= name_max_width:
                first_line = cand
            else:
                rest_text = " ".join(words[idx_w:])  # everything after current word becomes rest
                break
        if not first_line and words:
            first_line = _ellipsize(draw, words[0], font, name_max_width)
            rest_text = " ".join(words[1:]) if len(words) > 1 else ""

        remaining_lines = []
        if rest_text:
            remaining_lines = _wrap_text_to_lines(draw, rest_text, font, max_text_width, max(0, max_event_lines - 1))

        lines = [first_line] + remaining_lines
        if not lines:
            lines = [""]

        # Draw first line
        draw.text((name_x, cursor_y), lines[0], font=font, fill=body_rgb)

        displayed_name_w = _text_width(draw, lines[0], font)
        tag_start_x = name_x + displayed_name_w + 6
        max_right = x + width - 4

        # measure each line's actual height using textbbox and include spacing
        line_heights = []
        total_text_h = 0
        try:
            bbox_X = draw.textbbox((0, 0), "X", font=font)
            spacing_px = max(2, int((bbox_X[3] - bbox_X[1]) * 0.12))
        except Exception:
            spacing_px = max(2, int(getattr(font, "size", 12) * 0.12))

        for ln in lines:
            try:
                bbox = draw.textbbox((0, 0), ln if ln else "X", font=font)
                h = bbox[3] - bbox[1]
            except Exception:
                h = getattr(font, "size", 12)
            line_heights.append(h)
            total_text_h += h
        if len(lines) > 1:
            total_text_h += spacing_px * (len(lines) - 1)

        # estimate chip height for centering
        try:
            chip_bbox = draw.textbbox((0, 0), "X", font=small_font)
            chip_text_h = chip_bbox[3] - chip_bbox[1]
        except Exception:
            chip_text_h = getattr(small_font, "size", 12)
        chip_h_est = max(10, chip_text_h + (tag_padding_y * 2))

        # ensure row height includes chips and text
        total_row_h = max(line_height, total_text_h + min_icon_padding, chip_h_est + min_icon_padding)

        # vertical position for chips on the first line (centered)
        tag_top = cursor_y + max(0, (total_row_h - chip_h_est) // 2) - 2
        if tag_top < cursor_y:
            tag_top = cursor_y

        # Attempt to draw tags on the first line
        after_tags_x = draw_event_tags(draw, tag_start_x, tag_top, ev, small_font,
                                    padding_x=tag_padding_x, padding_y=tag_padding_y, gap=tag_gap, max_x=max_right)
        drew_on_first_line = (after_tags_x != tag_start_x)

        # Draw the remaining wrapped lines (if any)
        if len(lines) > 1:
            second_y = cursor_y + line_heights[0] + spacing_px
            ln_y = second_y
            for idx_ln, ln in enumerate(lines[1:]):
                draw.text((name_x, ln_y), ln, font=font, fill=body_rgb)
                ln_y += line_heights[1 + idx_ln] + spacing_px

            # If tags didn't fit on first line, try drawing them on the second line
            if not drew_on_first_line:
                draw_event_tags(draw, name_x, second_y, ev, small_font,
                                padding_x=tag_padding_x, padding_y=tag_padding_y, gap=tag_gap, max_x=max_right)

        # advance cursor using canonical height and draw dotted separator
        row_h = max(line_height, total_row_h)
        prev_cursor = cursor_y
        cursor_y += row_h

        # dotted separator: place it low enough so it doesn't overlap text.
        if dotted_line and i != len(events) - 1:
            # place line slightly above bottom of this row (but below text)
            y_line = prev_cursor + row_h - max(2, int(row_h * 0.18))
            start = x
            end = x + width
            pos = start
            while pos < end:
                # draw single pixel dot (rectangle 1x1)
                draw.rectangle([pos, y_line, pos + 1, y_line + 1], fill=dot_rgb)
                pos += dot_gap

    return cursor_y


def render_calendar(data: dict, width: int, height: int, days: int = 8, renderer_opts: dict = None):
    opts = renderer_opts or {}

    # options
    border_thickness = int(opts.get("border_thickness", 2))
    round_radius = int(opts.get("round_radius", 6))
    underline_date = bool(opts.get("underline_date", False))
    dotted_line_between_events = bool(opts.get("dotted_line_between_events", True))
    event_vspacing = int(opts.get("event_vspacing", 14))
    font_small_size = int(opts.get("font_small_size", 12))
    font_bold_size = int(opts.get("font_bold_size", 14))
    dot_gap = int(opts.get("dot_gap", 3))
    dot_color = opts.get("dot_color", "black")
    heading_color = opts.get("heading_color", "black")
    text_color_opt = opts.get("text_color", None)
    border_color = opts.get("border_color", "black")
    min_box_height = int(opts.get("min_box_height", 48))
    show_more_text = bool(opts.get("show_more_text", True))
    columns = int(opts.get("columns", 2))
    grid_gap = int(opts.get("grid_gap", 5))
    box_header_height = int(opts.get("box_header_height", 26))
    box_radius = int(opts.get("box_radius", round_radius))
    box_header_padding = int(opts.get("box_header_padding", 6))
    min_icon_padding = int(opts.get("min_icon_padding", 4))
    top_padding = int(opts.get("box_top_padding", 8))
    bottom_padding = int(opts.get("box_bottom_padding", 8))
    weather_debug = bool(opts.get("weather_debug", False))

    # event icon slot width (pixels)
    event_icon_slot = int(opts.get("event_icon_slot", 20))
    icon_pad_square = bool(opts.get("icon_pad_square", True))
    tint_event_icons = bool(opts.get("tint_event_icons", True))

    # NEW: gap between icon slot and text (used by measurement & rendering)
    icon_gap = int(opts.get("icon_gap", 6))

    # NEW: configurable max_event_lines (default 2)
    max_event_lines = int(opts.get("max_event_lines", 2))

    background_raw = opts.get("background", 255)
    bg_rgba = _normalize_bg(background_raw)
    lum = _luminance_from_color(background_raw)
    default_text_color_raw = text_color_opt if text_color_opt is not None else (0 if lum > 0.5 else 255)

    # normalize colors
    header_fill_raw = opts.get("header_fill_color", (255, 153, 0))
    header_text_raw = opts.get("header_text_color", None)
    if header_text_raw is None:
        header_text_raw = ("white" if opts.get("invert_text_on_fill", True) else "black")
    box_outline_raw = opts.get("border_color", "black")
    body_text_raw = default_text_color_raw

    hf = _normalize_bg(header_fill_raw)
    header_fill_rgba = (hf[0], hf[1], hf[2], 255)
    header_text_rgb = _normalize_color_input(header_text_raw)
    box_outline_rgb = _normalize_color_input(box_outline_raw)
    body_text_rgb = _normalize_color_input(body_text_raw)
    dot_rgb = _normalize_color_input(dot_color)

    # expose for fallback glyph
    globals()["box_outline_rgb"] = box_outline_rgb

    base = Image.new("RGBA", (width, height), color=bg_rgba)
    draw = ImageDraw.Draw(base)
    font_path = opts.get("font_path", DEFAULT_FONT)
    bold_font_path = opts.get("bold_font_path", DEFAULT_BOLD_FONT)
    font = _ensure_font(font_path, max(10, font_small_size))
    bold_font = _ensure_font(bold_font_path, font_bold_size)
    small_font = _ensure_font(font_path, font_small_size)

    # Ensure weather_tag_font is defined (safe fallback if opts missing)
    weather_tag_font = None
    try:
        weather_tag_font_name = opts.get("weather_tag_font", None)
        weather_tag_font_size = int(opts.get("weather_tag_font_size", max(10, font_small_size - 1)))
    except Exception:
        weather_tag_font_name = None
        weather_tag_font_size = max(10, font_small_size - 1)
    try:
        if weather_tag_font_name:
            if os.path.isfile(weather_tag_font_name):
                weather_tag_font = _ensure_font(weather_tag_font_name, weather_tag_font_size)
            else:
                candidate = os.path.join(FONTS_DIR, weather_tag_font_name)
                weather_tag_font = _ensure_font(candidate, weather_tag_font_size)
    except Exception:
        weather_tag_font = None
    if weather_tag_font is None:
        try:
            weather_tag_font = small_font
        except Exception:
            weather_tag_font = font
    """
    title = opts.get("title", "Dokkveien 19 - Ukeskalender")
    draw.text((12, 8), title, font=bold_font, fill=_normalize_color_input(heading_color))

    start_label = opts.get("start_label", None)
    if not start_label:
        evs = data.get("events", [])
        dates = sorted({ev.get("date") for ev in evs if ev.get("date")})
        if dates:
            try:
                dt = datetime.fromisoformat(dates[0])
                start_label = dt.strftime("%a %d %b %Y")
            except Exception:
                start_label = dates[0]
    if start_label:
        w = _text_width(draw, start_label, small_font)
        draw.text((width - w - 12, 10), start_label, font=small_font, fill=_normalize_color_input(default_text_color_raw))
    """

    events = data.get("events", []) or []

    # Optionally apply mapping if available and event lacks structured 'tags'
    if callable(apply_event_mapping):
        mapped_events = []
        for ev in events:
            ev_copy = dict(ev)
            # If mapping hasn't been applied (no 'tags' key), call mapping.
            if not ev_copy.get("tags"):
                try:
                    mapped = apply_event_mapping(ev_copy.get("name", "") if ev_copy.get("name") is not None else "")
                except Exception:
                    mapped = {}
                # Only update fields that mapping returns (preserve existing structured fields)
                for k in ("display_text", "tags", "tag_text", "tag_color_name", "tag_color_rgb",
                        "icon", "icon_size", "icon_color_name", "icon_color_rgb", "mode", "original_name"):
                    if k in mapped and mapped[k] is not None:
                        ev_copy[k] = mapped[k]
            mapped_events.append(ev_copy)
        events = mapped_events
        data["events"] = events

    groups = _group_events_by_date(events)
    ordered_dates = sorted(groups.keys())[:days]

    margin_x = 3
    margin_y = 3
    gap = grid_gap
    box_w = (width - margin_x * 2 - (columns - 1) * gap) // columns

    date_heights = {}
    # inner width for text area inside a box (used by measurement)
    inner_w = box_w - 16
    for d in ordered_dates:
        evs = groups.get(d, [])
        h = _measure_box_height_for_date(evs, box_header_height, event_vspacing, min_icon_padding,
                                        draw, font, small_font, inner_w, event_icon_slot, icon_gap,
                                        top_padding=top_padding, bottom_padding=bottom_padding,
                                        min_box_height=min_box_height, max_event_lines=max_event_lines)
        date_heights[d] = h

    placements = {}
    col_width = box_w
    col_x_positions = [margin_x + c * (col_width + gap) for c in range(columns)]
    bottom_limit = height - 3
    col_tops = [margin_y for _ in range(columns)]
    current_col = 0

    for d in ordered_dates:
        h = date_heights[d]
        # Try to place in current_col or any later column (preserve chronological order).
        placed = False
        for col_try in range(current_col, columns):
            if col_tops[col_try] + h <= bottom_limit:
                current_col = col_try
                x = col_x_positions[current_col]
                y = col_tops[current_col]
                placements[d] = (x, y, h)
                col_tops[current_col] = y + h + gap
                placed = True
                break

        # If not placed in current or later columns, skip this date entirely (do not wrap-around).
        if not placed:
            # skip adding this date so it won't be displayed
            continue

    for date_key, (x, y, box_h) in placements.items():
        hx0 = x + 2
        hy0 = y + 2
        hx1 = x + box_w - 2
        hy1 = y + box_header_height

        header_fill_rect = [hx0, hy0 - 1, hx1, hy1]
        try:
            # determine header color per-date (optionally override for weekend)
            draw_header_fill = header_fill_rgba
            try:
                from datetime import datetime
                dt = None
                # Try several common formats
                try:
                    dt = datetime.fromisoformat(str(date_key))
                except Exception:
                    try:
                        dt = datetime.strptime(str(date_key).split()[0], '%Y-%m-%d')
                    except Exception:
                        try:
                            dt = datetime.strptime(str(date_key).split()[0], '%d-%m-%Y')
                        except Exception:
                            dt = None
                if dt is not None and dt.weekday() >= 5:
                    # if user provided weekend color use it, otherwise default to red
                    weekend_col = None
                    try:
                        if isinstance(opts, dict):
                            weekend_col = opts.get('weekend_header_fill_color', None)
                    except Exception:
                        weekend_col = None
                    if weekend_col is None:
                        weekend_col = (255, 0, 0)
                    wf = _normalize_bg(weekend_col)
                    draw_header_fill = (wf[0], wf[1], wf[2], 255)
            except Exception:
                pass
            draw.rounded_rectangle(header_fill_rect, radius=box_radius, fill=draw_header_fill)
        except Exception:
            try:
                draw.rounded_rectangle(header_fill_rect, radius=box_radius, fill=header_fill_rgba)
            except Exception:
                draw.rectangle(header_fill_rect, fill=header_fill_rgba)

        except Exception:
            draw.rectangle(header_fill_rect, fill=header_fill_rgba)

        try:
            draw.rounded_rectangle([hx0-1, hy0-1, hx1+1, hy1+1], radius=0, outline=box_outline_rgb, width=border_thickness+1)
        except Exception:
            draw.rectangle([hx0, hy0, hx1, hy1], outline=box_outline_rgb, width=border_thickness)

        try:
            draw.rounded_rectangle([x, y, x + box_w, y + box_h], radius=box_radius,
                                outline=box_outline_rgb, width=border_thickness, fill=None)
        except Exception:
            draw.rectangle([x, y, x + box_w, y + box_h], outline=box_outline_rgb, width=border_thickness)

        # Format date into short Norwegian day + day + short month, e.g. "Man 17 Nov"
        pretty = date_key
        try:
            dt = datetime.fromisoformat(date_key)
            # Norwegian short day names and short months
            wk = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]
            months = ["Jan", "Feb", "Mar", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Des"]
            pretty = f"{wk[dt.weekday()]} {dt.day} {months[dt.month - 1]}"
        except Exception:
            pass
        draw.text((x + box_header_padding, y + 3), pretty, font=bold_font, fill=header_text_rgb)

        # weather (tinted icons)
        weather_entry = None
        for w in data.get("weather", []):
            if w.get("date") == date_key:
                weather_entry = w
                break

        if weather_entry:
            w_icon, temp_text, precip_text, wind_text = _gather_weather_values(weather_entry)

            small_icon_size = 16
            gap_between_parts = 10
            right_x = hx1 - box_header_padding


            # --- compact icon+text rendering for temp / precip / wind ----
            # Draw three compact icon + text groups in this order: Temp, Rain, Wind
            def _get_icon_name_for_wind(icon_manager):
                # prefer local 'wind' icon (wind.png) then fallback
                if _load_icon_image("wind", small_icon_size, icon_manager=icon_manager) is not None:
                    return "wind"
                if _load_icon_image("weather-windy", small_icon_size, icon_manager=icon_manager) is not None:
                    return "weather-windy"
                return None

            def _safe_float_str(v, fmt="{:.1f}"):
                try:
                    return fmt.format(float(v))
                except Exception:
                    try:
                        return str(v)
                    except Exception:
                        return ""

            # gather values safely from provider dict (weather_entry)
            temp_max = weather_entry.get("temp_max") or weather_entry.get("tempMax") or weather_entry.get("max_temp")
            temp_min = weather_entry.get("temp_min") or weather_entry.get("tempMin") or weather_entry.get("min_temp")
            precip = weather_entry.get("precip") if "precip" in weather_entry else (weather_entry.get("rain") or weather_entry.get("precipitation"))
            wind_val = None
            for k in ("wind_max", "wind_speed", "wind"):
                if k in weather_entry and weather_entry.get(k) is not None:
                    wind_val = weather_entry.get(k)
                    break
            wind_dir = None
            for k in ("wind_dir_deg", "wind_dir", "wind_deg"):
                if k in weather_entry and weather_entry.get(k) is not None:
                    wind_dir = weather_entry.get(k)
                    break

            # build texts
            temp_text = None
            if temp_max is not None or temp_min is not None:
                try:
                    tmax = int(round(float(temp_max))) if temp_max is not None else ""
                    tmin = int(round(float(temp_min))) if temp_min is not None else ""
                    temp_text = f"{tmax}° / {tmin}°"
                except Exception:
                    temp_text = f"{temp_max}° / {temp_min}°"

            precip_text = None
            if precip is not None:
                try:
                    precip_text = f"{float(precip):.1f} mm"
                except Exception:
                    precip_text = str(precip)

            wind_text = None
            if wind_val is not None:
                wind_text = f"{_safe_float_str(wind_val, '{:.1f}')} m/s"

            # helper to draw icon+text right-aligned, returns new right_x
            def _draw_icon_and_text_right(icon_name, text, right_x, y_top, icon_h, font_for_text):
                if not text:
                    return right_x
                p_w = _text_width(draw, text, font_for_text)
                # try to load icon (with manager if available)
                icon_im = None
                if opts and opts.get("icon_manager"):
                    try:
                        icon_im = _load_icon_image(icon_name, icon_h, icon_manager=opts.get("icon_manager"))
                    except Exception:
                        icon_im = None
                if icon_im is None:
                    # try name variants
                    for alt in (icon_name, icon_name.replace("_","-"), icon_name.replace("-","_")):
                        icon_im = _load_icon_image(alt, icon_h, icon_manager=opts.get("icon_manager"))
                        if icon_im:
                            break
                min_x_for_text = x + box_header_padding + _text_width(draw, pretty, bold_font) + 8
                text_x = right_x - p_w
                if text_x < min_x_for_text:
                    # no room for text
                    return right_x
                # if we have an icon, place it left of the text
                if icon_im:
                    icon_prepared = _resize_to_height_and_pad(icon_im, icon_h, pad_square=True)
                    icon_tinted = _tint_icon_to_color(icon_prepared, header_text_rgb)
                    iw, ih = icon_tinted.size
                    icon_x = text_x - iw - 6
                    if icon_x >= min_x_for_text:
                        icon_y = y + ((box_header_height - ih) // 2)
                        base.paste(icon_tinted, (icon_x, icon_y), icon_tinted)
                        draw.text((text_x, y + 6), text, font=font_for_text, fill=header_text_rgb)
                        return icon_x - gap_between_parts
                    else:
                        # not enough room for icon: draw text only
                        draw.text((text_x, y + 6), text, font=font_for_text, fill=header_text_rgb)
                        return text_x - gap_between_parts
                else:
                    # no icon file: draw text only
                    draw.text((text_x, y + 6), text, font=font_for_text, fill=header_text_rgb)
                    return text_x - gap_between_parts

            # Draw in requested order: Temperature -> Rain -> Wind
            if temp_text:
                right_x = _draw_icon_and_text_right("thermometer", temp_text, right_x, y, small_icon_size, small_font)

            if precip_text:
                pref = "umbrella"
                if _load_icon_image(pref, small_icon_size, icon_manager=opts.get("icon_manager")) is None:
                    pref = "cloud-rain"
                right_x = _draw_icon_and_text_right(pref, precip_text, right_x, y, small_icon_size, small_font)

            if wind_text:
                # append direction short label if available
                wd_label = wind_text
                try:
                    if wind_dir is not None:
                        dir_short = _deg_to_cardinal(float(wind_dir))
                        if dir_short:
                            wd_label = f"{wd_label} {dir_short}"
                except Exception:
                    pass
                # choose icon name (prefer 'wind' file)
                wind_icon_name = _get_icon_name_for_wind(opts.get("icon_manager") if opts else None)
                if wind_icon_name:
                    right_x = _draw_icon_and_text_right(wind_icon_name, wd_label, right_x, y, small_icon_size, small_font)
                else:
                    right_x = _draw_icon_and_text_right(None, wd_label, right_x, y, small_icon_size, small_font)

            # --- end compact block ---

        if underline_date:
            date_w = _text_width(draw, pretty, bold_font)
            date_x = x + box_header_padding
            underline_y = hy1 - 4
            draw.line((date_x, underline_y, date_x + date_w, underline_y), fill=box_outline_rgb, width=1)

        inner_x = x + 8
        inner_y = y + box_header_height + top_padding
        inner_w = box_w - 16
        max_bottom = y + box_h - bottom_padding

        evs = groups.get(date_key, [])
        try:
            evs = sorted(evs, key=lambda e: e.get("time") or "")
        except Exception:
            pass

        cur_y = inner_y
        if evs:
            cur_y = render_events_section(base, inner_x, cur_y, inner_w, evs, font,
                                        small_font=small_font, icon_manager=opts.get("icon_manager"),
                                        event_vspacing=event_vspacing, icon_gap=icon_gap,
                                        text_color=body_text_rgb, dotted_line=dotted_line_between_events,
                                        dot_color=dot_rgb, dot_gap=dot_gap, min_icon_padding=min_icon_padding,
                                        icon_pad_square=icon_pad_square, event_icon_slot=event_icon_slot,
                                        tint_event_icons=tint_event_icons, max_event_lines=max_event_lines)
        else:
            placeholder = opts.get("no_events_text", "")
            if placeholder:
                draw.text((inner_x, cur_y), placeholder, font=font, fill=body_text_rgb)

        if cur_y > max_bottom and show_more_text:
            more_y = max_bottom - getattr(font, "size", 12)
            draw.text((inner_x, more_y), "…", font=font, fill=body_text_rgb)

    return base


def make_mockup_with_bezel(image: Image.Image, bezel_asset: str = None, scale: float = 1.0):
    if not bezel_asset:
        if scale != 1.0:
            w, h = image.size
            return image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        return image
    bezel_path = os.path.join(ASSETS_DIR, bezel_asset)
    if not os.path.isfile(bezel_path):
        return image
    try:
        bezel = Image.open(bezel_path).convert("RGBA")
        bw, bh = bezel.size
        iw, ih = image.size
        out = Image.new("RGBA", bezel.size, (255, 255, 255, 0))
        bg = Image.new("RGBA", bezel.size, (255, 255, 255, 255))
        out.paste(bg, (0, 0))
        ox = (bw - iw) // 2
        oy = (bh - ih) // 2
        out.paste(image, (ox, oy))
        out.paste(bezel, (0, 0), bezel)
        if scale != 1.0:
            sw = int(out.size[0] * scale)
            sh = int(out.size[1] * scale)
            out = out.resize((sw, sh), Image.Resampling.LANCZOS)
        return out
    except Exception:
        return image


def _ensure_font(path: str, size: int):
    """
    Ensure a truetype font is returned. If the specified path is missing or invalid,
    try DEFAULT_FONT. If that fails, warn and fall back to a bitmap default font.
    """
    from PIL import ImageFont
    import os

    try:
        if path and os.path.isfile(path):
            return ImageFont.truetype(path, int(size))
    except Exception:
        pass

    # Try DEFAULT_FONT if available
    try:
        if 'DEFAULT_FONT' in globals() and DEFAULT_FONT and os.path.isfile(DEFAULT_FONT):
            return ImageFont.truetype(DEFAULT_FONT, int(size))
    except Exception:
        pass

    # Last resort fallback
    try:
        print("WARNING: truetype font unavailable; using bitmap fallback. Check assets/fonts/ for ttf files.")
    except Exception:
        pass
    from PIL import ImageFont as _IF
    return _IF.load_default()


    if weather_tag_font is None:
        try:
            weather_tag_font = _ensure_font(font_path, weather_tag_font_size)
        except Exception:
            weather_tag_font = small_font

# main.py
"""
Orkestrator: henter data og lager både raw output.png, mockup.png og en JPEG optimalisert for Inky.
Bruk: python main.py --days 10
Krev: pip install pillow requests
"""

import argparse
from pathlib import Path

from data_provider import initial_fetch_all
from layout_renderer import render_calendar, make_mockup_with_bezel
from inky_adapter import display_on_inky_if_available, save_png
from inky_icons_package import IconManager
from mappings import EVENT_MAPPINGS

# IMAGE PROCESSING (Pillow)
from PIL import Image, ImageOps, ImageFilter, ImageEnhance

# --- options --- (samme som før, holdes uendret)
opts = {
    "border_thickness": 1,
    "round_radius": 2,
    "underline_date": False,
    "day_fill": False,
    "invert_text_on_fill": True,
    "header_inverted": True,
    "header_fill_color": "BLUE",
    "header_text_color": "WHITE",
    "dotted_line_between_events": True,
    "event_vspacing": 14,
    "font_small_size": 16,
    "font_bold_size": 22,
    "dot_gap": 200,
    "dot_color": "WHITE",
    "heading_color": "BLACK",
    "text_color": "BLACK",
    "border_color": "BLACK",
    "min_box_height": 48,
    "show_more_text": True,
    "weather_debug": True,
    "icon_gap": 2
}

opts["icon_manager"] = IconManager()   # must be set before calling render_calendar(...)
opts["event_mappings"] = EVENT_MAPPINGS
opts["tint_event_icons"] = True

# --- FULL-COLOR JPEG export for Inky Frame SPECTRA 7.3 ---
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
from pathlib import Path

def save_for_inky_color(img, out_jpg=Path("output.jpg")):
    """
    Convert RGBA→RGB, resize, enhance and save as FULL COLOR JPEG (RGB).
    Perfect for Inky Frame SPECTRA 7.3 (7-color display).
    The Pico firmware will quantize to the 7-color palette automatically.
    """
    TARGET = (800, 480)

    # 1) Remove alpha (flatten to white)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        working = bg
    else:
        working = img.convert("RGB")

    # 2) Resize to target resolution (highest quality)
    if working.size != TARGET:
        working = working.resize(TARGET, Image.LANCZOS)

    # 3) Boost contrast + saturation slightly (helps e-ink color pop)
    working = ImageOps.autocontrast(working, cutoff=1)

    # Slight sharpness
    working = ImageEnhance.Sharpness(working).enhance(1.15)

    # Slight saturation boost (INKY likes strong colors)
    working = ImageEnhance.Color(working).enhance(1.2)

    # 4) Save full-color JPEG (NOT grayscale!)
    working.save(out_jpg,
                 format="JPEG",
                 quality=90,
                 optimize=True,
                 subsampling=0)

    print("Saved full-color JPEG for Inky:", out_jpg)


def main(single_run=True, days=10):
    print(f"[main] starting with days={days}")
    # Hent data med riktig days
    data = initial_fetch_all(days=days)
    # Debug: vis hvor mange events/weather-poster vi fikk
    ev_count = len(data.get("events", []))
    w_count = len(data.get("weather", []))
    print(f"Events: {ev_count}, Weather entries: {w_count}")

    # Render kalender med samme days-verdi
    img = render_calendar(data, width=800, height=480, days=days, renderer_opts=opts)
    if img is None:
        raise RuntimeError("render_calendar returned None")

    # lagre output PNG (som før)
    output_path = save_png(img, "output.png")
    print("Saved primary output to:", output_path)

    #Save FULL COLOR JPEG for Inky Frame
    try:
        save_for_inky_color(img, out_jpg=Path("output.jpg"))
    except Exception as e:
        print("ERROR saving full-color JPEG:", e)
    # mockup med bezel
    try:
        mock = make_mockup_with_bezel(img)
        mock.save("mockup.png")
        print("Saved mockup to: mockup.png")
    except Exception as e:
        print("Failed to create mockup.png:", e)

    # forsøk å sende til inky (hvis tilgjengelig)
    try:
        res = display_on_inky_if_available(img)
        print("Inky adapter result:", res)
    except Exception as e:
        print("display_on_inky_if_available failed:", e)

    # Done
    print("[main] finished")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inky Calendar runner")
    parser.add_argument("--days", "-d", type=int, default=7, help="Hvor mange dager å vise (f.eks. 7, 10, 14)")
    args = parser.parse_args()
    main(single_run=True, days=args.days)

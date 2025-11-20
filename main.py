# main.py
"""
Orkestrator: henter data og lager både raw output.png og en JPEG for Inky.
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

from PIL import Image

# --- renderer options ---
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

opts["icon_manager"] = IconManager()
opts["event_mappings"] = EVENT_MAPPINGS
opts["tint_event_icons"] = True


def save_jpeg_fast(img, out_path="output.jpg"):
    """
    Minimal, clean conversion from PNG → JPEG
    Ingen palettarbeid, ingen kvantisering – 100% ren konvertering.
    """
    img = img.convert("RGB")
    img.save(out_path, quality=100)
    print(f"Saved JPEG (simple RGB→JPEG): {out_path}")
    return out_path


def main(single_run=True, days=10):
    print(f"[main] starting with days={days}")

    # Hent data
    data = initial_fetch_all(days=days)
    print(f"Events: {len(data.get('events', []))}, Weather entries: {len(data.get('weather', []))}")

    # Render kalender
    img = render_calendar(data, width=800, height=480, days=days, renderer_opts=opts)
    if img is None:
        raise RuntimeError("render_calendar returned None")

    # Lag PNG
    output_path = save_png(img, "output.png")
    print("Saved primary output to:", output_path)

    # Lag enkel JPEG
    save_jpeg_fast(img, "output.jpg")

    # Forsøk å vise direkte på Inky (hvis adapteren har støtte)
    try:
        res = display_on_inky_if_available(img)
        print("Inky adapter result:", res)
    except Exception as e:
        print("display_on_inky_if_available failed:", e)

    print("[main] finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inky Calendar runner")
    parser.add_argument("--days", "-d", type=int, default=7, help="Hvor mange dager å vise (f.eks. 7, 10, 14)")
    args = parser.parse_args()
    main(single_run=True, days=args.days)

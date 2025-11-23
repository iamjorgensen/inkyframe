"""
Orkestrator: henter data og lager både raw output.png, en JPEG for Inky,
og en spritesheet .bin for best kvalitet på Inky Frame.
Bruk: python main_complete.py --days 10
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

# --- Inky palette quantize helpers ---
INKY_PALETTE_INDEXED = [
    (255, 255, 255),  # 0 = WHITE
    (0, 0, 0),        # 1 = BLACK
    (255, 0, 0),      # 2 = RED
    (255, 128, 0),    # 3 = ORANGE
    (255, 255, 0),    # 4 = YELLOW
    (0, 128, 0),      # 5 = GREEN
    (0, 0, 255),      # 6 = BLUE
]

def _make_palette_image_from_indexed(indexed_palette):
    flat = []
    # Build a 256-entry palette; ensure deterministic mapping
    for i in range(256):
        col = indexed_palette[i] if i < len(indexed_palette) else indexed_palette[i % len(indexed_palette)]
        flat.extend(col)
    pal = Image.new("P", (1,1))
    pal.putpalette(flat)
    return pal

def finalize_image_for_inky(img: Image.Image, out_png="output_for_inky.png", palette_indexed=INKY_PALETTE_INDEXED):
    """
    Quantize `img` to the exact indexed palette with NO dither and save a PNG.
    Returns the quantized Image in 'P' mode (palette indices correspond to palette_indexed order).
    """
    pal = _make_palette_image_from_indexed(palette_indexed)
    base = img.convert("RGB")
    quant = base.quantize(palette=pal, dither=Image.NONE)
    quant.save(out_png, optimize=True)
    print("Saved quantized PNG:", out_png)
    return quant

def save_spritesheet_from_quant(quant_img: Image.Image, out_path="output.bin"):
    """
    Write binary file where every byte is palette index (0..6) for each pixel
    reading palette index directly from the P-mode image.
    """
    if quant_img.mode != "P":
        raise RuntimeError("quant_img must be a 'P' (paletted) image produced by finalize_image_for_inky")
    w, h = quant_img.size
    pixels = quant_img.load()
    out = bytearray()
    for y in range(h):
        for x in range(w):
            out.append(pixels[x, y])
    with open(out_path, "wb") as f:
        f.write(out)
    print("Saved spritesheet binary:", out_path)
    return out_path

# --- renderer options ---
opts = {
    "border_thickness": 1,
    "round_radius": 2,
    "underline_date": False,
    "day_fill": False,
    "invert_text_on_fill": True,
    "header_inverted": True,
    "header_fill_color": "GREEN",
    "header_text_color": "WHITE",
    "dotted_line_between_events": True,
    "event_vspacing": 14,
    "font_small_size": 15,
    "font_bold_size": 16,
    "dot_gap": 200,
    "dot_color": "WHITE",
    "heading_color": "BLACK",
    "text_color": "BLACK",
    "border_color": "BLACK",
    "min_box_height": 48,
    "show_more_text": True,
    "weather_debug": True,
    "tag_font": "NotoSans-Bold.ttf",   # filename in assets/fonts OR full path
    "tag_font_size": 14,  
    "weather_tag_font": "Roboto-Regular.ttf",   # filename in assets/fonts or full path
    "weather_tag_font_size": 30,                # integer
    "weather_gap": 0,                            # pixel gap between each weather info block (default 
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


def save_spritesheet(img, out_png='output_for_inky.png', out_bin='output.bin'):
    """Save image for Inky: quantize to exact palette and write binary."""
    quant = finalize_image_for_inky(img, out_png=out_png)
    save_spritesheet_from_quant(quant, out_path=out_bin)
    return out_png, out_bin


def _try_render_calendar(events, opts, width=800, height=480, days=8):
    """
    Call render_calendar with the expected signature: render_calendar(data, width, height, days, renderer_opts)
    Returns a PIL Image.
    """
    try:
        img = render_calendar(events, width, height, days, opts)
        return img
    except TypeError as e:
        # try alternate ordering if code expects different arg order
        try:
            img = render_calendar(events, width, height, renderer_opts=opts)
            return img
        except Exception:
            print("render_calendar TypeError attempts failed:", e)
            raise
    except Exception as e:
        print("render_calendar failed:", e)
        raise


def _save_png_fallback(img, out="output.png"):
    """
    If save_png adapter exists, use it. Otherwise save via PIL.
    """
    try:
        save_png  # symbol imported earlier
    except NameError:
        img.convert("RGB").save(out)
        print("Saved PNG via PIL fallback:", out)
        return out
    try:
        save_png(img, out)
        print("Saved PNG via adapter:", out)
        return out
    except Exception as e:
        print("save_png adapter failed, falling back to PIL save:", e)
        img.convert("RGB").save(out)
        return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate InkyFrame calendar images")
    parser.add_argument("--days", type=int, default=7, help="How many days to fetch")
    parser.add_argument("--out-png", type=str, default="output.png", help="Output PNG path")
    parser.add_argument("--out-jpg", type=str, default="output.jpg", help="Output JPEG path")
    parser.add_argument("--out-bin", type=str, default="output.bin", help="Output spritesheet binary path")
    parser.add_argument("--debug-bezel", action="store_true", help="Also create mockup with bezel")
    parser.add_argument("--no-inky", action="store_true", help="Do not attempt to display on Inky even if available")
    args = parser.parse_args(argv)

    # Fetch data
    try:
        print(f"Fetching data for {args.days} days...")
        data = initial_fetch_all(days=args.days)
    except TypeError:
        # some providers expect a different signature
        data = initial_fetch_all(args.days)
    except Exception as e:
        print("Data fetch failed:", e)
        data = {}  # fallback to empty

    # attach options
    render_opts = dict(opts)  # copy global opts
    render_opts["days"] = args.days

    # Render calendar image
    try:
        img = _try_render_calendar(data, render_opts, width=800, height=480, days=args.days)
    except Exception as e:
        print("Primary render failed, attempting fallback empty render:", e)
        try:
            img = _try_render_calendar({}, render_opts, width=800, height=480, days=args.days)
        except Exception as e2:
            print("Fallback render failed:", e2)
            raise SystemExit(1)

    # Ensure we have a PIL.Image
    from PIL import Image as _Image
    if not hasattr(img, "convert"):
        # maybe render returned (img, meta)
        if isinstance(img, (list, tuple)) and len(img) > 0:
            img_candidate = img[0]
            if hasattr(img_candidate, "convert"):
                img = img_candidate
            else:
                raise RuntimeError("render_calendar did not return an image")
        else:
            raise RuntimeError("render_calendar did not return an image")

    # Produce JPEG (fast)
    try:
        save_jpeg_fast(img, out_path=args.out_jpg)
    except Exception as e:
        print("save_jpeg_fast failed:", e)
        try:
            img.convert("RGB").save(args.out_jpg, quality=95)
            print("Saved JPG via PIL fallback:", args.out_jpg)
        except Exception as e2:
            print("Failed to save JPG fallback:", e2)


if __name__ == "__main__":
    main()

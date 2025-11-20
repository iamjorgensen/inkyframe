"""
Inky Impression mockup emulator with support for icons/images
- Renders to a window (tkinter) and saves a PNG
- Loads icons/images from ./assets (creates sample icons if folder missing)
- Converts image to a 7-color e-ink palette with optional dithering

Requirements:
    pip install pillow

Run:
    python inky_emulator.py

Default target resolution: 800x480 (adjustable)
"""
from PIL import Image, ImageDraw, ImageFont, ImageOps
import os
import sys
import math
try:
    import tkinter as tk
    from PIL import ImageTk
except Exception:
    tk = None

# Configuration
WIDTH, HEIGHT = 800, 480
ASSETS_DIR = "assets"
OUTPUT_PNG = "inky_emulator_output.png"
USE_DITHER = True

# 7-color palette (approx RGB values)
PALETTE_COLORS = [
    (255, 255, 255),  # white
    (0, 0, 0),        # black
    (255, 0, 0),      # red
    (255, 165, 0),    # orange
    (255, 255, 0),    # yellow
    (0, 128, 0),      # green
    (0, 0, 255),      # blue
]
# names for reference
PALETTE_NAMES = ["white", "black", "red", "orange", "yellow", "green", "blue"]

# Utility: ensure assets exist (create sample icons)
def ensure_assets():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    sample_path = os.path.join(ASSETS_DIR, "sample_icon.png")
    if not os.path.exists(sample_path):
        # create a round red icon with transparent background
        s = 128
        im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((8, 8, s-8, s-8), fill=(255, 40, 40, 255))
        # try to load a nicer font, fallback to default
        try:
            f = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
        except Exception:
            f = ImageFont.load_default()

        # Pillow 10+ uses textbbox instead of textsize — compute width/height robustly
        try:
            bbox = d.textbbox((0, 0), "!", font=f)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except Exception:
            # final fallback: estimate using textlength and font size
            try:
                w = d.textlength("!", font=f)
                h = getattr(f, 'size', 16)
            except Exception:
                w, h = 8, 12

        d.text(((s-w)/2, (s-h)/2), "!", fill=(255,255,255,255), font=f)
        im.save(sample_path)

# Load any image from assets and resize while preserving aspect
def load_icon(name, size):
    path = os.path.join(ASSETS_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    im = Image.open(path).convert("RGBA")
    im.thumbnail((size, size), Image.LANCZOS)
    return im

# Compose a sample mockup: calendar + icons + images
def render_mockup():
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (255,255,255,255))
    draw = ImageDraw.Draw(canvas)

    # Background header bar
    header_h = 64
    draw.rectangle((0,0,WIDTH,header_h), fill=(230,230,230,255))
    # Title
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
        font_small = ImageFont.load_default()
    draw.text((12, 18), "Kalender — Mockup (Inky emulator)", font=font, fill=(0,0,0,255))

    # Weather icon area (top-right)
    icon_size = 48
    try:
        icon = load_icon("sample_icon.png", icon_size)
    except Exception:
        icon = None
    if icon:
        canvas.paste(icon, (WIDTH - icon_size - 12, 8), icon)

    # Calendar body: simple day boxes with small icons
    margin = 12
    cols = 7
    rows = 1
    box_w = (WIDTH - 2*margin - (cols-1)*6) // cols
    box_h = 240
    y0 = header_h + 14
    # draw day boxes
    for i in range(cols):
        x = margin + i*(box_w+6)
        draw.rectangle((x, y0, x+box_w, y0+box_h), outline=(200,200,200,255), fill=(255,255,255,255))
        day_title = f"{['Man','Tir','Ons','Tor','Fre','Lør','Søn'][i]} 17.11"
        draw.text((x+8, y0+8), day_title, font=font_small, fill=(0,0,0,255))
        # paste an icon for some boxes
        if i % 2 == 0 and icon:
            ix = x + 8
            iy = y0 + 36
            canvas.paste(icon, (ix, iy), icon)
            draw.text((ix+icon_size+8, iy+6), "Møte med Ola\nKl. 09:00", font=font_small, fill=(0,0,0,255))

    # Bottom strip with a photo example
    photo_h = 120
    photo_w = WIDTH - 2*margin
    photo = Image.new("RGB", (photo_w, photo_h), (100,140,200))
    # if user provided a photo in assets, use it
    photo_path = os.path.join(ASSETS_DIR, "sample_photo.jpg")
    if os.path.exists(photo_path):
        try:
            p = Image.open(photo_path).convert("RGB")
            p.thumbnail((photo_w, photo_h), Image.LANCZOS)
            # center it
            px = (photo_w - p.width)//2
            py = (photo_h - p.height)//2
            photo.paste(p, (px, py))
        except Exception:
            pass
    canvas.paste(photo, (margin, y0+box_h+12))
    draw.rectangle((margin, y0+box_h+12, margin+photo_w, y0+box_h+12+photo_h), outline=(160,160,160,255))

    return canvas

# Build a palette image that can be used for quantize
def build_palette_image():
    # Pillow expects palette images of mode 'P' with a palette of 768 values (256*3)
    pal_img = Image.new('P', (16,16))
    palette = []
    for c in PALETTE_COLORS:
        palette.extend(c)
    # pad to 256
    while len(palette) < 768:
        palette.extend((0,0,0))
    pal_img.putpalette(palette)
    return pal_img

# Convert RGBA image to 7-color e-ink palette with optional dithering
def convert_to_7color(img_rgba, dither=True):
    # flatten on white background
    bg = Image.new('RGB', img_rgba.size, (255,255,255))
    bg.paste(img_rgba, mask=img_rgba.split()[3] if img_rgba.mode=='RGBA' else None)
    pal = build_palette_image()
    # quantize using the custom palette
    if dither:
        converted = bg.quantize(palette=pal, dither=Image.FLOYDSTEINBERG)
    else:
        converted = bg.quantize(palette=pal, dither=0)
    return converted.convert('RGB')

# Save output and optionally open window
def run():
    ensure_assets()
    out = render_mockup()
    converted = convert_to_7color(out, dither=USE_DITHER)
    converted.save(OUTPUT_PNG)
    print(f"Saved output to {OUTPUT_PNG}")

    if tk is None:
        print("tkinter not available — skipping window preview")
        return

    # Show preview in a tkinter window
    root = tk.Tk()
    root.title("Inky Emulator Preview")
    root.geometry(f"{WIDTH}x{HEIGHT}")

    tk_img = ImageTk.PhotoImage(converted.resize((WIDTH, HEIGHT)))
    lbl = tk.Label(root, image=tk_img)
    lbl.pack()

    def on_key(e):
        if e.keysym == 's':
            print('Saved (again)')
            converted.save(OUTPUT_PNG)
        elif e.keysym == 'q':
            root.destroy()

    root.bind('<Key>', on_key)
    root.mainloop()

if __name__ == '__main__':
    run()

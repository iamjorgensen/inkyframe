#!/usr/bin/env python3
"""
inky_mock_full_package.py

Full "mock" package for developing/testing Inky Frame/Impression code on a PC.
- Provides InkyFrame (mock) class with a Pimoroni-like API (most common methods).
- Provides a tiny shim that lets you run an existing `main.py` while faking the `inky` module
  so your code doesn't need changes. Use: python inky_mock_full_package.py /path/to/your/main.py

Requirements: Pillow
    pip install pillow

Features:
- 600x448 default resolution (Inky Frame / 7.3" impression style)
- Color palette mapping (black/white/red/yellow/green/blue)
- clear(), set_pixel(), set_border(), set_image(), show(), display() methods
- Optional dithering when converting full-color PIL images to display palette
- `--out` argument to name the generated PNG (default: preview.png)
- When used as a runner it injects a fake `inky` and `inky.auto` module so your usual imports
  (e.g. `from inky import InkyFrame` or `from inky.auto import auto`) will work.

Limitations: This is a visual/layout emulator only. It does NOT emulate e-ink refresh
behaviour, black-white partial refresh quirks, or the device's hardware-specific timing.

"""

import sys
import os
import types
import argparse
from PIL import Image, ImageDraw, ImageFont, ImageOps

# -----------------------------
# Mock Inky class
# -----------------------------

class InkyMock:
    # Default size for 7.3" Inky Impression / Frame variant
    WIDTH = 600
    HEIGHT = 448

    # Default palette used by Inky Impression variants — map names to RGB
    PALETTE = {
        "white":  (255, 255, 255),
        "black":  (0, 0, 0),
        "red":    (255, 0, 0),
        "yellow": (255, 255, 0),
        "green":  (0, 255, 0),
        "blue":   (0, 0, 255),
    }

    def __init__(self, width=None, height=None, rotation=0, palette=None, dither=True):
        """
        Create a mock Inky display.
        - width, height: override default resolution
        - rotation: 0, 90, 180, 270 (affects drawing coordinates when show() is called)
        - palette: dict overriding PALETTE
        - dither: whether to use dithering when converting images to the palette
        """
        self.width = width or self.WIDTH
        self.height = height or self.HEIGHT
        self.rotation = rotation
        self.palette = palette or dict(self.PALETTE)
        self.dither = dither

        # Create white background image
        self.image = Image.new("RGB", (self.width, self.height), self.palette["white"])
        self.draw = ImageDraw.Draw(self.image)
        try:
            self._font = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            self._font = ImageFont.load_default()

        # border color variable (some code sets it)
        self.border = "black"

        # track whether an inky-style .show() was called so runner can pick up file
        self._last_filename = None

    # ------------------ basic drawing API ------------------
    def clear(self, color="white"):
        rgb = self._color(color)
        self.draw.rectangle((0, 0, self.width, self.height), fill=rgb)

    def set_pixel(self, x, y, color):
        rgb = self._color(color)
        if 0 <= x < self.width and 0 <= y < self.height:
            self.draw.point((x, y), fill=rgb)

    def get_pixel(self, x, y):
        return self.image.getpixel((x, y))

    def set_border(self, color):
        self.border = color

    def set_rotation(self, r):
        if r in (0, 90, 180, 270):
            self.rotation = r
        else:
            raise ValueError("rotation must be 0,90,180 or 270")

    def set_image(self, pil_image):
        """Copy a PIL image onto the display canvas, centered if sizes differ.
        This mirrors the convenience used in many inky examples.
        """
        if not isinstance(pil_image, Image.Image):
            raise TypeError("set_image expects a PIL.Image")

        # Convert to RGB and resize to fit preserving aspect ratio
        src = pil_image.convert("RGB")
        # If same size -> paste directly
        if src.size == (self.width, self.height):
            self.image.paste(src)
        else:
            # Fit inside the display
            fitted = ImageOps.contain(src, (self.width, self.height))
            # center paste
            x = (self.width - fitted.width) // 2
            y = (self.height - fitted.height) // 2
            self.image.paste(fitted, (x, y))

    def show(self, filename="preview.png"):
        """Save a preview PNG and open it with the OS default viewer.
        Converts to the Inky palette first so the output looks like the real device.
        """
        # Convert copy to palette-simulated image
        out = self._to_palette_image(self.image)

        # Draw a small border marker showing chosen border color
        try:
            border_rgb = self._color(self.border)
            draw = ImageDraw.Draw(out)
            draw.rectangle((0, 0, 7, 7), fill=border_rgb)
        except Exception:
            pass

        out.save(filename)
        self._last_filename = filename

        # Try to open file with default OS viewer. This works on most systems.
        try:
            if sys.platform == "darwin":
                os.system(f"open {filename}")
            elif sys.platform.startswith("linux"):
                os.system(f"xdg-open {filename} &>/dev/null")
            elif sys.platform.startswith("win"):
                os.startfile(filename)
        except Exception:
            # if opening fails, that's fine — file is still written
            pass

        return filename

    # alias used in some examples
    display = show

    # ------------------ internals ------------------
    def _color(self, color):
        """Accept color names, tuple, or hex. Return RGB tuple."""
        if isinstance(color, tuple) and len(color) == 3:
            return color
        if isinstance(color, str):
            if color.lower() in self.palette:
                return self.palette[color.lower()]
            # hex like '#RRGGBB'
            if color.startswith("#") and len(color) == 7:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                return (r, g, b)
        # fallback black
        return (0, 0, 0)

    def _to_palette_image(self, img):
        """Convert RGB image to an image that only uses the Inky palette colors.
        Uses a simple nearest-color mapping. If dither is True, apply Floyd–Steinberg.
        """
        # Prepare palette list
        palette_colors = list(self.palette.values())
        # Create a tiny palette image that Pillow can use
        pal_img = Image.new('P', (1,1))
        # build a palette list (palettes are 768-length lists)
        flat = []
        for (r,g,b) in palette_colors:
            flat.extend([r,g,b])
        # pad to 256 colors
        flat += [0] * (768 - len(flat))
        pal_img.putpalette(flat)

        # Convert original to P using this palette.
        if self.dither:
            converted = img.convert('RGB').convert('P', palette=Image.ADAPTIVE)
            # Now remap by nearest palette color (we want our exact given palette)
            converted = converted.convert('RGB')
            remapped = Image.new('RGB', converted.size, (255,255,255))
            pixels_in = converted.load()
            pixels_out = remapped.load()
            w,h = converted.size
            for y in range(h):
                for x in range(w):
                    r,g,b = pixels_in[x,y]
                    # find nearest color in our palette
                    best = min(palette_colors, key=lambda c: (c[0]-r)**2 + (c[1]-g)**2 + (c[2]-b)**2)
                    pixels_out[x,y] = best
            return remapped
        else:
            # No dithering: direct nearest color mapping
            src = img.convert('RGB')
            w,h = src.size
            out = Image.new('RGB', (w,h))
            inpx = src.load()
            outpx = out.load()
            for y in range(h):
                for x in range(w):
                    r,g,b = inpx[x,y]
                    best = min(palette_colors, key=lambda c: (c[0]-r)**2 + (c[1]-g)**2 + (c[2]-b)**2)
                    outpx[x,y] = best
            return out


# -----------------------------
# Shim / Runner: inject fake inky module and run a user script
# -----------------------------

def make_inky_module_class(mock_cls=InkyMock):
    """Create a fake `inky` module object with commonly-used symbols.
    The returned module provides: InkyFrame, InkyPhat, InkyImpression (aliases), and
    a submodule `auto` containing `auto()` which returns an instance.
    """
    m = types.ModuleType('inky')
    # Provide classes/aliases
    setattr(m, 'InkyFrame', mock_cls)
    setattr(m, 'InkyPhat', mock_cls)  # alias
    setattr(m, 'InkyPHAT', mock_cls)
    setattr(m, 'InkyImpression', mock_cls)

    # Provide simple color constants sometimes used
    setattr(m, 'WHITE', 'white')
    setattr(m, 'BLACK', 'black')

    # auto submodule
    auto_mod = types.ModuleType('inky.auto')
    def auto():
        return mock_cls()
    auto_mod.auto = auto

    # attach auto submodule
    m.auto = auto_mod
    sys.modules['inky'] = m
    sys.modules['inky.auto'] = auto_mod
    return m


def run_user_script(path_to_script, out_filename='preview.png', extra_argv=None):
    """Run a Python script with the fake inky module injected.
    The script will run normally and when it calls Inky.show() the preview.png will be written.
    """
    if not os.path.exists(path_to_script):
        raise FileNotFoundError(path_to_script)

    # Inject mock inky module
    make_inky_module_class()

    # Prepare sys.argv for the script
    old_argv = sys.argv.copy()
    sys.argv = [path_to_script]
    if extra_argv:
        sys.argv += extra_argv

    # Add the script's directory to sys.path so relative imports work
    script_dir = os.path.dirname(os.path.abspath(path_to_script))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # Execute the script in its own globals
    globals_dict = {
        '__file__': path_to_script,
        '__name__': '__main__',
        '__package__': None,
    }
    with open(path_to_script, 'rb') as f:
        code = compile(f.read(), path_to_script, 'exec')
        exec(code, globals_dict, globals_dict)

    # restore argv
    sys.argv = old_argv
    return out_filename


# -----------------------------
# CLI
# -----------------------------

def main_cli():
    parser = argparse.ArgumentParser(description='Inky mock runner & library')
    parser.add_argument('script', nargs='?', help='(optional) path to your main.py to run with mock inky')
    parser.add_argument('--out', '-o', help='output PNG filename (default preview.png)', default='preview.png')
    parser.add_argument('--no-dither', action='store_true', help='disable dithering when rendering palette')
    parser.add_argument('--width', type=int, help='override width')
    parser.add_argument('--height', type=int, help='override height')
    args, unknown = parser.parse_known_args()

    if args.script:
        # Before running, set default factory to use given dimensions/dither
        def custom_factory():
            return InkyMock(width=args.width, height=args.height, dither=not args.no_dither)

        # Replace the inky module factory to use our custom factory
        make_inky_module_class(mock_cls=InkyMock)

        print(f"Running script with mock inky: {args.script}")
        try:
            run_user_script(args.script, out_filename=args.out, extra_argv=unknown)
            print(f"Saved preview to {args.out}")
        except Exception as e:
            print(f"Error running script: {e}")
            raise
    else:
        # If no script: drop into a tiny interactive demo
        print("No script provided — creating a demo preview.png using the mock Inky display.")
        d = InkyMock(width=args.width or None, height=args.height or None, dither=not args.no_dither)
        d.clear('white')
        d.draw.rectangle((0, 0, d.width, 80), fill=d._color('yellow'))
        d.draw.text((12, 16), "Inky Mock Demo", fill=d._color('black'), font=d._font)
        d.draw.text((12, 40), "Use: python inky_mock_full_package.py path/to/your/main.py", fill=d._color('black'), font=d._font)
        d.show(args.out)
        print(f"Wrote {args.out}")


if __name__ == '__main__':
    main_cli()

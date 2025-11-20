"""
fetch_feather_icons.py

Small utility to download SVG icons (default: Feather icons) and convert them to PNG(s).
Creates an `assets/icons/` folder with PNGs and an `assets/icons/icons_mapping.json` mapping events/keywords to filenames.

Changes in this version (per user request):
 - Much-expanded Norwegian event->icon mapping (see DEFAULT_EVENT_MAP).
 - Keeps PNG filenames with size suffix (e.g. cpu-20px.png) but temporary SVG filenames are now clean (e.g. cpu.svg) instead of cpu-20px.tmp.svg.
 - Added a small list of suggested non-Feather custom icons (CUSTOM_ICON_SUGGESTIONS) -- fill the URLs if you have preferred sources or use `--custom` with your own file.
 - Filename handling: the saved intermediate SVG will be named `{icon_name}.svg` in the output directory while produced PNGs remain `<icon_name>-<size>px.png`.

Usage examples:
  python fetch_feather_icons.py --out assets/icons --size 20 --names calendar,coffee,umbrella
  python fetch_feather_icons.py --out assets/icons --size 20,40 --custom custom_urls.txt

NOTE: This script requires 'requests' and either 'cairosvg' (preferred) or 'inkscape' in PATH for SVG->PNG conversion.

"""

from __future__ import annotations
import argparse
import os
import sys
import json
import shutil
from pathlib import Path
from typing import List, Tuple

try:
    import requests
except Exception:
    print("This script requires the 'requests' package. Install with: pip install requests")
    raise

# Conversion: prefer cairosvg if available
USE_CAIROSVG = True
try:
    import cairosvg
except Exception:
    USE_CAIROSVG = False


FEATHER_RAW_BASE = "https://raw.githubusercontent.com/feathericons/feather/master/icons/{}.svg"
OUTPUT_MAPNAME = "icons_mapping.json"

# Expanded starter set of icon names (Feather + suggestions). Add more names here.
DEFAULT_NAMES = [
    # common
    "calendar", "trash-2","clock", "bell", "gift", "coffee", "home", "phone", "users",
    "book", "briefcase", "heart", "star", "alert-circle", "sun", "cloud",
    "cloud-rain", "umbrella", "wind", "thermometer", "tv", "camera", "music",
    "shopping-cart", "map-pin", "film", "scissors", "truck", "cpu", "battery",
    "activity", "target", "flag", "shopping-bag", "headphones", "droplet",
    # extra Feather names that are handy
    "play", "pause", "stop", "repeat", "refresh-cw", "map", "map-pin", "navigation",
    "phone-call", "mail", "folder", "file-text", "clipboard", "check-circle", "x-circle",
    # social / food / travel
    "coffee", "cutlery", "globe", "briefcase", "user-check", "user-minus",
]

# Some icons are not in Feather. Use custom suggestions for these (names only here; URLs in CUSTOM_ICON_SUGGESTIONS)
# Example missing icons: football, skull (r.i.p), coffin, bed, cross (medical), dumbbell, church
CUSTOM_ICON_SUGGESTIONS = {
    # name: "url to raw svg"
    # Example (fill these with your preferred sources or pass via --custom custom_urls.txt):
    "football": "",  # typical sources: Tabler Icons, Material Icons (raw svg URL)
    "skull": "",
    "coffin": "",
    "bed": "",
    "cross-medical": "",
    "dumbbell": "",
    "pray": "",
    "birthday-cake": "",
}

# Norwegian event -> icon mapping (editable). Where Feather doesn't provide an icon name, map to a custom name above.
DEFAULT_EVENT_MAP = {
    # birthdays, celebrations
    "bursdag": "gift",
    "bursdag (barn)": "gift",
    "barnebursdag": "gift",
    "jubileum": "star",
    "kake": "birthday-cake",

    # everyday / family
    "jobb": "briefcase",
    "møte": "users",
    "videomøte": "video",  # 'video' may not exist in Feather, adjust if necessary
    "skole": "book",
    "barnehage": "book",
    "henting": "clock",
    "levering": "clock",
    "foreldremøte": "users",
    "sfo": "book",

    # health & safety
    "lege": "cross-medical",
    "tannlege": "cross-medical",
    "vaksine": "shield",
    "påminnelse": "bell",
    "medisin": "droplet",

    # travel / errands
    "handletur": "shopping-cart",
    "butikk": "shopping-bag",
    "post": "mail",
    "levering": "truck",
    "reise": "globe",

    # weather / outdoors
    "piknik": "map-pin",
    "tur": "map",
    "ferie": "sun",

    # sports & activities
    "fotball": "football",
    "trening": "activity",
    "gym": "dumbbell",
    "dans": "music",
    "svømming": "droplet",

    # home & chores
    "vask": "scissors",
    "vask (maskin)": "scissors",
    "rengjøring": "broom",  # may not be in Feather
    "avtale": "calendar",

    # social / leisure
    "kino": "film",
    "konsert": "music",
    "middag": "coffee",
    "kveld": "moon",

    # sleep / bedtime
    "leggetid": "bed",
    "sover": "bed",

    # end of life / remembrance
    "r.i.p": "skull",
    "dødsdag": "coffin",
    "gravferd": "coffin",

    # reminders / alerts
    "viktig": "alert-circle",
    "henting skole": "clock",
    "betalingsfrist": "credit-card",

    # misc
    "legekontroll": "cross-medical",
    "bilvask": "truck",
    "hjertestarter": "heart",
}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def fetch_svg_by_name(name: str) -> Tuple[bytes, str]:
    """Fetch SVG content from Feather by icon name. Returns (bytes, source_url)."""
    url = FEATHER_RAW_BASE.format(name)
    r = requests.get(url, timeout=15)
    if r.status_code == 200 and r.content.strip():
        return r.content, url
    else:
        raise RuntimeError(f"Failed to fetch {name} from Feather (status={r.status_code}) at {url})")


def fetch_svg_from_url(url: str) -> Tuple[bytes, str]:
    r = requests.get(url, timeout=15)
    if r.status_code == 200 and r.content.strip():
        return r.content, url
    else:
        raise RuntimeError(f"Failed to fetch SVG from {url} (status={r.status_code})")


def save_bytes(path: Path, data: bytes):
    with open(path, "wb") as f:
        f.write(data)


def convert_svg_to_png(svg_bytes: bytes, out_path: Path, size: int = 20, transparent: bool = True, name: str = None):
    """Convert SVG bytes to PNG file at out_path with width=size and height=size.
    Tries cairosvg, otherwise falls back to inkscape CLI if available.
    The intermediate SVG filename will be `<name>.svg` (clean) in the output folder.
    """
    ensure_dir(out_path.parent)
    if USE_CAIROSVG:
        try:
            cairosvg.svg2png(bytestring=svg_bytes, write_to=str(out_path), output_width=size, output_height=size)
            return
        except Exception as e:
            print(f"cairosvg conversion failed: {e}")
    # Fallback: try inkscape command-line (needs inkscape in PATH)
    # Use a clean intermediate SVG filename (strip size suffix)
    if name:
        tmp_svg = out_path.parent / f"{name}.svg"
    else:
        tmp_svg = out_path.with_suffix('.svg')
    save_bytes(tmp_svg, svg_bytes)
    inkscape_cmd = shutil.which("inkscape")
    if not inkscape_cmd:
        # If cairosvg failed and inkscape isn't available, raise with helpful message
        raise RuntimeError("No conversion method available: install 'cairosvg' or make 'inkscape' available in PATH.")
    try:
        # newer inkscape: inkscape input.svg --export-filename=out.png --export-width=XX --export-height=YY
        cmd = f'"{inkscape_cmd}" "{tmp_svg}" --export-filename="{out_path}" --export-width={size} --export-height={size}'
        rc = os.system(cmd)
        if rc != 0:
            raise RuntimeError(f"Inkscape returned non-zero exit code: {rc}")
    finally:
        try:
            tmp_svg.unlink()
        except Exception:
            pass


def parse_custom_file(path: Path) -> List[Tuple[str, str]]:
    """Parse a file where each non-empty line is 'name,url'. Returns list of tuples."""
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "," in line:
                name, url = [p.strip() for p in line.split(",", 1)]
            else:
                url = line
                name = Path(url).stem
            pairs.append((name, url))
    return pairs


def build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download SVG icons and convert to PNG(s).")
    p.add_argument("--out", default="assets/icons", help="output folder")
    p.add_argument("--size", default="20", help="comma-separated sizes (px) to produce, e.g. 20 or 20,40")
    p.add_argument("--names", help="comma-separated Feather icon names to fetch (falls back to DEFAULT_NAMES if omitted)")
    p.add_argument("--custom", help="path to a file with lines 'name,url' for icons not in Feather")
    p.add_argument("--map", help="path to write event->icon mapping json (defaults to assets/icons/icons_mapping.json)")
    p.add_argument("--transparent", action="store_true", help="produce transparent background if supported")
    return p.parse_args()


def main():
    args = build_args()
    out_dir = Path(args.out)
    ensure_dir(out_dir)
    sizes = [int(s.strip()) for s in args.size.split(",") if s.strip()]

    names = []
    if args.names:
        names = [n.strip() for n in args.names.split(",") if n.strip()]
    else:
        names = DEFAULT_NAMES

    custom_pairs: List[Tuple[str, str]] = []
    # Combine user-provided custom file with suggested CUSTOM_ICON_SUGGESTIONS (if URLs provided)
    if args.custom:
        custom_pairs.extend(parse_custom_file(Path(args.custom)))
    # Add any suggestions that have non-empty URL
    for nm, url in CUSTOM_ICON_SUGGESTIONS.items():
        if url:
            custom_pairs.append((nm, url))

    # We'll collect metadata: which sizes produced for each icon and source URLs
    produced = {}

    # Process Feather names first
    for name in names:
        try:
            svg_bytes, source = fetch_svg_by_name(name)
        except Exception as e:
            print(f"Skipping '{name}': {e}")
            continue
        produced[name] = {"source": source, "sizes": []}
        for size in sizes:
            out_filename = f"{name}-{size}px.png"
            out_path = out_dir / out_filename
            try:
                convert_svg_to_png(svg_bytes, out_path, size=size, transparent=args.transparent, name=name)
                produced[name]["sizes"].append(out_filename)
                print(f"Wrote {out_path}")
            except Exception as e:
                print(f"Failed to convert {name} to {size}px: {e}")

    # Process custom URL icons
    for name, url in custom_pairs:
        try:
            svg_bytes, source = fetch_svg_from_url(url)
        except Exception as e:
            print(f"Skipping custom '{name}': {e}")
            continue
        produced[name] = {"source": source, "sizes": []}
        for size in sizes:
            out_filename = f"{name}-{size}px.png"
            out_path = out_dir / out_filename
            try:
                convert_svg_to_png(svg_bytes, out_path, size=size, transparent=args.transparent, name=name)
                produced[name]["sizes"].append(out_filename)
                print(f"Wrote {out_path}")
            except Exception as e:
                print(f"Failed to convert custom {name} to {size}px: {e}")

    # Write mapping file
    mapping_path = Path(args.map) if args.map else (out_dir / OUTPUT_MAPNAME)
    # If existing mapping is present, try to preserve and merge
    existing = {}
    if mapping_path.exists():
        try:
            existing = json.loads(mapping_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    merged_map = existing.get('event_mapping_merged', {}) if isinstance(existing, dict) and 'event_mapping_merged' in existing else existing
    if not isinstance(merged_map, dict):
        merged_map = {}
    # Add defaults only where missing
    for k, v in DEFAULT_EVENT_MAP.items():
        if k not in merged_map:
            merged_map[k] = v

    # Also write a small index of the produced images
    index = {k: v for k, v in produced.items()}
    output = {"icons_produced": index, "event_mapping_defaults_added": DEFAULT_EVENT_MAP, "event_mapping_merged": merged_map}
    mapping_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote mapping to {mapping_path}")


if __name__ == '__main__':
    main()

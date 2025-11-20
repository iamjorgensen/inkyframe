# inky_icons_package.py
"""
IconManager for Inky Frame Calendar Project.

Responsibilities:
 - load PNG icons from assets/icons into memory (default load size)
 - provide helper methods to fetch/rescale icons for renderer or other parts
 - consult mappings.py for mapping decisions (mapping_info_for_event, weather_to_icon)
 - keep this file free of any event -> icon mapping data (use mappings.py for that)

API:
  IconManager(icons_dir=None, load_size=20)
    .get(name) -> PIL.Image or None
    .get_icon_image(name, size) -> PIL.Image or None
    .render_icon(name, size) -> PIL.Image or None  (alias)
    .find_for_keyword(text, size=None) -> PIL.Image or None
    .get_weather_icon(entry, size=None) -> PIL.Image or None
"""
import os
from PIL import Image
import logging

# try to import mapping helpers from mappings.py (non-fatal fallback)
try:
    from mappings import mapping_info_for_event, weather_to_icon, color_to_rgb
except Exception:
    mapping_info_for_event = None
    weather_to_icon = None
    color_to_rgb = None

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")

# default size we keep in memory for quick access; renderer will resize/pad as needed
DEFAULT_LOAD_SIZE = 20

logger = logging.getLogger("IconManager")


class IconManager:
    def __init__(self, icons_dir: str = None, load_size: int = DEFAULT_LOAD_SIZE):
        self.icons_dir = icons_dir or ICONS_DIR
        self.load_size = int(load_size or DEFAULT_LOAD_SIZE)
        self._icons = {}  # name -> PIL.Image (RGBA) at load_size
        self._load_icons_from_dir()

    def _load_icons_from_dir(self):
        """Load all .png files in icons_dir into memory (resized to load_size height)."""
        if not os.path.isdir(self.icons_dir):
            logger.debug("IconManager: icons dir does not exist: %s", self.icons_dir)
            return
        for fn in os.listdir(self.icons_dir):
            if not fn.lower().endswith(".png"):
                continue
            name = os.path.splitext(fn)[0]
            path = os.path.join(self.icons_dir, fn)
            try:
                im = Image.open(path).convert("RGBA")
                w, h = im.size
                if h != self.load_size:
                    new_w = max(1, int(w * (self.load_size / float(h))))
                    im = im.resize((new_w, self.load_size), Image.Resampling.LANCZOS)
                self._icons[name] = im
            except Exception as ex:
                logger.debug("IconManager: failed to load icon %s: %s", path, ex)
        # debug listing when requested
        try:
            if os.environ.get("INKY_DEBUG_ICONS", "0") == "1":
                print("IconManager: loaded icons:", sorted(list(self._icons.keys())))
        except Exception:
            pass

    def available_icons(self):
        return list(self._icons.keys())

    def _get_raw(self, key: str):
        if not key:
            return None
        k = str(key).strip().lower()
        return self._icons.get(k)

    def get(self, name: str):
        """
        Return a copy of the icon PIL image for `name` at the manager's load_size (RGBA),
        or None if not found.
        """
        im = self._get_raw(name)
        if im is None:
            return None
        # return a copy to avoid accidental in-place changes
        return im.copy()

    def get_icon_image(self, name: str, size: int):
        """
        Return an RGBA PIL.Image scaled so that its height == size (preserve aspect).
        If icon not found, return None.
        """
        im = self._get_raw(name)
        if im is None:
            return None
        try:
            im2 = im.copy()
            w, h = im2.size
            if h != size:
                new_w = max(1, int(w * (size / float(h))))
                im2 = im2.resize((new_w, int(size)), Image.Resampling.LANCZOS)
            return im2
        except Exception:
            return None

    # alias used by some older caller names
    render_icon = get_icon_image

    def find_for_keyword(self, text: str, size: int = None):
        """
        Use mapping_info_for_event (if available) to find a matching icon for the provided
        event `text`. If mapping_info_for_event returns an 'icon' key, return the icon image.
        Otherwise, do a naive substring scan over available icon names and return the first hit.

        Returns PIL.Image (resized to `size` if provided) or None.
        """
        if not text:
            return None

        # 1) mappings.py helper
        if mapping_info_for_event:
            try:
                mapping = mapping_info_for_event(text)
                if mapping and mapping.get("icon"):
                    icon_name = mapping.get("icon")
                    if size:
                        return self.get_icon_image(icon_name, size)
                    else:
                        return self.get(icon_name)
            except Exception:
                # swallow mapping errors and fallback to simple heuristics
                pass

        # 2) simple heuristic: look for icon name substrings in the text
        txt = str(text).lower()
        for icon_name in self._icons.keys():
            if icon_name in txt:
                if size:
                    return self.get_icon_image(icon_name, size)
                else:
                    return self.get(icon_name)

        # 3) no inference found
        return None

    def get_weather_icon(self, weather_entry: dict, size: int = None):
        """
        Try mapping weather symbol -> icon via mappings.weather_to_icon if available,
        otherwise fallback to reading possible keys from weather_entry and using ICON_NAME_MAP
        from layout_renderer via the loader (mapping helper must be available in mappings.py).
        """
        # Prefer mapping helper
        if weather_to_icon:
            try:
                # mapping might expect symbol or full entry; try symbol first
                symbol = None
                if isinstance(weather_entry, dict):
                    # try common keys
                    for k in ("icon", "symbol", "weather_icon", "main"):
                        if k in weather_entry and weather_entry.get(k):
                            symbol = weather_entry.get(k)
                            break
                if symbol is None:
                    symbol = weather_entry
                mapped = weather_to_icon(symbol)
                if mapped:
                    if size:
                        return self.get_icon_image(mapped, size)
                    else:
                        return self.get(mapped)
            except Exception:
                pass

        # fallback: try common entry keys and search icons by name
        candidates = []
        if isinstance(weather_entry, dict):
            for k in ("icon", "symbol", "main", "weather_icon"):
                if k in weather_entry and weather_entry.get(k):
                    candidates.append(str(weather_entry.get(k)))
        else:
            candidates.append(str(weather_entry))

        for cand in candidates:
            cand_norm = cand.strip().lower()
            # try exact icon name first
            if cand_norm in self._icons:
                return self.get_icon_image(cand_norm, size) if size else self.get(cand_norm)
            # try substring match
            for icon_name in self._icons.keys():
                if icon_name in cand_norm or cand_norm in icon_name:
                    return self.get_icon_image(icon_name, size) if size else self.get(icon_name)

        # nothing found
        return None


# convenience factory for one-line instantiation used across project
_default_manager = None


def get_default_icon_manager():
    global _default_manager
    if _default_manager is None:
        _default_manager = IconManager()
    return _default_manager


# simple CLI test when run directly
if __name__ == "__main__":
    im = get_default_icon_manager()
    print("Loaded icons:", im.available_icons()[:120])
    # quick smoke test of mapping-based inference (if mappings.py exists)
    if mapping_info_for_event:
        test_cases = [
            "Middag: Pasta",
            "Movar: Restavfall",
            "Husk: betal regning",
            "Bursdag: Ola",
        ]
        for t in test_cases:
            res = im.find_for_keyword(t)
            print("find_for_keyword:", t, "->", type(res), bool(res))
    else:
        print("mappings.mapping_info_for_event not available in this environment.")

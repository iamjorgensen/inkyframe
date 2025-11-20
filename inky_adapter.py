# inky_adapter.py
from PIL import Image
from pathlib import Path

def save_png(img: Image.Image, path="output.png"):
    img.save(path)
    return Path(path).resolve()

def display_on_inky_if_available(img: Image.Image):
    """
    Hvis du senere har en inky_py_full_package som tilbyr en funksjon som aksepterer PIL.Image,
    kan du endre denne funksjonen til å bruke den. Her gjør vi en try/except for robusthet.
    """
    try:
        import inky_py_full_package as ipkg
        # ulike mulige API-er vi prøver (best-effort)
        if hasattr(ipkg, "display_from_pil"):
            ipkg.display_from_pil(img)
            return "displayed_via_ipkg.display_from_pil"
        elif hasattr(ipkg, "render") and callable(ipkg.render):
            # noen render-funksjoner aksepterer PIL eller returnerer PIL
            maybe = ipkg.render(img)
            if isinstance(maybe, Image.Image):
                maybe.save("output.png")
                return "ipkg.render_returned_image_saved"
            else:
                return "ipkg.render_called"
        else:
            # fallback: lagre PNG
            p = save_png(img, "output.png")
            return f"saved_png:{p}"
    except Exception:
        p = save_png(img, "output.png")
        return f"saved_png:{p}"

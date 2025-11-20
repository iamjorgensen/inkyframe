from PIL import Image, ImageStat, ImageOps, ImageDraw, ImageFont
import os

p = "output.png"
if not os.path.exists(p):
    print("Fant ikke output.png i cwd:", os.getcwd())
    raise SystemExit

img = Image.open(p)
print("Fil:", p, "mode:", img.mode, "size:", img.size)

# Compute stats
stat = ImageStat.Stat(img.convert("L"))
ext = stat.extrema[0]   # (min, max)
mean = stat.mean[0]

print("Luma stats:")
print("  min:", ext[0])
print("  max:", ext[1])
print("  mean:", mean)

if ext[0] == ext[1]:
    print("=> Bildet er HELT ensfarget (blank).")
else:
    print("=> Bildet har variasjon (ikke helt blankt).")

# Invert for inspection
inv = ImageOps.invert(img.convert("RGB"))
inv.save("debug_inverted_output.png")
print("Lagret debug_inverted_output.png")

# Draw overlay
dbg = img.convert("RGBA")
draw = ImageDraw.Draw

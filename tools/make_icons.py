"""Vẽ logo Private Picture (khóa chân dung trong khung ảnh, màu đồng thau trên nền tối) và xuất:
  assets/logo.png (512), assets/logo.ico (nhiều cỡ), icon Android (mipmap: nền + lớp trước cho adaptive icon, và bản vuông bo góc).
Chạy: python tools/make_icons.py"""
import math
import os

from PIL import Image, ImageChops, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 4                                   # vẽ lớn gấp 4 rồi thu nhỏ cho mượt
BRASS_A, BRASS_B = (233, 197, 138), (169, 121, 61)
DARK_A, DARK_B = (42, 36, 27), (18, 15, 11)


def _bez(p0, p1, p2, p3, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def _grad(size, a, b):
    """Chuyển màu chéo từ góc trên trái (a) sang góc dưới phải (b)."""
    w, h = size
    g = Image.linear_gradient("L").resize((w, h))          # dọc
    gx = Image.linear_gradient("L").rotate(90).resize((w, h))   # ngang
    m = ImageChops.add(g, gx, scale=2)
    return Image.composite(Image.new("RGB", size, b), Image.new("RGB", size, a), m)


def mark_mask(size, scale=1.0):
    """Mặt nạ của biểu tượng (khung + chân dung) trên khung 512 x 512 quy ước, thu theo `scale` quanh tâm."""
    k = size / 512.0 * S * scale
    off = (size * S - 512 * k) / 2
    P = lambda x, y: (off + x * k, off + y * k)
    big = size * S
    m = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(m)
    # khung ảnh (viền bo góc)
    d.rounded_rectangle([P(104, 104), P(408, 408)], radius=46 * k, outline=255, width=int(18 * k))
    # chân dung = đầu + vai
    cx, cy, r = P(256, 214)[0], P(256, 214)[1], 54 * k
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    pts = [P(256, 262)] + _bez((256, 262), (204, 262), (166, 296), (158, 360))[1:]
    pts = [P(*p) if isinstance(p, tuple) and False else p for p in pts]
    poly = [P(256, 262)]
    poly += [P(*q) for q in _bez((256, 262), (204, 262), (166, 296), (158, 360))[1:]]
    poly += [P(354, 360)]
    poly += [P(*q) for q in _bez((354, 360), (346, 296), (308, 262), (256, 262))[1:]]
    d.polygon(poly, fill=255)
    # lỗ khóa (khoét)
    d.rounded_rectangle([P(244, 300), P(268, 352)], radius=12 * k, fill=0)
    cr = 15 * k
    cx2, cy2 = P(256, 300)
    d.ellipse([cx2 - cr, cy2 - cr, cx2 + cr, cy2 + cr], fill=0)
    return m.resize((size, size), Image.LANCZOS)


def logo(size, square=False, scale=1.0, with_bg=True):
    """Logo đầy đủ: nền tối bo góc kiểu icon app (square=True: nền vuông phủ kín cho adaptive icon) + biểu tượng đồng thau."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if with_bg:
        bg = _grad((size, size), DARK_A, DARK_B).convert("RGBA")
        if not square:
            mask = Image.new("L", (size * S, size * S), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * S - 1, size * S - 1], radius=112 / 512 * size * S, fill=255)
            bg.putalpha(mask.resize((size, size), Image.LANCZOS))
        img = bg
    brass = _grad((size, size), BRASS_A, BRASS_B).convert("RGBA")
    brass.putalpha(mark_mask(size, scale))
    return Image.alpha_composite(img, brass)


def main():
    assets = os.path.join(ROOT, "assets")
    os.makedirs(assets, exist_ok=True)
    big = logo(512)
    big.save(os.path.join(assets, "logo.png"))
    big.save(os.path.join(assets, "logo.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    res = os.path.join(ROOT, "android", "app", "src", "main", "res")
    for dens, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        d = os.path.join(res, f"mipmap-{dens}")
        os.makedirs(d, exist_ok=True)
        logo(px).save(os.path.join(d, "ic_launcher.png"))
        logo(px).save(os.path.join(d, "ic_launcher_round.png"))
        fg = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}[dens]
        logo(fg, with_bg=False, scale=0.62).save(os.path.join(d, "ic_launcher_foreground.png"))     # lớp trước: biểu tượng gọn trong vùng an toàn (66%)
    anyd = os.path.join(res, "mipmap-anydpi-v26")
    os.makedirs(anyd, exist_ok=True)
    for name in ("ic_launcher", "ic_launcher_round"):
        with open(os.path.join(anyd, name + ".xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                    '    <background android:drawable="@color/ic_launcher_background"/>\n'
                    '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n</adaptive-icon>\n')
    vals = os.path.join(res, "values")
    os.makedirs(vals, exist_ok=True)
    with open(os.path.join(vals, "ic_launcher_colors.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#1D1913</color>\n</resources>\n')


if __name__ == "__main__":
    main()

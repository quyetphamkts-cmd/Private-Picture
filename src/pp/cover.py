"""Ảnh đại diện của người: chỉ gương mặt (khuôn mặt đã cắt sẵn) hoặc bán thân (cắt rộng hơn quanh khuôn mặt từ ảnh nhỏ của ảnh, tỉ lệ 3:4)."""
import io
import os

from PIL import Image, ImageOps

from .secure import SEC


def bust_box(w, h, box, ratio=0.75):
    """Khung cắt bán thân (trái, trên, phải, dưới, điểm ảnh) quanh khuôn mặt `box` = (x, y, rộng, cao) chuẩn hóa 0–1; tỉ lệ rộng/cao = ratio."""
    x, y, bw, bh = box
    fw, fh = max(1.0, bw * w), max(1.0, bh * h)
    cx, fy = (x + bw / 2) * w, y * h
    cw = fw * 3.0                                  # rộng gấp ~3 lần mặt: lấy cả vai
    ch = cw / ratio
    if cw > w or ch > h:                           # ảnh nhỏ hơn khung muốn cắt: lấy khung lớn nhất cùng tỉ lệ
        k = min(w / cw, h / ch)
        cw, ch = cw * k, ch * k
    left = min(max(0.0, cx - cw / 2), w - cw)
    top = min(max(0.0, fy - fh * 0.45), h - ch)    # chừa một chút phía trên đầu
    return int(left), int(top), int(left + cw), int(top + ch)


def _open_full(src, want):
    im = Image.open(src)
    im.draft("RGB", (want, want))                      # JPEG: giải mã nhanh ở độ phân giải vừa đủ
    return ImageOps.exif_transpose(im).convert("RGB")


def _source(img_thumb_path, original=None, want=2600, fetch=None):
    """Ảnh nguồn để cắt, ưu tiên nét nhất: ảnh gốc trên ổ đĩa, rồi ảnh gốc lấy bằng fetch() (trong tệp nén / bản mã hóa trên Drive), cuối cùng mới là ảnh nhỏ của ảnh."""
    if original and not str(original).startswith("zip://") and os.path.isfile(original):
        try:
            return _open_full(original, want)
        except Exception:
            pass
    if fetch is not None:
        try:
            return _open_full(io.BytesIO(fetch()), want)
        except Exception:
            pass
    return Image.open(io.BytesIO(SEC.read_file(img_thumb_path))).convert("RGB")


def _crop_bytes(img_thumb_path, original, box, boxfn, out_w=520, fetch=None):
    try:
        im = _source(img_thumb_path, original, fetch=fetch)
        c = im.crop(boxfn(im.width, im.height, box))
        if c.width > out_w:
            c = c.resize((out_w, int(c.height * out_w / c.width)), Image.LANCZOS)
        out = io.BytesIO()
        c.save(out, "JPEG", quality=92, subsampling=0)
        return out.getvalue()
    except Exception:
        return None


def bust_bytes(img_thumb_path, box, original=None):
    """JPEG ảnh bán thân (cắt rộng quanh khuôn mặt, tỉ lệ 3:4); dùng ảnh gốc nếu có để nét. None nếu không đọc được."""
    return _crop_bytes(img_thumb_path, original, box, bust_box)


def full_bytes(img_thumb_path, box, original=None):
    """JPEG ảnh toàn thân (khung 3:4 lớn nhất quanh khuôn mặt); dùng ảnh gốc nếu có để nét. None nếu không đọc được."""
    return _crop_bytes(img_thumb_path, original, box, full_box)


def full_box(w, h, box, ratio=0.75):
    """Khung cắt TOÀN THÂN: khung 3:4 lớn nhất trong ảnh, đặt sao cho khuôn mặt nằm trong khung (khuôn mặt ở khoảng 1/5 phía trên)."""
    x, y, bw, bh = box
    cx, cy = (x + bw / 2) * w, (y + bh / 2) * h
    cw, ch = (h * ratio, float(h)) if w / h > ratio else (float(w), w / ratio)
    left = min(max(0.0, cx - cw / 2), w - cw)
    top = min(max(0.0, cy - ch * 0.2), h - ch)
    return int(left), int(top), int(left + cw), int(top + ch)


def _upto_box(w, h, box, mult, ratio=0.75):
    """Khung cắt 3:4 cao khoảng `mult` lần khuôn mặt (từ trên đầu xuống), mặt ở gần phía trên; không vượt ảnh."""
    x, y, bw, bh = box
    fh = max(1.0, bh * h)
    cx = (x + bw / 2) * w
    ch = min(float(h), fh * mult)
    cw = ch * ratio
    if cw > w:
        cw = float(w)
        ch = cw / ratio
    left = min(max(0.0, cx - cw / 2), w - cw)
    top = min(max(0.0, y * h - fh * 0.9), h - ch)          # chừa đỉnh đầu/tóc phía trên mặt
    return int(left), int(top), int(left + cw), int(top + ch)


def thigh_box(w, h, box, ratio=0.75):
    """Từ GIỮA ĐÙI lên (cao khoảng 6 lần khuôn mặt)."""
    return _upto_box(w, h, box, 6.0, ratio)


def navel_box(w, h, box, ratio=0.75):
    """Từ RỐN lên (cao khoảng 4 lần khuôn mặt)."""
    return _upto_box(w, h, box, 4.0, ratio)


def thigh_bytes(img_thumb_path, box, original=None, out_w=520, fetch=None):
    """JPEG ảnh từ giữa đùi lên; dùng ảnh gốc nếu có để nét. None nếu không đọc được."""
    return _crop_bytes(img_thumb_path, original, box, thigh_box, out_w, fetch)


def navel_bytes(img_thumb_path, box, original=None, out_w=520, fetch=None):
    """JPEG ảnh từ rốn lên; dùng ảnh gốc nếu có để nét. None nếu không đọc được."""
    return _crop_bytes(img_thumb_path, original, box, navel_box, out_w, fetch)

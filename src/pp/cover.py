"""Ảnh đại diện của người: chỉ gương mặt (khuôn mặt đã cắt sẵn) hoặc bán thân (cắt rộng hơn quanh khuôn mặt từ ảnh nhỏ của ảnh, tỉ lệ 3:4)."""
import io
import time
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


# ---------------------------------------------------------------- kho ảnh profile làm sẵn khi máy rảnh
POOL_W = 640
POOL_MAX = 40            # tối đa số ảnh làm sẵn cho mỗi người (đủ để đổi ảnh đại diện rất lâu mà không lặp)


def _pool_dir():
    from . import paths
    return paths.sub("cover_pool")


def pooled_bytes(db, fid, out_w=None):
    """Ảnh profile đã làm sẵn của một khuôn mặt (None nếu chưa có). out_w nhỏ hơn bản đã lưu thì thu nhỏ lại."""
    r = db.one("SELECT file FROM cover_render WHERE face_id=?", (fid,))
    if not r or not r["file"]:
        return None
    try:
        b = SEC.read_file(r["file"])
    except OSError:
        return None
    if out_w and out_w < POOL_W:
        try:
            im = Image.open(io.BytesIO(b))
            im = im.resize((out_w, int(im.height * out_w / im.width)), Image.LANCZOS)
            o = io.BytesIO()
            im.save(o, "JPEG", quality=92, subsampling=0)
            return o.getvalue()
        except Exception:
            return None
    return b


KIND = "thigh"            # ảnh profile LUÔN cắt từ GIỮA ĐÙI lên


def profile_cached(db, fid, img_thumb_path, box, original=None, out_w=520, fetch=None):
    """Ảnh profile (từ giữa đùi lên): dùng ảnh đã làm sẵn nếu có (không phải đọc lại ảnh gốc)."""
    if fid is not None:
        b = pooled_bytes(db, fid, out_w)
        if b:
            return b
    return thigh_bytes(img_thumb_path, box, original, out_w, fetch)


def render_pool_item(db, row, fetch=None):
    """Làm sẵn một ảnh profile (cắt từ rốn lên) và lưu mã hóa. Trả về True nếu thành công."""
    box = (row["x"], row["y"], row["w"], row["h"])
    b = thigh_bytes(row["thumb"], box, row["path"], POOL_W, fetch)
    if not b:
        db.x("INSERT OR REPLACE INTO cover_render(face_id,person_id,file,tried) VALUES(?,?,NULL,1)", (row["fid"], row["person_id"]))
        return False
    path = str(_pool_dir() / f"{row['fid']}-thigh.jpg")
    SEC.write_file(path, b)
    db.x("INSERT OR REPLACE INTO cover_render(face_id,person_id,file,tried) VALUES(?,?,?,1)", (row["fid"], row["person_id"], path))
    return True


def ensure_pool(db, stop=lambda: False, pause=lambda: None, fetch_for=None):
    """Khi máy rảnh: làm sẵn ảnh profile cho mọi người theo VÒNG: vòng 1 mỗi người một ảnh, vòng 2 thêm ảnh thứ hai, vòng 3 thêm ảnh thứ ba… cho tới hết ảnh hợp lệ
    của từng người (tối đa POOL_MAX). Trong mỗi người, ảnh đánh dấu sao được làm trước, rồi tới các ảnh thường. Ảnh hợp lệ = Naked, một người, nhìn thẳng thấy trọn mặt.
    Trả về số ảnh mới làm được."""
    from . import paths
    for r in db.q("SELECT face_id, file FROM cover_render WHERE face_id NOT IN (SELECT id FROM faces) OR (file IS NOT NULL AND file NOT LIKE '%-thigh.jpg')"):       # dọn ảnh của mặt đã biến mất và ảnh làm sẵn kiểu cũ (từ rốn lên)
        if r["file"]:
            try:
                os.remove(r["file"])
            except OSError:
                pass
        db.x("DELETE FROM cover_render WHERE face_id=?", (r["face_id"],))
    todo = {}
    for p in db.q("SELECT id FROM persons WHERE hidden=0"):
        cands = [dict(c, person_id=p["id"]) for c in db.cover_candidates(p["id"], KIND)][:POOL_MAX]
        have = {r["face_id"] for r in db.q("SELECT face_id FROM cover_render WHERE person_id=? AND tried=1", (p["id"],))}
        done = sum(1 for c in cands if c["fid"] in have)
        pending = [c for c in cands if c["fid"] not in have]
        if pending:
            todo[p["id"]] = [done, pending]
    made = 0
    while todo and not stop():
        progressed = False
        for pid in list(todo):
            if stop():
                break
            done, pending = todo[pid]
            if not pending:
                del todo[pid]
                continue
            pause()
            c = pending.pop(0)
            fetch = fetch_for({"id": c["iid"], "path": c["path"]}) if fetch_for else None
            if render_pool_item(db, c, fetch):
                made += 1
            progressed = True
            time.sleep(0.05)
        if not progressed:
            break
    return made

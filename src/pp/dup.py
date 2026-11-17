"""Phát hiện ảnh trùng lặp: cùng nội dung (kể cả bản thu nhỏ, nén lại) -> giữ bản tốt nhất, ẩn các bản thừa (không xóa tệp)."""
import io

import numpy as np
from PIL import Image

from .db import blob_to_vec
from .secure import SEC


def _dhash(thumb):
    try:
        rgb = Image.open(io.BytesIO(SEC.read_file(thumb))).convert("RGB")
    except Exception:
        return None
    mean = np.asarray(rgb.resize((1, 1), Image.BOX), np.int16).reshape(3)
    a = np.asarray(rgb.convert("L").resize((9, 8), Image.LANCZOS), np.int16)
    bits = (a[:, 1:] > a[:, :-1]).ravel()
    return int("".join("1" if b else "0" for b in bits), 2), mean


def _same(ha, hb, max_ham):
    """Hai ảnh cùng nội dung: dấu vân tay hình (dHash) gần nhau và màu trung bình không khác nhiều."""
    return bin(ha[0] ^ hb[0]).count("1") <= max_ham and int(np.abs(ha[1] - hb[1]).max()) <= 24


def _key(r):
    """Ảnh nào nên giữ: nhiều điểm ảnh nhất, rồi dung lượng lớn, ưu tiên tệp rời hơn trong file nén, đường dẫn ngắn."""
    return (-(r["w"] or 0) * (r["h"] or 0), -(r["size"] or 0), 1 if str(r["path"]).startswith("zip://") else 0, len(str(r["path"])), r["id"])


def find_groups(db, clip_thr=0.96, max_ham=8, progress=None):
    rows = db.q("SELECT id,path,w,h,size,thumb,clip FROM images WHERE thumb IS NOT NULL")
    n = len(rows)
    if n < 2:
        return []
    has_clip = [i for i, r in enumerate(rows) if r["clip"] is not None]
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    hashes = {}

    def h(i):
        if i not in hashes:
            hashes[i] = _dhash(rows[i]["thumb"])
        return hashes[i]
    # 1) cùng kích thước điểm ảnh và dung lượng, cùng dấu vân tay hình: bản sao y hệt (kể cả ảnh chưa có vectơ nội dung)
    same_meta = {}
    for i, r in enumerate(rows):
        if r["w"] and r["h"] and r["size"]:
            same_meta.setdefault((r["w"], r["h"], r["size"]), []).append(i)
    for idxs in same_meta.values():
        for k, a in enumerate(idxs):
            for b in idxs[k + 1:]:
                ha, hb = h(a), h(b)
                if ha is not None and hb is not None and _same(ha, hb, 4):
                    parent[find(a)] = find(b)
    # 2) giống nội dung (CLIP) và dấu vân tay hình gần nhau: bản thu nhỏ, nén lại, đổi định dạng
    if len(has_clip) >= 2:
        m = np.stack([blob_to_vec(rows[i]["clip"]) for i in has_clip]).astype(np.float32)
        m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        pos = np.array(has_clip)
        step = 1500
        for s in range(0, len(has_clip), step):
            sim = m[s:s + step] @ m.T
            ii, jj = np.nonzero(sim >= clip_thr)
            for a, b in zip(pos[ii + s], pos[jj]):
                if a >= b:
                    continue
                ha, hb = h(int(a)), h(int(b))
                if ha is not None and hb is not None and _same(ha, hb, max_ham):
                    parent[find(int(a))] = find(int(b))
            if progress:
                progress(min(len(has_clip), s + step), len(has_clip))
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(rows[i])
    out = []
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=_key)
        out.append({"keep": g[0]["id"], "members": [r["id"] for r in g]})
    out.sort(key=lambda x: -len(x["members"]))
    return out


def apply(db, groups):
    """Ghi lại danh sách ảnh ẩn (các bản thừa). Ảnh người dùng đã chọn bỏ ẩn thì không ẩn lại."""
    ignore = {r["image_id"] for r in db.q("SELECT image_id FROM dup_ignore")}
    db.c.execute("DELETE FROM dup_hidden")
    hidden = 0
    for g in groups:
        for i in g["members"]:
            if i != g["keep"] and i not in ignore:
                db.c.execute("INSERT OR REPLACE INTO dup_hidden(image_id,keep_id) VALUES(?,?)", (i, g["keep"]))
                hidden += 1
    db.commit()
    return hidden


def hidden_ids(db):
    return {r["image_id"] for r in db.q("SELECT image_id FROM dup_hidden")}


def restore(db, ids):
    for i in ids:
        db.c.execute("DELETE FROM dup_hidden WHERE image_id=?", (i,))
        db.c.execute("INSERT OR IGNORE INTO dup_ignore(image_id) VALUES(?)", (i,))
    db.commit()


def restore_all(db):
    db.c.execute("INSERT OR IGNORE INTO dup_ignore SELECT image_id FROM dup_hidden")
    db.c.execute("DELETE FROM dup_hidden")
    db.commit()


def set_keep(db, groups, keep_id):
    """Người dùng chọn ảnh giữ lại khác cho nhóm chứa keep_id."""
    for g in groups:
        if keep_id in g["members"]:
            g["keep"] = keep_id
            db.c.execute("DELETE FROM dup_ignore WHERE image_id IN (%s)" % ",".join("?" * len(g["members"])), g["members"])
            db.commit()
            return g
    return None


# ---------------------------------------------------------------- xóa bớt bản độ phân giải thấp (chuyển vào Thùng rác)
STRICT_CLIP, STRICT_HAM = 0.985, 4


def _trash(path):
    from send2trash import send2trash
    send2trash(path)


def deletable(db, groups):
    """Các bản thừa CHẮC CHẮN trùng với ảnh giữ lại (giống hơn mức ẩn thông thường), độ phân giải không cao hơn, là tệp rời trên ổ đĩa.
    Trả về [(id, đường dẫn, dung lượng)]."""
    import os
    out = []
    for g in groups:
        keep = db.one("SELECT id,path,w,h,vid,clip,thumb FROM images WHERE id=?", (g["keep"],))
        if not keep or keep["clip"] is None:
            continue
        kv = blob_to_vec(keep["clip"]).astype(np.float32)
        kv /= max(float(np.linalg.norm(kv)), 1e-9)
        kh = _dhash(keep["thumb"]) if keep["thumb"] else None
        if kh is None:
            continue
        for i in g["members"]:
            if i == g["keep"]:
                continue
            r = db.one("SELECT id,path,w,h,size,vid,clip,thumb FROM images WHERE id=?", (i,))
            if not r or r["vid"] or str(r["path"]).startswith("zip://") or r["clip"] is None or not os.path.isfile(r["path"]):
                continue
            if (r["w"] or 0) * (r["h"] or 0) > (keep["w"] or 0) * (keep["h"] or 0):
                continue                                      # không bao giờ xóa bản có độ phân giải cao hơn
            v = blob_to_vec(r["clip"]).astype(np.float32)
            v /= max(float(np.linalg.norm(v)), 1e-9)
            h = _dhash(r["thumb"]) if r["thumb"] else None
            if h is None or float(v @ kv) < STRICT_CLIP or not _same(kh, h, STRICT_HAM):
                continue
            out.append((r["id"], r["path"], r["size"] or 0))
    return out


def _same_pixels(pa, pb):
    """Hai tệp ảnh cùng kích thước điểm ảnh và MỌI điểm ảnh giống hệt nhau (so sánh toàn bộ, không dùng dấu vân tay)."""
    try:
        with Image.open(pa) as a, Image.open(pb) as b:
            if a.size != b.size:
                return False
            return bool(np.array_equal(np.asarray(a.convert("RGB")), np.asarray(b.convert("RGB"))))
    except Exception:
        return False


def exact_items(db, groups):
    """Bản thừa Y HỆT từng byte với ảnh giữ lại (cả hai là tệp rời trên ổ đĩa; bản thừa không có độ phân giải cao hơn). An toàn nhất để tự xóa.
    Trả về [(id, đường dẫn, dung lượng)]."""
    import hashlib
    import os
    out = []

    def digest(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.digest()
    for g in groups:
        keep = db.one("SELECT id,path,w,h,size,vid FROM images WHERE id=?", (g["keep"],))
        if not keep or keep["vid"] or str(keep["path"]).startswith("zip://") or not os.path.isfile(keep["path"]):
            continue                                          # bản giữ lại phải là tệp rời còn nguyên trên ổ đĩa
        kd = None
        for i in g["members"]:
            if i == g["keep"]:
                continue
            r = db.one("SELECT id,path,w,h,size,vid FROM images WHERE id=?", (i,))
            if not r or r["vid"] or str(r["path"]).startswith("zip://") or not os.path.isfile(r["path"]) or os.path.abspath(r["path"]) == os.path.abspath(keep["path"]):
                continue
            if (r["w"] or 0) * (r["h"] or 0) > (keep["w"] or 0) * (keep["h"] or 0):
                continue
            try:
                if os.path.getsize(r["path"]) == os.path.getsize(keep["path"]):
                    kd = kd or digest(keep["path"])
                    if digest(r["path"]) != kd and not _same_pixels(keep["path"], r["path"]):
                        continue                              # cùng dung lượng: y hệt byte, hoặc khác byte (siêu dữ liệu) nhưng từng điểm ảnh khớp hệt
                elif not _same_pixels(keep["path"], r["path"]):
                    continue                                  # khác dung lượng (nén khác, siêu dữ liệu): chỉ xóa khi TỪNG điểm ảnh giống hệt; bản giữ lại là bản tốt nhất
            except OSError:
                continue
            out.append((r["id"], r["path"], r["size"] or 0))
    return out


def trash_images(db, items):
    """Chuyển các tệp vào Thùng rác rồi xóa khỏi thư viện. Trả về (số tệp đã xóa, danh sách lỗi)."""
    from .scan import Scanner
    done, errors = [], []
    for iid, path, _ in items:
        try:
            _trash(path)
            done.append(iid)
        except Exception as e:
            errors.append(f"{path}: {e}")
    if done:
        Scanner(db)._drop(done)
        qs = ",".join("?" * len(done))
        db.x(f"DELETE FROM dup_hidden WHERE image_id IN ({qs})", done)
        db.x(f"DELETE FROM person_guess WHERE image_id IN ({qs})", done)
    return len(done), errors


def rekeep(db, group):
    """Chọn lại ảnh giữ lại (độ phân giải cao nhất) trong nhóm sau khi người dùng loại bớt ảnh."""
    qs = ",".join("?" * len(group["members"]))
    rows = db.q(f"SELECT id,path,w,h,size FROM images WHERE id IN ({qs})", group["members"])
    rows.sort(key=_key)
    group["members"] = [r["id"] for r in rows]
    group["keep"] = group["members"][0] if rows else None
    return group


def confirmed_items(db, groups):
    """Tất cả bản thừa của các nhóm đã được người dùng xem và xác nhận. Chỉ tệp rời trên ổ đĩa mới xóa được.
    Trả về (danh sách (id, đường dẫn, dung lượng), số ảnh bị bỏ qua vì nằm trong file nén hoặc Kho mã hóa)."""
    import os
    items, skipped = [], 0
    for g in groups:
        keep = db.one("SELECT w,h FROM images WHERE id=?", (g["keep"],))
        for i in g["members"]:
            if i == g["keep"]:
                continue
            r = db.one("SELECT id,path,w,h,size,vid FROM images WHERE id=?", (i,))
            if not r:
                continue
            if r["vid"] or str(r["path"]).startswith("zip://") or not os.path.isfile(r["path"]):
                skipped += 1
                continue
            if keep and (r["w"] or 0) * (r["h"] or 0) > (keep["w"] or 0) * (keep["h"] or 0):
                skipped += 1                                  # không bao giờ xóa bản có độ phân giải cao hơn bản giữ lại
                continue
            items.append((r["id"], r["path"], r["size"] or 0))
    return items, skipped

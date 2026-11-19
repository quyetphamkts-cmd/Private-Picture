"""Gom nhóm: mặt theo người, ảnh tương tự, tìm theo chữ hoặc theo ảnh mẫu."""
import json
import numpy as np

from .db import blob_to_vec, vec_to_blob


def auto_edit(fn):
    """Bước TỰ ĐỘNG của app (không phải người dùng sửa): thay đổi trong đó không ghi dấu thời gian 'sửa gần nhất' (xem DB.auto_edits)."""
    import functools

    @functools.wraps(fn)
    def w(db, *a, **k):
        with db.auto_edits():
            return fn(db, *a, **k)
    return w

FACE_THR = 0.45      # độ giống trung bình để gộp hai nhóm (0.363 của OpenCV dành cho so khớp 1-1, quá lỏng khi gom hàng nghìn ảnh)
MIN_FACE_PX = 40     # mặt nhỏ hơn thế này (điểm ảnh) quá mờ để gom đáng tin


def _unit(a):
    return a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-9)


# ---------------------------------------------------------------- đặc trưng bổ sung từ ảnh khuôn mặt
def _lab(rgb):
    """sRGB (0..1) -> CIE Lab."""
    c = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def face_attr(thumb):
    """Từ ảnh cắt mặt (có chừa lề 30%): màu da (vùng má, theo sắc độ a,b nên ít phụ thuộc ánh sáng), màu tóc (dải phía trên), độ nét.
    Mắt quá nhỏ ở ảnh thường nên không dùng. Trả về None nếu không đọc được."""
    import io
    from PIL import Image, ImageFilter
    from .secure import SEC
    try:
        im = Image.open(io.BytesIO(SEC.read_file(thumb))).convert("RGB").resize((64, 64), Image.BILINEAR)
    except Exception:
        return None
    a = np.asarray(im, np.float32) / 255.0
    lab = _lab(a)
    sk = lab[29:42, 21:43].reshape(-1, 3)
    sk = sk[(sk[:, 0] > 15) & (sk[:, 0] < 95)]
    g = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES), np.float32)[12:52, 12:52] / 255.0
    sharp = float(np.log1p(g.var() * 1000))
    if len(sk) < 8:
        return None
    s = np.median(sk, axis=0)
    band = lab[0:14, 14:50].reshape(-1, 3)                     # dải phía trên khuôn mặt: tóc (và một ít nền)
    de = np.linalg.norm(band - s, axis=1)
    hair = band[(de > 14) & (band[:, 0] < 93)]                  # bỏ điểm giống màu da và điểm trắng cháy sáng
    if len(hair) < 24:
        hair = band
    h = np.median(hair, axis=0)
    return (float(s[0]), float(s[1]), float(s[2]), float(h[0]), float(h[1]), float(h[2]), sharp)


ATTR_VERSION = 2          # tăng khi đổi cách tính đặc trưng (tự tính lại)


def _attrs(db, rows):
    if db.get_meta("face_attr_v") != str(ATTR_VERSION):
        db.x("DELETE FROM face_attr")
        db.set_meta("face_attr_v", ATTR_VERSION)
    cache = {r["face_id"]: tuple(r[k] for k in ("sk_l", "sk_a", "sk_b", "hr_l", "hr_a", "hr_b", "sharp")) for r in db.q("SELECT * FROM face_attr")}
    for r in rows:
        if r["id"] in cache or not r["thumb"]:
            continue
        v = face_attr(r["thumb"])
        if v is not None:
            cache[r["id"]] = v
            db.c.execute("INSERT OR REPLACE INTO face_attr(face_id,sk_l,sk_a,sk_b,hr_l,hr_a,hr_b,sharp) VALUES(?,?,?,?,?,?,?,?)", (r["id"], *v))
    db.commit()
    return cache


# ---------------------------------------------------------------- màu tóc và chữ cái đầu của tên (để lọc danh sách người rất dài)
HAIR = [("black", "Đen"), ("brown", "Nâu"), ("brunette", "Nâu sẫm"), ("blonde", "Vàng hoe"), ("red", "Đỏ, hung đỏ"), ("gray", "Bạc, trắng")]
HAIR_NAMES = dict(HAIR)


def hair_class(L, a, b):
    """Phân màu tóc từ màu Lab trung vị của vùng tóc. Chỉ là ước lượng gần đúng (vùng tóc nhỏ, nhuộm tóc và ánh sáng ảnh hưởng nhiều)."""
    chroma = float(np.hypot(a, b))
    if L < 24:
        return "black"
    if L > 55 and chroma < 9:
        return "gray"
    if a > 14 and b > 10 and 28 <= L <= 62:
        return "red"
    if L > 55 and b > 14:
        return "blonde"
    if L < 36:
        return "brunette"
    if L < 56:
        return "brown"
    return "blonde" if b > 8 else "gray"


def person_hair(db):
    """{id người: mã màu tóc} theo trung vị vùng tóc của các khuôn mặt thuộc người đó."""
    rows = db.q("SELECT f.person_id pid, a.hr_l l, a.hr_a a, a.hr_b b FROM faces f JOIN face_attr a ON a.face_id=f.id WHERE f.person_id IS NOT NULL")
    by = {}
    for r in rows:
        by.setdefault(r["pid"], []).append((r["l"], r["a"], r["b"]))
    return {pid: hair_class(*np.median(np.array(v, np.float32), axis=0)) for pid, v in by.items()}


def letter_key(name, given=False):
    """Chữ cái đầu để xếp A–Z: của cả họ tên (mặc định) hoặc của TÊN GỌI (từ cuối, theo cách gọi tiếng Việt). 'Đ' tính là D; không phải chữ: '#'."""
    toks = fold(name or "").split()
    if not toks:
        return "#"
    c = (toks[-1] if given else toks[0])[:1]
    return c.upper() if c.isalpha() and c.isascii() else "#"


def _penalty(a, b):
    """Phạt khi màu da hoặc màu tóc khác hẳn (0 nếu thiếu dữ liệu). a, b: bộ (sk_l, sk_a, sk_b, hr_l, hr_a, hr_b, sharp)."""
    if a is None or b is None:
        return 0.0
    skin = min(1.0, max(0.0, (float(np.hypot(a[1] - b[1], a[2] - b[2])) - 7.0) / 10.0))
    hair = min(1.0, max(0.0, (abs(a[3] - b[3]) - 28.0) / 30.0))
    return 0.20 * skin + 0.06 * hair


def _upgma(C, sizes, thr):
    """Gom theo liên kết trung bình (UPGMA): mỗi cặp nhóm chỉ gộp khi độ giống TRUNG BÌNH giữa mọi mặt của hai nhóm đủ cao
    (tránh hiện tượng 'bắc cầu' nối hai người khác nhau qua vài mặt mờ). Ô -1e9 là cấm gộp. Trả về danh sách chỉ số thuộc từng nhóm."""
    n = C.shape[0]
    C = C.astype(np.float32).copy()
    np.fill_diagonal(C, -1e9)
    sizes = sizes.astype(np.float32).copy()
    active = np.ones(n, bool)
    members = [[i] for i in range(n)]
    best = C.argmax(1)
    bestv = C[np.arange(n), best]
    while n > 1:
        a = int(bestv.argmax())
        if bestv[a] < thr:
            break
        b = int(best[a])
        sa, sb = sizes[a], sizes[b]
        row = (sa * C[a] + sb * C[b]) / (sa + sb)
        C[a, :] = row
        C[:, a] = row
        C[a, a] = -1e9
        C[b, :] = -1e9
        C[:, b] = -1e9
        active[b] = False
        bestv[b] = -1e9
        sizes[a] = sa + sb
        members[a] += members[b]
        members[b] = []
        stale = np.nonzero(active & ((best == a) | (best == b)))[0]
        if len(stale):
            best[stale] = C[stale].argmax(1)
            bestv[stale] = C[stale, best[stale]]
        better = active & (C[:, a] > bestv)
        best[better] = a
        bestv[better] = C[better, a]
        best[a] = int(C[a].argmax())
        bestv[a] = C[a, best[a]]
    return [m for m in members if m]


FACE_THR_BY_DIM = {128: 0.45, 512: 0.42}      # SFace (128 chiều) và ArcFace (512 chiều) có thang độ giống khác nhau
LEADER_BY_DIM = {128: 0.72, 512: 0.72}


def face_dim(db):
    """Số chiều vectơ khuôn mặt đang dùng: lấy số chiều của mô hình mới nhất đã quét (ưu tiên 512 nếu đã có)."""
    r = db.one("SELECT MAX(length(vec)) n FROM faces")
    return int((r["n"] or 512) // 4) if r and r["n"] else 512


def default_thr(db):
    return FACE_THR_BY_DIM.get(face_dim(db), FACE_THR)


# ---------------------------------------------------------------- tên người từ tên file nén
_STOP = {"high", "quality", "no", "watermark", "new", "folder", "photo", "photos", "image", "images", "download", "downloads", "pictures",
         "picture", "pic", "pics", "copy", "final", "backup", "archive", "scan", "hd", "full", "album", "video", "videos", "collection",
         "set", "pack", "raw", "original", "originals", "free", "best", "mix", "vol", "part", "the", "and", "of", "with", "for"}
_NOISE_TAIL = {"hd", "fullhd", "4k", "8k", "raw", "pack", "set", "photos", "photo", "pics"}


def fold(s):
    """Chữ thường, bỏ dấu tiếng Việt, gom khoảng trắng (để so khớp tên không phân biệt dấu/hoa thường)."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFD", str(s).replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def known_names(db):
    """Tập tên (đã gấp) của người đã đặt tên: để nhận ra nghệ danh có số như 'La Sirena 69' (số đó thuộc về tên, không phải số thứ tự tệp)."""
    return {fold(r["name"]) for r in db.q("SELECT name FROM persons WHERE name IS NOT NULL")}


def name_from_archive(path, known=None, keep_digits=False):
    """Tên người suy ra từ tên file nén (vd. 'Nguyen Van A.zip' -> 'Nguyen Van A'); None nếu tên file không giống tên người
    (từ chung như 'High Quality', 'Photos', ít hơn 2 hoặc nhiều hơn 5 từ...).
    Số ở cuối tên thường là số thứ tự tệp ('Anna Nguyen 02') nên bị bỏ, TRỪ khi `known` (tên người đã có) cho biết đó là nghệ danh có số
    ('La Sirena 69'), hoặc keep_digits=True (phần tên đứng trước dấu phân cách trong danh sách nhiều tên)."""
    import os
    import re
    base = os.path.basename(str(path).replace("\\", "/"))
    base = re.sub(r"(\.tar)?\.[A-Za-z0-9]{1,4}$", "", base)
    if len(_split_names(re.sub(r"\s*(\.{2,}|\u2026)\s*$", "", base.strip()))) > 1:
        return None                                                     # nhiều tên nối với nhau: không phải tên một người
    toks = re.sub(r"[_\-\.]+", " ", base).split()
    while toks and (toks[0].isdigit() or fold(toks[0]) in _NOISE_TAIL or (any(c.isdigit() for c in toks[0]) and len(toks) > 2)):      # bỏ mã ở đầu như '191777_hd'
        toks.pop(0)
    while toks:
        last = toks[-1]
        if fold(last) in _NOISE_TAIL:                                    # bỏ đuôi như 'hd'
            toks.pop()
        elif last.isdigit():
            if (keep_digits and len(last) <= 3 and len(toks) >= 3) or (known and fold(" ".join(toks)) in known):
                break                                                    # nghệ danh có số: giữ
            toks.pop()                                                   # số thứ tự tệp như '2024', '3'
        else:
            break
    while toks and (toks[0].isdigit() or fold(toks[0]) in _NOISE_TAIL or (any(c.isdigit() for c in toks[0]) and len(toks) > 2)):      # bỏ mã ở đầu như '191777_hd'
        toks.pop(0)
    if not 2 <= len(toks) <= 5:
        return None
    if any(not (t.replace("'", "").isalpha() or (i == len(toks) - 1 and i >= 1 and t.isdigit() and len(t) <= 3)) for i, t in enumerate(toks)) \
            or any(fold(t) in _STOP for t in toks):
        return None
    name = " ".join(toks)
    return name.title() if name.islower() else name


def _archive_of(path):
    body = str(path)[len("zip://"):]
    return body.split("!/", 1)[0]


def _consensus_identity(faces, img_arch, thr):
    """Từ các khuôn mặt ứng viên (lấy từ MỌI file nén mang tên một người): gom thành các danh tính (hai mặt cùng ảnh luôn khác người) rồi chọn
    danh tính xuất hiện ở NHIỀU FILE NÉN NHẤT (rồi nhiều ảnh nhất, rồi mặt lớn hơn). Một người lạ chỉ chụp chung ở một file không thể thắng.
    Trả về tâm danh tính hoặc None."""
    if not faces:
        return None
    V = _unit(np.stack([blob_to_vec(f["vec"]) for f in faces]).astype(np.float32))
    C = V @ V.T
    imgs = np.array([f["image_id"] for f in faces])
    C[imgs[:, None] == imgs[None, :]] = -1e9
    best, best_key, best_cen = None, None, None
    for g in _upgma(C, np.ones(len(faces)), thr):
        n_arch = len({img_arch.get(int(imgs[i])) for i in g})
        n_img = len({int(imgs[i]) for i in g})
        area = sum((faces[i]["w"] or 0) * (faces[i]["h"] or 0) for i in g)
        key = (n_arch, n_img, area)
        if best_key is None or key > best_key:
            best, best_key, best_cen = g, key, _unit(V[g].mean(axis=0))
    return best_cen


_SPLIT = None


def _split_names(base):
    """Tách theo từ nối giữa các tên: , ; & + / ' - ' and with feat ft vs x và với va (chỉ khi đứng riêng một từ; 'Mary-Jane' không bị tách)."""
    import re
    global _SPLIT
    if _SPLIT is None:
        _SPLIT = re.compile(r"\s*(?:&|\+|,|;|/|\s[-\u2013\u2014]\s|\b(?:va|và|and|with|với|feat\.?|ft\.?|vs\.?|x)\b)\s*", re.I)
    return [x.strip() for x in _SPLIT.split(re.sub(r"_+", " ", base)) if x and x.strip(" .\u2026")]


def _has_more(base):
    """Tên file kết thúc bằng '...' hoặc '…': còn những người khác chưa được ghi tên."""
    import re
    return bool(re.search(r"(\.{2,}|\u2026)\s*$", base.strip()))


def _names_in_base(base, known=None):
    """Tên (đã tách) trong tên file có nhiều người: 'Anna Nguyen & Bella Tran' hoặc 'Anna Nguyen, Bella Tran, ...' -> ['Anna Nguyen', 'Bella Tran']
    (mỗi phần phải giống tên người; phần '...' chỉ báo còn người khác chưa ghi tên, xem _has_more)."""
    import re
    base = re.sub(r"\s*(\.{2,}|\u2026)\s*$", "", base.strip())
    parts = _split_names(base)
    if len(parts) < 2:
        return []
    out = []
    for k, x in enumerate(parts):
        nm = name_from_archive(x.strip() + ".x", known, keep_digits=(k < len(parts) - 1))     # số trong phần không phải cuối thuộc về nghệ danh
        if not nm:
            t = re.sub(r"^(\d+\W*)+", "", x.strip())                  # tên ngắn một từ (3-4 ký tự…) chỉ nhận khi đứng trong danh sách có từ nối
            if t.replace("'", "").isalpha() and len(t) >= 3 and " " not in t and fold(t) not in _STOP and fold(t) not in _NOISE_TAIL:
                nm = t.title() if t.islower() else t
        if not nm:
            return []
        out.append(nm)
    return out


def archive_names(arch, known=None):
    """Danh sách tên (đã gấp dấu) ghi trên tên một tệp nén: nhiều tên, hoặc một tên."""
    import os
    import re
    base = re.sub(r"(\.tar)?\.[A-Za-z0-9]{1,4}$", "", os.path.basename(arch))
    names = _names_in_base(base, known)
    if not names:
        one = name_from_archive(arch, known)
        names = [one] if one else []
    return names


@auto_edit
def infer_names(db, min_arch=2, min_img=3, min_side=2, auto=False, auto_arch=3, auto_img=8):
    """Suy đoán tên cho các nhóm mặt CHƯA có tên, thận trọng vì một tệp nén có thể chứa nhiều người (kể cả người không ghi tên):
    - mỗi tệp: bỏ các tên đã có người riêng trong tệp (từ 2 ảnh), còn lại là 'tên chưa ai nhận' của tệp đó;
    - nhóm mặt phải xuất hiện ở ít nhất min_arch tệp mang tên; tên chung của MỌI tệp đó phải còn đúng một;
    - phải có ít nhất một tệp 'rõ ràng': trong tệp chỉ có đúng 1 tên chưa ai nhận, đúng 1 nhóm mặt chưa tên và tên tệp không có '...';
      hoặc nhóm xuất hiện ở từ 3 tệp trở lên mà vẫn chỉ ra đúng một tên;
    - nếu hai nhóm cùng nhận một tên thì không nhóm nào được gợi ý (không đủ chắc là nhóm nào).
    Chỉ là gợi ý (bảng person_suggest); người dùng xác nhận. Với auto=True, gợi ý rất mạnh (từ auto_arch tệp và auto_img ảnh trở lên) được tự đặt tên."""
    import re
    import os
    named_in = {}
    for r in db.q("""SELECT i.path path, p.name name, COUNT(DISTINCT i.id) n FROM faces f JOIN images i ON i.id=f.image_id
                     JOIN persons p ON p.id=f.person_id WHERE i.path LIKE 'zip://%' AND p.name IS NOT NULL GROUP BY i.path, p.id"""):
        k = (_archive_of(r["path"]), fold(r["name"]))
        named_in[k] = named_in.get(k, 0) + r["n"]
    kn = known_names(db)
    arch_names, more = {}, {}
    cl, per_arch = {}, {}                                    # nhóm -> {imgs, archs}; (tệp, nhóm) -> số ảnh
    for r in db.q("""SELECT f.person_id pid, i.id iid, i.path path FROM faces f JOIN images i ON i.id=f.image_id
                     JOIN persons p ON p.id=f.person_id WHERE i.path LIKE 'zip://%' AND p.name IS NULL"""):
        a = _archive_of(r["path"])
        if a not in arch_names:
            arch_names[a] = archive_names(a, kn)
            more[a] = _has_more(re.sub(r"(\.tar)?\.[A-Za-z0-9]{1,4}$", "", os.path.basename(a)))
        d = cl.setdefault(r["pid"], {"imgs": set(), "archs": set()})
        d["imgs"].add(r["iid"])
        d["archs"].add(a)
        per_arch.setdefault((a, r["pid"]), set()).add(r["iid"])
    face_imgs = {}                                           # tệp -> số ảnh có mặt (để biết một nhóm chiếm bao nhiêu phần của tệp)
    for r in db.q("SELECT i.path path, COUNT(DISTINCT i.id) n FROM images i WHERE i.path LIKE 'zip://%' AND i.id IN (SELECT image_id FROM faces) GROUP BY i.path"):
        a = _archive_of(r["path"])
        face_imgs[a] = face_imgs.get(a, 0) + r["n"]
    clusters_in = {}                                         # tệp -> số nhóm mặt chưa tên có ≥ min_side ảnh trong tệp
    for (a, pid), imgs in per_arch.items():
        if len(imgs) >= min_side:
            clusters_in[a] = clusters_in.get(a, 0) + 1
    db.c.execute("DELETE FROM person_suggest")
    cand_of, strong = {}, []
    for pid, d in cl.items():
        archs = [a for a in d["archs"] if arch_names.get(a)]
        if not archs or len(d["imgs"]) < min_img:
            continue
        cand, shown, clean = None, {}, False
        for a in archs:
            ns = {fold(n): n for n in arch_names[a] if named_in.get((a, fold(n)), 0) < 2}
            shown.update(ns)
            cand = set(ns) if cand is None else cand & set(ns)
            if len(ns) == 1 and clusters_in.get(a, 0) == 1 and not more[a]:
                clean = True
        solo_ok = False                                      # một tệp duy nhất vẫn đủ khi loại trừ cho ra đúng một tên và đúng một nhóm chiếm phần lớn tệp
        if len(archs) == 1:
            a = archs[0]
            solo_ok = clean and len(d["imgs"]) >= 4 and len(d["imgs"]) >= 0.5 * max(1, face_imgs.get(a, 1))
        if cand and len(cand) == 1 and ((len(archs) >= min_arch and (clean or len(archs) >= 3)) or solo_ok):
            k = next(iter(cand))
            cand_of[pid] = (k, shown[k], len(archs), len(d["imgs"]))
    count = {}
    for k, *_ in cand_of.values():
        count[k] = count.get(k, 0) + 1
    out = 0
    for pid, (k, nm, na, ni) in cand_of.items():
        if count[k] == 1:
            db.c.execute("INSERT OR REPLACE INTO person_suggest VALUES(?,?,?,?)", (pid, nm, na, ni))
            out += 1
            if auto and na >= auto_arch and ni >= auto_img:
                strong.append((pid, nm))
    db.commit()
    try:
        out += infer_names_by_photo(db)                      # thêm căn cứ từ ảnh chụp chung với người đã có tên
    except Exception:
        pass
    for pid, nm in strong:                                   # bằng chứng rất mạnh (nhiều tệp cùng chỉ ra một tên): tự đặt tên, không bắt làm tay
        if not db.one("SELECT name FROM persons WHERE id=?", (pid,))["name"]:
            rename_person(db, pid, nm)
            db.x("DELETE FROM person_suggest WHERE person_id=?", (pid,))
    return out


@auto_edit
def demote_extra_names(db):
    """Một ảnh chỉ có MỘT người (một khuôn mặt, đã thuộc một người) thì chỉ mang MỘT tên: tên khác do app tự gán thêm (đề xuất đã nhận từ tên tệp nén...) chuyển thành
    tên DỰ PHÒNG (đề xuất chưa xác nhận); chỉ khi người dùng bảo tên đầu không đúng thì mới tính tới tên dự phòng. Ảnh có nhiều người thì giữ nhiều tên.
    Trả về số tên đã chuyển thành dự phòng."""
    cur = db.c.execute("""UPDATE person_guess SET state=0 WHERE state=2
        AND image_id IN (SELECT image_id FROM faces GROUP BY image_id HAVING COUNT(*)=1 AND MAX(person_id) IS NOT NULL)
        AND person_id<>(SELECT f.person_id FROM faces f WHERE f.image_id=person_guess.image_id)""")
    db.commit()
    return cur.rowcount or 0


@auto_edit
def claim_single_name_archives(db):
    """Tệp nén chỉ mang tên MỘT người: coi toàn bộ ảnh trong tệp là của người đó (kể cả ảnh không thấy mặt hoặc mặt không khớp rõ).
    Ảnh nào người dùng đã loại khỏi người này (state=1) thì tôn trọng, không thêm lại. Trả về số ảnh được thêm."""
    named = {fold(p["name"]): p["id"] for p in db.q("SELECT id,name FROM persons WHERE name IS NOT NULL")}
    kn = set(named)
    by_arch = {}
    for r in db.q("SELECT id,path FROM images WHERE path LIKE 'zip://%'"):
        by_arch.setdefault(_archive_of(r["path"]), []).append(r["id"])
    n = 0
    for arch, ids in by_arch.items():
        names = archive_names(arch, kn)
        if len(names) != 1 or fold(names[0]) not in named:
            continue
        pid = named[fold(names[0])]
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            qs = ",".join("?" * len(part))
            have = {r["image_id"] for r in db.q(f"SELECT image_id FROM faces WHERE person_id=? AND image_id IN ({qs})", [pid, *part])}
            seen = {r["image_id"]: r["state"] for r in db.q(f"SELECT image_id,state FROM person_guess WHERE person_id=? AND image_id IN ({qs})", [pid, *part])}
            for iid in part:
                if iid in have or seen.get(iid) == 1:
                    continue
                if seen.get(iid) != 2:
                    db.c.execute("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,1.0,2)", (iid, pid))
                    n += 1
    db.commit()
    demote_extra_names(db)                                     # ảnh một người đã có tên từ khuôn mặt: tên theo tệp nén chỉ là dự phòng
    return n


def _mashup_people(db, min_person_imgs=2):
    """Mỗi ảnh có từ 2 người trở lên (đã loại bóng gương, ảnh trùng đã ẩn): trả về (nhãn từng người, {mã ảnh: tập mã người})."""
    label = {}
    count = {}
    for p in db.q("""SELECT p.id id, p.name name, (SELECT name FROM person_suggest s WHERE s.person_id=p.id) sg,
                     (SELECT COUNT(DISTINCT image_id) FROM faces WHERE person_id=p.id) n FROM persons p WHERE p.hidden=0"""):
        count[p["id"]] = p["n"]
        label[p["id"]] = p["name"] or (f"Có thể là {p['sg']}" if p["sg"] else f"Chưa đặt tên #{p['id']}")
    per_img = {}
    for r in db.q("SELECT image_id iid, person_id pid FROM faces WHERE person_id IS NOT NULL AND image_id NOT IN (SELECT image_id FROM dup_hidden)"):
        if r["pid"] in label and count.get(r["pid"], 0) >= min_person_imgs:
            per_img.setdefault(r["iid"], set()).add(r["pid"])
    cand = [i for i, ps in per_img.items() if len(ps) >= 2]
    for k in range(0, len(cand), 400):                          # loại ảnh chỉ có MỘT người thật: khuôn mặt thứ hai là bóng trong gương / phản chiếu / mặt bị tách đôi
        chunk = cand[k:k + 400]
        faces = {}
        for r in db.q(f"SELECT image_id iid, person_id pid, h, score, vec FROM faces WHERE person_id IS NOT NULL AND image_id IN ({','.join('?' * len(chunk))})", chunk):
            if r["pid"] in per_img[r["iid"]] and r["vec"] is not None:
                faces.setdefault(r["iid"], []).append((r["h"] or 0.0, r["score"] or 0.0, r["pid"], blob_to_vec(r["vec"])))
        for iid, fl in faces.items():
            fl.sort(key=lambda t: -t[0] * t[1])                 # mặt lớn, rõ trước
            kept = []
            for h, sc, pid, v in fl:
                n = float(np.linalg.norm(v)) or 1.0
                v = v / n
                if any(kp != pid and float(np.dot(v, kv)) >= 0.5 for kp, kv in kept):
                    continue                                     # giống hệt một người đã có trong ảnh: cùng một người (bóng gương)
                if kept and h < 0.3 * fl[0][0]:
                    continue                                     # mặt quá nhỏ so với mặt chính: thường là ảnh phản chiếu / áp phích phía sau
                kept.append((pid, v))
            per_img[iid] = {kp for kp, _ in kept}
    return label, {i: ps for i, ps in per_img.items() if len(ps) >= 2}


MASHUP_DEFAULTS = {"min_score": 0.9, "small_ratio": 0.3, "same_thr": 0.5}
BODY_MIN_SCORE = 0.55          # người (cả thân) phát hiện với độ tin cậy từ mức này mới tính
BODY_MIN_H = 0.18              # và cao ít nhất chừng này so với chiều cao ảnh (bỏ người quá nhỏ ở xa / hình trên áp phích nhỏ)
FACE_STRONG = 0.95             # mặt không nằm trong người nào: chỉ tính nếu điểm nhận diện rất cao


def mashup_params(db):
    """Ngưỡng đếm người: mặc định, hoặc giá trị đã tự hiệu chỉnh theo thư viện (calibrate_mashup)."""
    out = dict(MASHUP_DEFAULTS)
    for k in out:
        v = db.get_meta("mashup_" + k)
        if v:
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out


def _dedupe_faces(fl, min_score, small_ratio, same_thr):
    """Mặt của MỘT ảnh -> các mặt 'thật' (bỏ mặt quá nhỏ so với mặt chính; hai mặt giống hệt nhau như bóng gương chỉ tính một). fl: [(diện tích, vectơ, điểm, tâm x, tâm y)]."""
    fl = sorted((f for f in fl if f[2] >= min_score), key=lambda t: -t[0])
    kept = []
    for f in fl:
        if kept and f[0] < small_ratio * fl[0][0]:
            continue
        v = _unit(f[1])
        if any(float(v @ k[1]) >= same_thr for k in kept):
            continue
        kept.append((f[0], v, f[2], f[3], f[4]))
    return kept


def fuse_count(kept, all_faces, bodies):
    """Số người trong ảnh = ghép KHUÔN MẶT với NGƯỜI (cả thân) phát hiện được:
    - mặt thật nằm trong một người được xác nhận; mỗi mặt thật là một người;
    - người không có khuôn mặt nào (quay lưng, che mặt) vẫn được tính, trừ khi trong khung người đó có một mặt đã bị loại (bóng gương, áp phích);
    - mặt thật không nằm trong người nào (mặt cận cảnh, thân bị cắt) chỉ tính nếu điểm nhận diện rất cao."""
    def inside(cx, cy, b):
        x, y, w, h = b[:4]
        return x - 0.05 * w <= cx <= x + w * 1.05 and y - 0.05 * h <= cy <= y + h * 1.05
    bodies = [b for b in bodies if b[4] >= BODY_MIN_SCORE and b[3] >= BODY_MIN_H]
    n_faces_in = sum(1 for f in kept if any(inside(f[3], f[4], b) for b in bodies))
    n_body_only = sum(1 for b in bodies if not any(inside(f[3], f[4], b) for f in all_faces))
    n_face_only = sum(1 for f in kept if f[2] >= FACE_STRONG and not any(inside(f[3], f[4], b) for b in bodies))
    return n_faces_in + n_body_only + n_face_only


def mashup_counts(db, params=None):
    """{mã ảnh: số người} cho ảnh có từ 2 người trở lên (đã bỏ ảnh trùng đã ẩn). Đếm theo khuôn mặt thật; nếu ảnh đã có dữ liệu phát hiện người (bảng image_body) thì ghép cả hai."""
    p = params or mashup_params(db)
    dim = face_dim(db)
    hidden = {r["image_id"] for r in db.q("SELECT image_id FROM dup_hidden")}
    bodies = {}
    for r in db.q("SELECT image_id, boxes FROM image_body"):
        try:
            bodies[r["image_id"]] = json.loads(r["boxes"] or "[]")
        except ValueError:
            bodies[r["image_id"]] = []
    ids = {r["image_id"] for r in db.q("""SELECT image_id FROM faces WHERE px>=? AND vec IS NOT NULL GROUP BY image_id HAVING COUNT(*)>=2""", (MIN_FACE_PX,))}
    ids |= {i for i, bl in bodies.items() if sum(1 for b in bl if b[4] >= BODY_MIN_SCORE and b[3] >= BODY_MIN_H) >= 2}          # nhiều người quay lưng, ít mặt
    ids = [i for i in ids if i not in hidden]
    out = {}
    for k in range(0, len(ids), 400):
        chunk = ids[k:k + 400]
        by = {}
        for r in db.q(f"SELECT image_id iid, x, y, w, h, score, vec FROM faces WHERE px>=? AND vec IS NOT NULL AND image_id IN ({','.join('?' * len(chunk))})",
                      [MIN_FACE_PX, *chunk]):
            if len(r["vec"]) == dim * 4:
                by.setdefault(r["iid"], []).append(((r["w"] or 0.0) * (r["h"] or 0.0), blob_to_vec(r["vec"]).astype(np.float32), r["score"] or 0.0,
                                                    (r["x"] or 0.0) + (r["w"] or 0.0) / 2, (r["y"] or 0.0) + (r["h"] or 0.0) / 2))
        for iid in chunk:
            fl = by.get(iid, [])
            kept = _dedupe_faces(fl, p["min_score"], p["small_ratio"], p["same_thr"])
            n = fuse_count(kept, fl, bodies[iid]) if iid in bodies else len(kept)
            if n >= 2:
                out[iid] = n
    return out


def mashup_by_count(db, min_score=None, same_thr=None, small_ratio=None):
    """Mashup chia theo SỐ NGƯỜI trong ảnh: {số người: [mã ảnh]} (từ 2 người trở lên). Xem mashup_counts."""
    p = mashup_params(db)
    for k, v in (("min_score", min_score), ("same_thr", same_thr), ("small_ratio", small_ratio)):
        if v is not None:
            p[k] = v
    out = {}
    for iid, n in mashup_counts(db, p).items():
        out.setdefault(n, []).append(iid)
    return out


def calibrate_mashup(db, min_images=150):
    """Tự hiệu chỉnh ngưỡng đếm mặt bằng số NGƯỜI phát hiện được làm chuẩn đối chiếu: thử các tổ hợp ngưỡng điểm mặt và tỉ lệ mặt nhỏ, chọn tổ hợp ít đếm thừa nhất
    (đếm thiếu bị phạt nhẹ hơn vì người quay lưng không có mặt). Ghi vào cài đặt; trả về ngưỡng đã chọn hoặc None nếu chưa đủ dữ liệu."""
    dim = face_dim(db)
    ref = {}
    for r in db.q("SELECT image_id, boxes FROM image_body WHERE n>=1"):
        try:
            bl = [b for b in json.loads(r["boxes"] or "[]") if b[4] >= BODY_MIN_SCORE and b[3] >= BODY_MIN_H]
        except ValueError:
            continue
        if 1 <= len(bl) <= 8:
            ref[r["image_id"]] = len(bl)
    if len(ref) < min_images:
        return None
    ids = list(ref)
    data = {}
    for k in range(0, len(ids), 400):
        chunk = ids[k:k + 400]
        for r in db.q(f"SELECT image_id iid, w, h, score, vec FROM faces WHERE px>=? AND vec IS NOT NULL AND image_id IN ({','.join('?' * len(chunk))})", [MIN_FACE_PX, *chunk]):
            if len(r["vec"]) == dim * 4:
                data.setdefault(r["iid"], []).append(((r["w"] or 0.0) * (r["h"] or 0.0), blob_to_vec(r["vec"]).astype(np.float32), r["score"] or 0.0, 0.0, 0.0))
    best = None
    for ms in (0.8, 0.85, 0.9, 0.95):
        for sr in (0.15, 0.2, 0.3, 0.4):
            loss = 0.0
            for iid, n_ref in ref.items():
                n = len(_dedupe_faces(data.get(iid, []), ms, sr, MASHUP_DEFAULTS["same_thr"]))
                loss += max(0, n - n_ref) * 1.0 + max(0, n_ref - n) * 0.4
            if best is None or loss < best[0] - 1e-9:
                best = (loss, ms, sr)
    db.set_meta("mashup_min_score", str(best[1]))
    db.set_meta("mashup_small_ratio", str(best[2]))
    return {"min_score": best[1], "small_ratio": best[2], "images": len(ref), "loss": round(best[0], 1)}


def ensure_bodies(db, engine, stop=lambda: False, batch=40, limit=None, read=None):
    """Phát hiện người (cả thân) cho các ảnh chưa có dữ liệu, đọc từ ảnh nhỏ đã lưu (nhanh). Lưu vào image_body. Trả về số ảnh đã xử lý."""
    from PIL import Image, ImageOps
    import io
    if read is None:
        from .secure import SEC
        read = SEC.read_file
    rows = db.q("SELECT id, thumb FROM images WHERE thumb IS NOT NULL AND id NOT IN (SELECT image_id FROM image_body) ORDER BY id")
    n = 0
    for r in rows:
        if stop() or (limit is not None and n >= limit):
            break
        try:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(read(r["thumb"])))).convert("RGB")
            res = engine.detect(np.asarray(im))
            boxes = [[round(d["box"][0], 4), round(d["box"][1], 4), round(d["box"][2], 4), round(d["box"][3], 4), round(d["score"], 3)] for d in res]
            db.c.execute("INSERT OR REPLACE INTO image_body(image_id,n,boxes) VALUES(?,?,?)", (r["id"], len(boxes), json.dumps(boxes)))
        except Exception:
            db.c.execute("INSERT OR REPLACE INTO image_body(image_id,n,boxes) VALUES(?,0,'[]')", (r["id"],))
        n += 1
        if n % batch == 0:
            db.commit()
    db.commit()
    return n


def photo_combos(db, min_photos=2, min_person_imgs=2):
    """Mashup: ảnh chụp KẾT HỢP từ 2 người trở lên trong cùng một tấm ảnh (không phải ảnh cá nhân từng người), KỂ CẢ người chưa có tên.
    Gom theo tổ hợp người; người chưa đặt tên hiện là 'Chưa đặt tên #mã' (hoặc 'Có thể là …' nếu app đã đề xuất tên). Một người chỉ tính khi có từ
    min_person_imgs ảnh (bớt nhóm 1 ảnh gây nhiễu); tổ hợp dưới min_photos ảnh thì ẩn.
    Trả về [{names, ids:[mã ảnh], n, persons:[mã người]}] xếp theo số ảnh giảm dần."""
    label, per_img = _mashup_people(db, min_person_imgs)
    combos = {}
    for iid, pids in per_img.items():
        if len(pids) < 2:
            continue
        key = tuple(sorted(pids))
        c = combos.setdefault(key, {"persons": list(key), "names": [label[k] for k in key], "ids": []})
        c["ids"].append(iid)
    out = []
    for c in combos.values():
        c["n"] = len(c["ids"])
        if c["n"] >= min_photos:
            out.append(c)
    return sorted(out, key=lambda c: (-c["n"], c["names"]))


@auto_edit
def apply_refs(db, warn_thr=0.30, name_thr=0.50, boost=0.10, min_faces=5):
    """Dùng ảnh tham chiếu (vectơ lấy từ internet, bảng person_ref) để: (1) cảnh báo nhóm mang tên X mà khuôn mặt (trung vị) khác xa ảnh tham chiếu của X,
    (2) gợi ý tên cho nhóm chưa có tên giống ảnh tham chiếu của một người đã biết, (3) tăng độ chắc cho đề xuất có khuôn mặt khớp ảnh tham chiếu.
    Không tự sửa gì: chỉ ghi cảnh báo (ref_flag), ứng viên (person_candidates) và điểm đề xuất. Trả về (số cảnh báo, số gợi ý tên)."""
    dim = face_dim(db)
    cen = {}
    for r in db.q("SELECT person_id,vec FROM person_ref WHERE dim=?", (dim,)):
        cen.setdefault(r["person_id"], []).append(blob_to_vec(r["vec"]))
    cen = {p: _unit(np.mean(_unit(np.stack(v).astype(np.float32)), axis=0)) for p, v in cen.items() if len(v) >= 3}
    if not cen:
        return 0, 0
    names = {r["id"]: r["name"] for r in db.q("SELECT id,name FROM persons WHERE hidden=0")}
    db.c.execute("DELETE FROM ref_flag")
    flags = 0
    suggested = 0
    for pid, c in cen.items():                                                   # (1) cảnh báo gán nhầm tên
        if not names.get(pid):
            continue
        vs = [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM faces WHERE person_id=? AND vec IS NOT NULL", (pid,)) if len(r["vec"]) == dim * 4]
        if len(vs) >= min_faces:
            sims = _unit(np.stack(vs).astype(np.float32)) @ c
            med = float(np.median(sims))
            if med < warn_thr:
                db.c.execute("INSERT OR REPLACE INTO ref_flag(person_id,sim,n) VALUES(?,?,?)", (pid, med, len(vs)))
                flags += 1
    for p in db.q("SELECT id FROM persons WHERE name IS NULL AND hidden=0"):       # (2) gợi ý tên cho nhóm chưa có tên
        vs = [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM faces WHERE person_id=? AND vec IS NOT NULL", (p["id"],)) if len(r["vec"]) == dim * 4]
        if len(vs) < 2:
            continue
        mc = _unit(np.mean(_unit(np.stack(vs).astype(np.float32)), axis=0))
        ranked = sorted(((float(mc @ c), q) for q, c in cen.items() if names.get(q)), reverse=True)[:2]
        if ranked and ranked[0][0] >= name_thr and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.05):
            for sc, q in ranked[:1]:
                db.c.execute("INSERT OR REPLACE INTO person_candidates(person_id,name,score) VALUES(?,?,?)", (p["id"], names[q], sc))
                suggested += 1
    for g in db.q("SELECT image_id,person_id,score FROM person_guess WHERE state=0"):  # (3) tăng độ chắc cho đề xuất
        c = cen.get(g["person_id"])
        if c is None:
            continue
        vs = [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM faces WHERE image_id=? AND vec IS NOT NULL", (g["image_id"],)) if len(r["vec"]) == dim * 4]
        if vs and float(np.max(_unit(np.stack(vs).astype(np.float32)) @ c)) >= name_thr:
            db.c.execute("UPDATE person_guess SET score=? WHERE image_id=? AND person_id=? AND state=0", (min(1.0, (g["score"] or 0) + boost), g["image_id"], g["person_id"]))
    db.commit()
    return flags, suggested


@auto_edit
def infer_candidates(db, top=3, min_imgs=2):
    """Với người chưa có tên mà app CHƯA đủ chắc để đề xuất (không có trong person_suggest): liệt kê tối đa `top` tên có khả năng nhất để người dùng xem ảnh rồi chọn.
    Căn cứ: các tên ghi trên tệp nén chứa ảnh của người đó (trừ tên đã có người riêng trong tệp); mỗi tệp chia đều điểm cho các tên còn lại, cộng dồn theo số ảnh.
    Điểm = phần trăm ảnh của người đó ủng hộ tên ấy. Ghi vào bảng person_candidates (xóa và tính lại mỗi lần). Trả về số người có ứng viên."""
    import re
    import os
    kn = known_names(db)
    named_in = {}
    for r in db.q("""SELECT i.path path, p.name name, COUNT(DISTINCT i.id) n FROM faces f JOIN images i ON i.id=f.image_id
                     JOIN persons p ON p.id=f.person_id WHERE i.path LIKE 'zip://%' AND p.name IS NOT NULL GROUP BY i.path, p.id"""):
        k = (_archive_of(r["path"]), fold(r["name"]))
        named_in[k] = named_in.get(k, 0) + r["n"]
    cache = {}
    per = {}                                                    # người -> {tệp: số ảnh}
    for r in db.q("""SELECT f.person_id pid, i.path path, COUNT(DISTINCT i.id) n FROM faces f JOIN images i ON i.id=f.image_id
                     JOIN persons p ON p.id=f.person_id WHERE i.path LIKE 'zip://%' AND p.name IS NULL AND p.hidden=0
                     GROUP BY f.person_id, i.path"""):
        a = _archive_of(r["path"])
        d = per.setdefault(r["pid"], {})
        d[a] = d.get(a, 0) + r["n"]
    suggested = {r["person_id"] for r in db.q("SELECT person_id FROM person_suggest")}
    db.c.execute("DELETE FROM person_candidates")
    made = 0
    for pid, archs in per.items():
        total = sum(archs.values())
        if pid in suggested or total < min_imgs:
            continue
        score = {}
        for a, c in archs.items():
            if a not in cache:
                cache[a] = archive_names(a, kn)
            names = [n for n in cache[a] if named_in.get((a, fold(n)), 0) < 2]
            for n in names:
                score[n] = score.get(n, 0.0) + c / len(names)
        ranked = sorted(score.items(), key=lambda kv: -kv[1])[:top]
        for n, sc in ranked:
            db.c.execute("INSERT OR REPLACE INTO person_candidates VALUES(?,?,?)", (pid, n, sc / total))
        made += 1 if ranked else 0
    db.commit()
    return made


def infer_names_by_photo(db, min_imgs=3, agree=0.8):
    """Suy tên từ ảnh chụp chung: trong một ảnh đã có người có tên thì người còn lại phải là một trong các tên khác ghi trên tên tệp nén
    (tên trên tệp trừ những người đã nhận ra ngay trong ảnh đó). Nhóm chưa tên mà phần lớn ảnh của nó cùng chỉ ra MỘT tên thì đề xuất tên đó
    (chỉ ghi gợi ý, không tự đặt tên; không ghi đè gợi ý sẵn có). Trả về số gợi ý mới."""
    kn = known_names(db)
    img_people = {}
    for r in db.q("""SELECT f.image_id iid, f.person_id pid, p.name name, i.path path FROM faces f JOIN persons p ON p.id=f.person_id
                     JOIN images i ON i.id=f.image_id WHERE i.path LIKE 'zip://%' AND p.hidden=0"""):
        d = img_people.setdefault(r["iid"], {"path": r["path"], "named": set(), "unnamed": set()})
        if r["name"]:
            d["named"].add(fold(r["name"]))
        else:
            d["unnamed"].add(r["pid"])
    cache = {}
    votes = {}                                                  # nhóm chưa tên -> {tên: số ảnh ủng hộ}, tổng số ảnh có căn cứ
    seen = {}
    for iid, d in img_people.items():
        if not d["unnamed"] or len(d["unnamed"]) > 1 or not d["named"]:
            continue                                            # chỉ dùng ảnh có đúng 1 người chưa tên cùng với người đã có tên: suy ra chắc nhất
        a = _archive_of(d["path"])
        if a not in cache:
            cache[a] = {fold(n): n for n in archive_names(a, kn)}
        cand = {k: v for k, v in cache[a].items() if k not in d["named"]}
        if not cand:
            continue
        pid = next(iter(d["unnamed"]))
        seen[pid] = seen.get(pid, 0) + 1
        v = votes.setdefault(pid, {})
        for k, nm in cand.items():
            v[nm] = v.get(nm, 0) + 1
    made = 0
    for pid, v in votes.items():
        n = seen.get(pid, 0)
        if n < min_imgs or db.one("SELECT 1 FROM person_suggest WHERE person_id=?", (pid,)):
            continue
        ranked = sorted(v.items(), key=lambda kv: -kv[1])
        best, second = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0)
        if best[1] >= agree * n and second < 0.5 * best[1]:
            db.c.execute("INSERT OR REPLACE INTO person_suggest VALUES(?,?,?,?)", (pid, best[0], 1, n))
            made += 1
    db.commit()
    return made


@auto_edit
def assign_by_session(db, gap_min=40, min_known=3, dominance=0.8, share=0.35, floor=0.62):
    """Chia ảnh thành các BUỔI CHỤP (cùng thư mục hoặc tệp nén, giờ chụp liên tiếp cách nhau không quá gap_min phút) rồi gợi ý người cho các ảnh
    chưa rõ người trong buổi đó, như Google Ảnh: nếu phần lớn ảnh đã nhận ra của buổi là cùng một người (từ `dominance` trở lên) thì ảnh còn lại
    của buổi nhiều khả năng cũng là người đó; buổi có hai ba người nổi bật (mỗi người từ `share`) thì gợi ý cho từng người.
    Mỗi gợi ý còn phải giống các ảnh đã biết của người đó (CLIP >= floor) nên ảnh lạ trong buổi không bị gán nhầm. Chỉ ghi gợi ý
    (person_guess state 0) cho người dùng duyệt; không ghi đè gợi ý đã có, đã xác nhận hay đã loại. Trả về số gợi ý mới."""
    import os
    rows = db.q("SELECT id,path,taken,clip FROM images WHERE taken IS NOT NULL AND thumb IS NOT NULL AND vid IS NULL ORDER BY taken")
    if not rows:
        return 0
    named = {r["id"] for r in db.q("SELECT id FROM persons WHERE name IS NOT NULL AND hidden=0")}
    if not named:
        return 0
    img_named, has_face = {}, set()
    for r in db.q("SELECT image_id iid, person_id pid FROM faces WHERE person_id IS NOT NULL"):
        has_face.add(r["iid"])
        if r["pid"] in named:
            img_named.setdefault(r["iid"], set()).add(r["pid"])
    groups = {}
    for r in rows:
        key = _archive_of(r["path"]) if str(r["path"]).startswith("zip://") else os.path.dirname(str(r["path"]))
        groups.setdefault(key, []).append(r)
    sessions = []
    for lst in groups.values():
        cur, last = [], None
        for r in lst:
            t = _ts(r["taken"])
            if t is None:
                continue
            if last is not None and t - last > gap_min * 60:
                sessions.append(cur)
                cur = []
            cur.append(r)
            last = t
        if cur:
            sessions.append(cur)
    refs = {}
    made = 0
    for ses in sessions:
        known = [r for r in ses if r["id"] in img_named]
        if len(known) < min_known or len(ses) == len(known):
            continue
        counts = {}
        for r in known:
            for pid in img_named[r["id"]]:
                counts[pid] = counts.get(pid, 0) + 1
        best = max(counts, key=counts.get)
        if counts[best] >= dominance * len(known):
            cands = [best]
        else:
            cands = [p for p, c in counts.items() if c >= share * len(known)]
            if len(cands) < 2:
                continue                                          # không có ai nổi bật rõ: không đoán
        for r in ses:
            if r["id"] in img_named or r["clip"] is None:
                continue
            v = _unit(blob_to_vec(r["clip"]))
            for pid in cands:
                if pid not in refs:
                    refs[pid] = _clip_refs(db, pid)
                if refs[pid] is None:
                    continue
                top = float(np.mean(np.sort(refs[pid] @ v)[-3:]))
                if top < floor:
                    continue
                if db.one("SELECT 1 FROM person_guess WHERE image_id=? AND person_id=?", (r["id"], pid)):
                    continue
                if db.one("SELECT 1 FROM face_reject fr JOIN faces f ON f.id=fr.face_id WHERE f.image_id=? AND fr.person_id=?", (r["id"], pid)):
                    continue                                      # mặt trong ảnh đã bị loại khỏi người này
                db.c.execute("INSERT INTO person_guess(image_id,person_id,score,state) VALUES(?,?,?,0)", (r["id"], pid, top))
                made += 1
    db.commit()
    return made


def archive_coverage(db):
    """Thống kê tệp nén có nhiều tên người: số tên ghi trên tên file so với số người thực sự có ảnh trong tệp.
    Trả về danh sách {archive, names, counts{tên: số ảnh}, missing[tên không thấy ảnh nào], more(có '...'), unnamed(số nhóm mặt chưa có tên), images}."""
    import os
    import re
    out = []
    kn = known_names(db)
    by_arch = {}
    for r in db.q("SELECT id,path FROM images WHERE path LIKE 'zip://%'"):
        by_arch.setdefault(_archive_of(r["path"]), []).append(r["id"])
    for arch, ids in by_arch.items():
        base = re.sub(r"(\.tar)?\.[A-Za-z0-9]{1,4}$", "", os.path.basename(arch))
        names = _names_in_base(base, kn)
        more = _has_more(base)
        if len(names) < 2 and not (names and more):
            continue
        qs = ",".join("?" * len(ids))
        owned = {}
        for r in db.q(f"SELECT p.name name, COUNT(DISTINCT f.image_id) n FROM faces f JOIN persons p ON p.id=f.person_id "
                      f"WHERE f.image_id IN ({qs}) AND p.name IS NOT NULL GROUP BY p.id", ids):
            owned[fold(r["name"])] = owned.get(fold(r["name"]), 0) + r["n"]
        for r in db.q(f"SELECT p.name name, COUNT(DISTINCT g.image_id) n FROM person_guess g JOIN persons p ON p.id=g.person_id "
                      f"WHERE g.image_id IN ({qs}) AND g.state=2 AND p.name IS NOT NULL GROUP BY p.id", ids):
            owned[fold(r["name"])] = owned.get(fold(r["name"]), 0) + r["n"]
        counts = {nm: owned.get(fold(nm), 0) for nm in names}
        unnamed = db.one(f"SELECT COUNT(*) c FROM (SELECT f.person_id FROM faces f JOIN persons p ON p.id=f.person_id "
                         f"WHERE f.image_id IN ({qs}) AND p.name IS NULL GROUP BY f.person_id HAVING COUNT(DISTINCT f.image_id)>=2)", ids)["c"]
        out.append({"archive": arch, "names": names, "counts": counts, "missing": [n for n, c in counts.items() if c == 0],
                    "more": more, "unnamed": unnamed, "images": len(ids)})
    return out


@auto_edit
def seed_from_archives(db):
    """Ảnh trong file nén có tên người thì mặc định là của người đó.
    - Tên file khớp người đã có (không phân biệt dấu, hoa thường; kèm số hoặc chữ khác cũng được); một file có thể mang NHIỀU tên người.
      Nếu chưa có người đó mà tên file trông giống một tên người thì tạo người mới.
    - Cùng một người có tên trong NHIỀU file nén: danh tính của họ được xác định xuyên các file (khuôn mặt xuất hiện ở nhiều file nén nhất),
      nên người lạ chụp chung trong một file không thể bị nhầm là người đó.
    - Mỗi ảnh gán đúng khuôn mặt giống danh tính đó; file chỉ có một tên và ảnh chỉ có một mặt thì mặc định là người đó."""
    import os
    rows = db.q("SELECT id,path FROM images WHERE path LIKE 'zip://%'")
    if not rows:
        return 0
    dim = face_dim(db)
    k = default_thr(db) / 0.42
    persons = [(p["id"], fold(p["name"])) for p in db.q("SELECT id,name FROM persons WHERE name IS NOT NULL") if len(fold(p["name"])) >= 3]
    by_arch, img_arch = {}, {}
    for r in rows:
        a = _archive_of(r["path"])
        by_arch.setdefault(a, []).append(r["id"])
        img_arch[r["id"]] = a
    kn_all = known_names(db)
    arch_people = {}                                           # file nén -> [id người]
    for arch, img_ids in by_arch.items():
        base = os.path.basename(arch)
        af = " " + fold(base) + " "
        found = []
        for pid, pn in sorted(persons, key=lambda x: -len(x[1])):
            if f" {pn} " in af and not any(pn in fold(db.one("SELECT name FROM persons WHERE id=?", (q,))["name"]) for q in found):
                found.append(pid)
        import re as _re
        multi = _names_in_base(_re.sub(r"(\.tar)?\.[A-Za-z0-9]{1,4}$", "", base), kn_all)          # 'Anna Nguyen, Bella Tran, ...' -> các người có tên
        if multi and len(found) < len(multi):
            has_free = db.one(f"SELECT 1 FROM faces WHERE image_id IN ({','.join('?' * len(img_ids))}) AND person_id IS NULL AND locked=0 LIMIT 1", img_ids)
            found = []
            for nm in multi:
                ex = next((pid for pid, pn in persons if pn == fold(nm)), None)
                if ex is None and has_free:
                    ex = db.x("INSERT INTO persons(name) VALUES(?)", (nm,)).lastrowid
                    persons.append((ex, fold(nm)))
                if ex is not None:
                    found.append(ex)
        if not found:
            nm = name_from_archive(arch, kn_all)
            if nm:
                ex = db.one("SELECT id FROM persons WHERE name=?", (nm,))
                if ex:
                    found = [ex["id"]]
                elif db.one(f"SELECT 1 FROM faces WHERE image_id IN ({','.join('?' * len(img_ids))}) AND person_id IS NULL AND locked=0 LIMIT 1", img_ids):
                    pid = db.x("INSERT INTO persons(name) VALUES(?)", (nm,)).lastrowid
                    persons.append((pid, fold(nm)))
                    found = [pid]
        if found:
            arch_people[arch] = found
    if not arch_people:
        return 0
    # danh tính của từng người: mốc đã có (mặt đã khóa + hồ sơ lưu), nếu chưa có thì đồng thuận xuyên mọi file nén mang tên họ
    person_archs = {}
    for arch, pids in arch_people.items():
        for p in pids:
            person_archs.setdefault(p, []).append(arch)
    centre = {}
    for pid, archs in person_archs.items():
        refs = [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM faces WHERE person_id=? AND locked=1", (pid,)) if len(r["vec"]) == dim * 4]
        refs += [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM person_profile WHERE person_id=? AND dim=?", (pid, dim))]
        if refs:
            centre[pid] = _unit(np.mean(_unit(np.stack(refs).astype(np.float32)), axis=0))
            continue
        iids = [i for a in archs for i in by_arch[a]]
        cand = []
        for c in range(0, len(iids), 500):
            part = iids[c:c + 500]
            cand += [f for f in db.q(f"SELECT id,image_id,vec,w,h FROM faces WHERE image_id IN ({','.join('?' * len(part))}) AND locked=0", part)
                     if len(f["vec"]) == dim * 4]
        # nếu file có nhiều tên mà chưa có mốc thì không đoán được ai là ai: chỉ xác định khi file chỉ mang tên người này
        solo = [f for f in cand if len(arch_people[img_arch[f["image_id"]]]) == 1]
        cen = _consensus_identity(solo, img_arch, default_thr(db))
        if cen is not None:
            centre[pid] = cen
    T = 0.28 * k
    done = 0
    for arch, img_ids in by_arch.items():
        pids = arch_people.get(arch)
        if not pids:
            continue
        for iid in img_ids:
            faces = db.q("SELECT id,vec,person_id,locked FROM faces WHERE image_id=?", (iid,))
            have = {f["person_id"] for f in faces if f["locked"]}
            free = [f for f in faces if not f["locked"] and len(f["vec"]) == dim * 4]
            todo = [p for p in pids if p not in have]
            if not free or not todo:
                continue
            F = _unit(np.stack([blob_to_vec(f["vec"]) for f in free]).astype(np.float32))
            cand = []
            for pj, p in enumerate(todo):
                if p in centre:
                    sims = F @ centre[p]
                    cand += [(float(sims[fi]), fi, pj) for fi in range(len(free))]
            used_f, used_p, chosen = set(), set(), []
            top2 = {}                                           # mặt -> hai độ giống cao nhất (nhiều người cùng file: mặt phải rõ ràng giống MỘT người)
            for sim, fi, pj in cand:
                top2.setdefault(fi, []).append(sim)
            for sim, fi, pj in sorted(cand, reverse=True):
                if sim < T or fi in used_f or pj in used_p:
                    continue
                ss = sorted(top2[fi], reverse=True)
                if len(pids) > 1 and len(ss) > 1 and ss[0] - ss[1] < 0.03 * k:
                    continue                                    # giống hai người ngang nhau: để ảnh chưa gán thay vì đoán bừa
                used_f.add(fi)
                used_p.add(pj)
                chosen.append((fi, todo[pj]))
            if not chosen and len(pids) == 1 and len(free) == 1:
                chosen = [(0, pids[0])]                         # file chỉ có một tên và ảnh chỉ có một mặt: mặc định là người đó
            for fi, p in chosen:
                db.c.execute("UPDATE faces SET person_id=?, locked=1 WHERE id=?", (p, free[fi]["id"]))
                done += 1
    db.commit()
    return done


@auto_edit
def cluster_incremental(db):
    """Cập nhật NHẸ sau khi quét nền ít ảnh mới: gán tên theo tệp nén, sửa mặt gán nhầm, gán mặt mới cho người đã biết; không gom lại cả thư viện
    (mặt hoàn toàn lạ chờ lần gom đầy đủ). Trả về số mặt mới còn chưa xếp vào người nào."""
    seed_from_archives(db)
    merge_same_name(db)
    reconcile_named(db)
    attach_to_named(db)
    enforce_rejects(db)
    pend = [r["id"] for r in db.q("""SELECT id FROM faces WHERE person_id IS NULL AND locked=0 AND px>=?
                                     AND id NOT IN (SELECT face_id FROM face_reject)""", (MIN_FACE_PX,))]
    reassign_faces(db, pend)
    save_profiles(db)
    return db.one("""SELECT COUNT(*) c FROM faces WHERE person_id IS NULL AND locked=0 AND px>=?
                     AND id NOT IN (SELECT face_id FROM face_reject)""", (MIN_FACE_PX,))["c"]


# ---------------------------------------------------------------- hồ sơ khuôn mặt của người đã đặt tên (nhớ cả khi ảnh bị xóa)
PROFILE_K = 24


def save_profiles(db):
    """Lưu tối đa PROFILE_K khuôn mặt tiêu biểu (chất lượng cao, đa dạng) của mỗi người đã đặt tên. Hồ sơ vẫn còn khi toàn bộ ảnh của người
    đó bị xóa; khi ảnh của họ được thêm lại, khuôn mặt mới được nhận ra đúng là người này."""
    dim = face_dim(db)
    for p in db.q("SELECT id FROM persons WHERE name IS NOT NULL"):
        rows = [r for r in db.q("SELECT vec,score,px FROM faces WHERE person_id=? AND locked=1", (p["id"],)) if len(r["vec"]) == dim * 4]
        if not rows:
            continue                                          # không còn mặt nào: giữ nguyên hồ sơ cũ
        rows.sort(key=lambda r: -(r["score"] or 0) * min(r["px"] or 0, 200))
        chosen = []
        for r in rows:
            v = _unit(blob_to_vec(r["vec"]).astype(np.float32))
            if all(float(v @ c) < 0.92 for c in chosen):      # bỏ các mặt gần như trùng nhau để hồ sơ đa dạng
                chosen.append(v)
            if len(chosen) >= PROFILE_K:
                break
        db.c.execute("DELETE FROM person_profile WHERE person_id=?", (p["id"],))
        for v in chosen:
            db.c.execute("INSERT INTO person_profile(person_id,dim,vec) VALUES(?,?,?)", (p["id"], dim, vec_to_blob(v)))
    db.commit()


NAMED_THR = 0.40         # độ giống (trung bình 5 mặt mẫu gần nhất) để tự gán một mặt cho người đã đặt tên (chuẩn hóa theo mô hình)
NAMED_MARGIN = 0.04      # người đã đặt tên tốt nhất phải hơn người thứ hai chừng này


RECONCILE_MARGIN = 0.08


@auto_edit
def reconcile_named(db):
    """Sửa các mặt đã bị khóa NHẦM vào người có tên (do gom sai trước khi đặt tên, hoặc do tên tệp nén gán nhầm) khi có thêm bằng chứng:
    mỗi mặt chưa do người dùng tự chỉnh tay được so với mặt mẫu của chính người đó (bỏ chính nó) và của các người có tên khác;
    nếu giống một người khác hơn hẳn (và đủ giống) thì chuyển sang người đó (không tự thả mặt chỉ vì ít giống, để không mất ảnh).
    Mặt người dùng tự chỉnh tay (lsrc='user') không bao giờ bị đổi. Trả về số mặt được sửa."""
    dim = face_dim(db)
    k = default_thr(db) / 0.42
    pids, E, owner = [], {}, {}
    for p in db.q("SELECT id FROM persons WHERE name IS NOT NULL"):
        rows = [r for r in db.q("SELECT id,image_id,vec,lsrc FROM faces WHERE person_id=? AND locked=1", (p["id"],)) if len(r["vec"]) == dim * 4]
        prof = [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM person_profile WHERE person_id=? AND dim=?", (p["id"], dim))]
        if len(rows) + len(prof) < 3:
            continue
        pids.append(p["id"])
        E[p["id"]] = (rows, _unit(np.stack([blob_to_vec(r["vec"]) for r in rows] + prof).astype(np.float32)))
    if len(pids) < 1:
        return 0
    fixed = 0

    def top5_mean(S):
        """Trung bình 5 điểm giống nhất của từng hàng (hàng có ít hơn 5 cột hợp lệ thì lấy hết); -1 nếu không có cột nào. Tính cả ma trận một lần (nhanh, không giữ luồng giao diện)."""
        if S.shape[1] == 0:
            return np.full(S.shape[0], -1.0, np.float32)
        t = -np.sort(-S, axis=1)[:, :5]
        ok = t > -1e8
        n = ok.sum(1)
        return np.where(n > 0, np.where(ok, t, 0.0).sum(1) / np.maximum(n, 1), -1.0)
    for pid in pids:
        rows, M = E[pid]
        idx = [i for i, r in enumerate(rows) if r["lsrc"] != "user"]
        if not idx:
            continue
        Vp = M[idx]
        S_own = Vp @ M.T
        S_own[np.arange(len(idx)), idx] = -1e9                                   # bỏ chính nó
        own = top5_mean(S_own)
        best = np.full(len(idx), -1.0)
        best_q = [None] * len(idx)
        for q in pids:
            if q == pid:
                continue
            sq = top5_mean(Vp @ E[q][1].T)
            better = sq > best
            for j in np.nonzero(better)[0]:
                best_q[j] = q
            best = np.where(better, sq, best)
        for j, i in enumerate(idx):
            r = rows[i]
            if best_q[j] is not None and best[j] >= NAMED_THR * k and best[j] - own[j] >= RECONCILE_MARGIN * k \
                    and not db.one("SELECT 1 FROM faces WHERE image_id=? AND person_id=? AND id<>?", (r["image_id"], best_q[j], r["id"])):
                db.c.execute("UPDATE faces SET person_id=? WHERE id=?", (best_q[j], r["id"]))
                fixed += 1
    db.commit()
    return fixed


@auto_edit
def attach_to_named(db, min_px=MIN_FACE_PX):
    """Tự gán khuôn mặt (ảnh mới lẫn ảnh cũ) cho NGƯỜI ĐÃ ĐẶT TÊN: so từng mặt với hồ sơ của mọi người có tên (mặt đã khóa và hồ sơ đã lưu,
    kể cả khi ảnh của họ đã bị xóa), lấy trung bình 5 mặt mẫu giống nhất nên người có nhiều kiểu ảnh (nghiêng, tuổi, ánh sáng) vẫn nhận ra.
    Chỉ gán khi đủ giống và hơn hẳn người thứ hai; mặt đã khóa (người dùng chỉnh tay) và mặt cùng ảnh với mặt đã khóa của người đó thì bỏ qua."""
    dim = face_dim(db)
    k = default_thr(db) / 0.42
    thr = NAMED_THR * k
    pids, exemplars = [], []
    for p in db.q("SELECT id FROM persons WHERE name IS NOT NULL"):
        ex = [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM faces WHERE person_id=? AND locked=1", (p["id"],)) if len(r["vec"]) == dim * 4]
        ex += [blob_to_vec(r["vec"]) for r in db.q("SELECT vec FROM person_profile WHERE person_id=? AND dim=?", (p["id"], dim))]
        if ex:
            pids.append(p["id"])
            exemplars.append(_unit(np.stack(ex).astype(np.float32)))
    if not pids:
        return 0
    faces = [f for f in db.q("SELECT id,image_id,vec,score,px,person_id FROM faces WHERE locked=0") if len(f["vec"]) == dim * 4
             and f["px"] >= min_px and f["score"] >= 0.85]
    if not faces:
        return 0
    V = _unit(np.stack([blob_to_vec(f["vec"]) for f in faces]).astype(np.float32))
    S = np.zeros((len(faces), len(pids)), np.float32)
    for j, E in enumerate(exemplars):
        s = V @ E.T
        kk = min(5, s.shape[1])
        S[:, j] = np.sort(s, axis=1)[:, -kk:].mean(axis=1)
    locked_in = {}
    for r in db.q("SELECT image_id,person_id FROM faces WHERE locked=1 AND person_id IS NOT NULL"):
        locked_in.setdefault(r["image_id"], set()).add(r["person_id"])
    rejected = {(r["face_id"], r["person_id"]) for r in db.q("SELECT face_id,person_id FROM face_reject")}
    best_for = {}                                          # (ảnh, người) -> (độ giống, id mặt): mỗi ảnh chỉ một mặt cho một người
    for i, f in enumerate(faces):
        order = np.argsort(-S[i])
        b1 = float(S[i, order[0]])
        b2 = float(S[i, order[1]]) if len(order) > 1 else -1.0
        weak = (f["px"] < 60)
        if b1 < thr + (0.04 if weak else 0.0) or b1 - b2 < NAMED_MARGIN:
            continue
        pid = pids[int(order[0])]
        if pid in locked_in.get(f["image_id"], ()):
            continue
        if (f["id"], pid) in rejected:
            continue
        key = (f["image_id"], pid)
        if key not in best_for or b1 > best_for[key][0]:
            best_for[key] = (b1, f["id"])
    n = 0
    for (iid, pid), (s, fid) in best_for.items():
        cur = db.one("SELECT person_id FROM faces WHERE id=?", (fid,))["person_id"]
        if cur != pid:
            db.c.execute("UPDATE faces SET person_id=? WHERE id=?", (pid, fid))
            n += 1
    db.commit()
    return n


def _profile_rows(db, dim, have_locked):
    """Khuôn mặt 'ảo' từ hồ sơ của người đã đặt tên mà hiện không còn mặt khóa nào, để làm mốc khi gom."""
    out = []
    k = 0
    for r in db.q("SELECT p.person_id pid, p.vec vec FROM person_profile p JOIN persons s ON s.id=p.person_id WHERE s.name IS NOT NULL AND p.dim=?", (dim,)):
        if r["pid"] in have_locked:
            continue
        k += 1
        out.append({"id": -k, "image_id": -(10 ** 6 + k), "vec": r["vec"], "score": 1.0, "px": 200.0, "person_id": r["pid"], "locked": 1, "thumb": None})
    return out


@auto_edit
def cluster_faces(db, thr=None, min_px=MIN_FACE_PX):
    """Gom khuôn mặt theo người, chặt chẽ hơn trước:
    - so khuôn mặt (SFace) kết hợp màu da, màu tóc; liên kết trung bình để không nối nhầm hai người;
    - hai mặt trong CÙNG MỘT ẢNH luôn là hai người khác nhau;
    - mặt mờ, nhỏ chỉ được gán khi rất chắc, không thì để chưa xếp nhóm;
    - người đã đặt tên là mốc cố định, hai người đã đặt tên không bao giờ bị gộp.
    thr: độ giống trung bình tối thiểu để gộp hai nhóm."""
    dim = face_dim(db)
    seed_from_archives(db)                    # ảnh trong file nén có tên người: mặc định là của người đó
    merge_same_name(db)                       # hai nhóm cùng tên là cùng một người
    reconcile_named(db)                       # sửa các mặt đã bị gán nhầm cho người có tên khi có thêm bằng chứng
    thr = default_thr(db) if thr is None else thr
    leader_thr = LEADER_BY_DIM.get(dim, 0.72)
    # chỉ dùng các mặt cùng số chiều (khi đang chuyển sang mô hình mới, mặt cũ chưa quét lại tạm thời bị bỏ qua)
    rows = [r for r in db.q("SELECT id,image_id,vec,score,px,person_id,locked,thumb FROM faces "
                            "WHERE locked=1 OR image_id NOT IN (SELECT image_id FROM image_art WHERE art=1)")        # bỏ mặt trong tranh vẽ
            if len(r["vec"]) == dim * 4]
    if not rows:
        return 0
    have_locked = {r["person_id"] for r in rows if r["locked"] and r["person_id"] is not None}
    rows = rows + _profile_rows(db, dim, have_locked)      # người đã đặt tên nhưng hiện không còn ảnh: vẫn làm mốc nhận diện
    n = len(rows)
    ids = np.array([r["id"] for r in rows])
    img = np.array([r["image_id"] for r in rows])
    vecs = _unit(np.stack([blob_to_vec(r["vec"]) for r in rows]).astype(np.float32))
    locked = np.array([bool(r["locked"]) and r["person_id"] is not None for r in rows])
    pers = np.array([r["person_id"] if r["person_id"] is not None else -1 for r in rows])
    attrs = _attrs(db, rows)
    at = [attrs.get(r["id"]) for r in rows]
    sharp = np.array([(attrs[r["id"]][6] if r["id"] in attrs else 3.0) for r in rows])
    quality = np.array([r["score"] * min(r["px"], 200) / 200.0 * (0.6 + 0.4 * min(1.0, sharp[k] / 3.0)) for k, r in enumerate(rows)])
    good = np.array([(r["px"] >= min_px and r["score"] >= 0.85) for k, r in enumerate(rows)])

    # ---- 1) nhóm mốc: mặt đã khóa theo từng người đã đặt tên
    groups, gfixed = [], []
    for pid in sorted(set(int(p) for p in pers[locked])):
        groups.append(list(np.nonzero(locked & (pers == pid))[0]))
        gfixed.append(pid)
    # ---- 2) nhóm lá: gộp các mặt rất giống nhau (và không cùng ảnh) cho gọn rồi mới gộp chặt bằng UPGMA
    free = [i for i in np.nonzero(~locked & good)[0]]
    free.sort(key=lambda i: -quality[i])
    leaders = []            # chỉ số nhóm trong `groups`
    lat = []                # đặc trưng màu da, tóc của từng nhóm lá
    cent = np.zeros((0, vecs.shape[1]), np.float32)
    imgsets = [set(int(img[i]) for i in g) for g in groups]
    for i in free:
        placed = False
        if len(leaders):
            sims = cent @ vecs[i]
            for k in np.argsort(-sims)[:5]:
                if sims[k] < leader_thr:
                    break
                if sims[k] - _penalty(at[i], lat[k]) < leader_thr:     # màu da, tóc khác hẳn: không gộp dù khuôn mặt giống
                    continue
                g = leaders[k]
                if int(img[i]) in imgsets[g]:
                    continue
                groups[g].append(i)
                imgsets[g].add(int(img[i]))
                cent[k] = _unit(vecs[groups[g]].mean(axis=0))
                placed = True
                break
        if not placed:
            groups.append([i])
            gfixed.append(None)
            imgsets.append({int(img[i])})
            leaders.append(len(groups) - 1)
            lat.append(at[i])
            cent = np.vstack([cent, vecs[i][None]])
    m = len(groups)
    if m:
        gc = _unit(np.stack([vecs[g].mean(axis=0) for g in groups]))
        sim = gc @ gc.T
        pen = np.zeros((m, m), np.float32)
        gat = []
        for g in groups:
            vs = [at[i] for i in g if at[i] is not None]
            gat.append(tuple(np.mean(vs, axis=0)) if vs else None)
        for x in range(m):
            for y in range(x + 1, m):
                pen[x, y] = pen[y, x] = _penalty(gat[x], gat[y])
        C = sim - pen
        byimg = {}
        for gi, s_ in enumerate(imgsets):
            for t in s_:
                byimg.setdefault(t, []).append(gi)
        for lst in byimg.values():                       # cùng một ảnh: không bao giờ gộp
            for x in lst:
                for y in lst:
                    if x != y:
                        C[x, y] = -1e9
        fx = [k for k, f in enumerate(gfixed) if f is not None]
        for x in fx:                                     # hai người đã đặt tên: không gộp
            for y in fx:
                if x != y:
                    C[x, y] = -1e9
        merged = _upgma(C, np.array([len(g) for g in groups]), thr)
    else:
        merged = []
    clusters = []            # (pid cố định hoặc None, danh sách chỉ số mặt)
    for mem in merged:
        fixed = [gfixed[k] for k in mem if gfixed[k] is not None]
        clusters.append((fixed[0] if fixed else None, [i for k in mem for i in groups[k]]))

    # ---- 3) mặt kém chất lượng: chỉ gán khi rất chắc (đủ giống và hơn hẳn nhóm thứ hai), không thì để chưa xếp nhóm
    assign = np.full(n, -1)
    for ci, (_, mem) in enumerate(clusters):
        for i in mem:
            assign[i] = ci
    weak = [i for i in np.nonzero(~locked & ~good)[0]]
    if clusters and weak:
        cc = _unit(np.stack([vecs[mem].mean(axis=0) for _, mem in clusters]))
        cat = []
        for _, mem in clusters:
            vs = [at[i] for i in mem if at[i] is not None]
            cat.append(tuple(np.mean(vs, axis=0)) if vs else None)
        cimgs = [set(int(img[i]) for i in mem) for _, mem in clusters]
        for i in weak:
            sc = cc @ vecs[i] - np.array([_penalty(at[i], c) for c in cat])
            for ci, s_ in enumerate(cimgs):
                if int(img[i]) in s_:
                    sc[ci] = -1e9
            order = np.argsort(-sc)
            b1 = float(sc[order[0]])
            b2 = float(sc[order[1]]) if len(order) > 1 else -1.0
            if b1 >= thr - 0.03 and b1 - b2 >= 0.05:
                assign[i] = int(order[0])
                clusters[int(order[0])][1].append(i)

    # ---- ghi vào cơ sở dữ liệu: xóa nhóm chưa tên và không còn mặt khóa
    named = {r["id"] for r in db.q("SELECT id FROM persons WHERE name IS NOT NULL")}
    keep = set(p for p, _ in clusters if p is not None) | named | set(int(p) for p in pers[locked])
    for r in db.q("SELECT id FROM persons"):
        if r["id"] not in keep:
            db.x("DELETE FROM persons WHERE id=?", (r["id"],))
    pid_of = {}
    for ci, (pid, mem) in enumerate(clusters):
        if pid is None:
            pid_of[ci] = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
        else:
            pid_of[ci] = pid
    for k in range(n):
        if locked[k]:
            continue
        new = pid_of.get(int(assign[k])) if assign[k] >= 0 else None
        db.c.execute("UPDATE faces SET person_id=? WHERE id=?", (new, int(ids[k])))
    db.commit()
    attach_to_named(db)                       # ảnh mới và ảnh cũ giống người đã đặt tên thì tự gán vào người đó
    enforce_rejects(db)                       # ảnh người dùng đã loại khỏi một người thì không quay lại người đó
    db.x("DELETE FROM persons WHERE id NOT IN (SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL) AND name IS NULL")
    save_profiles(db)
    return len(set(pid_of.values()))


# ---------------------------------------------------------------- gợi ý và tự gộp các nhóm là cùng một người
def _person_vectors(db, dim, max_each=40):
    """{id người: (ma trận mặt tiêu biểu, tâm, tập ảnh, số ảnh)} cho các nhóm đang hiện (chưa ẩn)."""
    out = {}
    for p in db.q("SELECT id,name FROM persons WHERE hidden=0"):
        rows = [r for r in db.q("SELECT image_id,vec,score,px FROM faces WHERE person_id=?", (p["id"],)) if len(r["vec"]) == dim * 4]
        if not rows:
            continue
        rows.sort(key=lambda r: -(r["score"] or 0) * min(r["px"] or 0, 200))
        M = _unit(np.stack([blob_to_vec(r["vec"]) for r in rows[:max_each]]).astype(np.float32))
        allv = _unit(np.stack([blob_to_vec(r["vec"]) for r in rows]).astype(np.float32))
        out[p["id"]] = (M, _unit(allv.mean(axis=0)), {r["image_id"] for r in rows}, len({r["image_id"] for r in rows}), p["name"])
    return out


def suggest_merges(db, loose=1.0):
    """Các cặp nhóm có thể là CÙNG MỘT NGƯỜI (vd. một người bị tách vì khác góc mặt, tuổi, ánh sáng). Bỏ qua cặp có ảnh chung (hai mặt cùng ảnh
    là hai người khác nhau), cặp đã đặt tên cả hai, và cặp người dùng đã bấm 'khác người'.
    Trả về [{a, b, score, centroid, topk, strong}] giảm dần theo độ giống; strong = đủ chắc để tự gộp."""
    dim = face_dim(db)
    k = default_thr(db) / 0.42                          # quy đổi ngưỡng theo mô hình nhận dạng
    pv = _person_vectors(db, dim)
    ids = sorted(pv)
    if len(ids) < 2:
        return []
    rej = {(r["a"], r["b"]) for r in db.q("SELECT a,b FROM person_nomerge")}
    cents = np.stack([pv[i][1] for i in ids])
    csim = cents @ cents.T
    out = []
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            a, b = ids[x], ids[y]
            if csim[x, y] < 0.28 * k or (a, b) in rej or pv[a][2] & pv[b][2]:
                continue
            if pv[a][4] and pv[b][4]:
                continue                                  # hai người đều đã đặt tên: không tự đề xuất gộp
            cross = pv[a][0] @ pv[b][0].T
            top = float(np.sort(cross.ravel())[-3:].mean())
            score = 0.5 * float(csim[x, y]) + 0.5 * top
            if score < 0.40 * k * loose and csim[x, y] < 0.40 * k * loose:
                continue
            strong = csim[x, y] >= 0.46 * k and top >= 0.56 * k
            out.append({"a": a, "b": b, "score": score, "centroid": float(csim[x, y]), "topk": top, "strong": bool(strong)})
    out.sort(key=lambda d: -d["score"])
    return out


def merge_target(db, a, b):
    """Gộp nhóm nào vào nhóm nào: giữ nhóm đã đặt tên, nếu không thì giữ nhóm nhiều ảnh hơn. Trả về (nguồn, đích)."""
    na = db.one("SELECT name FROM persons WHERE id=?", (a,))["name"]
    nb = db.one("SELECT name FROM persons WHERE id=?", (b,))["name"]
    if nb and not na:
        return a, b
    if na and not nb:
        return b, a
    ca = db.one("SELECT COUNT(DISTINCT image_id) n FROM faces WHERE person_id=?", (a,))["n"]
    cb = db.one("SELECT COUNT(DISTINCT image_id) n FROM faces WHERE person_id=?", (b,))["n"]
    return (b, a) if ca >= cb else (a, b)


def merge_pair(db, a, b):
    src, dst = merge_target(db, a, b)
    merge_persons(db, src, dst)
    return dst


def reject_merge(db, a, b):
    a, b = sorted((a, b))
    db.x("INSERT OR IGNORE INTO person_nomerge VALUES(?,?)", (a, b))


def auto_merge(db):
    """Tự gộp các cặp rất chắc là một người. Lặp lại vì sau mỗi lần gộp tâm nhóm đổi. Trả về số lần gộp."""
    n = 0
    for _ in range(50):
        strong = [d for d in suggest_merges(db) if d["strong"]]
        if not strong:
            break
        d = strong[0]
        merge_pair(db, d["a"], d["b"])
        n += 1
    return n


def rename_person(db, pid, name):
    name = name.strip() or None
    db.x("UPDATE persons SET name=? WHERE id=?", (name, pid))
    if name:   # đã đặt tên thì khóa các mặt hiện tại làm mốc và lưu hồ sơ khuôn mặt (nhớ cả khi ảnh sau này bị xóa)
        db.x("UPDATE faces SET locked=1 WHERE person_id=?", (pid,))
        save_profiles(db)
        merge_same_name(db)                   # đặt tên trùng với người đã có: gộp thành một
        reconcile_named(db)                   # mặt bị khóa nhầm vào người này (do gom sai) được trả về đúng người
        attach_to_named(db)                   # vừa đặt tên: các ảnh khác (cũ và mới) giống người này được gom vào ngay
        db.x("DELETE FROM persons WHERE id NOT IN (SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL) AND name IS NULL")


@auto_edit
def merge_same_name(db):
    """Hai người đã đặt TÊN GIỐNG HỆT (không phân biệt dấu, hoa thường) là cùng một người: gộp vào nhóm có nhiều ảnh hơn.
    (Trước đây hai người đã có tên không bao giờ tự gộp nên cùng tên vẫn ra hai nhóm.) Trả về số nhóm đã gộp."""
    by = {}
    for p in db.q("""SELECT p.id id, p.name name, (SELECT COUNT(*) FROM faces f WHERE f.person_id=p.id) n FROM persons p WHERE p.name IS NOT NULL"""):
        by.setdefault(fold(p["name"]), []).append(p)
    merged = 0
    for ps in by.values():
        if len(ps) < 2:
            continue
        ps.sort(key=lambda p: (-p["n"], p["id"]))
        dst = ps[0]["id"]
        for q in ps[1:]:
            src = q["id"]
            db.c.execute("UPDATE faces SET person_id=? WHERE person_id=?", (dst, src))             # giữ nguyên khóa / nguồn khóa của từng mặt
            db.c.execute("UPDATE OR IGNORE person_guess SET person_id=? WHERE person_id=?", (dst, src))
            db.c.execute("DELETE FROM person_guess WHERE person_id=?", (src,))
            db.c.execute("UPDATE person_profile SET person_id=? WHERE person_id=?", (dst, src))
            db.c.execute("DELETE FROM person_suggest WHERE person_id=?", (src,))
            db.c.execute("UPDATE face_reject SET person_id=? WHERE person_id=?", (dst, src))
            db.c.execute("DELETE FROM persons WHERE id=?", (src,))
            merged += 1
    db.commit()
    return merged


def merge_persons(db, src, dst):
    db.x("UPDATE faces SET person_id=?, locked=1, lsrc='user' WHERE person_id=?", (dst, src))
    db.x("UPDATE person_profile SET person_id=? WHERE person_id=?", (dst, src))
    db.x("DELETE FROM persons WHERE id=?", (src,))


def remove_from_person(db, pid, image_ids):
    """Người dùng loại ảnh khỏi một người: mặt đó không bao giờ quay lại người này, và app tự tìm người khác phù hợp nhất cho nó
    (người đã đặt tên hoặc nhóm giống nhất); không đủ chắc thì để chưa xếp nhóm cho lần gom sau."""
    qs = ",".join("?" * len(image_ids))
    db.x(f"UPDATE person_guess SET state=1 WHERE person_id=? AND image_id IN ({qs})", [pid, *image_ids])
    fids = [r["id"] for r in db.q(f"SELECT id FROM faces WHERE person_id=? AND image_id IN ({qs})", [pid, *image_ids])]
    for f in fids:
        db.c.execute("INSERT OR IGNORE INTO face_reject VALUES(?,?)", (f, pid))
    for iid in image_ids:                                      # ghi nhớ để các lần tự gán sau (kể cả tệp nén mang tên người này) không thêm lại
        db.c.execute("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,0,1)", (iid, pid))
    if fids:
        qf = ",".join("?" * len(fids))
        db.c.execute(f"UPDATE faces SET person_id=NULL, locked=0, lsrc=NULL WHERE id IN ({qf})", fids)
    db.commit()
    reassign_faces(db, fids)


@auto_edit
def reassign_faces(db, face_ids):
    """Gán lại từng mặt (đang không thuộc ai) cho người giống nhất, trừ những người đã bị loại cho mặt đó và người đã có mặt trong cùng ảnh."""
    if not face_ids:
        return 0
    dim = face_dim(db)
    k = default_thr(db) / 0.42
    pv = _person_vectors(db, dim)
    if not pv:
        return 0
    pids = list(pv)
    n = 0
    for c0 in range(0, len(face_ids), 500):                                  # theo lô: so cả lô mặt với từng người bằng phép nhân ma trận (nhanh gấp nhiều lần so với từng mặt một)
        chunk = face_ids[c0:c0 + 500]
        fs = [f for f in db.q(f"SELECT id,image_id,vec,person_id FROM faces WHERE id IN ({','.join('?' * len(chunk))})", chunk)
              if f["person_id"] is None and len(f["vec"]) == dim * 4]
        if not fs:
            continue
        V = _unit(np.stack([blob_to_vec(f["vec"]) for f in fs]).astype(np.float32))              # F x dim
        SC = np.empty((len(fs), len(pids)), np.float32)
        for j, pid in enumerate(pids):
            S = pv[pid][0] @ V.T                                                             # mẫu của người x F
            t = -np.sort(-S, axis=0)[:5]
            SC[:, j] = t.mean(0)
        qf = ",".join("?" * len(fs))
        rej, there = {}, {}
        for r in db.q(f"SELECT face_id, person_id FROM face_reject WHERE face_id IN ({qf})", [f["id"] for f in fs]):
            rej.setdefault(r["face_id"], set()).add(r["person_id"])
        for r in db.q(f"SELECT image_id, person_id FROM faces WHERE person_id IS NOT NULL AND image_id IN ({','.join('?' * len(fs))})", [f["image_id"] for f in fs]):
            there.setdefault(r["image_id"], set()).add(r["person_id"])
        for i, f in enumerate(fs):
            skip = rej.get(f["id"], set()) | there.get(f["image_id"], set())
            sc = sorted(((float(SC[i, j]), pid) for j, pid in enumerate(pids) if pid not in skip), reverse=True)[:2]
            if sc and sc[0][0] >= NAMED_THR * k and (len(sc) == 1 or sc[0][0] - sc[1][0] >= NAMED_MARGIN * k):
                db.c.execute("UPDATE faces SET person_id=? WHERE id=?", (sc[0][1], f["id"]))
                n += 1
    db.commit()
    return n


@auto_edit
def enforce_rejects(db):
    """Sau khi gom lại: mặt nào lại rơi vào người đã bị loại cho nó thì đưa ra và tìm người khác."""
    rows = db.q("SELECT f.id id FROM faces f JOIN face_reject r ON r.face_id=f.id AND r.person_id=f.person_id")
    ids = [r["id"] for r in rows]
    if ids:
        qf = ",".join("?" * len(ids))
        db.c.execute(f"UPDATE faces SET person_id=NULL WHERE id IN ({qf})", ids)
        db.commit()
        reassign_faces(db, ids)
    return len(ids)


def restore_to_person(db, image_ids, pid):
    """Hoàn tác việc loại ảnh khỏi một người (hoặc lấy lại ảnh từng bị loại nhầm): bỏ ghi nhớ 'không phải người này' của các ảnh đó với người này và
    đưa chúng trở lại người này (xác nhận thủ công). Trả về số ảnh đã đưa lại."""
    if not image_ids:
        return 0
    qs = ",".join("?" * len(image_ids))
    fids = [r["id"] for r in db.q(f"SELECT f.id id FROM faces f JOIN face_reject r ON r.face_id=f.id AND r.person_id=? WHERE f.image_id IN ({qs})", [pid, *image_ids])]
    if fids:
        qf = ",".join("?" * len(fids))
        db.x(f"DELETE FROM face_reject WHERE person_id=? AND face_id IN ({qf})", [pid, *fids])
        db.x(f"UPDATE faces SET person_id=?, locked=1, lsrc='user' WHERE id IN ({qf})", [pid, *fids])
    for iid in image_ids:
        had_face = bool(db.one("SELECT 1 FROM faces WHERE image_id=? AND person_id=?", (iid, pid)))
        db.x("DELETE FROM person_guess WHERE image_id=? AND person_id=? AND state=1", (iid, pid))
        if not had_face:
            db.x("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,1.0,2)", (iid, pid))
    return len(image_ids)


def assign_images_to_person(db, image_ids, to_pid, from_pid=None):
    """Người dùng tự thêm ảnh vào một người. Mặt của người đang xem (from_pid) trong ảnh được chuyển sang người đích; ảnh chỉ có một mặt thì chuyển mặt đó;
    ảnh không thấy mặt hoặc nhiều mặt mà không rõ mặt nào thì ghi là ảnh thuộc người đó (xác nhận thủ công). Trả về số ảnh đã thêm."""
    n = 0
    for iid in image_ids:
        faces = db.q("SELECT id, person_id FROM faces WHERE image_id=?", (iid,))
        mine = [f["id"] for f in faces if from_pid is not None and f["person_id"] == from_pid]
        pick = mine or ([faces[0]["id"]] if len(faces) == 1 else [])
        if not pick and len(faces) > 1:                         # nhiều mặt, không biết mặt nào: nếu có một mặt nổi bật (lớn hơn rõ rệt) thì đó là chủ thể của ảnh
            sz = sorted(db.q("SELECT id, w*h a FROM faces WHERE image_id=? ORDER BY a DESC", (iid,)), key=lambda r: -(r["a"] or 0))
            if sz[0]["a"] and sz[0]["a"] >= 1.5 * (sz[1]["a"] or 0):
                pick = [sz[0]["id"]]
        if from_pid is not None:                                # ảnh đang là của người khác theo đề xuất đã nhận: bỏ khỏi người đó
            db.x("UPDATE person_guess SET state=1 WHERE image_id=? AND person_id=? AND state=2", (iid, from_pid))
        if pick:
            qs = ",".join("?" * len(pick))
            db.x(f"UPDATE faces SET person_id=?, locked=1, lsrc='user' WHERE id IN ({qs})", [to_pid, *pick])
        else:
            db.x("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,1.0,2)", (iid, to_pid))
        n += 1
    restore_to_person(db, image_ids, to_pid)                    # ảnh từng bị loại nhầm khỏi người đích: bỏ ghi nhớ "không phải", để lần gom sau không đẩy ra lại
    return n


def move_to_person(db, image_ids, from_pid, to_pid):
    qs = ",".join("?" * len(image_ids))
    db.x(f"UPDATE faces SET person_id=?, locked=1, lsrc='user' WHERE person_id=? AND image_id IN ({qs})", [to_pid, from_pid, *image_ids])


# ---- ảnh có người nhưng không thấy mặt: đoán theo bối cảnh ----
def _style(db_thumb):
    """Đặc trưng nhìn nhanh của ảnh: histogram màu, độ sáng, độ nét/nhiễu (từ ảnh nhỏ)."""
    import io
    from PIL import Image, ImageFilter
    from .secure import SEC
    try:
        im = Image.open(io.BytesIO(SEC.read_file(db_thumb))).convert("RGB")
    except Exception:
        return None
    im.thumbnail((96, 96))
    a = np.asarray(im, np.float32) / 255.0
    q = np.minimum((a * 4).astype(int), 3)
    idx = q[..., 0] * 16 + q[..., 1] * 4 + q[..., 2]
    hist = np.bincount(idx.ravel(), minlength=64).astype(np.float32)
    hist /= max(1.0, hist.sum())
    g = np.asarray(im.convert("L").filter(ImageFilter.FIND_EDGES), np.float32) / 255.0
    return {"hist": hist, "bright": float(a.mean()), "sharp": float(np.log1p(g.var() * 1000))}


def _style_sim(a, b):
    if a is None or b is None:
        return 0.5
    inter = float(np.minimum(a["hist"], b["hist"]).sum())
    return 0.6 * inter + 0.25 * (1 - min(1.0, abs(a["bright"] - b["bright"]) * 3)) + 0.15 * (1 - min(1.0, abs(a["sharp"] - b["sharp"]) / 3))


def _archive(path):
    body = str(path)[len("zip://"):]
    return body.split("!/", 1)[0]


def _ts(s):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s)[:19]).timestamp()
    except Exception:
        return None


@auto_edit
def guess_faceless(db, presence=None, min_score=0.6, margin=0.04, max_ref=40):
    """Với ảnh KHÔNG thấy mặt: so với các ảnh đã biết của từng người theo nội dung (CLIP: không gian, ánh sáng, trang phục),
    màu và độ sáng, độ nét, và NGÀY GIỜ chụp. Ghi gợi ý vào bảng person_guess để người dùng xác nhận.
    presence(vec) -> True nếu ảnh có vẻ chụp người (kiểm tra bằng CLIP chữ); None thì bỏ qua bước này."""
    persons = db.persons()
    if not persons:
        return 0
    faceless = db.q("""SELECT id,path,thumb,taken,clip FROM images WHERE clip IS NOT NULL AND thumb IS NOT NULL
                       AND id NOT IN (SELECT image_id FROM faces)""")
    if not faceless:
        return 0
    decided = {(r["image_id"], r["person_id"]) for r in db.q("SELECT image_id,person_id FROM person_guess WHERE state<>0")}
    cand = []
    for r in faceless:
        v = blob_to_vec(r["clip"])
        if presence is not None and not presence(v):
            continue
        cand.append((r, _unit(v)))
    if not cand:
        db.x("DELETE FROM person_guess WHERE state=0")
        return 0
    # ảnh cùng một file nén thường là cùng một người (hoặc nhóm người chụp chung): thống kê người xuất hiện trong từng file nén
    arch_n, arch_tot = {}, {}
    for r in db.q("""SELECT DISTINCT f.person_id pid, i.path path FROM faces f JOIN images i ON i.id=f.image_id
                      WHERE f.person_id IS NOT NULL AND i.path LIKE 'zip://%'"""):
        a = _archive(r["path"])
        arch_n[(a, r["pid"])] = arch_n.get((a, r["pid"]), 0) + 1
    for r in db.q("""SELECT DISTINCT i.path path FROM faces f JOIN images i ON i.id=f.image_id WHERE i.path LIKE 'zip://%'"""):
        arch_tot[_archive(r["path"])] = arch_tot.get(_archive(r["path"]), 0) + 1
    refs = {}
    for p in persons:
        rows = db.person_images(p["id"])[:max_ref]
        rows = [r for r in rows if r["thumb"]]
        vecs, ts, st = [], [], []
        for r in db.q(f"SELECT id,clip,taken,thumb FROM images WHERE id IN ({','.join('?' * len(rows))}) AND clip IS NOT NULL",
                      [r["id"] for r in rows]) if rows else []:
            vecs.append(_unit(blob_to_vec(r["clip"])))
            ts.append(_ts(r["taken"]))
            st.append(_style(r["thumb"]))
        if vecs:
            refs[p["id"]] = (np.stack(vecs), ts, st)
    out = {}
    for r, v in cand:
        t = _ts(r["taken"])
        sty = None
        scores = []
        for pid, (M, ts, st) in refs.items():
            if (r["id"], pid) in decided:
                continue
            sims = M @ v
            top = float(np.mean(np.sort(sims)[-3:]))
            clip_s = max(0.0, min(1.0, (top - 0.70) / 0.25))
            ds = [abs(t - x) for x in ts if (t is not None and x is not None)]
            t_s = float(np.exp(-min(ds) / (45 * 60))) if ds else 0.0
            if sty is None:
                sty = _style(r["thumb"]) or False
            j = int(np.argmax(sims))
            s_s = _style_sim(sty or None, st[j])
            a = _archive(r["path"]) if str(r["path"]).startswith("zip://") else None
            if a and arch_tot.get(a):
                frac = arch_n.get((a, pid), 0) / arch_tot[a]
                scores.append((0.30 * clip_s + 0.15 * t_s + 0.15 * s_s + 0.40 * frac, pid))
            else:
                scores.append((0.45 * clip_s + 0.30 * t_s + 0.25 * s_s, pid))
        if not scores:
            continue
        scores.sort(reverse=True)
        best = scores[0]
        if best[0] >= min_score and (len(scores) == 1 or best[0] - scores[1][0] >= margin):
            out[r["id"]] = best
    db.x("DELETE FROM person_guess WHERE state=0")
    for iid, (s, pid) in out.items():
        db.c.execute("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,?,0)", (iid, pid, float(s)))
    db.commit()
    return len(out)


def _natkey(path):
    import re
    entry = str(path).split("!/", 1)[-1]
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", entry)]


def _clip_refs(db, pid, max_ref=40):
    rows = [r for r in db.person_images(pid)[:max_ref] if r["id"]]
    if not rows:
        return None
    ms = [_unit(blob_to_vec(r["clip"])) for r in db.q(f"SELECT clip FROM images WHERE clip IS NOT NULL AND id IN ({','.join('?' * len(rows))})",
                                                      [r["id"] for r in rows])]
    return np.stack(ms) if ms else None


@auto_edit
def assign_by_sequence(db, strong_gap=6, max_gap=12, floor=0.62, auto_floor=0.68):
    """File nén mang NHIỀU tên: ảnh của một người thường nằm liền nhau. Với ảnh chưa gán được bằng khuôn mặt (không có mặt, chụp từ phía sau,
    mặt quá nhỏ/nghiêng), dựa vào các ảnh đã nhận diện chắc chắn ở hai phía:
    - hai phía cùng một người và gần nhau: ứng viên mạnh; hai phía khác người (ranh giới): chọn bên giống hơn về nội dung (CLIP), màu/trang phục,
      giờ chụp; chênh lệch nhỏ thì bỏ qua;
    - mọi ứng viên còn phải giống các ảnh đã biết của người đó (CLIP) trên một ngưỡng, nên ảnh lạ trong vùng ấy không bị gán nhầm.
    Chỉ tự xác nhận khi chắc chắn; còn lại ghi thành gợi ý (person_guess state 0) để người dùng duyệt. Không ghi đè ảnh đã bị người dùng từ chối/xác nhận."""
    import os
    named = [(p["id"], fold(p["name"])) for p in db.q("SELECT id,name FROM persons WHERE name IS NOT NULL") if len(fold(p["name"])) >= 3]
    rows = db.q("SELECT id,path,thumb,clip,taken FROM images WHERE path LIKE 'zip://%'")
    by_arch = {}
    for r in rows:
        by_arch.setdefault(_archive_of(r["path"]), []).append(r)
    refs, written = {}, 0
    for arch, imgs in by_arch.items():
        af = " " + fold(os.path.basename(arch)) + " "
        pids = []
        for pid, pn in sorted(named, key=lambda x: -len(x[1])):
            if f" {pn} " in af and not any(pn in n for _, n in [(q, nn) for q, nn in named if q in pids]):
                pids.append(pid)
        if not pids:
            continue
        imgs.sort(key=lambda r: _natkey(r["path"]))
        label, skip = [], []
        for r in imgs:
            fs = db.q("SELECT person_id,locked FROM faces WHERE image_id=?", (r["id"],))
            mine = {f["person_id"] for f in fs if f["locked"] and f["person_id"] in pids}
            other = any(f["locked"] and f["person_id"] is not None and f["person_id"] not in pids for f in fs)
            label.append(next(iter(mine)) if len(mine) == 1 else (None if not mine else -1))
            skip.append(bool(mine) or other)
        anchors = [i for i, l in enumerate(label) if l not in (None, -1)]
        if not anchors:
            continue
        for pid in pids:
            if pid not in refs:
                refs[pid] = _clip_refs(db, pid)
        styles = {}

        def sty(i):
            if i not in styles:
                styles[i] = _style(imgs[i]["thumb"]) if imgs[i]["thumb"] else None
            return styles[i]

        def vec(i):
            return _unit(blob_to_vec(imgs[i]["clip"])) if imgs[i]["clip"] is not None else None

        def side_score(i, side_idx):
            """Độ giống của ảnh i với vài ảnh neo gần nhất ở một phía (CLIP + màu + giờ chụp)."""
            v = vec(i)
            if v is None or not side_idx:
                return 0.0
            near = sorted(side_idx, key=lambda j: abs(j - i))[:5]
            cs = sorted((float(v @ vec(j)) for j in near if vec(j) is not None), reverse=True)
            c = float(np.mean(cs[:3])) if cs else 0.0
            ss = float(np.mean([_style_sim(sty(i), sty(j)) for j in near]))
            t0 = _ts(imgs[i]["taken"])
            ds = [abs(t0 - _ts(imgs[j]["taken"])) for j in near if t0 is not None and _ts(imgs[j]["taken"]) is not None]
            tt = float(np.exp(-min(ds) / (30 * 60))) if ds else 0.0
            return 0.6 * c + 0.25 * ss + 0.15 * tt
        for i, r in enumerate(imgs):
            if skip[i]:
                continue
            prev = next((j for j in range(i - 1, -1, -1) if label[j] not in (None, -1)), None)
            nxt = next((j for j in range(i + 1, len(imgs)) if label[j] not in (None, -1)), None)
            Ls, strong = [], False
            if prev is not None and nxt is not None:
                gp, gn = i - prev, nxt - i
                if label[prev] == label[nxt] and gp + gn <= max_gap + 1:
                    Ls, strong = [label[prev]], gp + gn <= strong_gap + 1
                elif label[prev] != label[nxt]:
                    sp = side_score(i, [j for j in anchors if j < i and label[j] == label[prev]])
                    sn = side_score(i, [j for j in anchors if j > i and label[j] == label[nxt]])
                    if abs(sp - sn) >= 0.05:
                        Ls = [label[prev] if sp > sn else label[nxt]]
                    else:
                        Ls = [label[prev], label[nxt]]            # ảnh ở ranh giới, có thể có cả hai người: cho vào cả hai nhóm (chỉ là gợi ý)
            elif prev is not None and i - prev <= 3:
                Ls = [label[prev]]
            elif nxt is not None and nxt - i <= 3:
                Ls = [label[nxt]]
            if not Ls and len(pids) == 1 and anchors:                 # tệp chỉ mang tên một người: ảnh còn lại rất giống người đó cũng là gợi ý
                Ls = [pids[0]]
            v = vec(i)
            if not Ls or v is None:
                continue
            for L in Ls:
                if refs.get(L) is None:
                    continue
                sims = np.sort(refs[L] @ v)
                top = float(np.mean(sims[-3:]))
                if top < floor:
                    continue                                   # không giống các ảnh đã biết của người đó: không gán
                if db.one("SELECT 1 FROM person_guess WHERE image_id=? AND person_id=? AND state<>0", (r["id"], L)):
                    continue                                   # đã bị từ chối hoặc đã xác nhận
                db.c.execute("DELETE FROM person_guess WHERE image_id=? AND person_id=? AND state=0", (r["id"], L))
                state = 2 if (strong and len(Ls) == 1 and top >= auto_floor) else 0
                db.c.execute("INSERT INTO person_guess(image_id,person_id,score,state) VALUES(?,?,?,?)", (r["id"], L, top, state))
                written += 1
    db.commit()
    return written


def accept_guesses(db, pid, image_ids):
    for i in image_ids:
        fs = db.q("SELECT id, person_id FROM faces WHERE image_id=?", (i,))
        old = None
        if len(fs) == 1 and fs[0]["person_id"] not in (None, pid):      # ảnh một người: người dùng xác nhận tên này thì mặt chuyển sang tên này
            old = fs[0]["person_id"]
            db.c.execute("UPDATE faces SET person_id=?, locked=1, lsrc='user' WHERE id=?", (pid, fs[0]["id"]))
        db.c.execute("UPDATE person_guess SET state=2 WHERE person_id=? AND image_id=?", (pid, i))
        db.c.execute("UPDATE person_guess SET state=1 WHERE image_id=? AND person_id<>? AND state=0", (i, pid))
        if old is not None:                                              # tên cũ trở thành tên dự phòng (chưa xác nhận), chỉ dùng khi người dùng bảo tên mới không đúng
            db.c.execute("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,0.5,0)", (i, old))
    db.commit()


def reject_guesses(db, pid, image_ids):
    for i in image_ids:
        db.c.execute("UPDATE person_guess SET state=1 WHERE person_id=? AND image_id=?", (pid, i))
    db.commit()


def group_similar(ids, mat, thr=0.9, min_size=2):
    """Gom ảnh có nội dung tương tự (cùng cảnh, cùng góc nhìn). Trả về list các list id."""
    if len(ids) == 0:
        return []
    m = _unit(mat.astype(np.float32))
    leaders, groups = [], []
    for i in range(len(ids)):
        if leaders:
            s = m[leaders] @ m[i]
            j = int(np.argmax(s))
            if s[j] >= thr:
                groups[j].append(ids[i])
                continue
        leaders.append(i)
        groups.append([ids[i]])
    groups = [g for g in groups if len(g) >= min_size]
    groups.sort(key=len, reverse=True)
    return groups


def rank(ids, mat, query_vec, top=300, min_sim=None):
    s = _unit(mat.astype(np.float32)) @ _unit(np.asarray(query_vec, np.float32))
    order = np.argsort(-s)[:top]
    return [(ids[i], float(s[i])) for i in order if min_sim is None or s[i] >= min_sim]


def prototype(mat_rows):
    return _unit(np.mean(_unit(mat_rows.astype(np.float32)), axis=0))

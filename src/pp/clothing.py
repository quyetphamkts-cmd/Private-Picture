"""Phân loại ảnh theo trang phục bằng CLIP (so ảnh với các câu mô tả, không cần huấn luyện thêm). Chạy hoàn toàn trên máy.
Kết quả chỉ mang tính gợi ý để lọc ảnh; ảnh nhỏ, nhiều người mặc khác nhau hoặc góc chụp lạ có thể bị xếp sai."""
import numpy as np

from .db import blob_to_vec

# mã, tên hiển thị, các câu mô tả (tiếng Anh vì CLIP hiểu tiếng Anh tốt nhất)
CATS = [
    ("long", "Quần áo dài", ["a person wearing long pants and a long sleeve shirt", "a person wearing a long dress",
                              "a woman wearing an ao dai, a vietnamese traditional long dress", "a person fully dressed in long clothes"]),
    ("short", "Quần áo ngắn", ["a person wearing shorts and a t-shirt", "a person wearing a short skirt",
                                "a person in short sleeves and short pants", "a person in light summer clothes"]),
    ("swim", "Bikini, đồ bơi", ["a person wearing a bikini", "a woman in a swimsuit at the beach", "a person in swimwear by the pool",
                                  "a man wearing swim trunks"]),
    ("lingerie", "Nội y (tính là Dressed)", ["a woman wearing lingerie", "a person in underwear", "a woman in a bra and panties", "a model posing in sexy lingerie"]),
    ("topless", "Cởi trần", ["a shirtless man", "a person with a bare chest and no shirt", "a topless person"]),
    ("nude", "Không mặc gì", ["a nude person", "a naked person", "a photo of a naked body"]),
    ("portrait", "Chân dung (không thấy trang phục)", ["a close-up portrait of a human face", "a headshot photo of a person",
                                                      "a selfie of a person's face"]),
    ("none", "Không có người", ["a photo of a landscape", "a photo of a building", "a photo of an object with no people",
                                "a photo of food", "a photo of a cat", "a photo of a dog", "a photo of an animal", "a photo of a pet",
                                "a screenshot or a document"]),
]
NAMES = {c: n for c, n, _ in CATS}
MIN_PROB = 0.40        # xác suất tối thiểu để gán loại (nếu thấp hơn: chưa rõ)
SCALE = 100.0          # hệ số nhiệt của CLIP khi chuyển độ giống thành xác suất


def _unit(a):
    return a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-9)


def classify(mat, text_vecs):
    """mat: n×d vectơ ảnh; text_vecs: danh sách vectơ câu mô tả theo thứ tự CATS (phẳng). Trả về (chỉ số loại tốt nhất, xác suất) mỗi ảnh."""
    t = _unit(np.asarray(text_vecs, np.float32))
    sims = _unit(mat.astype(np.float32)) @ t.T
    cols, k = [], 0
    for _, _, prompts in CATS:
        cols.append(sims[:, k:k + len(prompts)].max(axis=1))
        k += len(prompts)
    logits = SCALE * np.stack(cols, axis=1)
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    p /= p.sum(axis=1, keepdims=True)
    best = p.argmax(axis=1)
    return best, p[np.arange(len(p)), best]


# Bộ lọc đơn giản cho người dùng: chỉ hai nhóm. Ảnh không có người hoặc chỉ có mặt thì không thuộc nhóm nào.
GROUPS = [("cloth", "Dressed"), ("nude", "Naked")]
GROUP_NAMES = dict(GROUPS)
_CLOTH_CATS = ("long", "short", "swim", "lingerie")      # đồ dài, đồ ngắn, bikini, đồ bơi, nội y: đều tính là Dressed
_NO_CLOTH_CATS = ("nude", "topless")            # không mặc gì hoặc cởi trần: Nude
NO_CLOTH_MIN = 0.45
CLOTH_MIN = 0.50


def probabilities(mat, text_vecs):
    """Xác suất của từng loại trong CATS cho mỗi ảnh (n × số loại)."""
    t = _unit(np.asarray(text_vecs, np.float32))
    sims = _unit(mat.astype(np.float32)) @ t.T
    cols, k = [], 0
    for _, _, prompts in CATS:
        cols.append(sims[:, k:k + len(prompts)].max(axis=1))
        k += len(prompts)
    logits = SCALE * np.stack(cols, axis=1)
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    return p / p.sum(axis=1, keepdims=True)


def group_of(p):
    """Từ xác suất các loại (một ảnh) ra nhóm 'cloth' / 'nocloth' / None. Cộng xác suất các loại cùng nhóm nên không phụ thuộc loại nào nhỉnh nhất."""
    idx = {c: i for i, (c, _, _) in enumerate(CATS)}
    no = sum(float(p[idx[c]]) for c in _NO_CLOTH_CATS)
    cl = sum(float(p[idx[c]]) for c in _CLOTH_CATS)
    if no >= NO_CLOTH_MIN:
        return "nude", no
    if cl >= CLOTH_MIN:
        return "cloth", cl
    return None, max(no, cl)


def analyze(db, text_fn, redo=False):
    """Phân loại các ảnh (chưa có kết quả, hoặc tất cả nếu redo). text_fn(câu) -> vectơ CLIP của câu. Trả về số ảnh đã phân loại."""
    if db.get_meta("cloth_v") != "2":                  # bản cũ chỉ có 2 nhóm: đổi tên 'không mặc đồ' thành Nude và phân loại lại (trừ ảnh bạn đã tự phân loại)
        db.c.execute("UPDATE cloth_group SET grp='nude' WHERE grp='nocloth'")
        db.c.execute("UPDATE cloth_manual SET grp='nude' WHERE grp='nocloth'")
        db.commit()
        redo = True
        db.set_meta("cloth_v", "2")
    rows = db.q("SELECT id,clip FROM images WHERE clip IS NOT NULL" if redo else
                "SELECT id,clip FROM images WHERE clip IS NOT NULL AND id NOT IN (SELECT image_id FROM cloth_group)")
    if not rows:
        return 0
    prompts = [p for _, _, ps in CATS for p in ps]
    tv = [text_fn(p) for p in prompts]
    mat = np.stack([blob_to_vec(r["clip"]) for r in rows])
    P = probabilities(mat, tv)
    manual = {r["image_id"] for r in db.q("SELECT image_id FROM cloth_manual")}          # ảnh người dùng đã tự phân loại: không ghi đè
    for r, p in zip(rows, P):
        if r["id"] in manual:
            continue
        b = int(p.argmax())
        db.c.execute("INSERT OR REPLACE INTO clothing(image_id,cat,prob) VALUES(?,?,?)", (r["id"], CATS[b][0] if p[b] >= MIN_PROB else None, float(p[b])))
        g, gp = group_of(p)
        db.c.execute("INSERT OR REPLACE INTO cloth_group(image_id,grp,p) VALUES(?,?,?)", (r["id"], g, gp))
    db.commit()
    return len(rows)


def group_counts(db, image_ids=None):
    """{'cloth': n, 'nude': n} cho toàn thư viện hoặc cho một tập ảnh."""
    out = {}
    if image_ids is None:
        for r in db.q("SELECT grp,COUNT(*) n FROM cloth_group WHERE grp IS NOT NULL GROUP BY grp"):
            out[r["grp"]] = r["n"]
        return out
    ids = list(image_ids)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in db.q(f"SELECT grp,COUNT(*) n FROM cloth_group WHERE grp IS NOT NULL AND image_id IN ({','.join('?' * len(part))}) GROUP BY grp", part):
            out[r["grp"]] = out.get(r["grp"], 0) + r["n"]
    return out


UNCLEAR = ("unclear", "Chưa rõ")          # chân dung, ảnh không thấy trang phục, hoặc máy chưa đủ chắc: không thuộc mặc đồ hay không mặc đồ


def known_ids(db):
    return {r["image_id"] for r in db.q("SELECT image_id FROM cloth_group WHERE grp IS NOT NULL")}


def options(counts, total):
    """Các lựa chọn của bộ lọc (mã, nhãn có số ảnh); cộng lại luôn đúng bằng tổng, ảnh còn lại nằm ở 'Chưa rõ'."""
    out = [(code, f"{name}  ({counts[code]})") for code, name in GROUPS if counts.get(code)]
    rest = total - sum(counts.get(code, 0) for code, _ in GROUPS)
    if rest > 0 and out:
        out.append((UNCLEAR[0], f"{UNCLEAR[1]}  ({rest})"))
    return out


def ids_in_group(db, grp):
    return {r["image_id"] for r in db.q("SELECT image_id FROM cloth_group WHERE grp=?", (grp,))}


def counts(db):
    """{mã loại: số ảnh}."""
    return {r["cat"]: r["n"] for r in db.q("SELECT cat,COUNT(*) n FROM clothing WHERE cat IS NOT NULL GROUP BY cat")}


def remove_clothing_labels(db):
    """Phân loại trang phục không còn là nhãn: gỡ các nhãn 'Mặc đồ' / 'Không mặc đồ' / 'Nude' / 'Nội y' mà các bản trước đã tự tạo (một lần)."""
    if db.get_meta("cloth_labels_removed") == "1":
        return
    for name in ("Mặc đồ", "Không mặc đồ", "Nude", "Nội y"):
        for r in db.q("SELECT id FROM labels WHERE name=?", (name,)):
            db.c.execute("DELETE FROM label_images WHERE label_id=?", (r["id"],))
            db.c.execute("DELETE FROM labels WHERE id=?", (r["id"],))
    db.commit()
    db.set_meta("cloth_labels_removed", "1")


def set_manual(db, image_ids, grp):
    """Người dùng tự phân loại ảnh: grp là 'cloth', 'nude' hoặc None (chưa rõ). Kết quả này không bị lần phân tích tự động ghi đè."""
    for i in image_ids:
        db.c.execute("INSERT OR REPLACE INTO cloth_manual(image_id,grp) VALUES(?,?)", (i, grp))
        db.c.execute("INSERT OR REPLACE INTO cloth_group(image_id,grp,p) VALUES(?,?,1.0)", (i, grp))
    db.commit()


def clear_manual(db, image_ids):
    """Bỏ phân loại tay: ảnh quay lại để lần phân tích tự động xử lý."""
    for i in image_ids:
        db.c.execute("DELETE FROM cloth_manual WHERE image_id=?", (i,))
        db.c.execute("DELETE FROM cloth_group WHERE image_id=?", (i,))
    db.commit()


def menu_options(db, image_ids):
    """Các lựa chọn phân loại hiện trong menu chuột phải: bỏ nhóm mà các ảnh đã chọn đang ở (nếu tất cả cùng một nhóm), tránh nhầm lẫn.
    Trả về danh sách (mã, tên); mã None là 'Chưa rõ'."""
    cur = set()
    for i in image_ids:
        r = db.one("SELECT grp FROM cloth_group WHERE image_id=?", (i,))
        cur.add(r["grp"] if r else None)
    only = next(iter(cur)) if len(cur) == 1 else "mixed"
    return [(c, n) for c, n in (("cloth", "Dressed"), ("nude", "Naked"), (None, "Chưa rõ")) if c != only]

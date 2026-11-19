"""Tự phân loại ảnh theo các nhãn bạn đã gắn: so nội dung (CLIP) của ảnh chưa có nhãn với các ảnh mẫu của từng nhãn."""
import time

import numpy as np

from .db import blob_to_vec

MIN_EXAMPLES = 3
SUGGEST_MIN = 0.80       # mức giống tối thiểu để được gợi ý
AUTO_MIN = 0.92          # mức giống để tự gán không cần hỏi
MARGIN = 0.03            # nhãn tốt nhất phải hơn nhãn thứ hai ít nhất chừng này
from .cluster import auto_edit as _auto_edit

FAVORITE = "Yêu thích"   # nhãn ngôi sao: chỉ do bạn tự bấm, không bao giờ tự gán hay gợi ý


def _unit(a):
    return a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-9)


def suggest(db, min_sim=SUGGEST_MIN, margin=MARGIN, min_examples=MIN_EXAMPLES, k=3):
    """Cho mỗi ảnh CHƯA có nhãn nào: nhãn giống nhất (trung bình k ảnh mẫu gần nhất của nhãn, nên nhãn nhiều kiểu ảnh vẫn đúng).
    Bỏ qua cặp (ảnh, nhãn) mà người dùng đã từng gỡ. Trả về {id nhãn: [(id ảnh, độ giống)] giảm dần}."""
    rows = db.q("SELECT id,clip FROM images WHERE clip IS NOT NULL")
    if not rows:
        return {}
    ids = np.array([r["id"] for r in rows])
    mat = _unit(np.stack([blob_to_vec(r["clip"]) for r in rows]).astype(np.float32))
    pos = {int(i): k_ for k_, i in enumerate(ids)}
    labeled = {r["image_id"] for r in db.q("SELECT DISTINCT image_id FROM label_images")}
    cand_idx = np.array([k_ for k_, i in enumerate(ids) if int(i) not in labeled])
    if len(cand_idx) == 0:
        return {}
    cand = mat[cand_idx]
    reject = {(r["label_id"], r["image_id"]) for r in db.q("SELECT label_id,image_id FROM label_reject")}
    labels = []
    for lab in db.labels():
        if lab["name"] == FAVORITE:
            continue
        mem = [pos[i] for i in db.label_ids(lab["id"]) if i in pos]
        if len(mem) >= min_examples:
            labels.append((lab["id"], mat[mem]))
    if not labels:
        return {}
    score = np.zeros((len(cand), len(labels)), np.float32)
    for j, (lid, M) in enumerate(labels):
        s = cand @ M.T
        kk = min(k, s.shape[1])
        score[:, j] = np.sort(s, axis=1)[:, -kk:].mean(axis=1)
    out = {}
    for r in range(len(cand)):
        order = np.argsort(-score[r])
        best = float(score[r, order[0]])
        second = float(score[r, order[1]]) if len(order) > 1 else 0.0
        if best < min_sim or (len(order) > 1 and best - second < margin):
            continue
        lid = labels[int(order[0])][0]
        iid = int(ids[cand_idx[r]])
        if (lid, iid) in reject:
            continue
        out.setdefault(lid, []).append((iid, best))
    for v in out.values():
        v.sort(key=lambda x: -x[1])
    return out


def apply(db, label_id, image_ids, auto=False):
    """Gắn nhãn. auto=True: ghi nhận để có thể hoàn tác hàng loạt."""
    now = time.time()
    n = 0
    for i in image_ids:
        cur = db.c.execute("INSERT OR IGNORE INTO label_images VALUES(?,?)", (label_id, i))
        if cur.rowcount:
            n += 1
            if auto:
                db.c.execute("INSERT OR REPLACE INTO label_auto(label_id,image_id,ts) VALUES(?,?,?)", (label_id, i, now))
    db.commit()
    return n


@_auto_edit
def strip_favorite_auto(db):
    """Gỡ ngôi sao mà app từng TỰ gán nhầm (do coi 'Yêu thích' như một nhãn thường và gán theo độ giống nội dung). Ngôi sao bạn tự bấm thì giữ nguyên."""
    lab = db.one("SELECT id FROM labels WHERE name=?", (FAVORITE,))
    if not lab:
        return 0
    rows = db.q("SELECT image_id FROM label_auto WHERE label_id=?", (lab["id"],))
    for r in rows:
        db.c.execute("DELETE FROM label_images WHERE label_id=? AND image_id=?", (lab["id"], r["image_id"]))
    db.c.execute("DELETE FROM label_auto WHERE label_id=?", (lab["id"],))
    db.commit()
    return len(rows)


@_auto_edit
def run_auto(db, thr=AUTO_MIN):
    """Tự gán nhãn cho các ảnh rất chắc chắn (sau mỗi lần quét). Trả về số ảnh đã gán."""
    strip_favorite_auto(db)
    total = 0
    for lid, lst in suggest(db, min_sim=thr).items():
        total += apply(db, lid, [i for i, s in lst if s >= thr], auto=True)
    return total


def undo_auto(db):
    """Gỡ mọi nhãn đã được tự gán (và ghi nhớ để lần sau không tự gán lại các ảnh đó)."""
    rows = db.q("SELECT label_id,image_id FROM label_auto")
    for r in rows:
        db.c.execute("DELETE FROM label_images WHERE label_id=? AND image_id=?", (r["label_id"], r["image_id"]))
        db.c.execute("INSERT OR IGNORE INTO label_reject VALUES(?,?)", (r["label_id"], r["image_id"]))
    db.c.execute("DELETE FROM label_auto")
    db.commit()
    return len(rows)


def reject(db, label_id, image_ids):
    for i in image_ids:
        db.c.execute("INSERT OR IGNORE INTO label_reject VALUES(?,?)", (label_id, i))
        db.c.execute("DELETE FROM label_auto WHERE label_id=? AND image_id=?", (label_id, i))
    db.commit()

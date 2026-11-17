"""Nhận biết tranh vẽ, hình minh họa, hoạt hình, áp phích (không phải ảnh chụp người thật) bằng CLIP, để khuôn mặt trong đó không bị gom thành "người".
Chỉ là gợi ý tự động: ảnh nghi là tranh vẽ bị bỏ ra khỏi danh sách Người (mặt đã bạn tự đặt tên/khóa thì giữ nguyên)."""
import numpy as np

from .db import blob_to_vec

ART = ["a painting", "an illustration", "a drawing", "a cartoon", "an anime character", "a digital artwork", "a poster with a stylized portrait",
       "a vintage artwork of a woman's face", "a comic book page"]
PHOTO = ["a photograph of a real person taken with a camera", "a candid photo of people", "a studio photo of a model", "a selfie",
         "a photo of a person outdoors"]
SCALE = 100.0
MIN_ART = 0.80


def _unit(a):
    return a / np.maximum(np.linalg.norm(a, axis=-1, keepdims=True), 1e-9)


def art_prob(mat, text_fn):
    t = _unit(np.stack([np.asarray(text_fn(p), np.float32) for p in ART + PHOTO]))
    sims = _unit(mat.astype(np.float32)) @ t.T
    a, ph = sims[:, :len(ART)].max(axis=1), sims[:, len(ART):].max(axis=1)
    return 1.0 / (1.0 + np.exp(np.clip(-SCALE * (a - ph), -50, 50)))


def detect(db, text_fn, redo=False):
    """Đánh dấu ảnh nghi là tranh vẽ và bỏ các khuôn mặt chưa khóa của ảnh đó khỏi nhóm người. Trả về số ảnh bị đánh dấu."""
    rows = db.q("SELECT id,clip FROM images WHERE clip IS NOT NULL" if redo else
                "SELECT id,clip FROM images WHERE clip IS NOT NULL AND id NOT IN (SELECT image_id FROM image_art)")
    if not rows:
        return 0
    P = art_prob(np.stack([blob_to_vec(r["clip"]) for r in rows]), text_fn)
    n = 0
    for r, p in zip(rows, P):
        is_art = int(p >= MIN_ART)
        db.c.execute("INSERT OR REPLACE INTO image_art(image_id,p,art) VALUES(?,?,?)", (r["id"], float(p), is_art))
        if is_art:
            db.c.execute("UPDATE faces SET person_id=NULL WHERE image_id=? AND locked=0", (r["id"],))
            n += 1
    db.commit()
    return n

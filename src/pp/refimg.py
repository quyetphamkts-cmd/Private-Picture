"""Ảnh tham chiếu từ internet cho những người đã có tên (đa phần là người nổi tiếng): app CHỈ gửi TÊN người ra ngoài (Wikidata, Wikimedia Commons và tùy chọn Google
Programmable Search nếu bạn nhập khóa), không bao giờ gửi ảnh nào trong thư viện. Từ ảnh tải về app tạo vectơ khuôn mặt rồi bỏ ảnh; chỉ lưu vectơ.
Kiểm tra chặt để không dùng nhầm người khác: mỗi ảnh phải có MỘT khuôn mặt nổi bật, và các mặt phải khớp nhau (đa số đồng thuận), không đủ thì bỏ."""
import io
import json
import time
import urllib.parse
import urllib.request

import numpy as np

from .db import blob_to_vec, vec_to_blob

UA = {"User-Agent": "PrivatePicture/1.0 (reference-portraits; contact: app user)"}
COMMONS = "https://commons.wikimedia.org"
WIKIDATA = "https://www.wikidata.org"
MAX_BYTES = 4_000_000
MIN_REFS = 3
SIM_THR = 0.45                                # hai mặt cùng người (ArcFace) thường > 0.45


def _get(url, timeout=15, binary=False, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, headers=UA)
    with opener(req, timeout=timeout) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("ảnh quá lớn")
    return data if binary else json.loads(data.decode("utf-8"))


def _filepath(title):
    t = title.replace("File:", "", 1)
    return f"{COMMONS}/wiki/Special:FilePath/{urllib.parse.quote(t.replace(' ', '_'))}?width=700"


def commons_urls(name, limit=8, get=_get):
    """Ảnh chân dung của người nổi tiếng trên Wikimedia Commons (hợp pháp, đã kiểm duyệt). Chỉ chấp nhận thực thể Wikidata là con người."""
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": name, "language": "en", "limit": 3, "format": "json", "type": "item"})
    hits = get(f"{WIKIDATA}/w/api.php?{q}").get("search", [])
    for h in hits:
        if (h.get("label") or "").strip().lower() != name.strip().lower() and name.strip().lower() not in [a.lower() for a in h.get("aliases", [])
                                                                                                           if isinstance(a, str)]:
            continue                                                       # tên phải khớp đúng, không đoán gần giống
        qid = h["id"]
        ent = get(f"{WIKIDATA}/w/api.php?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"}))
        claims = ent["entities"][qid].get("claims", {})
        inst = [c["mainsnak"]["datavalue"]["value"]["id"] for c in claims.get("P31", []) if c["mainsnak"].get("datavalue")]
        if "Q5" not in inst:
            continue                                                       # không phải con người
        files = [c["mainsnak"]["datavalue"]["value"] for c in claims.get("P18", []) if c["mainsnak"].get("datavalue")]
        urls = [_filepath(f) for f in files]
        cat = [c["mainsnak"]["datavalue"]["value"] for c in claims.get("P373", []) if c["mainsnak"].get("datavalue")]
        if cat and len(urls) < limit:
            m = get(f"{COMMONS}/w/api.php?" + urllib.parse.urlencode({"action": "query", "list": "categorymembers", "cmtitle": "Category:" + cat[0], "cmtype": "file",
                                                                     "cmlimit": 40, "format": "json"}))
            for it in m.get("query", {}).get("categorymembers", []):
                t = it["title"]
                if t.lower().endswith((".jpg", ".jpeg", ".png")):
                    urls.append(_filepath(t))
        return urls[:limit]
    return []


def web_urls(name, key, cx, limit=8, get=_get):
    """Tìm ảnh trên web bằng Google Programmable Search (cần khóa và mã công cụ tìm kiếm do bạn tạo); chỉ gửi tên người."""
    if not key or not cx:
        return []
    q = urllib.parse.urlencode({"key": key, "cx": cx, "q": f'"{name}" portrait', "searchType": "image", "num": 10, "imgType": "face", "safe": "off"})
    try:
        j = get(f"https://www.googleapis.com/customsearch/v1?{q}")
    except Exception:
        return []
    return [it["link"] for it in j.get("items", []) if it.get("link")][:limit]


def face_vectors(urls, engine, get=_get):
    """Vectơ của khuôn mặt nổi bật trong từng ảnh (bỏ ảnh nhiều người, mặt nhỏ, mặt mờ). Ảnh chỉ nằm trong bộ nhớ, không lưu."""
    from PIL import Image, ImageOps
    out = []
    for u in urls:
        try:
            data = get(u, binary=True)
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            im.thumbnail((1000, 1000))
            fs = engine.process(np.asarray(im))
        except Exception:
            continue
        fs = sorted(fs, key=lambda f: -(f["box"][2] * f["box"][3]))
        if not fs or fs[0]["score"] < 0.85 or fs[0]["px"] < 60:
            continue
        if len(fs) > 1 and fs[0]["box"][2] * fs[0]["box"][3] < 1.8 * fs[1]["box"][2] * fs[1]["box"][3]:
            continue                                                      # nhiều người ngang nhau: không biết ai là chủ thể
        out.append(np.asarray(fs[0]["vec"], np.float32))
    return out


def consistent(vecs, thr=SIM_THR, min_n=MIN_REFS):
    """Giữ lại nhóm mặt đồng thuận (nhiều mặt khớp nhau nhất); ít hơn min_n thì bỏ hết (nguy cơ lẫn người khác)."""
    if len(vecs) < min_n:
        return []
    v = np.stack([x / max(float(np.linalg.norm(x)), 1e-9) for x in vecs])
    sims = v @ v.T
    best = int(np.argmax((sims >= thr).sum(axis=1)))
    keep = [i for i in range(len(v)) if sims[best, i] >= thr]
    return [v[i] for i in keep] if len(keep) >= min_n else []


def fetch_person(db, pid, name, engine, key="", cx="", get=_get, pause=1.0):
    """Tải ảnh tham chiếu của một người, kiểm tra đồng thuận rồi lưu vectơ (thay bản cũ). Trả về số vectơ lưu."""
    try:
        urls = commons_urls(name, get=get)
    except Exception:
        urls = []
    vecs = consistent(face_vectors(urls, engine, get=get)) if urls else []
    src = "commons"
    if len(vecs) < MIN_REFS and key and cx:
        time.sleep(pause)
        vecs = consistent(face_vectors(web_urls(name, key, cx, get=get), engine, get=get))
        src = "web"
    db.c.execute("DELETE FROM person_ref WHERE person_id=?", (pid,))
    for v in vecs:
        db.c.execute("INSERT INTO person_ref(person_id,dim,vec,src) VALUES(?,?,?,?)", (pid, int(v.shape[0]), vec_to_blob(v), src))
    db.c.execute("INSERT OR REPLACE INTO ref_state(person_id,ts,n,status) VALUES(?,?,?,?)", (pid, time.time(), len(vecs), "ok" if vecs else "none"))
    db.commit()
    return len(vecs)


def run(db, engine, stop=lambda: False, max_people=15, get=_get, pause=1.0, recheck_days=45):
    """Chạy nền: người đã đặt tên mà chưa thử (hoặc thử đã lâu mà chưa có ảnh) thì tải ảnh tham chiếu; sau đó áp dụng vào cảnh báo / gợi ý tên."""
    from . import cluster
    key, cx = db.get_meta("refimg_key", ""), db.get_meta("refimg_cx", "")
    now = time.time()
    done = {r["person_id"]: r for r in db.q("SELECT person_id,ts,n FROM ref_state")}
    todo = []
    for p in db.q("SELECT id,name FROM persons WHERE name IS NOT NULL AND hidden=0 ORDER BY id"):
        st = done.get(p["id"])
        if st is None or (st["n"] == 0 and now - st["ts"] > recheck_days * 86400):
            todo.append(p)
    n = 0
    for p in todo[:max_people]:
        if stop():
            break
        try:
            n += 1 if fetch_person(db, p["id"], p["name"], engine, key, cx, get=get, pause=pause) else 0
        except Exception:
            pass
        time.sleep(pause)
    try:
        cluster.apply_refs(db)
    except Exception:
        pass
    return n

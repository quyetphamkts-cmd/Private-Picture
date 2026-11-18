"""Đồng bộ thư viện sang thư mục Google Drive (Drive for Desktop) để app Android đọc được khi PC tắt.

Mọi thứ trong thư mục đồng bộ được mã hóa AES-256-GCM bằng khóa suy ra từ MẬT KHẨU ĐỒNG BỘ (scrypt), Google không đọc được.
Định dạng: xem docs/SYNC_FORMAT.md."""
import base64
import hashlib
import json
import os
import time
import uuid

from . import paths, zipimg
from .secure import SEC, WrongPassword, derive, seal, unseal, encode_recovery, decode_recovery

FOLDER = "PrivatePicture-Sync"
CHECK = b"PPSYNC1"
MAX_ORIG = 120 * 1024 * 1024


def uid_of(path, mtime, size):
    """Mã ổn định của ảnh (không phụ thuộc id nội bộ): dùng đặt tên tệp và để điện thoại tham chiếu."""
    return hashlib.sha1(f"{path}|{int(mtime or 0)}|{size or 0}".encode("utf-8")).hexdigest()[:20]


def root_of(dest):
    return os.path.join(dest, FOLDER)


def setup(dest, password):
    """Tạo thư mục đồng bộ nếu chưa có (hoặc kiểm tra mật khẩu nếu đã có). Trả về khóa."""
    root = root_of(dest)
    os.makedirs(os.path.join(root, "thumbs"), exist_ok=True)
    os.makedirs(os.path.join(root, "orig"), exist_ok=True)
    os.makedirs(os.path.join(root, "inbox"), exist_ok=True)
    meta = os.path.join(root, "sync.json")
    if os.path.exists(meta):
        j = json.load(open(meta, encoding="utf-8"))
        key = derive(password, base64.b64decode(j["salt"]))
        if unseal(key, base64.b64decode(j["check"])) != CHECK:      # ném WrongPassword nếu sai
            raise WrongPassword()
        return key
    salt = os.urandom(16)
    key = derive(password, salt)
    json.dump({"v": 1, "kdf": "scrypt", "n": 32768, "r": 8, "p": 1, "salt": base64.b64encode(salt).decode(),
               "check": base64.b64encode(seal(key, CHECK)).decode()}, open(meta, "w", encoding="utf-8"))
    return key


def _write(path, data):
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


class Cancelled(Exception):
    pass


def read_original(db, row, vault=None, zip_pw=None):
    if row["vid"]:
        if vault is None:
            raise RuntimeError("Kho đang khóa")
        return vault.read(row["vid"])
    if zipimg.is_zip_path(row["path"]):
        return zipimg.read(row["path"], (zip_pw or {}).get(zipimg.archive_of(row["path"])))
    with open(row["path"], "rb") as f:
        return f.read()


def publish_app(dest):
    """Đặt bản app Android mới nhất vào thư mục đồng bộ để điện thoại tự cập nhật qua Drive (không cần đưa mã GitHub lên điện thoại).
    Cần mã truy cập cập nhật đã nhập trong ứng dụng; không có mã hoặc không có mạng thì bỏ qua. Trả về phiên bản đã đặt hoặc None."""
    from . import updater
    tok = updater.load_token()
    if not tok:
        return None
    d = os.path.join(root_of(dest), "app")
    os.makedirs(d, exist_ok=True)
    vj, apk = os.path.join(d, "version.json"), os.path.join(d, "PrivatePicture-Android.apk")
    try:
        have = json.load(open(vj, encoding="utf-8")).get("code", 0) if os.path.exists(vj) and os.path.exists(apk) else 0
    except Exception:
        have = 0
    info = updater.latest_android(tok)
    if info["code"] <= have:
        return None
    tmp = apk + ".dl"
    updater.download(info, tok, tmp)
    os.replace(tmp, apk)
    json.dump({"version": info["version"], "code": info["code"], "size": info["size"]}, open(vj, "w", encoding="utf-8"))
    return info["version"]


def publish_covers(db, root, key, uids, persons):
    """Ảnh profile mỗi người, tự động hoàn toàn: PC chọn ảnh theo nguyên tắc ảnh đại diện (Naked, đủ thân, nhìn thẳng, không lặp), cắt từ rốn lên bằng ảnh gốc
    (nét) rồi mã hóa đặt vào thư mục covers. Tệp tên '<mã người>-<chữ ký>.pe' nên khi PC đổi ảnh thì tên đổi, điện thoại chỉ tải tệp mới.
    Trả về {mã người: chữ ký} để ghi vào index."""
    from . import cover
    d = os.path.join(root, "covers")
    os.makedirs(d, exist_ok=True)
    out, keep = {}, set()
    for p in persons:
        try:
            c = db.cover_pick(p["id"], "navel")
        except Exception:
            c = None
        if not c:                                                  # không có ảnh cá nhân nào dùng được: dùng khuôn mặt đã cắt sẵn của chính người đó (chỉ có đúng một người)
            ft = db.person_cover(p["id"])
            if not ft:
                continue
            sig = hashlib.sha1(f"face|{ft}".encode()).hexdigest()[:10]
            name = f'{p["id"]}-{sig}.pe'
            path = os.path.join(d, name)
            if not os.path.exists(path):
                try:
                    from .secure import SEC
                    _write(path, seal(key, SEC.read_file(ft)))
                except Exception:
                    continue
            keep.add(name)
            out[str(p["id"])] = sig
            continue
        if c["iid"] not in uids:
            continue
        box = (c["x"], c["y"], c["w"], c["h"])
        sig = hashlib.sha1(f'{uids[c["iid"]]}|{box[0]:.4f},{box[1]:.4f},{box[2]:.4f},{box[3]:.4f}'.encode()).hexdigest()[:10]
        name = f'{p["id"]}-{sig}.pe'
        path = os.path.join(d, name)
        if not os.path.exists(path):
            b = cover.navel_bytes(c["thumb"], box, c["path"], 420, lambda iid=c["iid"], pth=c["path"]: read_original_any(db, {"id": iid, "path": pth}))
            if not b:
                continue
            _write(path, seal(key, b))
        keep.add(name)
        out[str(p["id"])] = sig
    for fn in os.listdir(d):
        if fn.endswith(".pe") and fn not in keep:
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass
    return out


def publish_clip(db, root, key, uids):
    """Đưa vectơ nội dung (CLIP) của từng ảnh lên Drive (mã hóa, dạng float16) để điện thoại tự chọn ảnh tương tự và gợi ý nhãn.
    Định dạng: b'PPV1' + n(int32) + dim(int32) + n mã ảnh (20 byte ASCII) + ma trận n×dim float16 (little-endian), đã chuẩn hóa độ dài."""
    import struct
    import numpy as np
    from .db import blob_to_vec
    rows = [r for r in db.q("SELECT id,clip FROM images WHERE clip IS NOT NULL AND thumb IS NOT NULL") if r["id"] in uids]
    if not rows:
        return False
    codes = [uids[r["id"]] for r in rows]
    sig = hashlib.sha1("|".join(sorted(codes)).encode()).hexdigest()
    path = os.path.join(root, "clip.pe")
    if os.path.exists(path) and db.get_meta("sync_clip_sig") == sig:
        return False
    m = np.stack([blob_to_vec(r["clip"]) for r in rows]).astype(np.float32)
    m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    body = b"PPV1" + struct.pack("<ii", len(rows), m.shape[1]) + b"".join(c.encode("ascii").ljust(20, b"\0")[:20] for c in codes) + m.astype("<f2").tobytes()
    _write(path, seal(key, body))
    db.set_meta("sync_clip_sig", sig)
    return True


def run(db, dest, password, include_originals=True, vault=None, zip_pw=None, progress=lambda d, t, s: None, cancel=lambda: False):
    """Đẩy thư viện lên thư mục đồng bộ (tăng dần: tệp đã có thì bỏ qua). Trả về thống kê."""
    key = setup(dest, password)
    root = root_of(dest)
    stats = {"thumbs": 0, "orig": 0, "removed": 0, "errors": 0, "skipped_big": 0, "inbox": 0}
    stats["inbox"] = apply_inbox(db, dest, key)
    try:
        stats["app"] = publish_app(dest)
    except Exception:
        stats["app"] = None
    imgs = db.q("SELECT id,path,mtime,size,w,h,taken,thumb,vid,name FROM images WHERE thumb IS NOT NULL")
    total, done = len(imgs), 0
    uids = {}
    entries = []
    for r in imgs:
        if cancel():
            raise Cancelled()
        u = uid_of(r["path"], r["mtime"], r["size"])
        uids[r["id"]] = u
        done += 1
        progress(done, total, r["name"] or os.path.basename(r["path"]))
        tp = os.path.join(root, "thumbs", u + ".pe")
        if not os.path.exists(tp):
            try:
                _write(tp, seal(key, SEC.read_file(r["thumb"])))
                stats["thumbs"] += 1
            except Exception:
                stats["errors"] += 1
                continue
        has_orig = False
        op = os.path.join(root, "orig", u + ".pe")
        if include_originals:
            if os.path.exists(op):
                has_orig = True
            elif (r["size"] or 0) > MAX_ORIG:
                stats["skipped_big"] += 1
            else:
                try:
                    _write(op, seal(key, read_original(db, r, vault, zip_pw)))
                    stats["orig"] += 1
                    has_orig = True
                except Exception:
                    stats["errors"] += 1
        entries.append({"uid": u, "name": r["name"] or os.path.basename(r["path"].split("!/")[-1]), "taken": r["taken"],
                        "w": r["w"], "h": r["h"], "size": r["size"], "orig": has_orig})
    try:
        publish_clip(db, root, key, uids)
    except Exception:
        stats["errors"] += 1
    try:
        from . import cluster as _cl
        _cl.demote_extra_names(db)                            # ảnh một người chỉ mang một tên; tên thừa thành dự phòng
    except Exception:
        pass
    try:
        from . import autolabel as _al
        _al.strip_favorite_auto(db)                          # ngôi sao chỉ do bạn tự bấm: gỡ các ngôi sao app từng tự gán nhầm
    except Exception:
        pass
    persons = [{"id": p["id"], "name": p["name"], "n": p["n"], "fav": 1 if p["favorite"] else 0} for p in db.persons()]
    sugs = {r["person_id"]: r for r in db.q("SELECT person_id,name,n_arch FROM person_suggest")}
    for p in persons:                                         # người chưa đặt tên: kèm tên PC đoán là đúng (theo tên trên tệp nén) để điện thoại hiện gợi ý
        sg = sugs.get(p["id"])
        if sg and not (p["name"] or "").strip() and (sg["name"] or "").strip():
            p["sug"] = sg["name"]
            p["sugn"] = sg["n_arch"] or 0
    link = []
    for p in persons:
        for r in db.person_images(p["id"]):
            if r["id"] in uids:
                link.append([uids[r["id"]], p["id"]])
    labels = [{"id": l["id"], "name": l["name"]} for l in db.labels()]
    label_links = [[uids[x["image_id"]], x["label_id"]] for x in db.q("SELECT label_id,image_id FROM label_images") if x["image_id"] in uids]
    cloth = [[uids[r["image_id"]], r["grp"]] for r in db.q("SELECT image_id,grp FROM cloth_group WHERE grp IS NOT NULL") if r["image_id"] in uids]
    from . import cluster
    # Mashup trên điện thoại dùng đúng cách đếm của PC: đếm số KHUÔN MẶT thật trong từng ảnh (không phụ thuộc mặt đã vào nhóm người nào). Mỗi mục là một nhóm "k người".
    combos = [{"names": [""] * k, "uids": [uids[i] for i in ids if i in uids]} for k, ids in sorted(cluster.mashup_by_count(db).items())]
    try:
        covers = publish_covers(db, root, key, uids, persons)    # ảnh profile mỗi người: PC chọn và cắt sẵn, điện thoại chỉ việc tải về dùng
    except Exception:
        covers = {}
        stats["errors"] += 1
    # ảnh app CHƯA chắc chắn là của người nào (đề xuất chờ xác nhận): điện thoại hiện ở trang đề xuất để bấm đúng / sai
    pids = {p["id"] for p in persons}
    guesses = [[uids[r["image_id"]], r["person_id"], round(float(r["score"] or 0), 3)] for r in db.q("SELECT image_id,person_id,score FROM person_guess WHERE state=0")
               if r["image_id"] in uids and r["person_id"] in pids]
    index = {"v": 1, "updated": time.time(), "images": entries, "persons": persons, "image_person": link, "clothing": cloth,
             "labels": labels, "label_images": label_links, "combos": combos, "covers": covers, "guesses": guesses,
             "acked": [r["name"] for r in db.q("SELECT name FROM inbox_done ORDER BY ts DESC LIMIT 2000")]}          # thao tác điện thoại PC đã nhận và áp dụng (hoặc đã xét)
    _write(os.path.join(root, "index.pe"), seal(key, json.dumps(index, ensure_ascii=False).encode("utf-8")))
    keep = set(uids.values()) | {r["uid"] for r in db.q("SELECT uid FROM archived")}      # không bao giờ dọn bản đã là bản duy nhất
    for sub in ("thumbs", "orig"):
        d = os.path.join(root, sub)
        for fn in os.listdir(d):
            if fn.endswith(".pe") and fn[:-3] not in keep:
                try:
                    os.remove(os.path.join(d, fn))
                    stats["removed"] += 1
                except OSError:
                    pass
    return stats


def _newer(db, key, ts):
    r = db.one("SELECT ts FROM edit_ts WHERE k=?", (key,))
    return r is None or ts > r["ts"]


def _stamp(db, keys, ts):
    for k in keys:
        db.c.execute("INSERT OR REPLACE INTO edit_ts(k,ts) VALUES(?,?)", (k, ts))


def apply_inbox(db, dest, key):
    """Áp dụng các chỉnh sửa do điện thoại gửi lên theo nguyên tắc 'bên nào sửa SAU CÙNG thì thắng': mỗi thao tác chỉ được áp dụng nếu
    mới hơn lần chỉnh sửa gần nhất trên PC của đúng mục đó (nhãn của ảnh, tên người, ẩn/gộp người...). Tệp xử lý xong sẽ bị xóa."""
    from . import cluster
    inbox = os.path.join(root_of(dest), "inbox")
    if not os.path.isdir(inbox):
        return 0
    files = sorted(f for f in os.listdir(inbox) if f.endswith(".pe"))
    if not files:
        return 0
    by_uid = {uid_of(r["path"], r["mtime"], r["size"]): r["id"] for r in db.q("SELECT id,path,mtime,size FROM images")}
    n = 0
    for fn in files:
        p = os.path.join(inbox, fn)
        try:
            j = json.loads(unseal(key, open(p, "rb").read()).decode("utf-8"))
        except Exception:
            continue
        try:
            file_ts = int(fn.split("-")[1]) / 1000.0
        except Exception:
            file_ts = 0.0
        for op in j.get("ops", []):
            kind = op.get("op")
            ts = float(op.get("ts") or file_ts)
            if kind == "rename_person":
                pid = op.get("person_id")
                if db.one("SELECT 1 FROM persons WHERE id=?", (pid,)) and _newer(db, f"pname:{pid}", ts):
                    cluster.rename_person(db, pid, op.get("name") or "")
                    db.x("DELETE FROM person_suggest WHERE person_id=?", (pid,))
                    _stamp(db, [f"pname:{pid}"], ts)
                    n += 1
            elif kind == "person_suggest_reject" and db.one("SELECT 1 FROM persons WHERE id=?", (op.get("person_id"),)):
                db.x("DELETE FROM person_suggest WHERE person_id=?", (op["person_id"],))
                db.x("DELETE FROM person_candidates WHERE person_id=?", (op["person_id"],))
                n += 1
            elif kind in ("label_add", "label_remove"):
                name = (op.get("name") or "").strip()
                iid = by_uid.get(op.get("image_uid"))
                if not name or iid is None:
                    continue
                r = db.one("SELECT id FROM labels WHERE name=?", (name,))
                if kind == "label_add":
                    lid = r["id"] if r else db.x("INSERT INTO labels(name) VALUES(?)", (name,)).lastrowid
                    if _newer(db, f"lm:{lid}|{iid}", ts):
                        db.x("INSERT OR IGNORE INTO label_images VALUES(?,?)", (lid, iid))
                        _stamp(db, [f"lm:{lid}|{iid}"], ts)
                        n += 1
                elif r and _newer(db, f"lm:{r['id']}|{iid}", ts):
                    db.x("DELETE FROM label_images WHERE label_id=? AND image_id=?", (r["id"], iid))
                    db.x("INSERT OR IGNORE INTO label_reject VALUES(?,?)", (r["id"], iid))
                    _stamp(db, [f"lm:{r['id']}|{iid}"], ts)
                    n += 1
            elif kind == "label_rename" and (op.get("name") or "").strip() and (op.get("new_name") or "").strip():
                old = db.one("SELECT id FROM labels WHERE name=?", (op["name"].strip(),))
                new_name = op["new_name"].strip()
                if old and _newer(db, f"label:{old['id']}", ts):
                    dst = db.one("SELECT id FROM labels WHERE name=? AND id<>?", (new_name, old["id"]))
                    if dst:                                  # trùng tên nhãn khác: gộp
                        db.x("INSERT OR IGNORE INTO label_images SELECT ?,image_id FROM label_images WHERE label_id=?", (dst["id"], old["id"]))
                        db.x("DELETE FROM label_images WHERE label_id=?", (old["id"],))
                        db.x("DELETE FROM labels WHERE id=?", (old["id"],))
                    else:
                        db.x("UPDATE labels SET name=? WHERE id=?", (new_name, old["id"]))
                    _stamp(db, [f"label:{old['id']}"], ts)
                    n += 1
            elif kind == "label_delete" and (op.get("name") or "").strip():
                old = db.one("SELECT id FROM labels WHERE name=?", (op["name"].strip(),))
                if old and _newer(db, f"label:{old['id']}", ts):
                    db.x("DELETE FROM label_images WHERE label_id=?", (old["id"],))
                    db.x("DELETE FROM labels WHERE id=?", (old["id"],))
                    _stamp(db, [f"label:{old['id']}"], ts)
                    n += 1
            elif kind == "person_merge":
                a, b = op.get("src_id"), op.get("dst_id")
                if a != b and db.one("SELECT 1 FROM persons WHERE id=?", (a,)) and db.one("SELECT 1 FROM persons WHERE id=?", (b,)) \
                        and _newer(db, f"person:{a}", ts) and _newer(db, f"person:{b}", ts):
                    cluster.merge_persons(db, a, b)
                    _stamp(db, [f"person:{a}", f"person:{b}"], ts)
                    n += 1
            elif kind == "person_hide":
                pid = op.get("person_id")
                if _newer(db, f"person:{pid}", ts):
                    db.x("UPDATE persons SET hidden=1 WHERE id=?", (pid,))
                    _stamp(db, [f"person:{pid}"], ts)
                    n += 1
            elif kind in ("person_restore", "person_add") and op.get("image_uid") in by_uid and db.one("SELECT 1 FROM persons WHERE id=?", (op.get("person_id"),)):
                pid, iid = op["person_id"], by_uid[op["image_uid"]]
                if _newer(db, f"pimg:{pid}|{iid}", ts):
                    if kind == "person_restore":
                        cluster.restore_to_person(db, [iid], pid)           # hoàn tác loại nhầm
                    else:
                        cluster.assign_images_to_person(db, [iid], pid)      # điện thoại thêm ảnh vào một người
                    _stamp(db, [f"pimg:{pid}|{iid}"], ts)
                    n += 1
            elif kind == "person_create" and (op.get("name") or "").strip():
                name = op["name"].strip()
                uids_in = [by_uid[u] for u in (op.get("image_uids") or []) if u in by_uid]
                if uids_in and _newer(db, f"pcreate:{name}|{min(uids_in)}", ts):
                    r = db.one("SELECT id FROM persons WHERE name=? COLLATE NOCASE AND hidden=0", (name,))
                    pid = r["id"] if r else db.x("INSERT INTO persons(name) VALUES(?)", (name,)).lastrowid
                    cluster.assign_images_to_person(db, uids_in, pid)        # tạo người mới (hoặc dùng người cùng tên) và thêm các ảnh đã chọn
                    _stamp(db, [f"pcreate:{name}|{min(uids_in)}"], ts)
                    n += 1
            elif kind == "cloth_clear" and op.get("image_uid") in by_uid:
                iid = by_uid[op["image_uid"]]
                if _newer(db, f"cloth:{iid}", ts):
                    from . import clothing
                    clothing.clear_manual(db, [iid])                          # hoàn tác phân loại: ảnh quay lại để phân tích tự động xử lý
                    _stamp(db, [f"cloth:{iid}"], ts)
                    n += 1
            elif kind == "cloth_set" and op.get("image_uid") in by_uid and op.get("grp") in ("cloth", "nude"):
                iid = by_uid[op["image_uid"]]
                if _newer(db, f"cloth:{iid}", ts):
                    from . import clothing
                    clothing.set_manual(db, [iid], op["grp"])           # điện thoại phân loại Dressed / Naked: ghi như phân loại tay trên PC
                    _stamp(db, [f"cloth:{iid}"], ts)
                    n += 1
            elif kind in ("guess_accept", "guess_reject", "guess_restore") and op.get("image_uid") in by_uid and db.one("SELECT 1 FROM persons WHERE id=?", (op.get("person_id"),)):
                pid, iid = op["person_id"], by_uid[op["image_uid"]]
                if _newer(db, f"pimg:{pid}|{iid}", ts):
                    if kind == "guess_accept":
                        cluster.accept_guesses(db, pid, [iid])                    # xác nhận đúng người
                    elif kind == "guess_reject":
                        cluster.reject_guesses(db, pid, [iid])                    # không phải người này
                    else:
                        db.x("UPDATE person_guess SET state=0 WHERE image_id=? AND person_id=? AND state=1", (iid, pid))      # hoàn tác: về lại đề xuất
                    _stamp(db, [f"pimg:{pid}|{iid}"], ts)
                    n += 1
            elif kind == "person_fav" and db.one("SELECT 1 FROM persons WHERE id=?", (op.get("person_id"),)):
                pid = op["person_id"]
                if _newer(db, f"fav:{pid}", ts):
                    db.c.execute("UPDATE persons SET favorite=? WHERE id=?", (1 if op.get("fav") else 0, pid))
                    _stamp(db, [f"fav:{pid}"], ts)                              # trái tim người: điện thoại bấm thì PC cập nhật theo (và ngược lại qua danh mục)
                    n += 1
            elif kind == "person_remove" and op.get("image_uid") in by_uid:
                pid, iid = op.get("person_id"), by_uid[op["image_uid"]]
                if _newer(db, f"pimg:{pid}|{iid}", ts):
                    cluster.remove_from_person(db, pid, [iid])
                    _stamp(db, [f"pimg:{pid}|{iid}"], ts)
                    n += 1
        try:
            db.c.execute("INSERT OR REPLACE INTO inbox_done(name,ts) VALUES(?,?)", (fn, time.time()))        # ghi nhận trước khi xóa tệp
            os.remove(p)
        except OSError:
            pass
    db.c.execute("DELETE FROM inbox_done WHERE ts<?", (time.time() - 7 * 86400,))
    db.commit()
    return n


# ---------------------------------------------------------------- thống kê, giải phóng dung lượng, khôi phục ảnh gốc
def _du(folder):
    n = size = 0
    for dp, _, fns in os.walk(folder):
        for fn in fns:
            try:
                size += os.path.getsize(os.path.join(dp, fn))
                n += 1
            except OSError:
                pass
    return n, size


def stats(dest):
    """Dung lượng thực tế của thư mục đồng bộ (cũng là phần đang chiếm trong Google Drive)."""
    root = root_of(dest)
    out = {"thumbs": _du(os.path.join(root, "thumbs")), "orig": _du(os.path.join(root, "orig")), "app": _du(os.path.join(root, "app")),
           "inbox": _du(os.path.join(root, "inbox"))}
    other = 0
    for fn in os.listdir(root) if os.path.isdir(root) else []:
        p = os.path.join(root, fn)
        if os.path.isfile(p):
            other += os.path.getsize(p)
    out["other"] = other
    out["total"] = sum(v[1] for v in out.values() if isinstance(v, tuple)) + other
    return out


def _creds(db):
    d, pw = db.get_meta("sync_dir"), db.get_meta("sync_pw")
    if not d or not pw:
        raise RuntimeError("Chưa cấu hình đồng bộ điện thoại (thư mục và mật khẩu).")
    return d, setup(d, pw)


def read_archived(db, image_id):
    """Giải mã ảnh gốc từ thư mục đồng bộ cho ảnh đã được giải phóng khỏi PC (nguyên vẹn từng byte)."""
    r = db.one("SELECT uid FROM archived WHERE image_id=?", (image_id,))
    if not r:
        raise FileNotFoundError("Ảnh không còn trên PC và chưa có bản trên Drive.")
    d, key = _creds(db)
    return unseal(key, open(os.path.join(root_of(d), "orig", r["uid"] + ".pe"), "rb").read())


def read_original_any(db, row):
    """Đọc ảnh gốc: từ tệp trên PC (hoặc trong tệp nén) nếu còn, không thì từ bản mã hóa trong thư mục đồng bộ (ảnh đã giải phóng / đã dọn khỏi tệp nén)."""
    path = row["path"]
    try:
        if zipimg.is_zip_path(path):
            return zipimg.read(path)
        with open(path, "rb") as f:
            return f.read()
    except zipimg.PasswordNeeded:
        raise
    except Exception:                                            # Windows báo OSError (không phải FileNotFoundError) với đường dẫn zip:// không phải tệp thật
        return read_archived(db, row["id"])


def free_candidates(db, dest, min_age=0):
    """Ảnh rời trên PC đã có bản mã hóa trong thư mục đồng bộ: [(id, đường dẫn, dung lượng, uid)] (chưa kiểm chứng)."""
    out = []
    root = os.path.join(root_of(dest), "orig")
    done = {r["image_id"] for r in db.q("SELECT image_id FROM archived")}
    for r in db.q("SELECT id,path,mtime,size FROM images WHERE vid IS NULL AND thumb IS NOT NULL AND ml=1 AND err IS NULL"):      # chỉ giải phóng ảnh đã phân tích xong (mặt, nội dung)
        if r["id"] in done or zipimg.is_zip_path(r["path"]) or not os.path.isfile(r["path"]):
            continue
        u = uid_of(r["path"], r["mtime"], r["size"])
        fp = os.path.join(root, u + ".pe")
        if os.path.exists(fp):
            try:
                if min_age and time.time() - os.path.getmtime(fp) < min_age:          # chạy tự động: chờ Drive kịp tải bản mã hóa lên mạng
                    continue
            except OSError:
                continue
            out.append((r["id"], r["path"], r["size"] or 0, u))
    return out


def _trash(path):
    from send2trash import send2trash
    send2trash(path)


def free_local(db, dest, password, progress=lambda d, t, s: None, cancel=lambda: False, min_age=0):
    """Xóa (chuyển vào Thùng rác) ảnh gốc trên PC sau khi ĐÃ KIỂM CHỨNG từng tệp: giải mã bản trong thư mục đồng bộ và so sánh từng byte
    với tệp trên PC. Ảnh được ghi nhận là 'archived' để thư viện vẫn giữ, xem và khôi phục được từ bản Drive."""
    import hashlib
    key = setup(dest, password)
    cands = free_candidates(db, dest, min_age)
    st = {"freed": 0, "files": 0, "errors": 0, "mismatch": 0}
    for k, (iid, path, size, u) in enumerate(cands, 1):
        if cancel():
            raise Cancelled()
        progress(k, len(cands), os.path.basename(path))
        try:
            local = open(path, "rb").read()
            remote = unseal(key, open(os.path.join(root_of(dest), "orig", u + ".pe"), "rb").read())
        except Exception:
            st["errors"] += 1
            continue
        if hashlib.sha256(local).digest() != hashlib.sha256(remote).digest():
            st["mismatch"] += 1
            continue
        db.x("INSERT OR REPLACE INTO archived(image_id,uid) VALUES(?,?)", (iid, u))      # ghi nhận trước khi xóa
        try:
            _trash(path)
            st["freed"] += size or len(local)
            st["files"] += 1
        except Exception:
            db.x("DELETE FROM archived WHERE image_id=?", (iid,))
            st["errors"] += 1
    return st


def archive_clean_candidates(db, dest, min_age=1800, why=None):
    """Tệp nén đã đồng bộ: những ảnh trong tệp (đã quét xong) có bản mã hóa trong thư mục đồng bộ (đã nằm đó ít nhất min_age giây, để Drive kịp tải lên) thì
    đủ điều kiện dọn; tệp còn trên đĩa và là định dạng xóa bớt được (ZIP, 7z). Ảnh nào CHƯA đủ điều kiện thì bỏ qua riêng (không chặn cả tệp nén).
    `why` (dict, tùy chọn) nhận số lượng theo lý do chưa dọn: 'rar' (định dạng chỉ đọc), 'ro' (không ghi được), 'ml' (chưa phân tích xong),
    'sync' (chưa có bản mã hóa), 'age' (chưa đủ thời gian). Trả về [(đường dẫn tệp nén, [(id ảnh, uid, tên trong tệp)])]."""
    why = why if why is not None else {}
    root = os.path.join(root_of(dest), "orig")
    done = {r["image_id"] for r in db.q("SELECT image_id FROM archived")}
    by = {}
    for r in db.q("SELECT id,path,mtime,size,ml,err FROM images WHERE path LIKE 'zip://%'"):
        by.setdefault(zipimg.archive_of(r["path"]), []).append(r)
    now = time.time()
    out = []
    for arch, rows in by.items():
        pending = [r for r in rows if r["id"] not in done]
        if not pending:
            continue
        if not zipimg.can_delete(arch) or not os.path.isfile(arch):
            why["rar"] = why.get("rar", 0) + len(pending)
            continue
        if not os.access(arch, os.W_OK):
            why["ro"] = why.get("ro", 0) + len(pending)
            continue
        items = []
        for r in pending:
            if not r["ml"] or r["err"]:                       # chưa phân tích xong: chưa dọn ảnh này (để còn quét lại được từ ảnh gốc)
                why["ml"] = why.get("ml", 0) + 1
                continue
            u = uid_of(r["path"], r["mtime"], r["size"])
            fp = os.path.join(root, u + ".pe")
            try:
                if not os.path.isfile(fp):
                    why["sync"] = why.get("sync", 0) + 1
                    continue
                if now - os.path.getmtime(fp) < min_age:
                    why["age"] = why.get("age", 0) + 1
                    continue
            except OSError:
                why["sync"] = why.get("sync", 0) + 1
                continue
            items.append((r["id"], u, zipimg.split(r["path"])[1]))
        if items:
            out.append((arch, items))
    return out


def clean_archive(db, dest, password, arch, items, zip_pw=None):
    """Kiểm chứng từng ảnh trong tệp nén giống HỆT bản mã hóa trên Drive (so từng byte), rồi xóa các ảnh đó khỏi tệp nén, giữ tệp nén (rỗng) cùng tên.
    Ảnh được ghi nhận 'archived' nên vẫn xem, khôi phục được từ Drive. Trả về số ảnh đã dọn (0 nếu không làm được)."""
    import hashlib
    key = setup(dest, password)
    pw = (zip_pw or {}).get(arch)
    for iid, u, entry in items:
        try:
            local = zipimg.read(zipimg.make(arch, entry), pw)
            remote = unseal(key, open(os.path.join(root_of(dest), "orig", u + ".pe"), "rb").read())
        except Exception:
            return 0
        if hashlib.sha256(local).digest() != hashlib.sha256(remote).digest():
            return 0
    for iid, u, _ in items:
        db.c.execute("INSERT OR REPLACE INTO archived(image_id,uid) VALUES(?,?)", (iid, u))       # ghi nhận trước khi xóa
    db.commit()
    if not zipimg.delete_entries(arch, [e for _, _, e in items], pw):
        for iid, _, _ in items:
            db.c.execute("DELETE FROM archived WHERE image_id=?", (iid,))
        db.commit()
        return 0
    return len(items)


def restore(db, ids, out_dir=None):
    """Khôi phục ảnh gốc từ bản trên Drive. out_dir=None: về đúng vị trí cũ trên PC (ảnh hết là 'archived'); ngược lại lưu vào out_dir."""
    d, key = _creds(db)
    n, errors = 0, []
    for iid in ids:
        r = db.one("SELECT i.path,a.uid FROM images i JOIN archived a ON a.image_id=i.id WHERE i.id=?", (iid,))
        if not r:
            continue
        try:
            data = unseal(key, open(os.path.join(root_of(d), "orig", r["uid"] + ".pe"), "rb").read())
            target = r["path"]
            if zipimg.is_zip_path(target):                       # ảnh vốn nằm trong tệp nén: khôi phục thành tệp ảnh trong thư mục cạnh tệp nén (hoặc thư mục đã chọn)
                arch, entry = zipimg.split(target)
                base_dir = out_dir or os.path.join(os.path.dirname(arch), os.path.splitext(os.path.basename(arch))[0])
                os.makedirs(base_dir, exist_ok=True)
                target = os.path.join(base_dir, os.path.basename(entry))
                base, ext = os.path.splitext(target)
                k = 1
                while os.path.exists(target):
                    target = f"{base} ({k}){ext}"
                    k += 1
                with open(target, "wb") as f:
                    f.write(data)
                n += 1
                continue
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
                target = os.path.join(out_dir, os.path.basename(r["path"]))
                base, ext = os.path.splitext(target)
                k = 1
                while os.path.exists(target):
                    target = f"{base} ({k}){ext}"
                    k += 1
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
            if not out_dir:
                db.x("DELETE FROM archived WHERE image_id=?", (iid,))
            n += 1
        except Exception as e:
            errors.append(f"{r['path']}: {e}")
    return n, errors


def recovery_key(dest, password):
    """Khóa khôi phục: chính khóa mã hóa của thư mục đồng bộ, viết dạng dễ chép (A1B2-…). Giữ bí mật như mật khẩu; có nó thì không cần mật khẩu."""
    return encode_recovery(setup(dest, password))


def open_key(dest, secret):
    """Mở thư mục đồng bộ có sẵn bằng mật khẩu đồng bộ HOẶC khóa khôi phục. Trả về khóa; ném WrongPassword nếu cả hai đều sai."""
    meta = os.path.join(root_of(dest), "sync.json")
    if not os.path.exists(meta):
        raise FileNotFoundError("Không thấy thư mục PrivatePicture-Sync (sync.json) ở đây.")
    j = json.load(open(meta, encoding="utf-8"))
    chk = base64.b64decode(j["check"])
    try:
        key = derive(secret, base64.b64decode(j["salt"]))
        if unseal(key, chk) == CHECK:
            return key
    except WrongPassword:
        pass
    try:
        key = decode_recovery(secret)
        if unseal(key, chk) == CHECK:
            return key
    except WrongPassword:
        pass
    raise WrongPassword()


def restore_library(db, dest, secret, out_dir, progress=lambda d, t, s: None, cancel=lambda: False):
    """Dựng lại thư viện trên máy mới từ thư mục đồng bộ: giải mã ảnh gốc về out_dir, thêm out_dir vào thư viện, ghi nhớ tên người/nhãn
    để áp lại sau khi quét (apply_restore_meta). Trả về {'restored','missing','errors'}."""
    key = open_key(dest, secret)
    root = root_of(dest)
    try:
        idx = json.loads(unseal(key, open(os.path.join(root, "index.pe"), "rb").read()))
    except FileNotFoundError:
        raise FileNotFoundError("Thiếu index.pe: máy cũ chưa đồng bộ xong hoặc Drive chưa tải hết về máy này.")
    os.makedirs(out_dir, exist_ok=True)
    imgs = idx.get("images", [])
    paths, st = {}, {"restored": 0, "missing": 0, "errors": 0}
    for k, im in enumerate(imgs, 1):
        if cancel():
            raise Cancelled()
        progress(k, len(imgs), im.get("name") or "")
        src = os.path.join(root, "orig", im["uid"] + ".pe")
        if not os.path.exists(src):
            st["missing"] += 1
            continue
        try:
            data = unseal(key, open(src, "rb").read())
            base, ext = os.path.splitext(os.path.basename(im.get("name") or im["uid"] + ".jpg"))
            target, n = os.path.join(out_dir, base + ext), 1
            while os.path.exists(target):
                target = os.path.join(out_dir, f"{base} ({n}){ext}")
                n += 1
            with open(target, "wb") as f:
                f.write(data)
            paths[target] = im["uid"]
            st["restored"] += 1
        except Exception:
            st["errors"] += 1
    keep = {"paths": paths, "persons": idx.get("persons", []), "image_person": idx.get("image_person", []),
            "labels": idx.get("labels", []), "label_images": idx.get("label_images", []), "clothing": idx.get("clothing", [])}
    db.set_meta("restore_pending", json.dumps(keep, ensure_ascii=False))
    db.add_folder(out_dir, "data", 0)
    return st


def apply_restore_meta(db):
    """Sau khi quét lại thư mục đã khôi phục: áp lại nhãn, nhóm trang phục và đặt tên người (theo nhóm khuôn mặt chiếm nhiều ảnh nhất). Trả về số mục đã áp."""
    raw = db.get_meta("restore_pending")
    if not raw:
        return 0
    d = json.loads(raw)
    id_of = {}
    for path, uid in d["paths"].items():
        r = db.one("SELECT id FROM images WHERE path=?", (path,))
        if r:
            id_of[uid] = r["id"]
    if len(id_of) < len(d["paths"]):          # chưa quét xong hết: giữ lại để áp sau
        if not id_of:
            return 0
    n = 0
    lab = {}
    for l in d["labels"]:
        db.x("INSERT OR IGNORE INTO labels(name) VALUES(?)", (l["name"],))
        lab[l["id"]] = db.one("SELECT id FROM labels WHERE name=?", (l["name"],))["id"]
    for u, lid in d["label_images"]:
        if u in id_of and lid in lab:
            db.x("INSERT OR IGNORE INTO label_images(label_id,image_id) VALUES(?,?)", (lab[lid], id_of[u]))
            n += 1
    for u, g in d.get("clothing", []):
        if u in id_of:
            db.x("INSERT OR IGNORE INTO cloth_group(image_id,grp,p) VALUES(?,?,1.0)", (id_of[u], g))
    names = {p["id"]: p["name"] for p in d["persons"] if p.get("name")}
    votes = {}                                  # tên -> {person_id mới: số ảnh}
    for u, pid in d["image_person"]:
        if pid in names and u in id_of:
            for f in db.q("SELECT person_id FROM faces WHERE image_id=? AND person_id IS NOT NULL", (id_of[u],)):
                v = votes.setdefault(names[pid], {})
                v[f["person_id"]] = v.get(f["person_id"], 0) + 1
    used = set()
    for name, v in sorted(votes.items(), key=lambda kv: -max(kv[1].values())):
        for npid, _ in sorted(v.items(), key=lambda kv: -kv[1]):
            if npid in used:
                continue
            cur = db.one("SELECT name FROM persons WHERE id=?", (npid,))
            if cur and not cur["name"]:
                db.x("UPDATE persons SET name=? WHERE id=?", (name, npid))
                used.add(npid)
                n += 1
                break
    db.set_meta("restore_pending", "")
    return n


def post_ops(dest, key, device, ops):
    """(Dùng để kiểm thử, và làm mẫu cho app điện thoại) ghi một tệp thay đổi vào inbox."""
    inbox = os.path.join(root_of(dest), "inbox")
    os.makedirs(inbox, exist_ok=True)
    name = f"{device}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.pe"
    _write(os.path.join(inbox, name), seal(key, json.dumps({"device": device, "ops": ops}).encode("utf-8")))
    return name

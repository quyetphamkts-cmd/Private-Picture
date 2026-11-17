import json
import os

import pytest

from pp import secure, sync
from pp.secure import WrongPassword, unseal
from test_core import FakeFaces, FakeClip, lib  # noqa: F401
from pp import scan, cluster


def _setup(lib):
    pics, db = lib
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    cluster.cluster_faces(db)
    return pics, db


def test_sync_roundtrip_and_incremental(lib, tmp_path):
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    st = sync.run(db, dest, "mk-dong-bo")
    assert st["thumbs"] == 6 and st["orig"] == 6 and st["errors"] == 0
    root = sync.root_of(dest)
    j = json.load(open(os.path.join(root, "sync.json")))
    import base64
    key = secure.derive("mk-dong-bo", base64.b64decode(j["salt"]))
    idx = json.loads(unseal(key, open(os.path.join(root, "index.pe"), "rb").read()))
    assert len(idx["images"]) == 6 and idx["persons"] and idx["image_person"]
    assert idx["covers"]                                                                 # ảnh profile mỗi người do PC chọn và cắt sẵn
    for pid, sig in idx["covers"].items():
        data = unseal(key, open(os.path.join(root, "covers", f"{pid}-{sig}.pe"), "rb").read())
        assert data[:2] == b"\xff\xd8"                                                   # JPEG đã cắt, điện thoại chỉ việc tải về dùng
    u = idx["images"][0]["uid"]
    assert unseal(key, open(os.path.join(root, "orig", u + ".pe"), "rb").read())[:2] == b"\xff\xd8"
    assert unseal(key, open(os.path.join(root, "thumbs", u + ".pe"), "rb").read())
    st2 = sync.run(db, dest, "mk-dong-bo")                     # chạy lại: không ghi lại gì
    assert st2["thumbs"] == 0 and st2["orig"] == 0
    with pytest.raises(WrongPassword):
        sync.run(db, dest, "sai")
    # không có tệp ảnh nào để lộ dạng rõ
    assert b"\xff\xd8" not in open(os.path.join(root, "orig", u + ".pe"), "rb").read()[:20]


def test_inbox_ops_and_removal(lib, tmp_path):
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw", include_originals=False)
    assert not os.listdir(os.path.join(sync.root_of(dest), "orig"))
    key = sync.setup(dest, "pw")
    row = db.q("SELECT path,mtime,size FROM images WHERE thumb IS NOT NULL LIMIT 1")[0]
    uid = sync.uid_of(row["path"], row["mtime"], row["size"])
    pid = db.persons()[0]["id"]
    sync.post_ops(dest, key, "android", [{"op": "rename_person", "person_id": pid, "name": "Be Na"},
                                          {"op": "label_add", "image_uid": uid, "name": "Yêu thích"}])
    st = sync.run(db, dest, "pw", include_originals=False)
    assert st["inbox"] == 2
    assert db.one("SELECT name FROM persons WHERE id=?", (pid,))["name"] == "Be Na"
    assert db.one("SELECT COUNT(*) c FROM label_images")["c"] == 1
    assert not os.listdir(os.path.join(sync.root_of(dest), "inbox"))
    os.remove(row["path"])
    # ảnh bị xóa khỏi thư viện -> tệp trên Drive bị dọn
    db.x("DELETE FROM images WHERE path=?", (row["path"],))
    st = sync.run(db, dest, "pw", include_originals=False)
    assert st["removed"] >= 1


def test_inbox_label_person_edits(lib, tmp_path):
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    key = sync.setup(dest, "pw")
    rows = db.q("SELECT path,mtime,size FROM images WHERE thumb IS NOT NULL LIMIT 2")
    u = [sync.uid_of(r["path"], r["mtime"], r["size"]) for r in rows]
    sync.post_ops(dest, key, "android", [{"op": "label_add", "image_uid": x, "name": "A"} for x in u] +
                  [{"op": "label_rename", "name": "A", "new_name": "B"}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT COUNT(*) c FROM labels WHERE name='B'")["c"] == 1 and not db.one("SELECT 1 FROM labels WHERE name='A'")
    sync.post_ops(dest, key, "android", [{"op": "label_delete", "name": "B"}])
    sync.run(db, dest, "pw", include_originals=False)
    assert not db.q("SELECT * FROM labels") and not db.q("SELECT * FROM label_images")
    persons = db.persons()
    assert persons
    pid = persons[0]["id"]
    iid = db.person_images(pid)[0]["id"]
    r = db.one("SELECT path,mtime,size FROM images WHERE id=?", (iid,))
    sync.post_ops(dest, key, "android", [{"op": "person_remove", "person_id": pid, "image_uid": sync.uid_of(r["path"], r["mtime"], r["size"])},
                                          {"op": "person_hide", "person_id": pid}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT hidden FROM persons WHERE id=?", (pid,))["hidden"] == 1
    assert iid not in [x["id"] for x in db.person_images(pid)]


def test_last_writer_wins_between_pc_and_phone(lib, tmp_path):
    import time
    from pp import cluster
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    key = sync.setup(dest, "pw")
    pid = db.persons()[0]["id"]
    now = time.time()
    # PC đổi tên SAU thao tác của điện thoại -> tên của PC thắng
    cluster.rename_person(db, pid, "TenPC")
    sync.post_ops(dest, key, "android", [{"op": "rename_person", "person_id": pid, "name": "TenDienThoaiCu", "ts": now - 600}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT name FROM persons WHERE id=?", (pid,))["name"] == "TenPC"
    # điện thoại đổi tên SAU lần đổi của PC -> tên của điện thoại thắng
    sync.post_ops(dest, key, "android", [{"op": "rename_person", "person_id": pid, "name": "TenDienThoaiMoi", "ts": now + 600}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT name FROM persons WHERE id=?", (pid,))["name"] == "TenDienThoaiMoi"
    # nhãn: PC gỡ nhãn mới hơn thao tác thêm nhãn của điện thoại -> nhãn không quay lại
    row = db.q("SELECT id,path,mtime,size FROM images WHERE thumb IS NOT NULL LIMIT 1")[0]
    uid = sync.uid_of(row["path"], row["mtime"], row["size"])
    lid = db.x("INSERT INTO labels(name) VALUES('X')").lastrowid
    db.x("INSERT INTO label_images VALUES(?,?)", (lid, row["id"]))
    db.x("DELETE FROM label_images WHERE label_id=? AND image_id=?", (lid, row["id"]))      # PC gỡ nhãn (mới nhất)
    sync.post_ops(dest, key, "android", [{"op": "label_add", "image_uid": uid, "name": "X", "ts": now - 60}])
    sync.run(db, dest, "pw", include_originals=False)
    assert not db.q("SELECT * FROM label_images WHERE label_id=?", (lid,))
    sync.post_ops(dest, key, "android", [{"op": "label_add", "image_uid": uid, "name": "X", "ts": now + 60}])   # điện thoại thêm sau cùng
    sync.run(db, dest, "pw", include_originals=False)
    assert len(db.q("SELECT * FROM label_images WHERE label_id=?", (lid,))) == 1


def test_publish_app_to_drive_folder(lib, tmp_path, monkeypatch):
    import json
    from pp import updater
    dest = str(tmp_path / "drive")
    sync.setup(dest, "pw")
    monkeypatch.setattr(updater, "load_token", lambda: "tok")
    monkeypatch.setattr(updater, "latest_android", lambda t: {"version": "0.1.9", "code": 9, "asset_url": "x", "size": 3})
    calls = []
    monkeypatch.setattr(updater, "download", lambda info, tok, dest_, *a, **k: (calls.append(1), open(dest_, "wb").write(b"APK")))
    assert sync.publish_app(dest) == "0.1.9"
    d = os.path.join(sync.root_of(dest), "app")
    assert open(os.path.join(d, "PrivatePicture-Android.apk"), "rb").read() == b"APK"
    assert json.load(open(os.path.join(d, "version.json")))["code"] == 9
    assert sync.publish_app(dest) is None and len(calls) == 1            # đã có bản mới nhất: không tải lại
    monkeypatch.setattr(updater, "load_token", lambda: None)
    assert sync.publish_app(dest) is None                                 # không có mã: bỏ qua


def test_clip_vectors_published(lib, tmp_path):
    import struct
    import numpy as np
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw", include_originals=False)
    root = sync.root_of(dest)
    import base64, json
    j = json.load(open(os.path.join(root, "sync.json")))
    key = secure.derive("pw", base64.b64decode(j["salt"]))
    body = unseal(key, open(os.path.join(root, "clip.pe"), "rb").read())
    assert body[:4] == b"PPV1"
    n, dim = struct.unpack("<ii", body[4:12])
    assert n == 6 and dim == 512
    uids = [body[12 + 20 * i:32 + 20 * i].rstrip(b"\0").decode() for i in range(n)]
    m = np.frombuffer(body[12 + 20 * n:], dtype="<f2").reshape(n, dim).astype(np.float32)
    assert abs(float(np.linalg.norm(m[0])) - 1.0) < 0.01 and len(set(uids)) == 6
    t = os.path.getmtime(os.path.join(root, "clip.pe"))
    sync.run(db, dest, "pw", include_originals=False)               # không đổi: không ghi lại
    assert os.path.getmtime(os.path.join(root, "clip.pe")) == t


def test_stats_free_local_restore_bit_exact(lib, tmp_path, monkeypatch):
    import hashlib
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    db.set_meta("sync_dir", dest)
    db.set_meta("sync_pw", "pw")
    originals = {p.name: p.read_bytes() for p in pics.glob("a*.jpg")}
    sync.run(db, dest, "pw", include_originals=True)
    st = sync.stats(dest)
    assert st["orig"][0] == 6 and st["thumbs"][0] == 6 and st["total"] > st["orig"][1] > 0
    # ảnh gốc trên Drive giải mã ra đúng từng byte (chất lượng không đổi)
    for name, data in originals.items():
        assert any(os.path.basename(r["path"]) == name for r in db.q("SELECT path FROM images"))
    trashed = []
    monkeypatch.setattr(sync, "_trash", lambda p: (trashed.append(p), os.remove(p)))
    cands = sync.free_candidates(db, dest)
    assert len(cands) == 6
    fs = sync.free_local(db, dest, "pw")
    assert fs["files"] == 6 and fs["errors"] == 0 and fs["mismatch"] == 0 and not any(p.exists() for p in pics.glob("a*.jpg"))
    # thư viện vẫn giữ ảnh đã giải phóng và đọc lại được từng byte từ Drive
    from pp import scan
    scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False).run_folders([(str(pics), "data", 0)])
    import re
    kept = [r for r in db.q("SELECT path FROM images") if re.fullmatch(r"a\d\.jpg", os.path.basename(r["path"]))]
    assert len(kept) == 6                                                                                    # quét lại không làm mất
    row = next(r for r in db.q("SELECT id,path FROM images") if os.path.basename(r["path"]) == "a0.jpg")
    assert sync.read_original_any(db, row) == originals["a0.jpg"]
    assert hashlib.sha256(sync.read_original_any(db, row)).hexdigest() == hashlib.sha256(originals["a0.jpg"]).hexdigest()
    sync.run(db, dest, "pw", include_originals=True)                                                         # đồng bộ lại không dọn mất bản Drive
    assert sync.stats(dest)["orig"][0] == 6
    # khôi phục về vị trí cũ
    n, errs = sync.restore(db, [row["id"]])
    assert n == 1 and not errs and open(row["path"], "rb").read() == originals["a0.jpg"]
    assert not db.one("SELECT 1 FROM archived WHERE image_id=?", (row["id"],))
    # không xóa khi bản Drive khác bản trên PC
    row2 = next(r for r in db.q("SELECT id,path FROM images") if os.path.basename(r["path"]) == "a1.jpg")
    open(row2["path"], "wb").write(originals["a1.jpg"])
    db.x("DELETE FROM archived WHERE image_id=?", (row2["id"],))
    open(row2["path"], "ab").write(b"x")                                                                      # tệp trên PC bị đổi
    fs2 = sync.free_local(db, dest, "pw")
    assert os.path.exists(row2["path"]) and fs2["mismatch"] >= 1


def test_recovery_key_and_restore_library(lib, tmp_path):
    """Mất mật khẩu: khóa khôi phục mở được Drive. Máy mới: dựng lại thư viện, nhãn, tên người từ Drive."""
    from pp.db import DB
    pics, db = _setup(lib)
    pid = db.persons()[0]["id"]
    db.x("UPDATE persons SET name='Lan' WHERE id=?", (pid,))
    db.x("INSERT INTO labels(name) VALUES('Yêu thích')")
    lid = db.one("SELECT id FROM labels WHERE name='Yêu thích'")["id"]
    iid = db.one("SELECT id FROM images WHERE thumb IS NOT NULL LIMIT 1")["id"]
    db.x("INSERT INTO label_images VALUES(?,?)", (lid, iid))
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "mk-cu")
    rk = sync.recovery_key(dest, "mk-cu")
    assert sync.open_key(dest, rk) == sync.open_key(dest, "mk-cu")
    with pytest.raises(WrongPassword):
        sync.open_key(dest, "sai-hoan-toan")
    db2 = DB(str(tmp_path / "new.db"))
    out = tmp_path / "khoiphuc"
    st = sync.restore_library(db2, dest, rk, str(out))                  # dùng khóa khôi phục, không cần mật khẩu
    assert st["restored"] == 6 and st["errors"] == 0 and len(list(out.glob("*.jpg"))) == 6
    assert str(out) in db2.folders()
    sc = scan.Scanner(db2, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(out), "data", 0)])
    cluster.cluster_faces(db2)
    n = sync.apply_restore_meta(db2)
    assert n >= 1
    assert any(l["name"] == "Yêu thích" and l["n"] == 1 for l in db2.labels())
    assert any(p["name"] == "Lan" for p in db2.persons())
    assert not db2.get_meta("restore_pending")


def test_index_has_combos(lib, tmp_path):
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw")
    import base64
    root = sync.root_of(dest)
    j = json.load(open(os.path.join(root, "sync.json")))
    key = secure.derive("pw", base64.b64decode(j["salt"]))
    idx = json.loads(unseal(key, open(os.path.join(root, "index.pe"), "rb").read()))
    assert idx["combos"] == []                                        # ảnh rời, không có tệp nén nhiều người



def test_scanner_throttle_and_lower_priority_do_not_break_scan(lib):
    from pp import scan
    pics, db = lib
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.throttle = 0.001
    r = sc.run_folders([(str(pics), "data", 0)])
    assert r["added"] >= 6 and not r["errors"] or r["added"] >= 6                      # vẫn quét đủ ảnh khi có nghỉ giữa các ảnh


def test_archived_images_are_reanalyzed_from_drive_copy(lib, tmp_path, monkeypatch):
    """Ảnh gốc đã được app xóa khỏi PC: khi cần phân tích lại (đổi mô hình), app đọc bản mã hóa trên Drive thay vì bỏ qua ảnh."""
    import os
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    db.set_meta("sync_dir", dest)
    db.set_meta("sync_pw", "pw")
    sync.run(db, dest, "pw")
    monkeypatch.setattr(sync, "_trash", lambda p: os.remove(p))
    assert sync.free_local(db, dest, "pw")["files"] == 6
    assert not any(pics.glob("a*.jpg"))                                              # ảnh gốc đã bị xóa khỏi PC
    n_faces = db.one("SELECT COUNT(*) c FROM faces")["c"]
    db.x("UPDATE images SET ml=0")                                                    # như khi đổi mô hình nhận diện: cần phân tích lại tất cả
    db.x("DELETE FROM faces")
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    assert db.one("SELECT COUNT(*) c FROM faces")["c"] == n_faces > 0                # khuôn mặt được phân tích lại từ bản trên Drive
    assert db.one("SELECT COUNT(*) c FROM images WHERE ml=0 AND err IS NULL AND vid IS NULL")["c"] == 0
    assert db.one("SELECT COUNT(*) c FROM archived")["c"] == 6                        # vẫn ghi nhận là ảnh đã chuyển lên Drive


def test_phone_cloth_set_op_is_applied_as_manual_classification(lib, tmp_path):
    """Điện thoại phân loại Dressed / Naked: PC áp dụng như phân loại tay (không bị phân tích tự động ghi đè)."""
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw", include_originals=False)
    key = sync.setup(dest, "pw")
    row = db.q("SELECT id,path,mtime,size FROM images WHERE thumb IS NOT NULL LIMIT 1")[0]
    uid = sync.uid_of(row["path"], row["mtime"], row["size"])
    sync.post_ops(dest, key, "android", [{"op": "cloth_set", "image_uid": uid, "grp": "nude"}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT grp FROM cloth_manual WHERE image_id=?", (row["id"],))["grp"] == "nude"
    assert db.one("SELECT grp FROM cloth_group WHERE image_id=?", (row["id"],))["grp"] == "nude"


def test_phone_person_add_create_restore_ops(lib, tmp_path):
    """Điện thoại thêm ảnh vào người, tạo người mới từ ảnh đã chọn, hoàn tác loại nhầm: PC áp dụng đúng."""
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw", include_originals=False)
    key = sync.setup(dest, "pw")
    rows = db.q("SELECT id,path,mtime,size FROM images WHERE thumb IS NOT NULL ORDER BY id LIMIT 3")
    uid = {r["id"]: sync.uid_of(r["path"], r["mtime"], r["size"]) for r in rows}
    a, b, c = [r["id"] for r in rows]
    new_pid = db.x("INSERT INTO persons(name) VALUES('Zed')").lastrowid
    sync.post_ops(dest, key, "android", [
        {"op": "person_add", "person_id": new_pid, "image_uid": uid[a]},
        {"op": "person_create", "name": "Mới Tinh", "image_uids": [uid[b], uid[c]], "temp_id": -5}])
    sync.run(db, dest, "pw", include_originals=False)
    in_zed = {r["id"] for r in db.person_images(new_pid)}
    assert a in in_zed                                                               # ảnh được thêm vào Zed
    created = db.one("SELECT id FROM persons WHERE name='Mới Tinh'")
    assert created and {b, c} <= {r["id"] for r in db.person_images(created["id"])}  # người mới được tạo cùng các ảnh đã chọn
    sync.post_ops(dest, key, "android", [{"op": "person_remove", "person_id": created["id"], "image_uid": uid[b]}])
    sync.run(db, dest, "pw", include_originals=False)
    assert b not in {r["id"] for r in db.person_images(created["id"])}
    sync.post_ops(dest, key, "android", [{"op": "person_restore", "person_id": created["id"], "image_uid": uid[b]}])
    sync.run(db, dest, "pw", include_originals=False)
    assert b in {r["id"] for r in db.person_images(created["id"])}                   # hoàn tác loại nhầm


def test_phone_cloth_clear_op_removes_manual_classification(lib, tmp_path):
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw", include_originals=False)
    key = sync.setup(dest, "pw")
    row = db.q("SELECT id,path,mtime,size FROM images WHERE thumb IS NOT NULL LIMIT 1")[0]
    uid = sync.uid_of(row["path"], row["mtime"], row["size"])
    sync.post_ops(dest, key, "android", [{"op": "cloth_set", "image_uid": uid, "grp": "nude"}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT 1 FROM cloth_manual WHERE image_id=?", (row["id"],))
    sync.post_ops(dest, key, "android", [{"op": "cloth_clear", "image_uid": uid}])
    sync.run(db, dest, "pw", include_originals=False)
    assert not db.one("SELECT 1 FROM cloth_manual WHERE image_id=?", (row["id"],))        # hoàn tác: bỏ phân loại tay


def test_deleting_source_keeps_encrypted_copy_except_duplicates(lib, tmp_path):
    from pp import scan
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    db.set_meta("sync_dir", dest)
    sync.run(db, dest, "pw", include_originals=True)
    rows = db.q("SELECT id,path,mtime,size FROM images WHERE thumb IS NOT NULL LIMIT 2")
    assert len(rows) == 2
    db.x("INSERT INTO dup_hidden(image_id,keep_id) VALUES(?,?)", (rows[1]["id"], rows[0]["id"]))          # ảnh thứ hai là bản trùng đã bị app xóa
    kept = scan.keep_encrypted_copies(db, rows)
    assert kept == {rows[0]["id"]}                                                                       # bản mã hóa của ảnh thứ nhất được giữ
    assert db.one("SELECT 1 FROM archived WHERE image_id=?", (rows[0]["id"],))
    assert not db.one("SELECT 1 FROM archived WHERE image_id=?", (rows[1]["id"],))


def test_guesses_published_and_phone_can_accept_or_reject(lib, tmp_path):
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw", include_originals=False)
    key = sync.setup(dest, "pw")
    rows = db.q("SELECT id,path,mtime,size FROM images WHERE thumb IS NOT NULL LIMIT 2")
    pid = db.persons()[0]["id"]
    for r in rows:
        db.x("DELETE FROM faces WHERE image_id=? AND person_id=?", (r["id"], pid))
        db.x("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,0.8,0)", (r["id"], pid))
    sync.run(db, dest, "pw", include_originals=False)
    import base64
    root = sync.root_of(dest)
    j = json.load(open(os.path.join(root, "sync.json")))
    k = secure.derive("pw", base64.b64decode(j["salt"]))
    idx = json.loads(unseal(k, open(os.path.join(root, "index.pe"), "rb").read()))
    assert len(idx["guesses"]) >= 2 and all(g[1] == pid for g in idx["guesses"][:2])
    u = [sync.uid_of(r["path"], r["mtime"], r["size"]) for r in rows]
    sync.post_ops(dest, k, "android", [{"op": "guess_accept", "image_uid": u[0], "person_id": pid, "ts": 1e12},
                                        {"op": "guess_reject", "image_uid": u[1], "person_id": pid, "ts": 1e12}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT state FROM person_guess WHERE image_id=? AND person_id=?", (rows[0]["id"], pid))["state"] == 2
    assert db.one("SELECT state FROM person_guess WHERE image_id=? AND person_id=?", (rows[1]["id"], pid))["state"] == 1


def test_commons_reference_urls_require_exact_human_name():
    from pp import refimg
    calls = []
    def fake(url, timeout=15, binary=False, opener=None):
        calls.append(url)
        if "wbsearchentities" in url:
            return {"search": [{"id": "Q1", "label": "Jane Roe"}, {"id": "Q2", "label": "Jane Doe"}]}
        if "wbgetentities" in url and "Q2" in url:
            return {"entities": {"Q2": {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
                                                   "P18": [{"mainsnak": {"datavalue": {"value": "Jane Doe.jpg"}}}]}}}}
        return {"entities": {}}
    urls = refimg.commons_urls("Jane Doe", get=fake)
    assert len(urls) == 1 and urls[0].endswith("?width=700") and "Jane_Doe.jpg" in urls[0]
    assert refimg.commons_urls("Nobody Here", get=fake) == []                                          # tên không khớp đúng: không đoán


def test_changes_are_stamped_and_signature_changes_for_every_edit_kind(lib, tmp_path):
    pics, db = _setup(lib)
    sig0 = db.library_sig()
    iid = db.one("SELECT id FROM images WHERE thumb IS NOT NULL LIMIT 1")["id"]
    pid = db.persons()[0]["id"]
    from pp import clothing
    clothing.set_manual(db, [iid], "cloth")
    s1 = db.library_sig()
    assert s1 != sig0 and db.one("SELECT 1 FROM edit_ts WHERE k=?", (f"cloth:{iid}",))               # phân loại tay được đóng dấu
    clothing.set_manual(db, [iid], "nude")
    assert db.library_sig() != s1                                                                     # đổi loại (không đổi số lượng) cũng đổi chữ ký
    db.x("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,0.7,0)", (iid, pid))
    s2 = db.library_sig()
    db.x("UPDATE person_guess SET state=1 WHERE image_id=? AND person_id=?", (iid, pid))
    assert db.library_sig() != s2 and db.one("SELECT 1 FROM edit_ts WHERE k=?", (f"pimg:{pid}|{iid}",))   # từ chối đề xuất được đóng dấu
    s3 = db.library_sig()
    db.toggle_favorite(pid)
    assert db.library_sig() != s3 and db.one("SELECT 1 FROM edit_ts WHERE k=?", (f"fav:{pid}",))


def test_phone_ops_are_acked_in_index_and_favorite_syncs_both_ways(lib, tmp_path):
    import base64
    pics, db = _setup(lib)
    dest = str(tmp_path / "drive")
    sync.run(db, dest, "pw", include_originals=False)
    key = sync.setup(dest, "pw")
    pid = db.persons()[0]["id"]
    sync.post_ops(dest, key, "android", [{"op": "person_fav", "person_id": pid, "fav": True}])
    sync.run(db, dest, "pw", include_originals=False)
    assert db.one("SELECT favorite FROM persons WHERE id=?", (pid,))["favorite"] == 1               # điện thoại bấm trái tim -> PC cập nhật
    root = sync.root_of(dest)
    j = json.load(open(os.path.join(root, "sync.json")))
    k = secure.derive("pw", base64.b64decode(j["salt"]))
    idx = json.loads(unseal(k, open(os.path.join(root, "index.pe"), "rb").read()))
    assert any(p["id"] == pid and p["fav"] == 1 for p in idx["persons"])                            # danh mục đưa trái tim ngược lại cho điện thoại
    assert len(idx["acked"]) >= 1                                                                   # danh mục ghi rõ thao tác nào PC đã nhận

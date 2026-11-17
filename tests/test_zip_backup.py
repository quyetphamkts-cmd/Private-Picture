import io, os, time, zipfile
import numpy as np
import pyzipper
from PIL import Image

from pp import backup, scan, watcher, zipimg
from test_core import FakeFaces, FakeClip, lib  # noqa: F401


def _jpg(c):
    b = io.BytesIO()
    Image.fromarray(np.full((120, 160, 3), c, np.uint8)).save(b, "JPEG")
    return b.getvalue()


def _mk(path, pw=None, n=2):
    if pw:
        z = pyzipper.AESZipFile(path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES)
        z.setpassword(pw.encode())
    else:
        z = zipfile.ZipFile(path, "w")
    with z:
        for i in range(n):
            z.writestr(f"d/p{i}.jpg", _jpg((40 * i + 20, 90, 150)))


def test_plain_zip_scanned(lib, tmp_path):
    pics, db = lib
    _mk(str(pics / "a.zip"))
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    rows = db.q("SELECT path FROM images WHERE path LIKE 'zip://%'")
    assert len(rows) == 2
    assert zipimg.read(rows[0]["path"])[:2] == b"\xff\xd8"


def test_locked_zip_then_password(lib):
    pics, db = lib
    _mk(str(pics / "s.zip"), "mk123")
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    r = sc.run_folders([(str(pics), "data", 0)])
    assert any(z.endswith("s.zip") for z in r["locked_zips"])
    assert not db.q("SELECT 1 FROM images WHERE path LIKE 'zip://%'")
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False, None, {str(pics / "s.zip"): "mk123"})
    r = sc.run_folders([(str(pics), "data", 0)])
    assert not r["locked_zips"]
    assert len(db.q("SELECT 1 FROM images WHERE path LIKE 'zip://%'")) == 2


def test_wrong_password(lib):
    pics, db = lib
    _mk(str(pics / "s.zip"), "right")
    e = zipimg.make(str(pics / "s.zip"), "d/p0.jpg")
    try:
        zipimg.read(e, "wrong")
        assert False
    except zipimg.PasswordNeeded:
        pass


def test_zip_deleted_removes_rows(lib):
    pics, db = lib
    _mk(str(pics / "a.zip"))
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    os.remove(pics / "a.zip")
    sc.run_folders([(str(pics), "data", 0)])
    assert not db.q("SELECT 1 FROM images WHERE path LIKE 'zip://%'")


def test_backup_rotation(lib, tmp_path):
    pics, db = lib
    out = tmp_path / "bk"
    for i in range(4):
        backup.make_backup(db, str(out), include_vault=False, keep=2)
        time.sleep(1.1)
    files = sorted(os.listdir(out))
    assert len(files) == 2 and all(f.endswith(".zip") for f in files)
    names = zipfile.ZipFile(out / files[-1]).namelist()
    assert not any("ai3d_keys" in n or "update_token" in n for n in names)


def test_due_and_watcher_filter():
    assert backup.due(None) and not backup.due(time.time())
    assert watcher._relevant("x/a.zip") and watcher._relevant("x/a.jpg")
    assert not watcher._relevant("x/a.jpg.part") and not watcher._relevant("x/~$a.jpg")


def test_guess_faceless_by_context(lib):
    import numpy as np
    from pp import cluster
    pics, db = lib

    class Faces(FakeFaces):
        def process(self, rgb):
            a = np.asarray(rgb, np.float32).reshape(-1, 3).mean(axis=0)
            return super().process(rgb) if a[0] > 150 else []       # ảnh đỏ có mặt; ảnh xanh không thấy mặt

    sc = scan.Scanner(db, Faces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    cluster.cluster_faces(db)
    assert db.persons()
    # ảnh không mặt: cho giống hệt một ảnh có mặt về nội dung và cùng ngày giờ; ảnh khác thì khác xa
    ref = db.one("SELECT i.id,i.clip,i.taken FROM images i JOIN faces f ON f.image_id=i.id LIMIT 1")
    blue = db.q("SELECT id FROM images WHERE id NOT IN (SELECT image_id FROM faces) AND clip IS NOT NULL")
    assert len(blue) >= 2
    db.x("UPDATE images SET clip=?, taken=? WHERE id=?", (ref["clip"], ref["taken"], blue[0]["id"]))
    far = np.zeros(512, np.float32)
    far[7] = 1.0
    db.x("UPDATE images SET clip=?, taken='1999-01-01 00:00:00' WHERE id=?", (far.tobytes(), blue[1]["id"]))
    n = cluster.guess_faceless(db)
    pid = db.persons()[0]["id"]
    got = {r["id"] for r in db.person_guesses(pid)}
    assert blue[0]["id"] in got and blue[1]["id"] not in got and n >= 1
    cluster.accept_guesses(db, pid, [blue[0]["id"]])
    assert blue[0]["id"] in {r["id"] for r in db.person_images(pid)}
    assert not db.person_guesses(pid) or blue[0]["id"] not in {r["id"] for r in db.person_guesses(pid)}
    cluster.guess_faceless(db)                 # chạy lại không đưa lại ảnh đã xác nhận
    assert blue[0]["id"] not in {r["id"] for r in db.person_guesses(pid)}


def _src(tmp_path, n=2):
    d = tmp_path / "src"
    (d / "sub").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / "sub" / f"p{i}.jpg").write_bytes(_jpg((40 * i + 20, 90, 150)))
    (d / "note.txt").write_text("x")
    return d


def _sevenz(args, cwd):
    import subprocess
    import pytest
    try:
        exe = zipimg._exe()
    except zipimg.NoTool:
        pytest.skip("không có 7-Zip để tạo file thử")
    subprocess.run([exe, *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def test_7z_tar_and_encrypted_header(lib, tmp_path):
    import tarfile
    pics, db = lib
    src = _src(tmp_path)
    _sevenz(["a", str(pics / "plain.7z"), "sub"], src)
    _sevenz(["a", str(pics / "pw.7z"), "-pSECRET", "-mhe=on", "sub"], src)       # mã hóa cả tên tệp
    _sevenz(["a", str(pics / "pw2.zip"), "-pZ1", "sub"], src)
    with tarfile.open(pics / "t.tar.gz", "w:gz") as t:
        t.add(src / "sub", arcname="sub")
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    r = sc.run_folders([(str(pics), "data", 0)])
    paths_ = [x["path"] for x in db.q("SELECT path FROM images WHERE path LIKE 'zip://%'")]
    assert sum(p.replace("\\", "/").endswith("plain.7z!/sub/p0.jpg") for p in paths_) == 1                 # 7z thường
    assert sum("t.tar.gz!/" in p for p in paths_) == 2                                  # tar.gz
    locked = {os.path.basename(z) for z in r["locked_zips"]}
    assert {"pw.7z", "pw2.zip"} <= locked                                               # có mật khẩu: báo, chưa quét
    assert zipimg.read([p for p in paths_ if "plain.7z" in p][0])[:2] == b"\xff\xd8"
    for name, pw in (("pw.7z", "SECRET"), ("pw2.zip", "Z1")):
        z = str(pics / name)
        with __import__("pytest").raises(zipimg.PasswordNeeded):
            zipimg.verify(z, "sai")
        assert zipimg.verify(z, pw)
    pwmap = {str(pics / "pw.7z"): "SECRET", str(pics / "pw2.zip"): "Z1"}
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False, None, pwmap)
    r = sc.run_folders([(str(pics), "data", 0)])
    assert not r["locked_zips"]
    assert len(db.q("SELECT 1 FROM images WHERE path LIKE '%pw.7z!/%'")) == 2


def test_archive_name_rules():
    for n in ("a.zip", "a.RAR", "a.7z", "a.tar.gz", "a.tgz", "a.cab", "x.part1.rar", "a.iso"):
        assert zipimg.is_archive_name(n), n
    for n in ("x.part2.rar", "x.part10.rar", "a.jpg", "a.txt", "a.gz"):
        assert not zipimg.is_archive_name(n), n


def test_guess_faceless_uses_same_archive(lib, tmp_path):
    import numpy as np
    from pp import cluster
    pics, db = lib

    class Faces(FakeFaces):
        def process(self, rgb):
            a = np.asarray(rgb, np.float32).reshape(-1, 3).mean(axis=0)
            return super().process(rgb) if a[0] > 150 else []

    # file nén: 1 ảnh có mặt (đỏ) và 1 ảnh không thấy mặt (xanh) -> cùng file nén nên được gợi ý cho người đó
    z = pics / "nhom.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.jpg", _jpg((220, 30, 30)))
        zf.writestr("b.jpg", _jpg((30, 30, 220)))
    sc = scan.Scanner(db, Faces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    cluster.cluster_faces(db)
    face_person = db.q("SELECT f.person_id pid FROM faces f JOIN images i ON i.id=f.image_id WHERE i.path LIKE '%nhom.zip!/a.jpg'")[0]["pid"]
    blue_in = db.one("SELECT id FROM images WHERE path LIKE '%nhom.zip!/b.jpg'")["id"]
    blue_out = db.q("SELECT id FROM images WHERE path NOT LIKE 'zip://%' AND id NOT IN (SELECT image_id FROM faces) LIMIT 1")[0]["id"]
    # làm cho ảnh xanh khác hẳn về nội dung, giờ, màu: chỉ còn tín hiệu "cùng file nén"
    far = np.zeros(512, np.float32)
    far[9] = 1.0
    db.x("UPDATE images SET clip=?, taken='1999-01-01 00:00:00' WHERE id IN (?,?)", (far.tobytes(), blue_in, blue_out))
    cluster.guess_faceless(db, min_score=0.35)
    got = {r["id"] for r in db.person_guesses(face_person)}
    assert blue_in in got and blue_out not in got


def test_duplicates_hide_and_restore(lib):
    import numpy as np
    from PIL import Image
    from pp import dup
    pics, db = lib
    # bản gốc lớn + bản thu nhỏ của cùng ảnh -> trùng; ảnh khác -> không trùng
    rng = np.random.default_rng(5)
    base = (rng.integers(0, 255, (400, 600, 3))).astype(np.uint8)
    Image.fromarray(base).save(pics / "goc.jpg", quality=95)
    Image.fromarray(base).resize((300, 200)).save(pics / "nho.jpg", quality=80)
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    ids = {os.path.basename(r["path"]): r["id"] for r in db.q("SELECT id,path FROM images")}
    # FakeClip chỉ dựa màu trung bình nên ép vectơ giống nhau cho cặp trùng
    v = db.one("SELECT clip FROM images WHERE id=?", (ids["goc.jpg"],))["clip"]
    db.x("UPDATE images SET clip=? WHERE id=?", (v, ids["nho.jpg"]))
    groups = dup.find_groups(db)
    g = [x for x in groups if ids["goc.jpg"] in x["members"]]
    assert len(g) == 1 and g[0]["keep"] == ids["goc.jpg"] and ids["nho.jpg"] in g[0]["members"]
    assert dup.apply(db, groups) >= 1
    assert ids["nho.jpg"] in dup.hidden_ids(db) and ids["goc.jpg"] not in dup.hidden_ids(db)
    dup.restore(db, [ids["nho.jpg"]])
    dup.apply(db, groups)                        # đã bỏ ẩn thì không bị ẩn lại
    assert ids["nho.jpg"] not in dup.hidden_ids(db)


def test_trash_only_lower_resolution_exact_duplicates(lib, monkeypatch):
    import numpy as np
    from PIL import Image
    from pp import dup
    pics, db = lib
    rng = np.random.default_rng(7)
    base = rng.integers(0, 255, (400, 600, 3)).astype(np.uint8)
    Image.fromarray(base).save(pics / "goc.jpg", quality=95)
    Image.fromarray(base).resize((300, 200)).save(pics / "nho.jpg", quality=85)
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    sc.run_folders([(str(pics), "data", 0)])
    ids = {os.path.basename(r["path"]): r["id"] for r in db.q("SELECT id,path FROM images")}
    v = db.one("SELECT clip FROM images WHERE id=?", (ids["goc.jpg"],))["clip"]
    db.x("UPDATE images SET clip=? WHERE id=?", (v, ids["nho.jpg"]))
    groups = [g for g in dup.find_groups(db) if ids["goc.jpg"] in g["members"]]    # bỏ qua các ảnh phẳng của bộ dữ liệu thử
    items = dup.deletable(db, groups)
    assert [os.path.basename(p) for _, p, _ in items] == ["nho.jpg"]        # chỉ bản thấp hơn, tệp gốc cao hơn không bị đụng
    removed = []
    monkeypatch.setattr(dup, "_trash", lambda p: (removed.append(p), os.remove(p)))
    n, errs = dup.trash_images(db, items)
    assert n == 1 and not errs and not os.path.exists(pics / "nho.jpg") and os.path.exists(pics / "goc.jpg")
    assert not db.one("SELECT 1 FROM images WHERE id=?", (ids["nho.jpg"],)) and db.one("SELECT 1 FROM images WHERE id=?", (ids["goc.jpg"],))
    # nếu ảnh "thừa" lại có độ phân giải CAO hơn ảnh được chọn giữ thì không bao giờ xóa
    db.x("UPDATE images SET w=10, h=10 WHERE id=?", (ids["goc.jpg"],))
    g2 = [{"keep": ids["goc.jpg"], "members": [ids["goc.jpg"]]}]
    assert dup.deletable(db, g2) == []


def test_clean_archive_keeps_empty_archive_and_restores_from_drive(lib, tmp_path, monkeypatch):
    """Tệp nén đã đồng bộ: xóa ảnh bên trong, giữ tệp rỗng cùng tên; ảnh vẫn khôi phục được từ Drive đúng từng byte."""
    import os
    import time
    import zipfile
    from pp import scan, sync, zipimg
    from test_core import FakeFaces, FakeClip
    pics, db = lib
    zp = tmp_path / "Anna Nguyen.zip"
    originals = {}
    with zipfile.ZipFile(zp, "w") as z:
        for i in range(3):
            data = (pics / f"a{i}.jpg").read_bytes()
            originals[f"a{i}.jpg"] = data
            z.writestr(f"a{i}.jpg", data)
        z.writestr("ghi_chu.txt", b"giu lai")
    folder = tmp_path / "arch"
    folder.mkdir()
    os.replace(zp, folder / "Anna Nguyen.zip")
    arch = str(folder / "Anna Nguyen.zip")
    scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False).run_folders([(str(folder), "data", 0)])
    dest = str(tmp_path / "drive")
    db.set_meta("sync_dir", dest)
    db.set_meta("sync_pw", "pw")
    sync.run(db, dest, "pw")
    assert sync.archive_clean_candidates(db, dest, min_age=3600) == []                  # chưa đủ 1 giờ: chưa dọn
    old = time.time() - 7200
    for fn in os.listdir(os.path.join(sync.root_of(dest), "orig")):
        os.utime(os.path.join(sync.root_of(dest), "orig", fn), (old, old))
    cands = sync.archive_clean_candidates(db, dest, min_age=3600)
    assert len(cands) == 1 and cands[0][0] == arch and len(cands[0][1]) == 3
    assert sync.clean_archive(db, dest, "pw", arch, cands[0][1]) == 3
    assert os.path.isfile(arch)                                                          # tệp nén vẫn còn, cùng tên
    with zipfile.ZipFile(arch) as z:
        assert z.namelist() == ["ghi_chu.txt"]                                           # ảnh đã xóa, tệp khác giữ nguyên
    quét_lại = scan.Scanner(db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False)
    quét_lại.run_folders([(str(folder), "data", 0)])
    assert db.one("SELECT COUNT(*) c FROM images WHERE path LIKE 'zip://%'")["c"] == 3        # ảnh vẫn nằm trong thư viện (đã archived)
    row = db.one("SELECT id,path FROM images WHERE path LIKE '%a1.jpg'")
    assert sync.read_original_any(db, row) == originals["a1.jpg"]                          # đọc từ bản mã hóa trên Drive đúng từng byte
    out = tmp_path / "khoiphuc"
    n, errs = sync.restore(db, [row["id"]], str(out))
    assert n == 1 and not errs and (out / "a1.jpg").read_bytes() == originals["a1.jpg"]    # tải về không mã hóa vẫn bình thường

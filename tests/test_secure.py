import io
import os

import numpy as np
import pytest
from PIL import Image

from pp import cluster, paths, scan, secure
from pp.db import DB
from pp.vault import Vault
from test_core import FakeClip, FakeFaces


@pytest.fixture()
def sec(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    secure.SEC.key = None
    yield secure.SEC
    secure.SEC.key = None


def make_pics(d, n=4):
    d.mkdir(exist_ok=True)
    rng = np.random.default_rng(3)
    out = []
    for i in range(n):
        base = (220, 20, 20) if i % 2 == 0 else (20, 20, 220)
        arr = np.clip(np.array(base) + rng.integers(-8, 8, (200, 300, 3)), 0, 255).astype(np.uint8)
        p = d / f"secret_{i}.jpg"
        Image.fromarray(arr).save(p)
        out.append(p)
    return out


def test_password(sec):
    assert not sec.configured()
    with pytest.raises(ValueError):
        sec.setup(True, True, "short")
    sec.setup(True, True, "mat-khau-dai")
    assert sec.configured() and sec.key
    sec.lock()
    with pytest.raises(secure.WrongPassword):
        sec.unlock("sai-mat-khau")
    sec.unlock("mat-khau-dai")
    assert sec.encrypt and sec.use_password and sec.key == sec.mk


def test_encrypted_db_and_thumbs(sec, tmp_path):
    sec.setup(True, True, "mat-khau-dai")
    pics = make_pics(tmp_path / "pics")
    db = DB(paths.enc_db_path(), key=sec.key)
    scan.Scanner(db, FakeFaces(), FakeClip()).run([str(tmp_path / "pics")])
    cluster.cluster_faces(db)
    cluster.rename_person(db, db.persons()[0]["id"], "TenBiMat")
    db.close()
    raw = open(paths.enc_db_path(), "rb").read()
    assert b"secret_0" not in raw and b"TenBiMat" not in raw and b"SQLite" not in raw
    for f in os.listdir(paths.thumbs_dir()) + os.listdir(paths.faces_dir()):
        sub = paths.thumbs_dir() if f in os.listdir(paths.thumbs_dir()) else paths.faces_dir()
        assert not open(sub / f, "rb").read(3) == b"\xff\xd8\xff"     # không phải JPEG thường
    # mở lại bằng khóa đúng
    db2 = DB(paths.enc_db_path(), key=sec.key)
    assert db2.one("SELECT COUNT(*) c FROM images")["c"] == 4
    assert db2.one("SELECT name FROM persons WHERE name IS NOT NULL")["name"] == "TenBiMat"
    t = db2.images()[0]["thumb"]
    assert Image.open(io.BytesIO(sec.read_file(t))).size[0] <= 320
    db2.close()
    # khóa sai
    with pytest.raises(secure.WrongPassword):
        DB(paths.enc_db_path(), key=os.urandom(32))


def test_import_mode(sec, tmp_path):
    sec.setup(True, True, "mat-khau-dai")
    pics = make_pics(tmp_path / "pics")
    originals = {p.name: p.read_bytes() for p in pics}
    db = DB(paths.enc_db_path(), key=sec.key)
    v = Vault(paths.vault_dir())
    v.use_key(sec.key)
    r = scan.Scanner(db, FakeFaces(), FakeClip(), vault=v).run_import(str(tmp_path / "pics"), delete_originals=True)
    assert r["done"] == 4
    assert not any(p.exists() for p in pics)            # ảnh gốc đã bị xóa
    rows = db.images()
    assert len(rows) == 4 and all(r["vid"] and r["path"].startswith("vault://") for r in rows)
    assert {r["name"] for r in rows} == set(originals)
    for r in rows:                                       # giải mã đúng nguyên bản
        assert v.read(r["vid"]) == originals[r["name"]]
    for f in os.listdir(paths.vault_dir()):
        if f.endswith(".enc"):
            assert open(paths.vault_dir() / f, "rb").read(4) in (b"PPV1",)
    # nhập lại lần hai: không nhập thêm
    assert scan.Scanner(db, FakeFaces(), FakeClip(), vault=v).run_import(str(tmp_path / "pics"))["total"] == 0
    # không có mô hình thì từ chối
    with pytest.raises(RuntimeError):
        scan.Scanner(db, vault=v).run_import(str(tmp_path / "pics"))


def test_per_folder_levels(sec, tmp_path):
    """Thư mục A giữ ảnh gốc, thư mục B mã hóa cả ảnh gốc; sau đó nâng A lên mức mã hóa."""
    sec.setup(True, True, "mat-khau-dai")
    a = make_pics(tmp_path / "A", 2)
    b = make_pics(tmp_path / "B", 2)
    db = DB(paths.enc_db_path(), key=sec.key)
    v = Vault(paths.vault_dir())
    v.use_key(sec.key)
    db.add_folder(str(tmp_path / "A"), "data")
    db.add_folder(str(tmp_path / "B"), "all", 1)
    sc = scan.Scanner(db, FakeFaces(), FakeClip(), vault=v)
    rows = [(r["path"], r["level"], r["del_orig"]) for r in db.folder_rows()]
    assert sc.run_folders(rows)["done"] == 4
    assert all(p.exists() for p in a) and not any(p.exists() for p in b)
    imgs = db.images()
    assert sum(1 for r in imgs if r["vid"]) == 2 and sum(1 for r in imgs if not r["vid"]) == 2
    # gắn nhãn cho ảnh ở A, rồi nâng A lên mức mã hóa: nhãn phải còn
    lid = db.x("INSERT INTO labels(name) VALUES('x')").lastrowid
    plain = [r["id"] for r in imgs if not r["vid"]]
    for i in plain:
        db.x("INSERT INTO label_images VALUES(?,?)", (lid, i))
    db.set_folder_level(str(tmp_path / "A"), "all", 0)
    rows = [(r["path"], r["level"], r["del_orig"]) for r in db.folder_rows()]
    r = sc.run_folders(rows)
    assert all(p.exists() for p in a)                     # chọn giữ ảnh gốc
    imgs = db.images()
    assert len(imgs) == 4 and all(r["vid"] for r in imgs)
    assert sorted(db.label_ids(lid)) == sorted(plain)
    assert {r["name"] for r in imgs if r["id"] in plain} == {p.name for p in a}


def test_recovery_and_change_password(sec):
    rk = sec.setup(True, True, "mat-khau-dai")
    assert len(rk.replace("-", "")) == 52 and sec.has_recovery()
    mk = sec.key
    sec.lock()
    # quên mật khẩu: dùng khóa khôi phục (gõ thường, thêm khoảng trắng vẫn nhận)
    sec.recover(" " + rk.lower() + " ", "mat-khau-moi-1")
    assert sec.key == mk
    sec.lock()
    with pytest.raises(secure.WrongPassword):
        sec.unlock("mat-khau-dai")
    sec.unlock("mat-khau-moi-1")
    assert sec.key == mk
    with pytest.raises(secure.WrongPassword):
        sec.recover("AAAA-BBBB", "mat-khau-moi-2")
    # đổi mật khẩu
    sec.change_password("mat-khau-moi-1", "mat-khau-moi-3")
    sec.lock()
    with pytest.raises(secure.WrongPassword):
        sec.unlock("mat-khau-moi-1")
    sec.unlock("mat-khau-moi-3")
    assert sec.key == mk
    sec.lock()
    sec.recover(rk, "mat-khau-moi-4")        # khóa khôi phục vẫn dùng được sau khi đổi mật khẩu
    assert sec.key == mk
    # tạo khóa khôi phục mới: khóa cũ vô hiệu
    rk2 = sec.new_recovery_key("mat-khau-moi-4")
    assert rk2 != rk
    sec.lock()
    with pytest.raises(secure.WrongPassword):
        sec.recover(rk, "mat-khau-moi-5")
    sec.recover(rk2, "mat-khau-moi-5")
    assert sec.key == mk


def test_migrate_v1(sec):
    """Cấu hình đời đầu (khóa sinh thẳng từ mật khẩu) vẫn mở được, dữ liệu cũ không phải mã hóa lại."""
    import json
    salt = os.urandom(16)
    k1 = secure.derive("mat-khau-cu-1", salt)
    sec.cfg.write_text(json.dumps({"v": 1, "mode": "data", "salt": salt.hex(), "check": secure.seal(k1, b"private-picture").hex()}))
    sec.unlock("mat-khau-cu-1")
    assert sec.key == k1
    cfg = json.loads(sec.cfg.read_text())
    assert cfg["v"] == 3 and cfg["encrypt"] and cfg["password"] and not sec.has_recovery()
    sec.lock()
    sec.unlock("mat-khau-cu-1")
    assert sec.key == k1
    rk = sec.new_recovery_key("mat-khau-cu-1")
    sec.lock()
    sec.recover(rk, "mat-khau-cu-2")
    assert sec.key == k1


# ---------------------------------------------------------------- hai công tắc độc lập
def test_matrix_no_security(sec):
    assert sec.setup(False, False) is None            # không có gì cần khôi phục
    sec.lock()
    sec.unlock()                                       # mở thẳng
    assert sec.key is None and not sec.use_password and sec.mk is None
    p = paths.app_dir() / "x.bin"
    sec.write_file(p, b"plain")
    assert p.read_bytes() == b"plain"                  # không mã hóa


def test_matrix_encrypt_without_password(sec):
    rk = sec.setup(True, False)                        # khóa gắn tài khoản Windows (DPAPI)
    assert rk and sec.key and not sec.use_password
    mk = sec.key
    p = paths.app_dir() / "y.bin"
    sec.write_file(p, b"secret")
    assert p.read_bytes()[:4] == secure.MAGIC and b"secret" not in p.read_bytes()
    sec.lock()
    assert not sec.needs_password()
    sec.unlock()                                       # không cần nhập gì
    assert sec.key == mk and sec.read_file(p) == b"secret"
    # tài khoản Windows đổi/hỏng: khóa khôi phục mở lại được
    import json
    cfg = json.loads(sec.cfg.read_text())
    cfg["wrap_os"] = secure.dpapi.protect(os.urandom(32)).hex()[:-4] + "0000" if secure.dpapi.SECURE else "00"
    sec.cfg.write_text(json.dumps(cfg))
    sec.lock()
    with pytest.raises((secure.UnlockError, secure.WrongPassword, ValueError, Exception)):
        sec.unlock()
    sec.recover(rk)
    assert sec.key == mk


def test_matrix_password_only_app_lock(sec):
    rk = sec.setup(False, True, "mat-khau-dai")
    assert rk and sec.key is None and sec.mk and sec.use_password
    p = paths.app_dir() / "z.bin"
    sec.write_file(p, b"abc")
    assert p.read_bytes() == b"abc"                    # dữ liệu không mã hóa, chỉ khóa ứng dụng
    sec.lock()
    with pytest.raises(secure.WrongPassword):
        sec.unlock("sai-mat-khau")
    sec.unlock("mat-khau-dai")
    assert sec.key is None and sec.use_password
    sec.lock()
    sec.recover(rk, "mat-khau-moi-1")
    sec.lock()
    sec.unlock("mat-khau-moi-1")


def test_reconfigure_transitions(sec):
    sec.setup(True, True, "mat-khau-dai")
    mk = sec.mk
    # tắt mật khẩu (giữ mã hóa): mở thẳng bằng tài khoản Windows, khóa gốc không đổi
    with pytest.raises(secure.WrongPassword):
        sec.reconfigure(True, False, current_password="sai")
    assert sec.reconfigure(True, False, current_password="mat-khau-dai") is None
    sec.lock()
    sec.unlock()
    assert sec.key == mk and not sec.use_password
    # bật lại mật khẩu
    with pytest.raises(ValueError):
        sec.reconfigure(True, True, "ngan")
    sec.reconfigure(True, True, "mat-khau-moi-9")
    sec.lock()
    with pytest.raises(secure.WrongPassword):
        sec.unlock("mat-khau-dai")
    sec.unlock("mat-khau-moi-9")
    assert sec.key == mk
    # tắt mã hóa (giữ mật khẩu = khóa ứng dụng)
    sec.reconfigure(False, True, current_password="mat-khau-moi-9")
    assert sec.key is None and sec.mk == mk
    # tắt cả hai
    sec.reconfigure(False, False, current_password="mat-khau-moi-9")
    assert sec.mk is None and not sec.cfg.read_text().count("wrap_pw")
    sec.lock()
    sec.unlock()
    assert sec.key is None
    # bật mã hóa từ không có gì: tạo khóa gốc mới và khóa khôi phục
    rk = sec.reconfigure(True, False)
    assert rk and sec.key


def test_migrate_roundtrip(sec, tmp_path):
    """Không mã hóa -> mã hóa -> không mã hóa: dữ liệu giữ nguyên."""
    from pp import migrate
    pics = make_pics(tmp_path / "pics")
    sec.setup(False, False)
    db = DB(paths.db_path())
    scan.Scanner(db, FakeFaces(), FakeClip()).run([str(tmp_path / "pics")])
    cluster.cluster_faces(db)
    cluster.rename_person(db, db.persons()[0]["id"], "TenBiMat")
    db.close()
    thumbs = sorted(os.listdir(paths.thumbs_dir()))
    plain_thumb = (paths.thumbs_dir() / thumbs[0]).read_bytes()
    assert plain_thumb[:3] == b"\xff\xd8\xff"
    # bật mã hóa
    old = sec.key
    sec.reconfigure(True, False)
    migrate.run(old, sec.key)
    assert not paths.db_path().exists() and paths.enc_db_path().exists()
    raw = paths.enc_db_path().read_bytes()
    assert b"secret_0" not in raw and b"TenBiMat" not in raw
    assert (paths.thumbs_dir() / thumbs[0]).read_bytes()[:4] == secure.MAGIC
    db = DB(paths.enc_db_path(), key=sec.key)
    assert db.one("SELECT name FROM persons WHERE name IS NOT NULL")["name"] == "TenBiMat"
    assert sec.read_file(db.images()[0]["thumb"])[:3] == b"\xff\xd8\xff"
    db.close()
    # tắt mã hóa
    old = sec.key
    sec.reconfigure(False, False)
    migrate.run(old, sec.key)
    assert paths.db_path().exists() and not paths.enc_db_path().exists()
    assert (paths.thumbs_dir() / thumbs[0]).read_bytes() == plain_thumb
    db = DB(paths.db_path())
    assert db.one("SELECT COUNT(*) c FROM images")["c"] == 4
    assert db.one("SELECT name FROM persons WHERE name IS NOT NULL")["name"] == "TenBiMat"


def test_dpapi_roundtrip():
    blob = secure.dpapi.protect(b"khoa-bi-mat-32-byte-abcdefghijkl")
    assert blob != b"khoa-bi-mat-32-byte-abcdefghijkl" or not secure.dpapi.SECURE
    assert secure.dpapi.unprotect(blob) == b"khoa-bi-mat-32-byte-abcdefghijkl"

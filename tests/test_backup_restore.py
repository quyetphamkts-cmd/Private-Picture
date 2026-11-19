"""Sao lưu lên thư mục Drive (mã hóa bằng khóa đồng bộ), liệt kê, khôi phục hai bước, quay lại, dọn bản cũ trên ổ C:."""
import json
import os
import time
import zipfile

import pytest

from pp import backup, paths, sync
from pp.secure import WrongPassword, encode_recovery
from test_core import lib  # noqa: F401


def _seed():
    root = paths.app_dir()
    (root / "thumbs").mkdir(exist_ok=True)
    (root / "faces").mkdir(exist_ok=True)
    (root / "thumbs" / "a.jpg").write_bytes(b"THUMB-A-ORIGINAL")
    (root / "faces" / "f.bin").write_bytes(b"FACE-1")
    (root / "security.json").write_text('{"v": 1}')
    (root / "ai3d_keys.enc").write_bytes(b"SECRET")
    return root


def _drive(db, tmp_path, pw="dong-bo-123"):
    d = tmp_path / "G" / "My Drive"
    d.mkdir(parents=True)
    db.set_meta("sync_dir", str(d))
    db.set_meta("sync_pw", pw)
    return d


def test_encrypted_backup_to_drive_and_restore(lib, tmp_path):
    pics, db = lib
    root = _seed()
    drive = _drive(db, tmp_path)
    dest, where = backup.target(db)
    assert where == "drive" and dest == os.path.join(str(drive), backup.FOLDER)
    key, salt = backup.sync_key(db)
    assert key is not None and salt
    db.x("INSERT INTO labels(name) VALUES('Gia đình')")
    db.commit()
    path = backup.make_backup(db, dest, include_vault=False, keep=3, key=key, salt=salt)

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert "backup.json" in names and "info.pe" in names and "data/thumbs/a.jpg" in names
        assert not any("ai3d_keys" in n for n in names)
        assert z.read("data/thumbs/a.jpg") != b"THUMB-A-ORIGINAL"          # từng tệp được mã hóa
        assert b"THUMB-A" not in z.read("data/thumbs/a.jpg")
    info = backup.read_info(path, key)
    assert info["labels"] == 1 and info["head"]["encrypted"]
    with pytest.raises(WrongPassword):
        backup.read_info(path, os.urandom(32))
    head = backup.header(path)
    assert backup.key_for(head, "dong-bo-123") == key                   # mật khẩu đồng bộ lúc sao lưu
    assert backup.key_for(head, encode_recovery(key)) == key            # hoặc khóa khôi phục
    with pytest.raises(WrongPassword):
        backup.key_for(head, "sai")

    # dữ liệu thay đổi sau khi sao lưu
    (root / "thumbs" / "a.jpg").write_bytes(b"CHANGED")
    (root / "thumbs" / "new.jpg").write_bytes(b"NEW")
    db.x("INSERT INTO labels(name) VALUES('Du lịch')")
    db.commit()
    backup.stage_restore(path, key)
    assert backup.staged()
    db.close()

    meta = backup.apply_staged()
    assert meta and not backup.staged()
    assert (root / "thumbs" / "a.jpg").read_bytes() == b"THUMB-A-ORIGINAL"
    assert not (root / "thumbs" / "new.jpg").exists()
    assert (root / "ai3d_keys.enc").read_bytes() == b"SECRET"            # khóa API không bị đụng tới
    from pp import db as dbm
    db2 = dbm.DB(paths.db_path())
    assert [r["name"] for r in db2.q("SELECT name FROM labels")] == ["Gia đình"]
    db2.close()
    assert backup.pending_old()
    backup.finish_restore()
    assert not backup.pending_old() and not (root / backup.OLD).exists()


def test_undo_restore_and_vault_kept(lib, tmp_path):
    pics, db = lib
    root = _seed()
    (root / "vault2").mkdir(exist_ok=True)
    (root / "vault2" / "v1").write_bytes(b"VAULT")
    out = tmp_path / "bk"
    path = backup.make_backup(db, str(out), include_vault=False, keep=3)       # không mã hóa, không gồm kho
    (root / "thumbs" / "a.jpg").write_bytes(b"CHANGED")
    backup.stage_restore(path)
    db.close()
    backup.apply_staged()
    assert (root / "vault2" / "v1").read_bytes() == b"VAULT"               # kho không có trong bản sao lưu: giữ nguyên
    assert (root / "thumbs" / "a.jpg").read_bytes() == b"THUMB-A-ORIGINAL"
    assert backup.undo_restore()
    assert (root / "thumbs" / "a.jpg").read_bytes() == b"CHANGED"
    assert (root / "vault2" / "v1").read_bytes() == b"VAULT"
    assert not backup.pending_old()


def test_list_rotation_and_legacy_cleanup(lib, tmp_path, monkeypatch):
    pics, db = lib
    _seed()
    monkeypatch.setattr(backup, "legacy_dir", lambda: tmp_path / "Documents" / "PrivatePicture-backup")
    legacy = backup.legacy_dir()
    legacy.mkdir(parents=True)
    (legacy / "PrivatePicture-backup-20261119-085802.zip").write_bytes(b"old")
    (legacy / "ghi-chu.txt").write_text("giữ lại", encoding="utf-8")
    drive = _drive(db, tmp_path)
    dest, _ = backup.target(db)
    key, salt = backup.sync_key(db)
    for _ in range(3):
        backup.make_backup(db, dest, include_vault=False, keep=2, key=key, salt=salt)
        time.sleep(1.1)
    items = backup.list_backups([(dest, "Google Drive"), (str(legacy), "Tài liệu (ổ C:)")])
    assert [b["where"] for b in items] == ["Google Drive", "Google Drive", "Tài liệu (ổ C:)"]
    assert items[0]["when"] > items[1]["when"]
    assert backup.clean_legacy() == 1
    assert (legacy / "ghi-chu.txt").exists()                              # chỉ xóa tệp sao lưu


def test_target_folder_and_no_drive(lib, tmp_path):
    pics, db = lib
    assert backup.target(db)[0] is None                                   # chưa thiết lập Drive
    db.set_meta("backup_place", "folder")
    db.set_meta("backup_dir", str(tmp_path / "D"))
    assert backup.target(db) == (str(tmp_path / "D"), "folder")


def test_not_enough_space(lib, tmp_path, monkeypatch):
    pics, db = lib
    _seed()
    import shutil
    from collections import namedtuple
    U = namedtuple("U", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: U(10, 10, 0))
    with pytest.raises(backup.BackupError):
        backup.make_backup(db, str(tmp_path / "bk"), include_vault=False)
    assert not [f for f in os.listdir(tmp_path / "bk") if f.endswith(".part")]


def test_old_format_and_bad_entries(lib, tmp_path):
    pics, db = lib
    root = _seed()
    db.snapshot()
    old = tmp_path / "PrivatePicture-backup-20261101-101010.zip"       # định dạng cũ: tệp nằm ở gốc zip
    with zipfile.ZipFile(old, "w") as z:
        z.write(paths.db_path(), "library.db")
        z.writestr("thumbs/a.jpg", b"OLD-THUMB")
    info = backup.stage_restore(str(old))
    assert info["head"]["v"] == 1
    assert (root / backup.STAGE / "thumbs" / "a.jpg").read_bytes() == b"OLD-THUMB"
    bad = tmp_path / "PrivatePicture-backup-20261101-101011.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("backup.json", json.dumps({"v": 2, "encrypted": False, "dirs": []}))
        z.writestr("info.json", "{}")
        z.writestr("data/library.db", b"x")
        z.writestr("data/../evil.txt", b"x")
    with pytest.raises(backup.BackupError):
        backup.stage_restore(str(bad))
    assert not (tmp_path / "evil.txt").exists()


def test_backup_dialog_backup_list_and_restore(tmp_path, monkeypatch):
    """Hộp thoại: sao lưu lên thư mục Drive, hiện trong danh sách, chọn bản rồi khôi phục -> chuẩn bị xong và yêu cầu mở lại app."""
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == "Khôi phục"))
    from pp.db import DB
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    from pp.ui.pages import BackupDialog
    db = DB(paths.db_path())
    _seed()
    _drive(db, tmp_path)
    db.set_meta("dup_auto", "0")
    w = MainWindow(AppContext(db=db))
    restarted = []
    monkeypatch.setattr(w, "restart_app", lambda: restarted.append(1))
    dlg = BackupDialog(w.ctx, w.pages["account"])
    assert dlg.r_drive.isChecked() and "PrivatePicture-Backup" in dlg.r_drive.text()

    def wait(th):
        while th.isRunning():
            app.processEvents()
            th.wait(50)
        app.processEvents()

    dlg.start()
    wait(dlg.worker)
    assert "Đã sao lưu" in dlg.status.text(), dlg.status.text()
    assert dlg.list.count() == 1 and dlg.list.item(0).data(0x0100)
    dlg.list.setCurrentRow(0)
    dlg.restore()
    wait(dlg.rw)                     # đọc thông tin -> hộp xác nhận (tự bấm Khôi phục) -> chuẩn bị
    wait(dlg.rw)
    assert backup.staged(), dlg.status.text()
    assert restarted == [1]
    assert len(backup.list_backups([(backup.drive_dir(db), "Drive")])) == 2      # đã tự sao lưu dữ liệu hiện tại trước khi khôi phục

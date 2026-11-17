import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest


def test_first_run_lock_unlock(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from pp import paths, secure
    from pp.ui import main as m
    from pp.ui import security as sd
    secure.SEC.key = None
    typed = {"pw": "mat-khau-dai"}

    def setup_exec(self):
        self.cb_enc.setChecked(True)
        self.cb_pw.setChecked(True)
        self.pw.setText(typed["pw"])
        self.pw2.setText(typed["pw"])
        self.ok()
        return 1

    def login_exec(self):
        self.pw.setText(typed["pw"])
        self.ok()
        return 1 if secure.SEC.key else 0
    monkeypatch.setattr(sd.RecoveryShowDialog, "exec", lambda self: 1)
    monkeypatch.setattr(sd.SetupDialog, "exec", setup_exec)
    monkeypatch.setattr(sd.LoginDialog, "exec", login_exec)
    monkeypatch.setattr(m, "SetupDialog", sd.SetupDialog)
    monkeypatch.setattr(m, "LoginDialog", sd.LoginDialog)

    ctl = m.Controller(app)
    ctl.start()
    assert ctl.win is not None and secure.SEC.key
    ctl.win.ctx.db.add_folder("/x/y", "all", 1)
    ctl.win.ctx.db.x("INSERT INTO persons(name) VALUES('Bí mật')")
    first = ctl.win
    ctl.lock()                      # khóa rồi mở lại bằng mật khẩu
    assert ctl.win is not first and ctl.win is not None
    rows = ctl.win.ctx.db.folder_rows()
    assert rows[0]["path"] == "/x/y" and rows[0]["level"] == "all"
    assert ctl.win.ctx.db.one("SELECT name FROM persons")["name"] == "Bí mật"
    assert "Bí mật".encode() not in open(paths.enc_db_path(), "rb").read()
    ctl.win.locking = True
    ctl.win.close()
    ctl.timer.stop()
    app.removeEventFilter(ctl)
    ctl.win = None
    # sai mật khẩu thì không mở
    secure.SEC.lock()
    with pytest.raises(secure.WrongPassword):
        secure.SEC.unlock("sai-mat-khau")


def test_folder_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from pp.ui.pages import FolderDialog
    d = FolderDialog(None, "/a/b")
    assert d.result_level() == ("data", False) and not d.dele.isEnabled()
    d.r2.setChecked(True)
    assert d.dele.isEnabled()
    d.dele.setChecked(True)
    assert d.result_level() == ("all", True)
    d2 = FolderDialog(None, "/a/b", allow_keep=False)
    assert d2.result_level()[0] == "all" and not d2.r1.isEnabled()


def test_recovery_dialogs(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    from pp import secure
    from pp.ui import security as sd
    secure.SEC.key = None
    rk = secure.SEC.setup(True, True, "mat-khau-dai")
    mk = secure.SEC.key
    secure.SEC.lock()
    d = sd.RecoverDialog()
    d.rk.setText(rk)
    d.pw.setText("mat-khau-moi-1")
    d.pw2.setText("mat-khau-moi-2")
    d.ok()
    assert "không khớp" in d.err.text() and not secure.SEC.key
    d.pw2.setText("mat-khau-moi-1")
    d.rk.setText("SAI-SAI")
    d.ok()
    assert "không đúng" in d.err.text() and not secure.SEC.key
    d.rk.setText(rk)
    d.ok()
    assert secure.SEC.key == mk
    # hộp hiện khóa: chỉ bấm Tiếp tục được sau khi tick xác nhận
    r = sd.RecoveryShowDialog(rk)
    ok = r.ok_btn
    assert not ok.isEnabled()
    r.chk.setChecked(True)
    assert ok.isEnabled()


# ---------------------------------------------------------------- các tổ hợp công tắc
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n, lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    from pp import secure
    from pp.ui import main as m, security as sd
    secure.SEC.key = secure.SEC.mk = None
    monkeypatch.setattr(sd.RecoveryShowDialog, "exec", lambda self: 1)
    return app, m, sd, secure


def _setup_with(sd, monkeypatch, enc, pw, password="mat-khau-dai"):
    def setup_exec(self):
        self.cb_enc.setChecked(enc)
        self.cb_pw.setChecked(pw)
        self.pw.setText(password)
        self.pw2.setText(password)
        self.ok()
        return 1
    monkeypatch.setattr(sd.SetupDialog, "exec", setup_exec)


def _close(app, ctl):
    ctl.timer.stop()
    app.removeEventFilter(ctl)
    if ctl.win:
        ctl.win.locking = True
        ctl.win.close()
        ctl.win = None


def test_start_without_any_security(tmp_path, monkeypatch):
    app, m, sd, secure = _env(tmp_path, monkeypatch)
    _setup_with(sd, monkeypatch, False, False)
    called = []
    monkeypatch.setattr(sd.LoginDialog, "exec", lambda self: called.append(1) or 0)
    ctl = m.Controller(app)
    ctl.start()
    assert ctl.win is not None and not called
    assert not ctl.win.ctx.encrypted and not ctl.win.ctx.has_password
    assert "vault" not in ctl.win.keys                       # không có Kho mã hóa khi tắt mã hóa
    ctl.win.ctx.db.x("INSERT INTO persons(name) VALUES('Rõ chữ')")
    _close(app, ctl)
    from pp import paths
    assert paths.db_path().exists() and not paths.enc_db_path().exists()
    # mở lại: vào thẳng, không hỏi gì
    ctl2 = m.Controller(app)
    secure.SEC.key = None
    ctl2.start()
    assert ctl2.win is not None and not called
    assert ctl2.win.ctx.db.one("SELECT name FROM persons")["name"] == "Rõ chữ"
    _close(app, ctl2)


def test_encrypt_without_password_opens_directly(tmp_path, monkeypatch):
    app, m, sd, secure = _env(tmp_path, monkeypatch)
    _setup_with(sd, monkeypatch, True, False)
    called = []
    monkeypatch.setattr(sd.LoginDialog, "exec", lambda self: called.append(1) or 0)
    ctl = m.Controller(app)
    ctl.start()
    assert ctl.win.ctx.encrypted and not ctl.win.ctx.has_password and "vault" in ctl.win.keys
    ctl.win.ctx.db.x("INSERT INTO persons(name) VALUES('Bí mật')")
    ctl.lock()                                               # không có mật khẩu thì không khóa
    assert ctl.win is not None and not called
    _close(app, ctl)
    from pp import paths
    assert "Bí mật".encode() not in paths.enc_db_path().read_bytes()
    ctl2 = m.Controller(app)
    secure.SEC.lock()
    ctl2.start()                                             # mở lại: tự giải mã bằng khóa gắn tài khoản
    assert ctl2.win.ctx.db.one("SELECT name FROM persons")["name"] == "Bí mật" and not called
    _close(app, ctl2)


def test_change_security_flow(tmp_path, monkeypatch):
    app, m, sd, secure = _env(tmp_path, monkeypatch)
    _setup_with(sd, monkeypatch, True, True)
    monkeypatch.setattr(sd.LoginDialog, "exec", lambda self: (self.pw.setText("mat-khau-dai"), self.ok(), 1)[2])
    ctl = m.Controller(app)
    ctl.start()
    db = ctl.win.ctx.db
    db.add_folder("/x/y", "all", 1)
    db.x("INSERT INTO persons(name) VALUES('Giữ lại')")
    # sai mật khẩu hiện tại: không đổi gì, cửa sổ mở lại
    ctl.change_security({"encrypt": False, "password": False, "new": "", "current": "sai-mat-khau"})
    assert ctl.win is not None and secure.SEC.encrypt and secure.SEC.use_password
    # tắt cả hai
    ctl.change_security({"encrypt": False, "password": False, "new": "", "current": "mat-khau-dai"})
    assert ctl.win is not None and not secure.SEC.encrypt and not secure.SEC.use_password
    assert not ctl.win.ctx.encrypted
    r = ctl.win.ctx.db.folder_rows()[0]
    assert r["level"] == "data" and r["del_orig"] == 0       # mức “mã hóa cả ảnh gốc” chuyển về giữ ảnh gốc
    assert ctl.win.ctx.db.one("SELECT name FROM persons")["name"] == "Giữ lại"
    # bật lại: mã hóa, không mật khẩu
    ctl.change_security({"encrypt": True, "password": False, "new": "", "current": ""})
    assert ctl.win.ctx.encrypted and "vault" in ctl.win.keys
    assert ctl.win.ctx.db.one("SELECT name FROM persons")["name"] == "Giữ lại"
    from pp import paths
    assert paths.enc_db_path().exists() and not paths.db_path().exists()
    _close(app, ctl)


def test_cannot_disable_encryption_with_vault_items(tmp_path, monkeypatch):
    app, m, sd, secure = _env(tmp_path, monkeypatch)
    _setup_with(sd, monkeypatch, True, False)
    ctl = m.Controller(app)
    ctl.start()
    from PIL import Image
    p = tmp_path / "a.jpg"
    Image.new("RGB", (40, 30)).save(p)
    ctl.win.ctx.vault.add(str(p))
    ctl.change_security({"encrypt": False, "password": False, "new": "", "current": ""})
    assert secure.SEC.encrypt and ctl.win is not None         # bị chặn, vẫn mã hóa
    _close(app, ctl)


def test_setup_dialog_validation(tmp_path, monkeypatch):
    app, m, sd, secure = _env(tmp_path, monkeypatch)
    d = sd.SetupDialog()
    d.cb_pw.setChecked(True)
    d.pw.setText("abcdefgh")
    d.pw2.setText("khacnhau1")
    d.ok()
    assert "không khớp" in d.err.text() and not secure.SEC.configured()
    d.pw2.setText("abcdefgh")
    d.pw.setText("abc")
    d.pw2.setText("abc")
    d.ok()
    assert "ít nhất 8" in d.err.text() and not secure.SEC.configured()
    d.cb_pw.setChecked(False)
    assert not d.pw.isEnabled()

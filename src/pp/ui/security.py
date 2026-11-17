"""Màn hình đặt mật khẩu lần đầu (chọn chế độ mã hóa) và màn hình đăng nhập."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from ..secure import SEC, WrongPassword


class SetupDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Private Picture – Thiết lập bảo mật")
        self.setMinimumWidth(560)
        l = QVBoxLayout(self)
        intro = QLabel("<h2 style='margin:0'>Thiết lập bảo mật</h2>"
                       "Mỗi tính năng dưới đây bật hay tắt tùy bạn, và đổi lại được sau trong <b>Cài đặt</b>.")
        intro.setWordWrap(True)
        l.addWidget(intro)
        self.cb_enc = QCheckBox("Mã hóa dữ liệu của ứng dụng (khuyên dùng)")
        d1 = QLabel("Tên người, nhãn, danh mục ảnh, ảnh thu nhỏ, khuôn mặt và Kho mã hóa được mã hóa AES-256. "
                    "Bật mã hóa mới dùng được mức “mã hóa cả ảnh gốc” cho từng thư mục.")
        self.cb_pw = QCheckBox("Hỏi mật khẩu khi mở ứng dụng")
        d2 = QLabel("Nếu bật mã hóa mà tắt mật khẩu, ứng dụng mở thẳng và khóa mã hóa gắn với tài khoản Windows của bạn "
                    "(người dùng tài khoản khác hoặc lấy ổ cứng đi sẽ không đọc được).")
        for d in (d1, d2):
            d.setWordWrap(True)
            d.setStyleSheet("color:#555;margin-left:22px")
        self.cb_enc.setChecked(True)
        self.cb_pw.setChecked(True)
        for w in (self.cb_enc, d1, self.cb_pw, d2):
            l.addWidget(w)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Mật khẩu (ít nhất 8 ký tự)")
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setPlaceholderText("Nhập lại mật khẩu")
        l.addWidget(self.pw)
        l.addWidget(self.pw2)
        self.cb_pw.toggled.connect(self.sync)
        self.cb_enc.toggled.connect(self.sync)
        self.warn = QLabel()
        self.warn.setWordWrap(True)
        l.addWidget(self.warn)
        self.err = QLabel()
        self.err.setStyleSheet("color:#c0392b")
        l.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tiếp tục")
        bb.button(QDialogButtonBox.Ok).setProperty("primary", True)
        bb.button(QDialogButtonBox.Cancel).setText("Thoát")
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        self.sync()

    def sync(self):
        pw = self.cb_pw.isChecked()
        self.pw.setEnabled(pw)
        self.pw2.setEnabled(pw)
        enc = self.cb_enc.isChecked()
        if enc or pw:
            self.warn.setText("<b>Quên mật khẩu (hoặc mất tài khoản Windows) thì chỉ khóa khôi phục mới mở lại được dữ liệu.</b> "
                              "Ứng dụng sẽ đưa bạn khóa này ở bước sau, hãy chép ra nơi an toàn.")
            self.warn.setStyleSheet("color:#b03a2e")
        else:
            self.warn.setText("Tắt cả hai: ứng dụng không bảo vệ gì, ai dùng máy này cũng xem được ảnh và dữ liệu.")
            self.warn.setStyleSheet("color:#555")

    def ok(self):
        enc, pw = self.cb_enc.isChecked(), self.cb_pw.isChecked()
        if pw and self.pw.text() != self.pw2.text():
            self.err.setText("Hai lần nhập mật khẩu không khớp.")
            return
        if not enc and not pw:
            if QMessageBox.question(self, "Không bảo vệ", "Bạn đã tắt cả mã hóa và mật khẩu. Ai dùng máy này cũng xem được dữ liệu. Tiếp tục?") != QMessageBox.Yes:
                return
        try:
            rk = SEC.setup(enc, pw, self.pw.text() if pw else None)
        except ValueError as e:
            self.err.setText(str(e))
            return
        if rk:
            note = ("Vì bạn tắt mật khẩu, khóa mã hóa gắn với tài khoản Windows này. Nếu cài lại Windows hoặc đổi tài khoản, "
                    "chỉ khóa khôi phục này mở lại được dữ liệu.") if (enc and not pw) else ""
            RecoveryShowDialog(rk, note=note).exec()
        self.accept()


class SecurityDialog(QDialog):
    """Đổi hai công tắc bảo mật sau khi đã thiết lập."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thay đổi bảo mật")
        self.setMinimumWidth(560)
        self.was_pw = SEC.use_password
        self.was_enc = SEC.encrypt
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Thay đổi bảo mật</h2>"))
        self.cb_enc = QCheckBox("Mã hóa dữ liệu của ứng dụng")
        self.cb_pw = QCheckBox("Hỏi mật khẩu khi mở ứng dụng")
        self.cb_enc.setChecked(self.was_enc)
        self.cb_pw.setChecked(self.was_pw)
        l.addWidget(self.cb_enc)
        l.addWidget(self.cb_pw)
        self.cur = QLineEdit()
        self.cur.setEchoMode(QLineEdit.Password)
        self.cur.setPlaceholderText("Mật khẩu hiện tại")
        self.cur.setVisible(self.was_pw)
        self.new = QLineEdit()
        self.new.setEchoMode(QLineEdit.Password)
        self.new2 = QLineEdit()
        self.new2.setEchoMode(QLineEdit.Password)
        self.new2.setPlaceholderText("Nhập lại mật khẩu")
        for w in (self.cur, self.new, self.new2):
            l.addWidget(w)
        self.note = QLabel()
        self.note.setWordWrap(True)
        l.addWidget(self.note)
        self.err = QLabel()
        self.err.setStyleSheet("color:#c0392b")
        l.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Áp dụng")
        bb.button(QDialogButtonBox.Ok).setProperty("primary", True)
        bb.button(QDialogButtonBox.Cancel).setText("Hủy")
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        self.cb_pw.toggled.connect(self.sync)
        self.cb_enc.toggled.connect(self.sync)
        self.sync()

    def sync(self):
        pw = self.cb_pw.isChecked()
        show_new = pw
        self.new.setVisible(show_new)
        self.new2.setVisible(show_new)
        self.new.setPlaceholderText("Mật khẩu mới (để trống nếu giữ mật khẩu hiện tại)" if self.was_pw else "Mật khẩu mới (ít nhất 8 ký tự)")
        self.cur.setVisible(self.was_pw)
        msgs = []
        if self.was_enc and not self.cb_enc.isChecked():
            msgs.append("Tắt mã hóa: dữ liệu sẽ được giải mã và lưu không mã hóa. Kho mã hóa phải trống (hãy xuất ảnh ra trước); "
                        "các thư mục mức “mã hóa cả ảnh gốc” sẽ chuyển về “giữ ảnh gốc tại chỗ”.")
        if (not self.was_enc) and self.cb_enc.isChecked():
            msgs.append("Bật mã hóa: dữ liệu hiện có được mã hóa. Có thể mất vài phút nếu thư viện lớn.")
        if self.was_pw and not pw:
            msgs.append("Tắt mật khẩu: ai mở được ứng dụng đều dùng được." + (" Khóa mã hóa sẽ gắn với tài khoản Windows này." if self.cb_enc.isChecked() else ""))
        self.note.setText("<br>".join(msgs))

    def values(self):
        return {"encrypt": self.cb_enc.isChecked(), "password": self.cb_pw.isChecked(),
                "new": self.new.text(), "current": self.cur.text()}

    def ok(self):
        pw = self.cb_pw.isChecked()
        if pw and self.new.text() != self.new2.text():
            self.err.setText("Hai lần nhập mật khẩu mới không khớp.")
            return
        if pw and not self.was_pw and len(self.new.text()) < 8:
            self.err.setText("Mật khẩu cần ít nhất 8 ký tự.")
            return
        if self.was_pw and not self.cur.text():
            self.err.setText("Hãy nhập mật khẩu hiện tại để xác nhận.")
            return
        if (self.cb_enc.isChecked(), pw) == (self.was_enc, self.was_pw) and not self.new.text():
            self.reject()
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, text="Nhập mật khẩu để mở ứng dụng"):
        super().__init__()
        self.setWindowTitle("Private Picture")
        self.setMinimumWidth(380)
        l = QVBoxLayout(self)
        l.addWidget(QLabel(f"<h2 style='margin:0'>🔒 Private Picture</h2>{text}"))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Mật khẩu")
        self.pw.returnPressed.connect(self.ok)
        self.err = QLabel()
        self.err.setStyleSheet("color:#c0392b")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Mở khóa")
        bb.button(QDialogButtonBox.Ok).setProperty("primary", True)
        bb.button(QDialogButtonBox.Cancel).setText("Thoát")
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        forgot = QPushButton("Quên mật khẩu? Dùng khóa khôi phục")
        forgot.setFlat(True)
        forgot.setStyleSheet("color:#1a5fb4;text-align:left")
        forgot.clicked.connect(self.forgot)
        for w in (self.pw, self.err, bb, forgot):
            l.addWidget(w)

    def forgot(self):
        if RecoverDialog().exec():
            self.accept()

    def ok(self):
        try:
            SEC.unlock(self.pw.text())
        except WrongPassword:
            self.err.setText("Sai mật khẩu.")
            self.pw.selectAll()
            return
        except Exception as e:
            self.err.setText(f"Lỗi: {e}")
            return
        self.accept()


class RecoveryShowDialog(QDialog):
    """Hiện khóa khôi phục một lần. Người dùng phải xác nhận đã lưu."""

    def __init__(self, key, first=False, note=""):
        super().__init__()
        self.key = key
        self.setWindowTitle("Khóa khôi phục")
        self.setMinimumWidth(560)
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Khóa khôi phục của bạn</h2>"))
        info = QLabel("Nếu quên mật khẩu, khóa này là <b>cách duy nhất</b> để mở lại dữ liệu và ảnh đã mã hóa. "
                      "Hãy <b>chép ra giấy hoặc lưu vào két, trình quản lý mật khẩu</b>, và cất cách xa máy này. "
                      "Ai có khóa này cũng mở được dữ liệu của bạn. Khóa chỉ hiện một lần.")
        info.setWordWrap(True)
        l.addWidget(info)
        if note:
            n = QLabel(note)
            n.setWordWrap(True)
            l.addWidget(n)
        box = QLineEdit(key)
        box.setReadOnly(True)
        box.setStyleSheet("font:600 15px Consolas,monospace;padding:8px")
        l.addWidget(box)
        row = QHBoxLayout()
        cp = QPushButton("Sao chép")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.key))
        sv = QPushButton("Lưu ra tệp văn bản…")
        sv.clicked.connect(self.save)
        row.addWidget(cp)
        row.addWidget(sv)
        row.addStretch(1)
        l.addLayout(row)
        self.chk = QCheckBox("Tôi đã lưu khóa khôi phục ở nơi an toàn")
        l.addWidget(self.chk)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok)
        self.ok_btn = self.bb.button(QDialogButtonBox.Ok)
        self.ok_btn.setText("Tiếp tục")
        self.ok_btn.setEnabled(False)
        self.chk.toggled.connect(lambda on: self.ok_btn.setEnabled(on))
        self.bb.accepted.connect(self.accept)
        l.addWidget(self.bb)

    def save(self):
        p, _ = QFileDialog.getSaveFileName(self, "Lưu khóa khôi phục", "PrivatePicture-khoa-khoi-phuc.txt", "Văn bản (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write("Private Picture - KHÓA KHÔI PHỤC\n" + self.key + "\n\nCất tệp này tách khỏi máy tính. Ai có khóa này đều mở được dữ liệu.\n")

    def reject(self):   # không cho đóng khi chưa xác nhận đã lưu
        if self.chk.isChecked():
            super().reject()


class RecoverDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Khôi phục bằng khóa")
        self.setMinimumWidth(520)
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Quên mật khẩu</h2>Nhập khóa khôi phục và đặt mật khẩu mới."))
        self.rk = QLineEdit()
        self.rk.setPlaceholderText("Khóa khôi phục (ABCD-EFGH-…)")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        needs = SEC.needs_password()
        self.pw.setPlaceholderText("Mật khẩu mới (ít nhất 8 ký tự)" if needs else "Mật khẩu mới (có thể để trống)")
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setPlaceholderText("Nhập lại mật khẩu mới")
        self.err = QLabel()
        self.err.setStyleSheet("color:#c0392b")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        for w in (self.rk, self.pw, self.pw2, self.err, bb):
            l.addWidget(w)

    def ok(self):
        if self.pw.text() != self.pw2.text():
            self.err.setText("Hai lần nhập mật khẩu không khớp.")
            return
        try:
            SEC.recover(self.rk.text(), self.pw.text() or None)
        except WrongPassword:
            self.err.setText("Khóa khôi phục không đúng.")
            return
        except ValueError as e:
            self.err.setText(str(e))
            return
        QMessageBox.information(self, "Xong", "Đã đặt mật khẩu mới.")
        self.accept()

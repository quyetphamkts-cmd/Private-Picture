import os
import shutil
import sys
import time

from PySide6.QtCore import QEvent, QObject, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import migrate, paths
from ..watcher import FolderWatcher
from ..db import DB
from ..secure import SEC, UnlockError, WrongPassword
from ..vault import Vault
from . import theme
from .ctx import AppContext
from .pages import (AccountPage, BackupWorker, ComboPage, FavoritesPage, DuplicatesPage, LabelsPage, LibraryPage, PeoplePage, SearchPage, SettingsPage, SimilarPage, VaultPage)
from .security import LoginDialog, RecoverDialog, RecoveryShowDialog, SetupDialog

PAGES = [("library", "All", LibraryPage), ("people", "Người", PeoplePage), ("combo", "Mashup", ComboPage), ("favorites", "Favorite", FavoritesPage), ("similar", "Ảnh tương tự", SimilarPage), ("dups", "Ảnh trùng lặp", DuplicatesPage),
         ("search", "Search", SearchPage), ("labels", "Nhãn", LabelsPage),
         ("vault", "Kho mã hóa", VaultPage),
         ("settings", "Cài đặt", SettingsPage)]           # một mục Cài đặt gồm hai thẻ: Thư mục và quét, Tài khoản và dữ liệu
# Ứng dụng như một cuốn sổ danh bạ ảnh: thanh bên chỉ có hai mục chính; các công cụ còn lại nằm trong nút "Công cụ"
NAV = ["people", "library", "combo", "favorites", "search", "settings"]          # giống thanh dưới của Android: Model, All, Mashup, Favorite, (Search), Cài đặt
TOOL_GROUPS = []
HIDDEN = ["labels", "similar", "dups"]      # vẫn có trang (các nút nội bộ mở tới), nhưng không hiện trong menu
IDLE_LOCK_SECONDS = 10 * 60


class MainWindow(QMainWindow):
    lock_requested = Signal()

    def __init__(self, ctx=None):
        super().__init__()
        self.ctx = ctx or AppContext()
        self.locking = False
        from .. import __version__
        self.setWindowTitle(f"Private Picture  v{__version__}")
        # kích thước theo màn hình đang dùng (không tràn), cho phép thu nhỏ; nội dung từng trang cuộn được khi cửa sổ nhỏ
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen().availableGeometry() if QGuiApplication.primaryScreen() else None
        if scr is not None:
            self.resize(min(1200, int(scr.width() * 0.92)), min(760, int(scr.height() * 0.9)))
            self.move(scr.x() + (scr.width() - self.width()) // 2, scr.y() + (scr.height() - self.height()) // 2)
        else:
            self.resize(1200, 760)
        self.setMinimumSize(640, 420)
        root = QWidget()
        lay = QHBoxLayout(root)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(132)
        left = QVBoxLayout(side)
        left.setContentsMargins(0, 14, 0, 10)
        brand = QLabel("Private\nPicture")
        brand.setStyleSheet("color:#F6DDB4;font-size:16px;font-weight:700;padding:4px 14px 10px 14px;background:transparent")
        left.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        from PySide6.QtCore import QSize
        self.nav.setIconSize(QSize(20, 20))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)       # vẫn cuộn được bằng con lăn; không hiện thanh cuộn trắng trên nền tối
        left.addWidget(self.nav, 1)
        if self.ctx.attached and self.ctx.has_password:
            lockb = QPushButton("🔒 Khóa ứng dụng")
            lockb.clicked.connect(self.lock_requested.emit)
            left.addWidget(lockb)
        self.stack = QStackedWidget()
        self.pages = {}
        self.keys = []
        self.rowkey = {}               # dòng trong thanh bên -> khóa trang
        by = {k: (n, c) for k, n, c in PAGES}
        from PySide6.QtWidgets import QScrollArea
        self.nav_keys = NAV + (["vault"] if self.ctx.encrypted else [])      # Kho mã hóa hiện ngay trên thanh bên khi bật mã hóa
        order = self.nav_keys + [k for g in TOOL_GROUPS for k in g] + HIDDEN
        for key in order:
            if key == "vault" and not self.ctx.encrypted:
                continue               # Kho mã hóa chỉ có khi bật mã hóa
            name, cls = by[key]
            self.keys.append(key)
            p = cls(self.ctx)
            self.pages[key] = p
            if key == "settings":
                from PySide6.QtWidgets import QTabWidget
                acct = AccountPage(self.ctx)
                self.pages["account"] = acct
                hub = QTabWidget()
                hub.setDocumentMode(True)
                hub.addTab(p, "Thư mục và quét")
                hub.addTab(acct, "Tài khoản và dữ liệu")
                self.settings_tabs = hub
                p = hub
            if key in self.nav_keys:
                self.rowkey[self.nav.count()] = key
                self.nav.addItem(QListWidgetItem(theme.nav_icon(key), {"people": "Model", "library": "All", "combo": "Mashup", "favorites": "Favorite", "search": "Search", "settings": "Cài đặt"}.get(key, "Kho mã hóa")))
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QScrollArea.NoFrame)
            # định dạng giới hạn theo tên để KHÔNG lan xuống các hộp thoại mở từ trang (nếu không hộp thoại bị nền đen, chữ tối)
            sc.setObjectName("pageScroll")
            sc.viewport().setObjectName("pageViewport")
            sc.setStyleSheet("QScrollArea#pageScroll{background:transparent}")
            sc.viewport().setStyleSheet("QWidget#pageViewport{background:transparent}")
            sc.setWidget(p)
            self.stack.addWidget(sc)
        # nút "Công cụ" ở cuối thanh bên: nhãn, ảnh tương tự, ảnh trùng, tìm kiếm, kho mã hóa, thư mục và quét, tài khoản
        self.scan_l = QLabel("")                            # tiến độ quét ngầm, nhỏ, chỉ hiện khi đang quét
        self.scan_l.setStyleSheet("color:#D1A468;font-size:11px;padding:0 10px;background:transparent")
        self.scan_l.setWordWrap(True)
        self.scan_l.setVisible(False)
        left.addWidget(self.scan_l)
        self._scan_hide = QTimer(self)                      # thông báo kết quả hiện khoảng 3 giây rồi ẩn
        self._scan_hide.setSingleShot(True)
        self._scan_hide.setInterval(3000)
        self._scan_hide.timeout.connect(lambda: (self.scan_l.setText(""), self.scan_l.setVisible(False)))

        def show_scan(t):
            self.scan_l.setText(t)
            self.scan_l.setVisible(bool(t))
            if t and not t.startswith("Đang"):
                self._scan_hide.start()                      # "Đã quét xong", "Đã dừng quét"…: tự ẩn sau 3 giây
            else:
                self._scan_hide.stop()
        self.ctx.scan_status.connect(show_scan)
        self.tools_b = QPushButton("Cài đặt")
        self.tools_b.setToolTip("Thư mục và quét, tài khoản, sao lưu, đồng bộ, cập nhật")
        self.tools_b.clicked.connect(lambda: self.goto("settings"))
        self.tools_b.setVisible(False)                      # Cài đặt nay là một mục ngang hàng trên thanh bên (như tab Cài đặt của Android)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(side)
        pad = QWidget()
        pl = QVBoxLayout(pad)
        pl.setContentsMargins(20, 14, 20, 12)
        pl.addWidget(self.stack)
        lay.addWidget(pad, 1)
        self.setCentralWidget(root)
        self.nav.currentRowChanged.connect(self.switch)
        self.stack.currentChanged.connect(self.update_scan_gate)
        self.ctx.changed.connect(self.refresh_current)
        self.ctx.locate.connect(self.locate_in_library)
        self.ctx.open_person.connect(self.open_person_page)
        self._nav_timer = QTimer(self)                                  # số đếm trên thanh bên chỉ cập nhật sau khi thao tác dừng (không làm chậm từng thao tác)
        self._nav_timer.setSingleShot(True)
        self._nav_timer.setInterval(700)
        self._nav_timer.timeout.connect(self.update_nav_counts)
        self.ctx.changed.connect(lambda: self._nav_timer.start())
        QTimer.singleShot(0, self.update_nav_counts)
        self.ctx.goto.connect(self.goto)
        from PySide6.QtGui import QShortcut, QKeySequence
        for seq, which in (("Ctrl+Shift+S", "sync"), ("Ctrl+Shift+B", "backup")):             # sao lưu và đồng bộ chạy tự động; phím tắt này chỉ để mở lại hộp cài đặt khi muốn chỉnh
            QShortcut(QKeySequence(seq), self, activated=lambda w=which: (self.pages["account"].sync_phone() if w == "sync" else self.pages["account"].backup()))
        self.goto("settings")          # luôn mở ở trang Cài đặt: người đứng cạnh không nhìn thấy ảnh riêng tư khi app vừa mở (cả lúc mở lại sau khi khóa)
        # theo dõi thư mục: thêm, xóa, đổi tên ảnh trong Windows thì thư viện tự cập nhật
        self.watcher = FolderWatcher(self)
        self.watcher.changed.connect(lambda roots: self.pages["settings"].auto_scan(roots))
        self.ctx.changed.connect(self.sync_watch)
        self.sync_watch()
        self._bw = None
        if self.ctx.attached:
            self._startup = []
            # cập nhật ứng dụng được kiểm tra / tải TRƯỚC; quét ảnh chỉ bắt đầu khi việc cập nhật xong (hoặc không có gì để cập nhật), tối đa chờ 3 phút
            self._scan_started = False

            def start_scan():
                if not self._scan_started:
                    self._scan_started = True
                    self.pages["settings"].auto_scan()
            self.pages["account"].updateIdle.connect(start_scan)
            for ms, fn in ((800, self.pages["account"].auto_check), (180000, start_scan),
                           (12000, self.auto_backup), (20000, self.auto_sync), (30000, self.ensure_sync_setup), (90000, self.auto_refimg)):
                t = QTimer(self)
                t.setSingleShot(True)
                t.timeout.connect(fn)
                t.start(ms)
                self._startup.append(t)
        self._save = QTimer(self)
        self._save.setInterval(2 * 60 * 1000)     # lưu snapshot mã hóa định kỳ
        self._save.timeout.connect(self.ctx.db.snapshot)
        self._save.start()
        self._sync_t = QTimer(self)
        self._sync_t.setInterval(15 * 60 * 1000)
        self._sync_t.timeout.connect(self.auto_sync)
        self._sync_t.start()
        self._chg_t = QTimer(self)                          # thư viện đổi (quét xong, gom mặt, sắp xếp, sửa tay...) rồi yên 10 giây thì tự đồng bộ cho điện thoại
        self._chg_t.setSingleShot(True)
        self._chg_t.timeout.connect(self.sync_if_changed)
        self.ctx.changed.connect(lambda: self._chg_t.start(10000))
        self._bak_t = QTimer(self)                          # sao lưu: mỗi 10 phút xem dữ liệu có đổi không, có thì sao lưu (tối đa mỗi giờ một bản)
        self._bak_t.setInterval(10 * 60 * 1000)
        self._bak_t.timeout.connect(self.auto_backup)
        self._bak_t.start()
        self._poll_t = QTimer(self)                         # mỗi 10 giây xem điện thoại có gửi chỉnh sửa lên không (chiều điện thoại -> PC)
        self._poll_t.setInterval(10000)
        self._poll_t.timeout.connect(self.poll_phone)
        self._poll_t.start()

    def sync_watch(self):
        on = self.ctx.db.get_meta("auto_scan", "1") == "1"
        self.watcher.set_folders([r["path"] for r in self.ctx.db.folder_rows()] if on else [])

    def auto_backup(self):
        import time
        db = self.ctx.db
        if db.get_meta("backup_auto", "1") != "1" or (self._bw and self._bw.isRunning()):
            return
        if not db.get_meta("backup_dir"):                          # sao lưu hoàn toàn tự động: chưa chọn nơi lưu thì dùng thư mục mặc định trong Tài liệu
            from pathlib import Path
            db.set_meta("backup_dir", str(Path.home() / "Documents" / "PrivatePicture-backup"))
        from .. import backup
        sig = db.library_sig()
        if sig == db.get_meta("backup_sig") or not backup.due(db.get_meta("backup_last"), days=1 / 24):      # chỉ sao lưu khi dữ liệu đã đổi, và cách lần trước ít nhất 1 giờ
            return
        self._bw = BackupWorker(db, db.get_meta("backup_dir"), db.get_meta("backup_vault", "1") == "1", int(db.get_meta("backup_keep", "5")))
        self._bw.done.connect(lambda path, err: (db.set_meta("backup_last", time.time()), db.set_meta("backup_sig", sig)) if path else None)
        self._bw.start()

    def auto_refimg(self):
        """Ảnh tham chiếu từ internet cho người đã đặt tên (chỉ gửi tên): chạy nền khi máy rảnh, kiểm tra lại mỗi 6 giờ."""
        db = self.ctx.db
        QTimer.singleShot(6 * 3600 * 1000, self.auto_refimg)
        if db.get_meta("refimg_auto", "1") != "1" or self.busy() or (getattr(self, "_rw", None) and self._rw.isRunning()):
            return
        from .pages import RefWorker
        self._rw = RefWorker(db)
        self._rw.done.connect(lambda n: self.ctx.changed.emit() if n else None)
        self._rw.start(QThread.LowPriority)

    def ensure_sync_setup(self):
        """Đồng bộ điện thoại tự động chạy sau khi đã cấu hình; chưa cấu hình (lần đầu) thì tự mở hộp cài đặt một lần để chọn thư mục Drive và mật khẩu đồng bộ."""
        db = self.ctx.db
        if db.get_meta("sync_dir") and db.get_meta("sync_pw"):
            return
        from .pages import SyncDialog
        SyncDialog(self.ctx, self).exec()

    def _sync_configured(self):
        db = self.ctx.db
        return bool(db.get_meta("sync_dir") and db.get_meta("sync_pw")) and (db.get_meta("sync_auto", "1") == "1" or db.get_meta("sync_after_scan", "1") == "1")

    def start_sync(self, quiet=True):
        """Đồng bộ hai chiều ngay: nhận chỉnh sửa từ điện thoại (thư mục inbox) rồi đẩy thư viện mới nhất lên Drive cho điện thoại. Trả về True nếu đã bắt đầu."""
        db = self.ctx.db
        if not self._sync_configured() or (getattr(self, "_sw", None) and self._sw.isRunning()):
            return False
        from .pages import SyncWorker
        sig = db.library_sig()
        self._sw = SyncWorker(db, db.get_meta("sync_dir"), db.get_meta("sync_pw"), db.get_meta("sync_orig", "1") == "1",
                              self.ctx.vault if self.ctx.vault.unlocked() else None, self.ctx.zip_passwords)
        if not quiet:
            self._sw.progress.connect(lambda d, t, n: self.ctx.scan_status.emit(f"Đang đồng bộ {d}/{t}"))
            self.ctx.scan_status.emit("Đang đồng bộ…")

        def done(st, err):
            if st:
                db.set_meta("sync_last", time.time())
                db.set_meta("sync_sig", sig)
                if not quiet:
                    self.ctx.scan_status.emit("Đã đồng bộ xong")
                self.ctx.changed.emit()
                QTimer.singleShot(31 * 60 * 1000, self.clean_archives_auto)          # sau 31 phút (Drive đã kịp tải lên) mới giải phóng PC
            elif not quiet:
                self.ctx.scan_status.emit("Đồng bộ gặp lỗi")
        self._sw.done.connect(done)
        self._sw.start()
        return True

    def auto_sync(self):
        self.clean_archives_auto()
        if self.busy():
            return
        self.start_sync()

    def sync_if_changed(self):
        """Thư viện đổi (quét xong, gom mặt, sắp xếp, bạn sửa tên / nhãn...) mà chưa đồng bộ thì tự đồng bộ cho điện thoại."""
        db = self.ctx.db
        if not self._sync_configured():
            return
        if self.busy() or (getattr(self, "_sw", None) and self._sw.isRunning()):
            self._chg_t.start(30000)                              # đang quét / đang đồng bộ: thử lại sau
            return
        if db.library_sig() != db.get_meta("sync_sig"):
            self.start_sync(quiet=False)

    def poll_phone(self):
        """Điện thoại gửi chỉnh sửa (đổi tên, thêm vào tên, phân loại...) qua thư mục inbox trên Drive: có thì nhận ngay, không chờ chu kỳ đồng bộ."""
        db = self.ctx.db
        d = db.get_meta("sync_dir")
        if not d or not self._sync_configured():
            return
        try:
            from .. import sync as _s
            inbox = os.path.join(_s.root_of(d), "inbox")
            has = os.path.isdir(inbox) and any(f.endswith(".pe") for f in os.listdir(inbox))
        except OSError:
            return
        if has and not (getattr(self, "_sw", None) and self._sw.isRunning()):
            self.start_sync(quiet=False)

    def clean_archives_auto(self):
        """Dọn tệp nén đã đồng bộ (nếu bật): xóa ảnh bên trong, giữ tệp rỗng cùng tên. Chạy nền, chậm rãi."""
        db = self.ctx.db
        if db.get_meta("sync_clean_archives", "1") != "1" or not db.get_meta("sync_dir") or not db.get_meta("sync_pw"):
            return
        if getattr(self, "_cw", None) and self._cw.isRunning() or (getattr(self, "_sw", None) and self._sw.isRunning()):
            return                                       # không chờ quét xong: chỉ xóa ảnh đã phân tích xong và đã có bản mã hóa giống hệt, nên chạy song song với quét vẫn an toàn
        from .pages import FreeWorker
        self._cw = FreeWorker(db, db.get_meta("sync_dir"), db.get_meta("sync_pw"), self.ctx.zip_passwords, min_age=1800)
        def finished(st, err):
            if not st:
                return
            n_loose, n_arch = st.get("files", 0), st.get("arch_imgs", 0)
            if n_loose or n_arch:
                self.ctx.db.snapshot()
                self.ctx.scan_status.emit(f"Đã giải phóng PC: {n_loose} ảnh rời, {n_arch} ảnh trong tệp nén")
                self.ctx.changed.emit()
                return
            names = {"rar": "ảnh trong tệp .rar/định dạng không xóa bớt được", "ro": "ảnh trong tệp chỉ đọc", "ml": "ảnh chưa phân tích xong", "sync": "ảnh chưa có bản mã hóa trên Drive", "age": "ảnh chưa đủ 30 phút sau khi đồng bộ"}
            parts = [f"{v} {names[k]}" for k, v in (st.get("why") or {}).items() if v and k in names]
            if parts:
                self.ctx.scan_status.emit("Chưa giải phóng được: " + "; ".join(parts))
        self._cw.done.connect(finished)
        self._cw.start(QThread.LowPriority)

    def sync_after_scan(self):
        """Sau khi quét xong có ảnh mới: đẩy lên thư mục đồng bộ cho điện thoại (nếu đã cấu hình), hiện tiến độ ngắn ở thanh bên."""
        if self.ctx.db.get_meta("sync_after_scan", "1") != "1" or not self._sync_configured():
            return
        if self.busy():
            QTimer.singleShot(2000, self.sync_after_scan)               # luồng quét còn đang kết thúc: thử lại sau chốc lát
            return
        self.start_sync(quiet=False)

    def busy(self):
        w = self.pages["settings"].worker
        return bool(w and w.isRunning())

    def switch(self, row):
        key = self.rowkey.get(row)
        if getattr(self, "_shown_once", False) and self.nav.hasFocus():
            self._user_nav = True
        if key is None:
            return
        self.stack.setCurrentIndex(self.keys.index(key))
        self.pages[key].refresh()
        if self.tools_b.property("primary"):                 # đang ở trang của thanh bên: bỏ đánh dấu nút Công cụ
            self.tools_b.setProperty("primary", False)
            self.tools_b.style().unpolish(self.tools_b)
            self.tools_b.style().polish(self.tools_b)

    def refresh_current(self):
        i = self.stack.currentIndex()
        if 0 <= i < len(self.keys):
            key = self.keys[i]
            self.pages[key].refresh()
            if key == "settings":
                self.pages["account"].refresh()

    def update_scan_gate(self, *_):
        """Quét tạm dừng khi người dùng đang ở trong Model / All / Mashup / Favorite (và app đang ở phía trước); ra ngoài các mục đó hoặc ra ngoài app thì chạy tiếp."""
        from .. import scan as _scan
        try:
            key = self.keys[self.stack.currentIndex()]
        except Exception:
            key = None
        _scan.PAUSED[0] = bool(_scan.PAUSE_ENABLED[0] and QApplication.applicationState() == Qt.ApplicationActive and key in (set(NAV) - {"settings"}) | {"vault"})

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_shown_once", False):                  # lần hiện cửa sổ đầu tiên: chắc chắn đang ở Cài đặt (không bao giờ lộ ảnh riêng tư khi vừa mở)
            self._shown_once = True
            self.goto("settings")
            QTimer.singleShot(0, lambda: self.goto("settings"))
            QTimer.singleShot(400, lambda: self.goto("settings") if self._stay_on_settings() else None)

    def _stay_on_settings(self):
        """Trong 0,4 giây đầu sau khi hiện cửa sổ, nếu người dùng chưa tự bấm sang mục khác thì vẫn giữ Cài đặt."""
        return not getattr(self, "_user_nav", False)

    def goto(self, key):
        if key == "account":                       # Tài khoản nay là thẻ thứ hai của mục Cài đặt
            self.goto("settings")
            self.settings_tabs.setCurrentIndex(1)
            return
        if key not in self.keys:
            return
        for row, k in self.rowkey.items():
            if k == key:
                self.nav.setCurrentRow(row)
                if self.keys[self.stack.currentIndex()] != key:      # chắc chắn đúng trang dù tín hiệu của thanh bên không chạy
                    self.stack.setCurrentIndex(self.keys.index(key))
                    self.pages[key].refresh()
                return
        # trang trong "Công cụ": không có dòng trên thanh bên, chuyển thẳng
        self.nav.blockSignals(True)
        self.nav.clearSelection()
        self.nav.setCurrentRow(-1)
        self.nav.blockSignals(False)
        self.stack.setCurrentIndex(self.keys.index(key))
        self.pages[key].refresh()
        if key == "settings":
            self.pages["account"].refresh()
        self.tools_b.setProperty("primary", True)
        self.tools_b.style().unpolish(self.tools_b)
        self.tools_b.style().polish(self.tools_b)

    def open_person_page(self, pid):
        """Mở trang ảnh của một người (từ tên người trong thông tin ảnh)."""
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible() and w is not self:
                w.close()
        self.goto("people")
        page = self.pages["people"]
        page.pid = pid
        page.show_person()

    def locate_in_library(self, iid):
        """Chuyển sang Tất cả và đưa ảnh này vào giữa khung để thấy các ảnh nằm gần nó."""
        for w in QApplication.topLevelWidgets():              # đóng cửa sổ mở rộng / xem nhanh nếu đang mở
            if isinstance(w, QDialog) and w.isVisible() and w is not self:
                w.close()
        self.goto("library")
        self.pages["library"].show_image(iid)

    def update_nav_counts(self):
        """Số model (người) và số ảnh ngay trên thanh bên."""
        db = self.ctx.db
        try:
            people = db.one("""SELECT COUNT(*) c FROM (SELECT p.id FROM persons p JOIN faces f ON f.person_id=p.id WHERE p.hidden=0
                               GROUP BY p.id HAVING p.name IS NOT NULL OR COUNT(DISTINCT f.image_id)>=2)""")["c"]
            photos = db.one("SELECT COUNT(*) c FROM images WHERE id NOT IN (SELECT image_id FROM dup_hidden)")["c"]
            from .. import cluster
            combos = sum(len(v) for v in cluster.mashup_by_count(db).values())
            favs = db.one("SELECT COUNT(*) c FROM label_images WHERE label_id=(SELECT id FROM labels WHERE name='Yêu thích')")["c"]
        except Exception:
            return
        for row, key in self.rowkey.items():
            it = self.nav.item(row)
            if it is not None and key in ("people", "library", "combo", "favorites"):
                it.setText({"people": f"Model\n{people:,}", "library": f"All\n{photos:,}", "combo": f"Mashup\n{combos:,}",
                            "favorites": f"Favorite\n{favs:,}"}[key].replace(",", "."))

    def quit_for_update(self):
        """Thoát hẳn ngay để bộ cập nhật chép tệp mới: dừng các luồng nền, lưu dữ liệu rồi kết thúc tiến trình."""
        try:
            for w in (self.pages["settings"].worker, getattr(self, "_sw", None), self._bw):
                if w is not None and w.isRunning():
                    if hasattr(w, "stop"):
                        w.stop()
                    w.wait(3000)
            self._save.stop()
            self.watcher.stop()
            self.ctx.shutdown()
        finally:
            os._exit(0)

    def closeEvent(self, e):
        w = self.pages["settings"].worker
        if w and w.isRunning():
            w.stop()
            w.wait(8000)
        self._save.stop()
        self.watcher.stop()
        if self._bw and self._bw.isRunning():
            self._bw.wait(60000)
        self.ctx.shutdown()
        super().closeEvent(e)
        src = getattr(self, "pending_update", None)
        if src and not self.locking:                       # bản mới đã tải sẵn ở nền: cài khi người dùng thoát app, không mở lại
            try:
                from .. import updater
                updater.apply(src, restart=False)
            except Exception:
                pass
        if not self.locking:
            QApplication.quit()


class Controller(QObject):
    """Thiết lập lần đầu, đăng nhập (nếu bật mật khẩu), mở cửa sổ chính, tự khóa, đổi cấu hình bảo mật."""

    def __init__(self, app):
        super().__init__()
        self.app, self.win, self.last = app, None, time.time()
        app.setQuitOnLastWindowClosed(False)
        app.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.check_idle)

    def _report_update_failure(self):
        """Lần cập nhật trước thất bại (tập lệnh ghi update_failed.txt): báo cho người dùng biết lý do thay vì im lặng vẫn chạy bản cũ."""
        try:
            from .. import paths, updater
            d = updater.install_dir()
            flag = os.path.join(d, "update_failed.txt") if d else None
            if not flag or not os.path.isfile(flag):
                return
            log = paths.app_dir() / "update.log"
            tail = ""
            try:
                tail = "\n".join(log.read_text(errors="replace").splitlines()[-6:])
            except Exception:
                pass
            os.remove(flag)
            last = [ln for ln in tail.splitlines() if ln.strip()]
            if not last or "that bai" not in " ".join(last[-3:]).lower():
                return                                       # tệp báo lỗi là của lần cũ; lần cập nhật gần nhất đã thành công
            QMessageBox.warning(self.win, "Cập nhật chưa xong",
                                "Lần cập nhật trước không chép được tệp mới nên ứng dụng vẫn là bản cũ (thường do phần mềm diệt virus hoặc thư mục cài đặt đang bị khóa).\n"
                                "Ứng dụng sẽ tự thử lại; nếu vẫn lỗi, hãy tải bản mới thủ công và giải nén đè lên thư mục cũ.\n\n" + tail)
        except Exception:
            pass

    def eventFilter(self, o, e):
        if e.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel):
            self.last = time.time()
        if e.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.Wheel, QEvent.MouseMove):
            from .. import scan as _scan
            _scan.note_input()
        return False

    # ---- khởi động ----
    def start(self):
        SEC.lock()
        if not SEC.configured():
            old_plain = paths.db_path().exists()
            if not SetupDialog().exec():
                self.app.quit()
                return
            if old_plain and SEC.key:          # đã có dữ liệu chưa mã hóa từ trước: mã hóa luôn
                migrate.run(None, SEC.key)
        elif not self.login():
            self.app.quit()
            return
        self.open_main()

    def login(self):
        """Mở khóa theo cấu hình. Trả về False nếu người dùng thoát."""
        if SEC.needs_password():
            return bool(LoginDialog().exec())
        try:
            SEC.unlock(None)
            return True
        except UnlockError as e:         # khóa gắn tài khoản Windows không mở được: dùng khóa khôi phục
            QMessageBox.warning(None, "Không mở được dữ liệu", str(e))
            return bool(RecoverDialog().exec())

    def open_db(self):
        want_enc = SEC.key is not None
        enc, plain = paths.enc_db_path(), paths.db_path()
        if want_enc and not enc.exists() and plain.exists():       # đổi dở dang lần trước: hoàn tất chuyển đổi
            migrate.convert_db(None, SEC.key)
        if not want_enc and not plain.exists() and enc.exists():
            raise RuntimeError("Dữ liệu đang ở dạng mã hóa nhưng cấu hình báo là không mã hóa. Hãy dùng khóa khôi phục hoặc khôi phục từ bản sao lưu.")
        return DB(enc if want_enc else plain, key=SEC.key)

    def open_main(self):
        try:
            db = self.open_db()
            vault = Vault(paths.vault_dir())
            if SEC.key:
                vault.use_key(SEC.key)
        except Exception as ex:
            QMessageBox.critical(None, "Không mở được dữ liệu", f"{ex}")
            self.app.quit()
            return
        self.win = MainWindow(AppContext(db, vault, attached=True))
        self.win.lock_requested.connect(self.lock)
        self.win.ctx.security_change.connect(self.change_security)
        self.win.showMaximized()                                # mặc định mở toàn màn hình
        from .. import scan as _scan
        _scan.PAUSE_ENABLED[0] = True
        from PySide6.QtCore import Qt as _Qt
        self.app.applicationStateChanged.connect(lambda st: (_scan.APP_ACTIVE.__setitem__(0, st == _Qt.ApplicationActive), self.win.update_scan_gate()))      # bấm ra ngoài app thì quét chạy hết tốc lực
        QTimer.singleShot(2500, self._report_update_failure)
        self.last = time.time()
        self.timer.start()

    def check_idle(self):
        if self.win and SEC.use_password and not self.win.busy() and time.time() - self.last > IDLE_LOCK_SECONDS:
            self.lock()

    def lock(self):
        if not SEC.use_password:
            return
        self.timer.stop()
        if self.win:
            self.win.locking = True
            self.win.close()
            self.win = None
        SEC.lock()
        if LoginDialog("Ứng dụng đã khóa. Nhập mật khẩu để mở lại.").exec():
            self.open_main()
        else:
            self.app.quit()

    # ---- đổi cấu hình bảo mật ----
    def change_security(self, v):
        win = self.win
        if win is None:
            return
        if SEC.encrypt and not v["encrypt"] and win.ctx.vault.index:
            QMessageBox.warning(win, "Không tắt được mã hóa", f"Kho mã hóa còn {len(win.ctx.vault.index)} ảnh. Hãy xuất ảnh ra "
                                "(chuột phải ảnh đã mã hóa → Xuất ảnh giải mã) và xóa khỏi kho trước khi tắt mã hóa.")
            return
        self.timer.stop()
        old_key = SEC.key
        was_encrypted = SEC.encrypt
        win.locking = True
        win.close()
        self.win = None
        rk = None
        try:
            rk = SEC.reconfigure(v["encrypt"], v["password"], v["new"] or None, v["current"] or None)
            self.app.setOverrideCursor(Qt.WaitCursor)
            try:
                migrate.run(old_key, SEC.key)
            finally:
                self.app.restoreOverrideCursor()
            if was_encrypted and not v["encrypt"]:        # mức “mã hóa cả ảnh gốc” không còn ý nghĩa
                db = self.open_db()
                db.x("UPDATE folders SET level='data', del_orig=0 WHERE level='all'")
                db.close()
            QMessageBox.information(None, "Đã đổi bảo mật", "Đã áp dụng cấu hình bảo mật mới.")
        except WrongPassword:
            QMessageBox.warning(None, "Lỗi", "Mật khẩu hiện tại không đúng. Chưa có gì thay đổi.")
        except ValueError as e:
            QMessageBox.warning(None, "Lỗi", str(e))
        except Exception as e:
            QMessageBox.critical(None, "Lỗi khi đổi bảo mật", f"{e}")
        if rk:
            note = ("Khóa mã hóa gắn với tài khoản Windows này; cài lại Windows hoặc đổi tài khoản thì chỉ khóa khôi phục này mở lại được dữ liệu."
                    if (SEC.encrypt and not SEC.use_password) else "")
            RecoveryShowDialog(rk, note=note).exec()
        self.open_main()


def _single_instance(name="PrivatePicture-instance"):
    """Chỉ cho chạy MỘT cửa sổ ứng dụng: nếu đã có bản đang chạy thì đưa nó lên trước rồi thoát bản mới. Trả về máy chủ cục bộ (giữ tham chiếu) hoặc None."""
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(400):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return None
    server = QLocalServer()
    QLocalServer.removeServer(name)
    server.listen(name)
    return server


def _raise_ui_priority():
    """Luồng giao diện chạy mức ưu tiên cao hơn một nấc so với các luồng nền (quét, nhận diện) để thao tác luôn mượt (Windows)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), 1)        # ABOVE_NORMAL
        except Exception:
            pass


def run():
    _raise_ui_priority()
    sys.setswitchinterval(0.001)                 # luồng giao diện giành lại quyền chạy Python nhanh hơn khi luồng quét đang bận (mặc định 5 ms)
    app = QApplication(sys.argv)
    try:
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(paths.resource("assets/logo.png"))))          # logo: biểu tượng cửa sổ và thanh tác vụ
    except Exception:
        pass
    server = _single_instance()
    if server is None:
        os._exit(0)                                         # đã có một cửa sổ đang chạy
    theme.apply(app)
    ctl = Controller(app)

    def raise_window():
        for conn in iter(lambda: server.nextPendingConnection(), None):
            conn.readAll()
        w = ctl.win
        if w is not None:
            w.showNormal()
            w.raise_()
            w.activateWindow()
    server.newConnection.connect(raise_window)
    QTimer.singleShot(0, ctl.start)
    rc = app.exec()
    os._exit(rc)           # kết thúc ngay sau khi đã lưu dữ liệu: tránh lỗi khi dọn dẹp các phiên ONNX lúc thoát

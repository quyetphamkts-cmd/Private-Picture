"""Theo dõi các thư mục ảnh: khi người dùng thêm, xóa, sửa hoặc đổi tên ảnh trong Windows thì báo để ứng dụng tự cập nhật."""
import os

from PySide6.QtCore import QObject, QTimer, Signal

from .scan import EXTS

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    AVAILABLE = True
except Exception:       # thiếu thư viện thì chỉ cập nhật khi quét tay hoặc khi mở ứng dụng
    FileSystemEventHandler = object
    Observer = None
    AVAILABLE = False


def _relevant(path):
    name = os.path.basename(path or "")
    if not name or name.startswith("~$") or name.endswith((".tmp", ".part", ".crdownload")):
        return False
    ext = os.path.splitext(name)[1].lower()
    from . import zipimg
    return ext in EXTS or zipimg.is_archive_name(name) or ext == ""        # ảnh, file nén (zip, rar, 7z...), hoặc thư mục


class _Handler(FileSystemEventHandler):
    def __init__(self, root, emit):
        super().__init__()
        self.root, self.emit = root, emit

    def on_any_event(self, event):
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return
        paths = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
        if any(_relevant(p) for p in paths if p):
            self.emit(self.root)


class FolderWatcher(QObject):
    changed = Signal(list)           # danh sách thư mục gốc có thay đổi
    _hit = Signal(str)

    def __init__(self, parent=None, debounce_ms=6000):
        super().__init__(parent)
        self.obs = Observer() if AVAILABLE else None
        self.watches = {}            # thư mục -> watch
        self.pending = set()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(debounce_ms)
        self.timer.timeout.connect(self._fire)
        self._hit.connect(self._on_hit)
        self._started = False

    def set_folders(self, folders):
        if not AVAILABLE:
            return
        want = {os.path.abspath(f) for f in folders if os.path.isdir(f)}
        for f in list(self.watches):
            if f not in want:
                try:
                    self.obs.unschedule(self.watches.pop(f))
                except Exception:
                    self.watches.pop(f, None)
        for f in want - set(self.watches):
            try:
                self.watches[f] = self.obs.schedule(_Handler(f, self._hit.emit), f, recursive=True)
            except Exception:
                pass
        if not self._started and self.watches:
            self.obs.daemon = True
            self.obs.start()
            self._started = True

    def _on_hit(self, root):
        self.pending.add(root)
        self.timer.start()           # đợi người dùng thao tác xong (chép nhiều tệp) rồi mới cập nhật

    def _fire(self):
        roots, self.pending = sorted(self.pending), set()
        if roots:
            self.changed.emit(roots)

    def stop(self):
        self.timer.stop()
        if self.obs is not None and self._started:
            try:
                self.obs.stop()
                self.obs.join(2)
            except Exception:
                pass
            self._started = False

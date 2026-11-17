import os

from PySide6.QtCore import QObject, Signal

from .. import models, paths
from ..secure import SEC
from ..db import DB
from ..vault import Vault


class AppContext(QObject):
    changed = Signal()      # dữ liệu thư viện đã đổi
    scan_status = Signal(str)   # tiến độ quét ngầm (hiện nhỏ ở thanh bên); chuỗi rỗng = xong
    open_person = Signal(int)   # mở trang ảnh của một người (mã người)
    locate = Signal(int)    # chuyển tới vị trí của một ảnh (mã ảnh) trong mục Tất cả ảnh
    goto = Signal(str)      # yêu cầu chuyển trang
    security_change = Signal(dict)   # yêu cầu đổi cấu hình bảo mật (bộ điều khiển xử lý)

    def __init__(self, db=None, vault=None, attached=False):
        super().__init__()
        self.db = db or DB(paths.db_path())
        try:
            from .. import clothing
            clothing.remove_clothing_labels(self.db)       # phân loại trang phục không còn là nhãn ảnh
            from .. import cluster
            cluster.merge_same_name(self.db)               # hai nhóm cùng tên: gộp một lần khi mở app
        except Exception:
            pass
        self.vault = vault or Vault(paths.vault_dir())
        self.attached = attached  # True: kho dùng khóa chính của ứng dụng (không có mật khẩu riêng)
        self._clip = None
        # mật khẩu file nén: chỉ lưu vào cơ sở dữ liệu khi đang bật mã hóa; nếu không thì chỉ giữ trong phiên làm việc
        self.zip_passwords = {}
        if self.encrypted:
            for r in self.db.q("SELECT k,v FROM meta WHERE k LIKE 'zippw:%'"):
                self.zip_passwords[r["k"][6:]] = r["v"]

    def set_zip_password(self, zip_path, pw):
        self.zip_passwords[zip_path] = pw
        if self.encrypted:
            self.db.set_meta("zippw:" + zip_path, pw)

    @property
    def encrypted(self):
        """Có đang mã hóa dữ liệu (và dùng được Kho mã hóa) không."""
        return (SEC.key is not None) if self.attached else True

    @property
    def has_password(self):
        return SEC.use_password if self.attached else False

    def shutdown(self):
        if not self.attached:
            self.vault.lock()
        self.db.close()

    def backup(self, dest):
        """Nén toàn bộ dữ liệu của ứng dụng (đã mã hóa) vào một tệp zip."""
        import zipfile
        self.db.snapshot()
        root = paths.app_dir()
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:
            for name in ("security.json", "library.enc"):
                if (root / name).exists():
                    z.write(root / name, name)
            for d in ("thumbs", "faces", "vault2"):
                for dp, _, fns in os.walk(root / d):
                    for fn in fns:
                        full = os.path.join(dp, fn)
                        z.write(full, os.path.relpath(full, root))

    def move_to_vault(self, items, delete_original):
        """Mã hóa ảnh đã có trong thư viện vào kho; giữ nguyên nhãn, tên người, dữ liệu phân tích."""
        import os
        import uuid
        n = 0
        for it in items:
            if it.get("vid"):
                continue
            vid = uuid.uuid4().hex
            self.vault.add(it["path"], iid=vid)
            self.db.x("UPDATE images SET path=?,vid=?,name=? WHERE id=?",
                      (f"vault://{vid}", vid, os.path.basename(it["path"]), it["id"]))
            if delete_original:
                try:
                    os.remove(it["path"])
                except OSError:
                    pass
            n += 1
        self.changed.emit()
        return n

    def delete_from_vault(self, items):
        for it in items:
            if it.get("vid"):
                self.vault.remove(it["vid"])
        self.purge_images([it["id"] for it in items if it.get("vid")])

    def models_ready(self):
        return models.ready()

    def clip(self):
        if self._clip is None and models.have(models.CLIP_FILES):
            try:
                self._clip = models.ClipEngine()
            except Exception:
                self._clip = None
        return self._clip

    def purge_images(self, ids):
        """Xóa ảnh khỏi danh mục và dọn cả ảnh thu nhỏ, ảnh mặt đã lưu trong bộ nhớ đệm."""
        db = self.db
        for i in ids:
            for r in db.q("SELECT thumb FROM faces WHERE image_id=?", (i,)):
                _rm(r["thumb"])
            r = db.one("SELECT thumb FROM images WHERE id=?", (i,))
            if r:
                _rm(r["thumb"])
            db.c.execute("DELETE FROM faces WHERE image_id=?", (i,))
            db.c.execute("DELETE FROM label_images WHERE image_id=?", (i,))
            db.c.execute("DELETE FROM images WHERE id=?", (i,))
        db.c.execute("DELETE FROM persons WHERE id NOT IN (SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL) AND name IS NULL")
        db.commit()
        self.changed.emit()


def _rm(p):
    try:
        if p:
            os.remove(p)
    except OSError:
        pass

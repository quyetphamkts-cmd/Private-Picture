"""Quét thư mục ảnh: tạo ảnh thu nhỏ, đọc ngày chụp, nhận diện mặt, vector nội dung.

Hai cách dùng:
  - quét thường: ảnh giữ nguyên ở thư mục cũ (chỉ lưu danh mục và ảnh thu nhỏ)
  - nhập vào kho (chế độ "mã hóa tất cả"): mỗi ảnh được mã hóa vào kho, dữ liệu phân tích lưu kèm
"""
import hashlib
import io
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
from PIL import Image, ImageOps

from . import paths, zipimg
from .db import vec_to_blob
from .secure import SEC

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # không có HEIC cũng chạy được
    pass

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".gif"}
SKIP_DIRS = {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)", "appdata"}
THUMB = 320
ML_SIDE = 1280


def iter_files(folders, zips=False, passwords=None, locked=None):
    """Duyệt ảnh trong thư mục. zips=True: duyệt cả ảnh nằm trong các file .zip (đường dẫn ảo zip://…!/…).
    Ảnh trong zip có mật khẩu mà chưa có mật khẩu thì bỏ qua và ghi đường dẫn zip vào `locked`."""
    passwords = passwords or {}
    for root in folders:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d.lower() not in SKIP_DIRS and not d.startswith(".")]
            for fn in fns:
                ext = os.path.splitext(fn)[1].lower()
                p = os.path.join(dp, fn)
                if ext in EXTS:
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    yield p, st.st_mtime, st.st_size
                elif zips and zipimg.is_archive_name(fn):
                    try:
                        st = os.stat(p)
                        ents = zipimg.entries(p, passwords.get(p))
                    except zipimg.PasswordNeeded:
                        if locked is not None:
                            locked.add(p)
                        continue
                    except Exception:
                        continue
                    for name, size, enc in ents:
                        if enc and not passwords.get(p):
                            if locked is not None:
                                locked.add(p)
                            continue
                        yield zipimg.make(p, name), st.st_mtime, size


def keep_encrypted_copies(db, rows):
    """Ảnh đã được mã hóa vào app (bản gốc mã hóa đã nằm trong thư mục đồng bộ) mà tệp gốc trên PC bị xóa: KHÔNG xóa khỏi thư viện, ghi nhận 'archived'
    để vẫn xem, phân tích và khôi phục được từ bản mã hóa. Ngoại lệ: ảnh trùng lặp do app tự ẩn / xóa thì để nguyên quy trình cũ. Trả về tập mã ảnh được giữ."""
    dest = db.get_meta("sync_dir")
    if not dest or not rows:
        return set()
    from . import sync as _sync
    root = _sync.root_of(dest)
    dup = {r["image_id"] for r in db.q("SELECT image_id FROM dup_hidden")}
    kept = set()
    for r in rows:
        if r["id"] in dup:
            continue
        u = _sync.uid_of(r["path"], r["mtime"], r["size"])
        if os.path.exists(os.path.join(root, "orig", u + ".pe")):
            db.x("INSERT OR REPLACE INTO archived(image_id,uid) VALUES(?,?)", (r["id"], u))
            kept.add(r["id"])
    return kept


def _under(path, roots):
    return os.path.normcase(os.path.abspath(zipimg.archive_of(path))).startswith(roots)


def _taken(im, mtime):
    try:
        ex = im.getexif()
        v = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        if v:
            return datetime.strptime(str(v)[:19], "%Y:%m:%d %H:%M:%S").isoformat(sep=" ")
    except Exception:
        pass
    return datetime.fromtimestamp(mtime).isoformat(sep=" ", timespec="seconds")


LAST_INPUT = [0.0]            # thời điểm người dùng thao tác gần nhất (chuột, phím, cuộn): quét nền nhường máy cho giao diện trong lúc đó


PAUSE_ENABLED = [False]      # chỉ bật trong ứng dụng thật (Controller), không bật khi chạy kiểm thử
PAUSED = [False]              # người dùng đang thao tác trong Model / All / Mashup / Favorite: quét tạm dừng, ra ngoài các mục đó (hoặc ra ngoài app) thì chạy tiếp
APP_ACTIVE = [True]           # cửa sổ app đang ở phía trước (người dùng đang dùng); False khi người dùng bấm ra ngoài app hoặc thu nhỏ: quét chạy hết tốc lực


def note_input():
    LAST_INPUT[0] = time.time()


def wait_idle(stop=lambda: False, quiet=1.5, max_wait=12.0):
    """Các bước nặng sau khi quét (gom mặt, phân loại…) chờ người dùng ngừng thao tác một lúc rồi mới chạy, để không giật giao diện (tối đa chờ max_wait giây)."""
    t0 = time.time()
    while PAUSED[0] and not stop():                     # đang dùng Model / All / Mashup / Favorite: chờ cho tới khi ra ngoài
        time.sleep(0.3)
    while APP_ACTIVE[0] and time.time() - LAST_INPUT[0] < quiet and time.time() - t0 < max_wait and not stop():
        time.sleep(0.2)


def load_one(path, mtime, zip_passwords=None):
    """Chạy ở luồng phụ: đọc ảnh, tạo ảnh thu nhỏ (dạng bytes JPEG) và bản dùng cho mô hình."""
    if zipimg.is_zip_path(path):
        im = Image.open(io.BytesIO(zipimg.read(path, (zip_passwords or {}).get(zipimg.archive_of(path)))))
    else:
        im = Image.open(path)
    return _prepare(im, path, mtime)


def load_bytes(data, path, mtime):
    """Như load_one nhưng từ dữ liệu ảnh đã có sẵn (bản gốc giải mã từ Drive cho ảnh đã được app xóa khỏi PC)."""
    return _prepare(Image.open(io.BytesIO(data)), path, mtime)


def _prepare(im, path, mtime):
    taken = _taken(im, mtime)
    orient = im.getexif().get(274, 1)
    ow, oh = im.size
    if orient in (5, 6, 7, 8):
        ow, oh = oh, ow
    if im.format == "JPEG":
        im.draft("RGB", (ML_SIDE * 2, ML_SIDE * 2))
    im = ImageOps.exif_transpose(im)
    if im.mode != "RGB":
        im = im.convert("RGB")
    ml = im.copy()
    ml.thumbnail((ML_SIDE, ML_SIDE), Image.LANCZOS)
    th = im.copy()
    th.thumbnail((THUMB, THUMB), Image.LANCZOS)
    b = io.BytesIO()
    th.save(b, "JPEG", quality=82)
    return {"path": path, "mtime": mtime, "w": ow, "h": oh, "taken": taken, "thumb_bytes": b.getvalue(), "ml": ml}


def _write_thumb(folder, key, data):
    p = folder / f"{key}.jpg"
    SEC.write_file(p, data)
    return str(p)


def _lower_thread_priority():
    """Luồng nền đọc ảnh chạy mức ưu tiên thấp hơn luồng giao diện (Windows) để giao diện luôn mượt khi đang quét."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), -1)       # BELOW_NORMAL
        except Exception:
            pass


class Scanner:
    def __init__(self, db, faces=None, clip=None, progress=None, cancel=lambda: False, vault=None, zip_passwords=None):
        self.db, self.faces, self.clip = db, faces, clip
        self.zip_passwords = zip_passwords if zip_passwords is not None else {}
        self.locked_zips = set()
        self.progress = progress or (lambda *a: None)
        self.cancel = cancel
        self.vault = vault
        self._importing = False
        self._from_drive = {}               # đường dẫn -> mã ảnh: ảnh đã xóa khỏi PC cần phân tích lại từ bản mã hóa trên Drive
        self.throttle = 0.0                 # giây nghỉ sau mỗi ảnh: quét nền nghỉ chút để máy còn sức cho giao diện
        self.stats = {"added": 0, "updated": 0, "removed": 0, "errors": 0, "imported": 0}

    # ------------------------------------------------------------ chung
    def _pipeline(self, todo, handle):
        done, total = 0, len(todo)
        with ThreadPoolExecutor(max_workers=2 if self.throttle else 3, initializer=_lower_thread_priority) as ex:
            window, it = [], iter(todo)

            def feed():
                while len(window) < 8:
                    try:
                        p, m, s = next(it)
                    except StopIteration:
                        return
                    window.append((p, m, s, ex.submit(self._load, p, m)))
            feed()
            while window:
                if self.cancel():
                    break
                p, m, s, fut = window.pop(0)
                feed()
                try:
                    handle(fut.result(), p, m, s)
                except Exception as e:  # ảnh hỏng thì bỏ qua, ghi lỗi
                    self._error(p, m, s, e)
                done += 1
                if done % 20 == 0:
                    self.db.commit()
                if done % 200 == 0:
                    self.db.snapshot()
                self.progress(done, total, p)
                if PAUSED[0] and not self.cancel():
                    self.db.commit()                                # lưu phần đã quét trước khi tạm dừng
                    self.progress(done, total, "Tạm dừng khi bạn đang dùng app, sẽ chạy tiếp khi bạn ra ngoài")
                    while PAUSED[0] and not self.cancel():
                        time.sleep(0.3)
                if APP_ACTIVE[0]:                                  # app đang ở phía trước: quét nhẹ nhàng, nhường giao diện
                    if self.throttle:
                        time.sleep(self.throttle)
                    if time.time() - LAST_INPUT[0] < 1.5:           # đang thao tác: nghỉ dài hơn để không giật
                        time.sleep(0.25)                            # (app ở phía sau: không nghỉ, quét nhanh)
        self.db.snapshot()
        return {"total": total, "done": done}

    def _load(self, p, m):
        iid = self._from_drive.get(p)
        if iid is not None:
            from . import sync
            return load_bytes(sync.read_archived(self.db, iid), p, m)
        return load_one(p, m, self.zip_passwords)

    def _error(self, p, m, s, e):
        self.stats["errors"] += 1
        if self._importing:
            return    # không ghi nhận ảnh hỏng khi nhập vào kho; sẽ thử lại lần sau
        self.db.x("INSERT INTO images(path,mtime,size,err,ml) VALUES(?,?,?,?,1) "
                  "ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime,size=excluded.size,err=excluded.err",
                  (p, m, s, str(e)[:200]))

    # ------------------------------------------------------------ quét thường
    def run_folders(self, rows):
        """rows: [(đường dẫn, mức 'data' hoặc 'all', xóa_ảnh_gốc)]. Mỗi thư mục xử lý theo mức riêng."""
        plain = [r[0] for r in rows if r[1] != "all"]
        tot = {"total": 0, "done": 0}
        parts = []
        if plain:
            parts.append(self.run(plain))
        for path, level, dele in rows:
            if level == "all" and not self.cancel():
                parts.append(self.run_import(path, bool(dele)))
        for r in parts:
            tot["total"] += r["total"]
            tot["done"] += r["done"]
        tot.update(self.stats)
        tot["locked_zips"] = sorted(self.locked_zips)
        return tot

    def run(self, folders):
        db = self.db
        seen = {p: (m, s) for p, m, s in iter_files(folders, True, self.zip_passwords, self.locked_zips)}
        have = {r["path"]: r for r in db.q("SELECT id,path,mtime,size,ml FROM images WHERE vid IS NULL")}
        roots = tuple(os.path.normcase(os.path.abspath(f)) for f in folders)
        # ảnh trong zip đang cần mật khẩu: giữ nguyên trong thư viện (không coi là đã bị xóa)
        archived = {r["image_id"] for r in db.q("SELECT image_id FROM archived")}     # ảnh gốc đã chuyển lên Drive (tệp trên PC đã xóa)
        gone = [r["id"] for p, r in have.items()
                if p not in seen and _under(p, roots) and r["id"] not in archived
                and not (zipimg.is_zip_path(p) and zipimg.archive_of(p) in self.locked_zips)]
        kept = keep_encrypted_copies(db, [r for r in have.values() if r["id"] in set(gone)])         # đã mã hóa vào app rồi thì xóa tệp gốc trên PC không làm mất ảnh
        gone = [i for i in gone if i not in kept]
        self._drop(gone)
        self.stats["removed"] += len(gone)
        want_ml = self.faces is not None and self.clip is not None
        todo = []
        for p, (m, s) in seen.items():
            r = have.get(p)
            if r is None or abs((r["mtime"] or 0) - m) > 1 or r["size"] != s or (want_ml and not r["ml"]):
                todo.append((p, m, s))
                self.stats["added" if r is None else "updated"] += 1
        if want_ml and db.get_meta("sync_dir") and db.get_meta("sync_pw"):
            # ảnh gốc đã được app xóa khỏi PC (archived) mà cần phân tích lại (đổi mô hình, hoặc chưa phân tích xong): đọc bản gốc từ Drive
            for r in db.q("""SELECT i.id,i.path,i.mtime,i.size FROM images i JOIN archived a ON a.image_id=i.id
                             WHERE i.ml=0 AND i.vid IS NULL AND i.err IS NULL"""):
                if r["path"] not in seen and _under(r["path"], roots):
                    todo.append((r["path"], r["mtime"], r["size"]))
                    self._from_drive[r["path"]] = r["id"]
                    self.stats["updated"] += 1
        return self._pipeline(todo, lambda d, p, m, s: self._store(
            d, s, path=p, name=os.path.basename(zipimg.split(p)[1] if zipimg.is_zip_path(p) else p)))

    def _drop(self, ids):
        for i in ids:
            for r in self.db.q("SELECT thumb FROM faces WHERE image_id=?", (i,)):
                _rm(r["thumb"])
            r = self.db.one("SELECT thumb FROM images WHERE id=?", (i,))
            if r:
                _rm(r["thumb"])
            self.db.x("DELETE FROM faces WHERE image_id=?", (i,))
            self.db.x("DELETE FROM label_images WHERE image_id=?", (i,))
            self.db.x("DELETE FROM images WHERE id=?", (i,))

    # ------------------------------------------------------------ nhập vào kho
    def run_import(self, folder, delete_originals=False):
        """Mã hóa từng ảnh trong thư mục vào kho. Ảnh đã có trong danh mục (quét thường trước đó) được chuyển
        đổi tại chỗ, giữ nguyên nhãn và tên người."""
        if self.vault is None:
            raise RuntimeError("Chưa có kho mã hóa")
        if self.faces is None or self.clip is None:
            raise RuntimeError("Cần tải mô hình trước khi nhập ảnh vào kho")
        done_src = {r["src"] for r in self.db.q("SELECT src FROM imported")}
        todo = [(p, m, s) for p, m, s in iter_files([folder]) if p not in done_src]
        self._importing = True

        def handle(d, p, m, s):
            vid = uuid.uuid4().hex
            old = self.db.one("SELECT id,ml FROM images WHERE path=? AND vid IS NULL", (p,))
            if old is not None and old["ml"]:
                self.vault.add(p, iid=vid)
                self.db.x("UPDATE images SET path=?,vid=?,name=? WHERE id=?",
                          (f"vault://{vid}", vid, os.path.basename(p), old["id"]))
            else:
                rid = self._store(d, s, path=f"vault://{vid}", name=os.path.basename(p), vid=vid)
                try:
                    self.vault.add(p, iid=vid)
                except Exception:
                    self._drop([rid])
                    raise
                if old is not None:
                    self._drop([old["id"]])
            self.db.x("INSERT OR REPLACE INTO imported(src,mtime,size,vid) VALUES(?,?,?,?)", (p, m, s, vid))
            self.stats["imported"] += 1
            if delete_originals:
                try:
                    os.remove(p)
                except OSError:
                    pass
        try:
            return self._pipeline(todo, handle)
        finally:
            self._importing = False

    # ------------------------------------------------------------ lưu kết quả
    def _store(self, d, size, path, name, vid=None):
        db = self.db
        vec, faces, ml_done = None, [], 0
        if self.faces is not None and self.clip is not None:
            faces = self.faces.process(np.asarray(d["ml"]))
            vec = self.clip.images([d["ml"]])[0]
            ml_done = 1
        key = hashlib.sha1(f"{path}|{d['mtime']}".encode("utf-8", "ignore")).hexdigest()[:20]
        thumb = _write_thumb(paths.thumbs_dir(), key, d["thumb_bytes"])
        db.x("""INSERT INTO images(path,mtime,size,w,h,taken,thumb,clip,ml,err,vid,name) VALUES(?,?,?,?,?,?,?,?,?,NULL,?,?)
                ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime,size=excluded.size,w=excluded.w,h=excluded.h,
                taken=excluded.taken,thumb=excluded.thumb,clip=excluded.clip,ml=excluded.ml,err=NULL,vid=excluded.vid,name=excluded.name""",
             (path, d["mtime"], size, d["w"], d["h"], d["taken"], thumb,
              vec_to_blob(vec) if vec is not None else None, ml_done, vid, name))
        iid = db.one("SELECT id FROM images WHERE path=?", (path,))["id"]
        if ml_done:
            for r in db.q("SELECT thumb FROM faces WHERE image_id=? AND locked=0", (iid,)):
                _rm(r["thumb"])
            db.x("DELETE FROM faces WHERE image_id=? AND locked=0", (iid,))
            im = d["ml"]
            W, H = im.size
            kept = db.q("SELECT id,x,y,w,h FROM faces WHERE image_id=?", (iid,))      # các mặt đã khóa (đã đặt tên) còn lại
            for f in faces:
                if f["score"] < 0.8:
                    continue
                x, y, w, h = f["box"]
                mine = _match_box(kept, (x, y, w, h))   # mặt đã khóa (đã đặt tên) trùng khung: cập nhật vectơ, giữ nguyên người
                m = 0.3
                box = (max(0, (x - m * w) * W), max(0, (y - m * h) * H), min(W, (x + w + m * w) * W), min(H, (y + h + m * h) * H))
                t = im.crop(tuple(int(v) for v in box))
                t.thumbnail((112, 112), Image.LANCZOS)
                b = io.BytesIO()
                t.save(b, "JPEG", quality=85)
                tp = _write_thumb(paths.faces_dir(), hashlib.sha1(os.urandom(8)).hexdigest()[:20], b.getvalue())
                if mine is not None:
                    old = db.one("SELECT thumb FROM faces WHERE id=?", (mine,))
                    db.x("UPDATE faces SET x=?,y=?,w=?,h=?,score=?,px=?,vec=?,thumb=? WHERE id=?",
                         (x, y, w, h, f["score"], f["px"], vec_to_blob(f["vec"]), tp, mine))
                    if old:
                        _rm(old["thumb"])
                    db.x("DELETE FROM face_attr WHERE face_id=?", (mine,))
                    kept = [k for k in kept if k["id"] != mine]
                    continue
                db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,thumb) VALUES(?,?,?,?,?,?,?,?,?)",
                     (iid, x, y, w, h, f["score"], f["px"], vec_to_blob(f["vec"]), tp))
        return iid


def _match_box(kept, box, min_iou=0.4):
    """Id của mặt cũ (đã khóa) có khung trùng nhất với khung mới, hoặc None."""
    x, y, w, h = box
    best, bi = 0.0, None
    for k in kept:
        ix = max(0.0, min(x + w, k["x"] + k["w"]) - max(x, k["x"]))
        iy = max(0.0, min(y + h, k["y"] + k["h"]) - max(y, k["y"]))
        inter = ix * iy
        union = w * h + k["w"] * k["h"] - inter
        iou = inter / union if union > 0 else 0.0
        if iou > best:
            best, bi = iou, k["id"]
    return bi if best >= min_iou else None


def _rm(p):
    try:
        if p:
            os.remove(p)
    except OSError:
        pass

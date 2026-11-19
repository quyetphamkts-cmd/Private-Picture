"""Sao lưu và khôi phục dữ liệu của ứng dụng.

Nơi lưu mặc định: thư mục `PrivatePicture-Backup` nằm cạnh thư mục đồng bộ điện thoại trong ổ Google Drive (Drive for Desktop),
nên bản sao lưu tự lên mạng mà không chiếm thêm ổ C: (chỉ cần đặt bộ nhớ đệm của Drive ở ổ khác).

Định dạng tệp `PrivatePicture-backup-YYYYmmdd-HHMMSS.zip`:
- `backup.json` (không mã hóa): phiên bản định dạng, thời điểm, có mã hóa không, mẫu kiểm tra khóa, muối của mật khẩu đồng bộ,
  danh sách thư mục có trong bản sao lưu.
- `info.pe` (hoặc `info.json` khi không mã hóa): số ảnh, số người, số nhãn... để hiện trước khi khôi phục.
- `data/<đường dẫn>`: từng tệp dữ liệu; khi mã hóa, mỗi tệp được mã hóa riêng (AES-256-GCM) bằng khóa đồng bộ.

Khôi phục chạy hai bước vì cơ sở dữ liệu đang mở thì không thay được: `stage_restore` giải nén vào `restore-staging`,
lần mở app sau `apply_staged` đổi chỗ dữ liệu cũ sang `before-restore` rồi đưa bản khôi phục vào. Mở được dữ liệu thì
`finish_restore` xóa bản cũ; không mở được thì `undo_restore` trả lại như trước.
"""
import base64
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from . import paths
from .secure import WrongPassword, decode_recovery, derive, seal, unseal

FOLDER = "PrivatePicture-Backup"
PATTERN = re.compile(r"^PrivatePicture-backup-(\d{8})-(\d{6})\.zip$")
SKIP = {"ai3d_keys.enc", "update_token.enc"}      # khóa API và mã cập nhật không đưa vào bản sao lưu
CHECK = b"PPBACKUP1"
FILES = ("security.json", "library.enc", "library.db")
DB_EXTRA = ("library.db-wal", "library.db-shm", "library.enc.tmp")
DIRS = ("thumbs", "faces", "vault2")
STAGE = "restore-staging"
OLD = "before-restore"
MARK = "restore.json"


class BackupError(Exception):
    pass


def legacy_dir():
    """Nơi các bản cũ tự lưu trước đây (Tài liệu trên ổ C:)."""
    return Path.home() / "Documents" / "PrivatePicture-backup"


def drive_dir(db):
    """Thư mục sao lưu trong Google Drive: cạnh thư mục đồng bộ điện thoại. None nếu chưa cấu hình đồng bộ."""
    d = db.get_meta("sync_dir")
    return os.path.join(d, FOLDER) if d else None


def sync_key(db):
    """(khóa, muối) của thư mục đồng bộ điện thoại để mã hóa bản sao lưu; (None, None) nếu chưa cấu hình."""
    d, pw = db.get_meta("sync_dir"), db.get_meta("sync_pw")
    if not d or not pw:
        return None, None
    from . import sync
    try:
        key = sync.setup(d, pw)
        j = json.load(open(os.path.join(sync.root_of(d), "sync.json"), encoding="utf-8"))
        return key, base64.b64decode(j["salt"])
    except Exception:
        return None, None


def target(db):
    """Nơi lưu đang dùng: (thư mục, 'drive' | 'folder') hoặc (None, lý do)."""
    if db.get_meta("backup_place", "drive") == "folder":
        d = (db.get_meta("backup_dir") or "").strip()
        return (d, "folder") if d else (None, "Chưa chọn thư mục lưu.")
    d = drive_dir(db)
    if not d:
        return None, "Chưa thiết lập Google Drive (Đồng bộ điện thoại)."
    if not os.path.isdir(os.path.dirname(d)):
        return None, "Không thấy ổ Google Drive. Hãy mở Google Drive cho máy tính."
    return d, "drive"


def _counts(db):
    one = lambda q: (db.one(q) or [0])[0]
    return {"images": one("SELECT COUNT(*) FROM images"),
            "persons": one("SELECT COUNT(*) FROM persons WHERE name IS NOT NULL AND name<>''"),
            "labels": one("SELECT COUNT(*) FROM labels"),
            "labeled": one("SELECT COUNT(*) FROM label_images"),
            "vault": one("SELECT COUNT(*) FROM images WHERE vid IS NOT NULL")}


def _walk(root, dirs, encrypted_db):
    """Các tệp sẽ đưa vào bản sao lưu: (đường dẫn đầy đủ, tên trong zip). Chỉ lấy tệp CSDL đang dùng (bản .db cũ còn sót
    sau khi bật mã hóa thì bỏ qua, để không lộ dữ liệu chưa mã hóa)."""
    out = []
    for n in FILES:
        if n == ("library.db" if encrypted_db else "library.enc"):
            continue
        p = root / n
        if p.is_file():
            out.append((str(p), n))
    for d in dirs:
        for dp, _, fns in os.walk(root / d):
            for fn in fns:
                if fn in SKIP or fn.endswith((".tmp", ".part")):
                    continue
                full = os.path.join(dp, fn)
                out.append((full, os.path.relpath(full, root).replace(os.sep, "/")))
    return out


def _need_space(path, need):
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return
    if free < need + 64 * 1024 * 1024:
        raise BackupError(f"Không đủ chỗ trống tại {path}: cần khoảng {need / 1048576:.0f} MB, còn {free / 1048576:.0f} MB.")


def make_backup(db, dest_dir, include_vault=True, keep=3, key=None, salt=None, progress=lambda d, t, s: None):
    """Ghi một bản sao lưu vào dest_dir (mã hóa từng tệp nếu có `key`), xóa các bản cũ vượt quá `keep`. Trả về đường dẫn tệp."""
    os.makedirs(dest_dir, exist_ok=True)
    db.snapshot()
    root = paths.app_dir()
    dirs = [d for d in DIRS if include_vault or d != "vault2"]
    items = _walk(root, dirs, db.key is not None)
    _need_space(dest_dir, sum(os.path.getsize(f) for f, _ in items if os.path.exists(f)))
    from . import __version__
    info = dict(_counts(db), app=__version__, created=time.time())
    head = {"v": 2, "created": info["created"], "encrypted": key is not None, "dirs": dirs,
            "check": base64.b64encode(seal(key, CHECK)).decode() if key else None,
            "salt": base64.b64encode(salt).decode() if (key and salt) else None}
    t = int(time.time())
    while True:                                          # không bao giờ ghi đè một bản đã có (hai bản trong cùng một giây)
        dest = os.path.join(dest_dir, time.strftime("PrivatePicture-backup-%Y%m%d-%H%M%S.zip", time.localtime(t)))
        if not os.path.exists(dest) and not os.path.exists(dest + ".part"):
            break
        t += 1
    tmp = dest + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED if key else zipfile.ZIP_DEFLATED, compresslevel=None if key else 1) as z:
            z.writestr("backup.json", json.dumps(head))
            raw = json.dumps(info, ensure_ascii=False).encode("utf-8")
            z.writestr("info.pe" if key else "info.json", seal(key, raw) if key else raw)
            for k, (full, name) in enumerate(items, 1):
                progress(k, len(items), name)
                try:
                    if name == "library.db":
                        with db.lock:                       # đọc tệp CSDL trong lúc không ai ghi, sau khi dồn WAL vào tệp chính: bản sao lưu nhất quán
                            db.con.commit()
                            db.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            data = open(full, "rb").read()
                    else:
                        data = open(full, "rb").read()
                except FileNotFoundError:                   # ảnh thu nhỏ vừa bị xóa trong lúc sao lưu
                    continue
                z.writestr("data/" + name, seal(key, data) if key else data)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    old = sorted(f for f in os.listdir(dest_dir) if PATTERN.match(f))
    for f in old[:-max(1, int(keep))]:
        try:
            os.remove(os.path.join(dest_dir, f))
        except OSError:
            pass
    return dest


def due(last_ts, days=1):
    try:
        return time.time() - float(last_ts) >= days * 86400
    except (TypeError, ValueError):
        return True


def list_backups(places):
    """Các bản sao lưu trong những thư mục cho trước [(thư mục, nhãn nơi lưu)], mới nhất trước. Chỉ đọc tên và kích thước tệp
    (không mở tệp, để không bắt Drive tải cả tệp về)."""
    out, seen = [], set()
    for d, where in places:
        if not d or not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            m = PATTERN.match(f)
            p = os.path.normcase(os.path.abspath(os.path.join(d, f)))
            if not m or p in seen:
                continue
            seen.add(p)
            try:
                size = os.path.getsize(os.path.join(d, f))
                when = time.mktime(time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"))
            except (OSError, ValueError):
                continue
            out.append({"path": os.path.join(d, f), "name": f, "size": size, "when": when, "where": where})
    return sorted(out, key=lambda b: -b["when"])


def _header(z):
    try:
        return json.loads(z.read("backup.json"))
    except KeyError:                                     # bản sao lưu kiểu cũ (v1): các tệp nằm thẳng ở gốc zip, không mã hóa riêng
        return {"v": 1, "encrypted": False, "dirs": [d for d in DIRS if any(n.startswith(d + "/") for n in z.namelist())]}


def header(path):
    with zipfile.ZipFile(path) as z:
        return _header(z)


def key_for(head, secret):
    """Khóa giải mã từ mật khẩu đồng bộ (dùng muối lưu trong bản sao lưu) hoặc khóa khôi phục. Ném WrongPassword nếu sai."""
    chk = base64.b64decode(head["check"])
    cands = []
    if head.get("salt"):
        cands.append(lambda: derive(secret, base64.b64decode(head["salt"])))
    cands.append(lambda: decode_recovery(secret))
    for c in cands:
        try:
            k = c()
            if unseal(k, chk) == CHECK:
                return k
        except WrongPassword:
            pass
    raise WrongPassword()


def read_info(path, key=None):
    """Thông tin của một bản sao lưu (để xác nhận trước khi khôi phục). Bản mã hóa cần `key` đúng, sai thì ném WrongPassword."""
    with zipfile.ZipFile(path) as z:
        head = _header(z)
        if head.get("encrypted"):
            if key is None or unseal(key, base64.b64decode(head["check"])) != CHECK:
                raise WrongPassword()
            info = json.loads(unseal(key, z.read("info.pe")))
        elif head["v"] >= 2:
            info = json.loads(z.read("info.json"))
        else:
            info = {}
    return dict(info, head=head, path=path, size=os.path.getsize(path))


def _safe(name):
    parts = name.split("/")
    if name.startswith("/") or ":" in name or any(p in ("", "..") for p in parts):
        raise BackupError(f"Tên tệp không hợp lệ trong bản sao lưu: {name}")
    if parts[0] not in FILES and parts[0] not in DIRS:
        raise BackupError(f"Tệp lạ trong bản sao lưu: {name}")
    return parts


def stage_restore(path, key=None, progress=lambda d, t, s: None, root=None):
    """Bước 1 của khôi phục: giải nén (và giải mã) bản sao lưu vào thư mục chờ. Áp dụng ở lần mở app sau (apply_staged)."""
    root = Path(root or paths.app_dir())
    info = read_info(path, key)
    head = info["head"]
    stage, tmp = root / STAGE, root / (STAGE + ".part")
    for d in (stage, tmp):
        shutil.rmtree(d, ignore_errors=True)
    tmp.mkdir()
    try:
        with zipfile.ZipFile(path) as z:
            prefix = "data/" if head["v"] >= 2 else ""
            names = [n for n in z.namelist() if n.startswith(prefix) and not n.endswith("/") and n not in ("backup.json", "info.json", "info.pe")]
            _need_space(root, sum(z.getinfo(n).file_size for n in names))
            if not any(n[len(prefix):] in ("library.db", "library.enc") for n in names):
                raise BackupError("Bản sao lưu không có cơ sở dữ liệu thư viện.")
            for k, n in enumerate(names, 1):
                rel = n[len(prefix):]
                parts = _safe(rel)
                progress(k, len(names), rel)
                data = z.read(n)
                if head.get("encrypted"):
                    data = unseal(key, data)
                out = tmp.joinpath(*parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
        for d in head.get("dirs", []):
            (tmp / d).mkdir(exist_ok=True)           # thư mục rỗng trong bản sao lưu vẫn phải thay thư mục hiện tại
        (tmp / MARK).write_text(json.dumps({"source": path, "created": info.get("created"), "dirs": head.get("dirs", []),
                                            "images": info.get("images"), "staged": time.time()}), encoding="utf-8")
        os.replace(tmp, stage)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return info


def staged(root=None):
    root = Path(root or paths.app_dir())
    return (root / STAGE / MARK).is_file()


def apply_staged(root=None):
    """Bước 2 (lúc khởi động, trước khi mở CSDL): chuyển dữ liệu hiện tại sang `before-restore`, đưa bản khôi phục vào.
    Trả về thông tin bản đã khôi phục, hoặc None nếu không có gì chờ."""
    root = Path(root or paths.app_dir())
    stage, old = root / STAGE, root / OLD
    if not (stage / MARK).is_file():
        return None
    meta = json.loads((stage / MARK).read_text(encoding="utf-8"))
    shutil.rmtree(old, ignore_errors=True)
    old.mkdir()
    names = list(FILES) + list(DB_EXTRA)          # thư mục không có trong bản sao lưu (vd. kho mã hóa) được giữ nguyên
    names += [d for d in DIRS if d in meta.get("dirs", []) or (stage / d).exists()]
    meta["dirs"] = [d for d in DIRS if d in names]
    moved, placed = [], []
    try:
        for n in names:
            if (root / n).exists():
                os.replace(root / n, old / n)
                moved.append(n)
        for p in list(stage.iterdir()):
            if p.name != MARK:
                os.replace(p, root / p.name)
                placed.append(p.name)
    except BaseException:                          # đổi chỗ giữa chừng bị lỗi (tệp đang bị khóa...): trả lại như cũ, giữ bản chờ để thử lại
        for n in placed:
            if (root / n).exists():
                os.replace(root / n, stage / n)
        for n in moved:
            if (old / n).exists():
                os.replace(old / n, root / n)
        shutil.rmtree(old, ignore_errors=True)
        raise
    (old / MARK).write_text(json.dumps(dict(meta, moved=moved, applied=time.time())), encoding="utf-8")
    shutil.rmtree(stage, ignore_errors=True)
    return meta


def pending_old(root=None):
    """Thông tin lần khôi phục vừa áp dụng mà chưa xác nhận mở được dữ liệu (còn giữ dữ liệu cũ), hoặc None."""
    p = Path(root or paths.app_dir()) / OLD / MARK
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def finish_restore(root=None):
    """Mở được dữ liệu sau khôi phục: xóa dữ liệu cũ đã cất."""
    shutil.rmtree(Path(root or paths.app_dir()) / OLD, ignore_errors=True)


def undo_restore(root=None):
    """Quay lại dữ liệu trước khi khôi phục."""
    root = Path(root or paths.app_dir())
    old = root / OLD
    meta = pending_old(root)
    if not meta:
        return False
    for n in list(FILES) + list(DB_EXTRA) + list(meta.get("dirs", [])):
        p = root / n
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            os.remove(p)
    for n in meta.get("moved", []):
        if (old / n).exists():
            os.replace(old / n, root / n)
    shutil.rmtree(old, ignore_errors=True)
    return True


def clean_legacy(keep_dir=None):
    """Xóa các bản sao lưu cũ tự lưu trong Tài liệu (ổ C:) sau khi đã có bản trên Drive. Trả về số tệp đã xóa."""
    d = legacy_dir()
    if not d.is_dir() or (keep_dir and os.path.normcase(os.path.abspath(keep_dir)) == os.path.normcase(str(d.resolve()))):
        return 0
    n = 0
    for f in os.listdir(d):
        if PATTERN.match(f) or (f.startswith("PrivatePicture-backup-") and f.endswith(".zip.part")):
            try:
                os.remove(d / f)
                n += 1
            except OSError:
                pass
    try:
        d.rmdir()                                    # chỉ xóa khi đã trống
    except OSError:
        pass
    return n

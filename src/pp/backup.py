"""Sao lưu dữ liệu của ứng dụng vào một thư mục (ví dụ thư mục Google Drive hoặc OneDrive đồng bộ trên máy)."""
import os
import re
import time
import zipfile

from . import paths

PATTERN = re.compile(r"^PrivatePicture-backup-\d{8}-\d{6}\.zip$")
SKIP = {"ai3d_keys.enc", "update_token.enc"}      # khóa API không đưa vào bản sao lưu


def make_backup(db, dest_dir, include_vault=True, keep=5):
    """Nén dữ liệu (đã mã hóa nếu đang bật mã hóa) thành một tệp zip trong dest_dir, xóa các bản cũ vượt quá `keep`."""
    os.makedirs(dest_dir, exist_ok=True)
    db.snapshot()
    root = paths.app_dir()
    dest = os.path.join(dest_dir, time.strftime("PrivatePicture-backup-%Y%m%d-%H%M%S.zip"))
    tmp = dest + ".part"
    names = ["security.json", "library.enc", "library.db"]
    dirs = ["thumbs", "faces"] + (["vault2"] if include_vault else [])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for n in names:
            if (root / n).exists():
                z.write(root / n, n)
        for d in dirs:
            for dp, _, fns in os.walk(root / d):
                for fn in fns:
                    if fn in SKIP:
                        continue
                    full = os.path.join(dp, fn)
                    z.write(full, os.path.relpath(full, root).replace(os.sep, "/"))
    os.replace(tmp, dest)
    old = sorted(f for f in os.listdir(dest_dir) if PATTERN.match(f))
    for f in old[:-max(1, int(keep))]:
        try:
            os.remove(os.path.join(dest_dir, f))
        except OSError:
            pass
    return dest


def due(last_ts, days=7):
    try:
        return time.time() - float(last_ts) >= days * 86400
    except (TypeError, ValueError):
        return True

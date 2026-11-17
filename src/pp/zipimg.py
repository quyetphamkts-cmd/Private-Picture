"""Ảnh nằm trong file nén: ZIP (kể cả mã hóa AES), RAR, 7z, TAR/TGZ/TBZ2/TXZ, CAB, ISO... (kể cả có mật khẩu).
Đường dẫn ảo: zip://<đường dẫn file nén>!/<tên trong file nén>. ZIP và TAR đọc trực tiếp bằng Python; các định dạng còn lại dùng 7-Zip."""
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

try:
    import pyzipper
except Exception:
    pyzipper = None

PREFIX, SEP = "zip://", "!/"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".gif"}
TAR_SUFFIX = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tbz", ".tar.xz", ".txz")
SEVEN_EXT = {".rar", ".7z", ".cab", ".iso", ".arj", ".lzh", ".lha", ".wim", ".udf", ".z", ".cpio", ".rpm", ".deb", ".xar", ".dmg"}
ARCHIVE_EXTS = {".zip"} | SEVEN_EXT | {".tar", ".tgz", ".tbz2", ".tbz", ".txz"}
_VOLUME = re.compile(r"\.part0*([2-9]|[1-9]\d+)\.rar$", re.I)       # phần nối tiếp của rar nhiều tập: chỉ đọc tập đầu


class PasswordNeeded(Exception):
    pass


class NoTool(Exception):
    pass


def is_archive_name(fn):
    n = fn.lower()
    if _VOLUME.search(n):
        return False
    return os.path.splitext(n)[1] in ARCHIVE_EXTS or n.endswith(TAR_SUFFIX)


def kind(path):
    n = path.lower()
    if n.endswith(TAR_SUFFIX):
        return "tar"
    return "zip" if n.endswith(".zip") else "7z"


def is_zip_path(p):
    return bool(p) and p.startswith(PREFIX)


def make(zip_path, entry):
    return f"{PREFIX}{zip_path}{SEP}{entry}"


def split(p):
    body = p[len(PREFIX):]
    i = body.index(SEP)
    return body[:i], body[i + len(SEP):]


def archive_of(p):
    return split(p)[0] if is_zip_path(p) else p


def _img(n):
    return os.path.splitext(n)[1].lower() in IMG_EXTS and not n.endswith("/") and "__MACOSX" not in n and not os.path.basename(n).startswith(".")


# ---------------------------------------------------------------- ZIP
def _zopen(path, password=None):
    cls = pyzipper.AESZipFile if pyzipper else zipfile.ZipFile
    z = cls(path)
    if password:
        z.setpassword(password.encode("utf-8"))
    return z


def _zip_entries(path):
    out = []
    with _zopen(path) as z:
        for i in z.infolist():
            if _img(i.filename):
                out.append((i.filename, i.file_size, bool(i.flag_bits & 0x1)))
    return out


def _zip_read(path, name, password):
    try:
        with _zopen(path, password) as z:
            return z.read(name)
    except RuntimeError as e:
        if "password" in str(e).lower():
            raise PasswordNeeded(path)
        raise
    except Exception as e:
        if "password" in str(e).lower() or "Bad" in type(e).__name__:
            raise PasswordNeeded(path)
        raise


# ---------------------------------------------------------------- TAR
def _tar_entries(path):
    out = []
    with tarfile.open(path) as t:
        for m in t:
            if m.isfile() and _img(m.name):
                out.append((m.name, m.size, False))
    return out


def _tar_read(path, name):
    with tarfile.open(path) as t:
        f = t.extractfile(name)
        return f.read() if f else b""


# ---------------------------------------------------------------- 7-Zip (RAR, 7z, CAB, ISO...)
def _exe():
    try:
        from . import paths
        here = paths.resource("assets/7z/7z.exe")
        if os.path.exists(str(here)):
            return str(here)
    except Exception:
        pass
    for n in ("7z", "7za", "7zz", "7zr", "7z.exe"):
        p = shutil.which(n)
        if p:
            return p
    for p in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if os.path.exists(p):
            return p
    raise NoTool("Thiếu công cụ giải nén 7-Zip")


def _run(args, password=None):
    cmd = [_exe(), *args[:1], "-y", "-sccUTF-8", "-spd", "-p" + (password or "x"), *args[1:]]
    flags = 0x08000000 if sys.platform.startswith("win") else 0          # không hiện cửa sổ đen
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    return r


def _is_pw_error(text):
    t = text.lower()
    return "wrong password" in t or "encrypted" in t or "data error in encrypted" in t or "cannot open encrypted" in t


def _seven_entries(path, password=None):
    r = _run(["l", "-slt", "-ba", path], password)
    err = (r.stderr + r.stdout[:2000]).decode("utf-8", "replace")
    if r.returncode not in (0, 1) and r.returncode != 2:
        raise RuntimeError(err[:200])
    if r.returncode == 2 and _is_pw_error(err):
        raise PasswordNeeded(path)
    out, cur = [], {}
    for line in r.stdout.decode("utf-8", "replace").splitlines() + [""]:
        if not line.strip():
            if cur.get("Path") is not None:
                isdir = cur.get("Folder") == "+" or "D" in cur.get("Attributes", "").split(" ")[0]
                if not isdir and _img(cur["Path"]):
                    out.append((cur["Path"], int(cur.get("Size") or 0), cur.get("Encrypted") == "+"))
            cur = {}
            continue
        if " = " in line:
            k, v = line.split(" = ", 1)
            cur[k.strip()] = v.strip() if k.strip() != "Path" else v
    return out


def _seven_read(path, name, password):
    r = _run(["e", "-so", path, name], password)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace")
        if _is_pw_error(err) or "crc failed" in err.lower() and password is None:
            raise PasswordNeeded(path)
        raise RuntimeError(err[:200] or f"7-Zip mã {r.returncode}")
    return r.stdout


# ---------------------------------------------------------------- giao diện chung
def entries(path, password=None):
    """[(tên, kích thước, có mật khẩu)] của các ảnh trong file nén. ZIP/TAR không cần mật khẩu để liệt kê."""
    k = kind(path)
    if k == "zip":
        return _zip_entries(path)
    if k == "tar":
        return _tar_entries(path)
    return _seven_entries(path, password)


def read(p, password=None):
    path, name = split(p)
    k = kind(path)
    if k == "zip":
        return _zip_read(path, name, password)
    if k == "tar":
        return _tar_read(path, name)
    return _seven_read(path, name, password)


def verify(path, password):
    """Kiểm tra mật khẩu bằng cách đọc thử một ảnh có mã hóa. Ném PasswordNeeded nếu sai."""
    ents = entries(path, password)
    enc = [e for e in ents if e[2]]
    target = (enc or ents)[:1]
    if target:
        read(make(path, target[0][0]), password)
    return True


def can_delete(path):
    """Định dạng có thể xóa bớt tệp bên trong: ZIP và 7z (RAR và các định dạng khác chỉ đọc được)."""
    n = path.lower()
    return n.endswith(".zip") or n.endswith(".7z")


def delete_entries(path, names, password=None):
    """Xóa các tệp `names` khỏi file nén nhưng GIỮ file nén (có thể còn rỗng) cùng tên. ZIP: ghi file mới rồi thay thế (an toàn); 7z: lệnh xóa của 7-Zip.
    Trả về True nếu xong; False nếu không làm được (định dạng chỉ đọc, hoặc còn tệp khác bị mã hóa không sao chép được). Không làm hỏng file cũ khi thất bại."""
    names = set(names)
    if not names or not can_delete(path):
        return False
    if kind(path) == "zip":
        tmp = path + ".pp-clean.tmp"
        try:
            with _zopen(path, password) as zin, zipfile.ZipFile(tmp, "w") as zout:
                for info in zin.infolist():
                    if info.filename in names:
                        continue
                    if info.is_dir():
                        zout.writestr(info, b"")
                        continue
                    if info.flag_bits & 0x1:
                        raise RuntimeError("còn tệp khác bị mã hóa")
                    ni = zipfile.ZipInfo(info.filename, info.date_time)
                    ni.compress_type = zipfile.ZIP_DEFLATED
                    ni.external_attr = info.external_attr
                    zout.writestr(ni, zin.read(info.filename))
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
    ok = True
    lst = sorted(names)
    for i in range(0, len(lst), 60):                       # chia nhỏ để lệnh không quá dài
        r = _run(["d", path, *lst[i:i + 60]], password)
        ok = ok and r.returncode == 0
    return ok

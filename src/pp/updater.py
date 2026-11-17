"""Tự cập nhật từ GitHub Releases của repo riêng tư, dùng mã truy cập chỉ-đọc do người dùng cung cấp."""
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlparse

from . import __version__, paths
from .secure import SEC

REPO = "quyetphamkts-cmd/Private-Picture"
API = "https://api.github.com"


class UpdateError(Exception):
    pass


def parse_version(s):
    nums = [int(x) for x in re.findall(r"\d+", s or "")][:3]
    return tuple(nums + [0] * (3 - len(nums)))


def is_newer(v, current=None):
    return parse_version(v) > parse_version(current or __version__)


# ---- mã truy cập (lưu mã hóa bằng khóa chính) ----
def _token_path():
    return paths.app_dir() / "update_token.enc"


def save_token(t):
    SEC.write_file(_token_path(), t.strip().encode())


def load_token():
    try:
        return SEC.read_file(_token_path()).decode().strip() or None
    except Exception:
        return None


# ---- mạng ----
class _DropAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub chuyển tệp sang máy chủ lưu trữ khác; không được gửi kèm mã truy cập sang đó."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlparse(newurl).netloc != urlparse(req.full_url).netloc:
            for k in list(new.headers):
                if k.lower() == "authorization":
                    del new.headers[k]
        return new


def _open(url, token, accept="application/vnd.github+json"):
    h = {"Accept": accept, "User-Agent": "PrivatePicture-updater", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    opener = urllib.request.build_opener(_DropAuthOnRedirect)
    try:
        return opener.open(urllib.request.Request(url, headers=h), timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise UpdateError("Mã truy cập không đúng hoặc đã hết hạn.")
        if e.code in (403, 404):
            raise UpdateError("Không truy cập được bản phát hành. Kiểm tra mã có quyền đọc (Contents: Read-only) với repo Private-Picture.")
        raise UpdateError(f"Lỗi máy chủ GitHub ({e.code}).")
    except urllib.error.URLError as e:
        raise UpdateError(f"Không có kết nối mạng ({e.reason}).")


def latest(token, repo=REPO, api=API):
    """Trả về dict {version, asset_url, size, notes} của bản phát hành mới nhất."""
    with _open(f"{api}/repos/{repo}/releases/latest", token) as r:
        data = json.load(r)
    m = re.search(r"version=([0-9][0-9.]*)", data.get("body") or "")
    if not m:
        raise UpdateError("Bản phát hành không ghi số phiên bản.")
    asset = next((a for a in data.get("assets", []) if a["name"].endswith(".zip")), None)
    if not asset:
        raise UpdateError("Bản phát hành chưa có tệp cài đặt.")
    return {"version": m.group(1), "asset_url": asset["url"], "size": asset.get("size", 0), "notes": data.get("body", "")}


def latest_android(token, repo=REPO, api=API):
    """Bản app Android mới nhất (release 'android-latest', tên có dạng 'App Android (v0.1.N)'; N cũng là mã phiên bản của APK)."""
    with _open(f"{api}/repos/{repo}/releases/tags/android-latest", token) as r:
        data = json.load(r)
    m = re.search(r"v(\d+\.\d+\.(\d+))", data.get("name") or "")
    asset = next((a for a in data.get("assets", []) if a["name"].endswith(".apk")), None)
    if not m or not asset:
        raise UpdateError("Chưa có bản Android phát hành.")
    return {"version": m.group(1), "code": int(m.group(2)), "asset_url": asset["url"], "size": asset.get("size", 0)}


def download(info, token, dest, progress=None, cancel=lambda: False, tries=3):
    """Tải tệp cập nhật; kiểm tra đủ dung lượng và là tệp zip thật, tự tải lại tối đa `tries` lần (mạng ngắt giữa chừng, GitHub đang thay tệp...)."""
    last = None
    for attempt in range(tries):
        try:
            with _open(info["asset_url"], token, "application/octet-stream") as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length") or info.get("size") or 0)
                done = 0
                while True:
                    if cancel():
                        raise UpdateError("Đã hủy tải.")
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            expect = info.get("size") or total
            if expect and done != expect:
                raise UpdateError(f"Tải chưa đủ ({done}/{expect} byte).")
            if not zipfile.is_zipfile(dest):
                raise UpdateError("Tệp tải về không phải tệp zip (GitHub có thể đang cập nhật bản mới).")
            return
        except UpdateError as e:
            if str(e) == "Đã hủy tải.":
                raise
            last = e
        except (OSError, ConnectionError) as e:
            last = UpdateError(f"Lỗi mạng khi tải: {e}")
        if attempt + 1 < tries:
            import time
            time.sleep(3 * (attempt + 1))
    raise UpdateError(f"{last} Hãy bấm Kiểm tra cập nhật lại sau vài phút.")


# ---- cập nhật theo phần đổi (chỉ tải các tệp khác bản đang cài) ----
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _resolve(url, token):
    """Địa chỉ tải thực (GitHub chuyển tệp sang kho lưu trữ có chữ ký): xác định một lần để các yêu cầu tải từng đoạn không đi qua API nhiều lần."""
    h = {"Accept": "application/octet-stream", "User-Agent": "PrivatePicture-updater", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    try:
        urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, headers=h), timeout=60).close()
        return url, token
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
            loc = e.headers["Location"]
            same = urlparse(loc).netloc == urlparse(url).netloc
            return loc, (token if same else None)           # không gửi mã truy cập sang máy chủ lưu trữ khác
        raise


class RangeFile(io.RawIOBase):
    """Tệp 'ảo' đọc từng đoạn từ một địa chỉ HTTP (Range) với bộ đệm khối 1 MB: cho zipfile mở zip từ xa mà chỉ tải các phần cần dùng."""
    BLOCK = 1 << 20

    def __init__(self, url, token, size):
        self.url, self.token, self.size, self.pos = url, token, int(size), 0
        self.cache = {}
        self.fetched = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def _block(self, i):
        if i in self.cache:
            return self.cache[i]
        start = i * self.BLOCK
        end = min(self.size, start + self.BLOCK) - 1
        h = {"Range": f"bytes={start}-{end}", "User-Agent": "PrivatePicture-updater"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        with urllib.request.build_opener(_DropAuthOnRedirect).open(urllib.request.Request(self.url, headers=h), timeout=60) as r:
            if r.status != 206:
                raise UpdateError("Máy chủ không hỗ trợ tải từng đoạn.")
            data = r.read()
        if len(data) != end - start + 1:
            raise UpdateError("Tải đoạn chưa đủ dung lượng.")
        if len(self.cache) > 6:
            self.cache.pop(next(iter(self.cache)))
        self.cache[i] = data
        self.fetched += len(data)
        return data

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = max(0, min(n, self.size - self.pos))
        out = []
        while n > 0:
            i, off = divmod(self.pos, self.BLOCK)
            blk = self._block(i)
            take = blk[off:off + n]
            out.append(take)
            self.pos += len(take)
            n -= len(take)
        return b"".join(out)

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def _crc_of(path):
    import zlib
    c = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            c = zlib.crc32(chunk, c)
    return c & 0xFFFFFFFF


def delta_download(info, token, install, out_dir, progress=None, cancel=lambda: False):
    """Chỉ tải các tệp trong bản mới KHÁC bản đang cài (so kích thước và CRC32), ghi vào out_dir. Trả về (số tệp, số byte tải thật) hoặc ném UpdateError
    nếu không làm được (khi đó người gọi tải cả tệp như trước)."""
    import shutil
    url, tok = _resolve(info["asset_url"], token)
    size = info.get("size") or 0
    if not size:
        raise UpdateError("Không biết dung lượng bản cập nhật.")
    rf = RangeFile(url, tok, size)
    changed = []
    try:
        with zipfile.ZipFile(rf) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            top = {i.filename.split("/", 1)[0] for i in infos}
            if len(top) != 1:
                raise UpdateError("Cấu trúc bản cập nhật không như dự kiến.")
            for i in infos:
                rel = i.filename.split("/", 1)[1]
                if any(p in ("..", "") for p in rel.replace("\\", "/").split("/")) or os.path.isabs(rel):
                    raise UpdateError("Tệp cập nhật không hợp lệ.")
                local = os.path.join(install, rel)
                if os.path.isfile(local) and os.path.getsize(local) == i.file_size and _crc_of(local) == i.CRC:
                    continue                                           # giống hệt tệp đang cài: không cần tải
                changed.append((i, rel))
            need = sum(i.compress_size for i, _ in changed) or 1
            if need > 0.9 * size:
                raise UpdateError("Phần đổi quá nhiều: tải cả bản.")
            shutil.rmtree(out_dir, ignore_errors=True)
            done = 0
            for i, rel in changed:
                if cancel():
                    raise UpdateError("Đã hủy tải.")
                dst = os.path.join(out_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(i) as src, open(dst, "wb") as f:
                    shutil.copyfileobj(src, f, 1 << 20)               # zipfile kiểm CRC khi đọc xong
                done += i.compress_size
                if progress:
                    progress(done, need)
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        raise UpdateError(f"Không cập nhật theo phần được: {e}")
    return len(changed), rf.fetched, need


def prepare(zip_path):
    """Giải nén bản mới vào thư mục tạm; trả về đường dẫn thư mục chứa PrivatePicture.exe."""
    root = paths.app_dir() / "update"
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    new = root / "new"
    new.mkdir(parents=True)
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise UpdateError("Tệp tải về bị lỗi (không phải tệp zip). Hãy bấm Kiểm tra cập nhật lại sau vài phút.")
    with zf as z:
        bad = z.testzip()
        if bad:
            raise UpdateError("Tệp tải về bị hỏng. Hãy thử lại.")
        for n in z.namelist():     # chống đường dẫn lạ
            if os.path.isabs(n) or ".." in n.replace("\\", "/").split("/"):
                raise UpdateError("Tệp cập nhật không hợp lệ.")
        z.extractall(new)
    for dp, _, fns in os.walk(new):
        if "PrivatePicture.exe" in fns:
            return dp
    raise UpdateError("Gói cập nhật không chứa PrivatePicture.exe.")


def install_dir():
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None


def _ps(s):
    return str(s).replace("'", "''")


def script_text(src, dst, pid, work, log, restart=True):
    """Tập lệnh PowerShell chạy ẨN (không có cửa sổ đen): chờ ứng dụng thoát (tối đa 20 giây rồi buộc tắt), tắt mọi tiến trình
    PrivatePicture.exe còn giữ tệp trong thư mục cài đặt, chép đè tệp mới (thử lại nếu tệp đang bị khóa), mở lại ứng dụng, ghi nhật ký."""
    start = ("Start-Process -FilePath (Join-Path $dst 'PrivatePicture.exe'); Log 'da mo lai ung dung'" if restart else "Log 'da cap nhat, khong mo lai (nguoi dung da thoat)'")
    return f"""$src = '{_ps(src)}'; $dst = '{_ps(dst)}'; $pid0 = {int(pid)}; $work = '{_ps(work)}'; $log = '{_ps(log)}'
function Log($m) {{ Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }}
Remove-Item -Path (Join-Path $dst 'update_failed.txt') -Force -ErrorAction SilentlyContinue
Log "bat dau cap nhat, cho tien trinh $pid0 thoat"
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Process -Id $pid0 -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {{ Start-Sleep -Milliseconds 400 }}
Get-Process -Name PrivatePicture -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -and $_.Path.StartsWith($dst, [System.StringComparison]::OrdinalIgnoreCase) }} | ForEach-Object {{ Log ('tat tien trinh ' + $_.Id); Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }}
Start-Sleep -Seconds 1
$code = 99
for ($i = 0; $i -lt 6; $i++) {{
  & robocopy $src $dst /E /R:3 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
  $code = $LASTEXITCODE
  Log ('robocopy ma ' + $code)
  if ($code -lt 8) {{ break }}
  Start-Sleep -Seconds 3
}}
if ($code -ge 8) {{
  Set-Content -Path (Join-Path $dst 'update_failed.txt') -Value 'Cap nhat that bai. Xem update.log trong thu muc du lieu hoac tai ban moi thu cong.'
  Log 'cap nhat that bai'
}} else {{
  {start}
}}
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
"""


def apply(src_dir, restart=True):
    """Chạy tập lệnh chờ ứng dụng thoát, chép đè tệp mới rồi mở lại. Gọi xong phải thoát ứng dụng."""
    dst = install_dir()
    if not dst:
        raise UpdateError("Chỉ cập nhật tự động được với bản đã cài (.exe).")
    if not os.access(dst, os.W_OK):
        raise UpdateError(f"Không có quyền ghi vào thư mục cài đặt: {dst}. Hãy đặt ứng dụng ở thư mục như D:\\PrivatePicture.")
    work = paths.app_dir() / "update"
    log = paths.app_dir() / "update.log"
    ps1 = paths.app_dir() / "apply_update.ps1"
    ps1.write_text("\ufeff" + script_text(src_dir, dst, os.getpid(), work, log, restart), encoding="utf-8")
    flags = 0x08000000 | 0x00000200      # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: chạy ẩn, tách khỏi ứng dụng
    subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(ps1)],
                     creationflags=flags, close_fds=True)

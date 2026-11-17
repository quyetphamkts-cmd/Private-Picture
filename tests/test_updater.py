import http.server
import io
import json
import threading
import zipfile

import pytest

from pp import paths, secure, updater


def make_zip():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("PrivatePicture/PrivatePicture.exe", b"MZ-fake")
        z.writestr("PrivatePicture/_internal/lib.dll", b"x" * 1000)
    return b.getvalue()


class Servers:
    def __init__(self, release_body="version=0.1.9\nghi chú"):
        self.seen_auth = {"api": [], "store": []}
        self.ranges = []
        self.allow_range = True
        self.zip = make_zip()
        outer = self

        class Store(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen_auth["store"].append(self.headers.get("Authorization"))
                rng = self.headers.get("Range")
                outer.ranges.append(rng)
                if rng and outer.allow_range:
                    a, b = rng.split("=")[1].split("-")
                    a, b = int(a), min(int(b), len(outer.zip) - 1)
                    data = outer.zip[a:b + 1]
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {a}-{b}/{len(outer.zip)}")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.zip)))
                self.end_headers()
                self.wfile.write(outer.zip)

            def log_message(self, *a):
                pass
        self.store = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Store)
        sport = self.store.server_address[1]

        class Api(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                auth = self.headers.get("Authorization")
                outer.seen_auth["api"].append(auth)
                if auth != "Bearer tok123":
                    self.send_response(401)
                    self.end_headers()
                    return
                if self.path.endswith("/releases/latest"):
                    body = json.dumps({"body": release_body, "assets": [
                        {"name": "x.txt", "url": "u", "size": 1},
                        {"name": "PrivatePicture-Windows.zip", "url": f"http://127.0.0.1:{self.server.server_address[1]}/asset/1",
                         "size": len(outer.zip)}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/asset/1":     # chuyển hướng sang máy chủ lưu trữ khác (cổng khác)
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{sport}/blob")
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *a):
                pass
        self.api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
        for s in (self.store, self.api):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.api.server_address[1]}"

    def close(self):
        self.store.shutdown()
        self.api.shutdown()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    secure.SEC.key = None
    yield tmp_path
    secure.SEC.key = None


def test_versions():
    assert updater.is_newer("0.1.10", "0.1.9") and not updater.is_newer("0.1.9", "0.1.9")
    assert updater.is_newer("0.2.0", "0.1.99") and updater.is_newer("0.1.1", "0.0.0")


def test_token_encrypted(env):
    secure.SEC.setup(True, True, "mat-khau-dai")
    updater.save_token("github_pat_SECRET")
    assert b"github_pat_SECRET" not in open(updater._token_path(), "rb").read()
    assert updater.load_token() == "github_pat_SECRET"


def test_check_download_prepare(env):
    srv = Servers()
    try:
        info = updater.latest("tok123", repo="a/b", api=srv.url)
        assert info["version"] == "0.1.9" and updater.is_newer(info["version"])
        dest = env / "dl.zip"
        got = []
        updater.download(info, "tok123", str(dest), lambda d, t: got.append((d, t)))
        assert dest.read_bytes() == srv.zip and got[-1][0] == len(srv.zip)
        # mã truy cập chỉ gửi cho máy chủ API, không gửi sang máy chủ lưu trữ
        assert srv.seen_auth["store"] == [None]
        assert "Bearer tok123" in srv.seen_auth["api"]
        d = updater.prepare(str(dest))
        assert (env / "home" / "update" / "new" / "PrivatePicture" / "PrivatePicture.exe").exists()
        assert d.endswith("PrivatePicture")
        with pytest.raises(updater.UpdateError, match="không đúng"):
            updater.latest("sai-ma", repo="a/b", api=srv.url)
    finally:
        srv.close()


def test_release_without_version(env):
    srv = Servers(release_body="không có số phiên bản")
    try:
        with pytest.raises(updater.UpdateError, match="phiên bản"):
            updater.latest("tok123", repo="a/b", api=srv.url)
    finally:
        srv.close()


def test_bad_zip_paths(env):
    p = env / "evil.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(updater.UpdateError):
        updater.prepare(str(p))


def test_update_script_hidden_powershell():
    t = updater.script_text(r"C:\tmp\new\PrivatePicture", r"D:\Private Picture's", 1234, r"C:\tmp", r"C:\data\update.log")
    assert "robocopy" in t and "1234" in t and "PrivatePicture.exe" in t
    assert "Stop-Process" in t and "AddSeconds(20)" in t               # chờ tối đa 20 giây rồi buộc tắt
    assert "D:\\Private Picture''s" in t                                # dấu nháy đơn trong đường dẫn được thoát đúng
    assert "update.log" in t and "cmd /c" not in t


def test_download_rejects_non_zip_and_truncated(env, monkeypatch):
    srv = Servers()
    try:
        info = updater.latest("tok123", repo="a/b", api=srv.url)
        monkeypatch.setattr("time.sleep", lambda s: None)
        bad = dict(info, size=len(srv.zip) + 10)                       # tải thiếu so với dung lượng công bố
        with pytest.raises(updater.UpdateError, match="Tải chưa đủ"):
            updater.download(bad, "tok123", str(env / "x.zip"), tries=2)
        srv.zip, good = b"<html>not a zip</html>", srv.zip           # GitHub trả trang lỗi thay vì tệp zip
        with pytest.raises(updater.UpdateError, match="không phải tệp zip"):
            updater.download(dict(info, size=0), "tok123", str(env / "y.zip"), tries=2)
        (env / "z.zip").write_bytes(b"junk")
        with pytest.raises(updater.UpdateError, match="không phải tệp zip"):
            updater.prepare(str(env / "z.zip"))
    finally:
        srv.close()


def test_script_can_skip_restart():
    a = updater.script_text("C:/s", "C:/d", 123, "C:/w", "C:/l.log", True)
    b = updater.script_text("C:/s", "C:/d", 123, "C:/w", "C:/l.log", False)
    assert "Start-Process -FilePath" in a and "Start-Process -FilePath" not in b          # cập nhật khi thoát: không mở lại app
    assert "robocopy" in b


def test_delta_download_fetches_only_changed_files(env, tmp_path):
    """Chỉ tải các tệp khác bản đang cài: tệp giống hệt (cùng kích thước và CRC) không được tải."""
    srv = Servers()
    try:
        big = b"y" * 12_000_000                                          # tệp lớn không đổi
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", zipfile.ZIP_STORED) as z:
            z.writestr("PrivatePicture/PrivatePicture.exe", b"NEW-CODE")
            z.writestr("PrivatePicture/_internal/big.dll", big)
            z.writestr("PrivatePicture/_internal/small.txt", b"hello")
        srv.zip = b.getvalue()
        install = tmp_path / "inst"
        (install / "_internal").mkdir(parents=True)
        (install / "PrivatePicture.exe").write_bytes(b"OLD-CODE")         # khác
        (install / "_internal" / "big.dll").write_bytes(big)              # giống hệt
        info = updater.latest("tok123", repo="a/b", api=srv.url)
        info["size"] = len(srv.zip)
        out = tmp_path / "out"
        n, fetched, need = updater.delta_download(info, "tok123", str(install), str(out))
        assert n == 2 and sorted(p.name for p in out.rglob("*") if p.is_file()) == ["PrivatePicture.exe", "small.txt"]
        assert (out / "PrivatePicture.exe").read_bytes() == b"NEW-CODE" and not (out / "_internal" / "big.dll").exists()
        assert fetched < len(srv.zip) // 3                                # tải ít hơn nhiều so với cả bản
        assert srv.seen_auth["store"] and all(a is None for a in srv.seen_auth["store"])   # không gửi mã truy cập sang máy chủ lưu trữ
        srv.allow_range = False                                           # máy chủ không hỗ trợ tải từng đoạn: báo lỗi để người gọi tải cả bản
        with pytest.raises(updater.UpdateError):
            updater.delta_download(info, "tok123", str(install), str(tmp_path / "out2"))
    finally:
        srv.close()

"""Kho riêng tư: ảnh được mã hóa AES-256-GCM bằng mật khẩu của bạn. Khi xem, ảnh được giải mã trong bộ nhớ."""
import io
import json
import os
import time
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from PIL import Image, ImageOps

from .secure import WrongPassword

MAGIC = b"PPV1"


class Vault:
    def __init__(self, root):
        self.root = str(root)
        os.makedirs(self.root, exist_ok=True)
        self.key = None
        self.index = []

    # ---- khóa ----
    @property
    def meta_path(self):
        return os.path.join(self.root, "vault.json")

    def exists(self):
        return os.path.exists(self.meta_path)

    def unlocked(self):
        return self.key is not None

    def _derive(self, password, salt):
        return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))

    def create(self, password):
        if self.exists():
            raise RuntimeError("Kho đã tồn tại")
        if len(password) < 6:
            raise ValueError("Mật khẩu cần ít nhất 6 ký tự")
        salt = os.urandom(16)
        self.key = self._derive(password, salt)
        with open(self.meta_path, "w") as f:
            json.dump({"v": 1, "salt": salt.hex(), "check": self._enc(b"private-picture").hex()}, f)
        self.index = []
        self._save_index()

    def unlock(self, password):
        with open(self.meta_path) as f:
            m = json.load(f)
        key = self._derive(password, bytes.fromhex(m["salt"]))
        try:
            if AESGCM(key).decrypt(*self._split(bytes.fromhex(m["check"])), None) != b"private-picture":
                raise WrongPassword()
        except InvalidTag:
            raise WrongPassword()
        self.key = key
        self._load_index()

    def use_key(self, key):
        """Dùng khóa chính của ứng dụng (không cần mật khẩu riêng)."""
        self.key = key
        self._load_index()

    def lock(self):
        self.key = None
        self.index = []

    # ---- mã hóa ----
    def _enc(self, data: bytes) -> bytes:
        nonce = os.urandom(12)
        return MAGIC + nonce + AESGCM(self.key).encrypt(nonce, data, None)

    @staticmethod
    def _split(blob):
        if blob[:4] != MAGIC:
            raise ValueError("Tệp không phải định dạng kho")
        return blob[4:16], blob[16:]

    def _dec(self, blob: bytes) -> bytes:
        nonce, ct = self._split(blob)
        try:
            return AESGCM(self.key).decrypt(nonce, ct, None)
        except InvalidTag:
            raise WrongPassword()

    def _p(self, name):
        return os.path.join(self.root, name)

    def _save_index(self):
        tmp = self._p("index.enc.tmp")
        with open(tmp, "wb") as f:
            f.write(self._enc(json.dumps(self.index).encode()))
        os.replace(tmp, self._p("index.enc"))

    def _load_index(self):
        p = self._p("index.enc")
        self.index = json.loads(self._dec(open(p, "rb").read())) if os.path.exists(p) else []

    # ---- tệp ----
    def add(self, path, delete_original=False, iid=None):
        data = open(path, "rb").read()
        iid = iid or uuid.uuid4().hex
        thumb = b""
        w = h = 0
        try:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
            w, h = im.size
            im = im.convert("RGB")
            im.thumbnail((320, 320))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=82)
            thumb = b.getvalue()
        except Exception:
            pass
        with open(self._p(iid + ".enc"), "wb") as f:
            f.write(self._enc(data))
        with open(self._p(iid + ".t.enc"), "wb") as f:
            f.write(self._enc(thumb))
        self.index.append({"id": iid, "name": os.path.basename(path), "w": w, "h": h,
                           "size": len(data), "added": time.strftime("%Y-%m-%d %H:%M:%S")})
        self._save_index()
        if delete_original:
            try:
                os.remove(path)
            except OSError:
                pass
        return iid

    def read(self, iid) -> bytes:
        return self._dec(open(self._p(iid + ".enc"), "rb").read())

    def thumb(self, iid) -> bytes:
        return self._dec(open(self._p(iid + ".t.enc"), "rb").read())

    def remove(self, iid):
        for suf in (".enc", ".t.enc"):
            try:
                os.remove(self._p(iid + suf))
            except OSError:
                pass
        self.index = [e for e in self.index if e["id"] != iid]
        self._save_index()

    def export(self, iid, dest):
        with open(dest, "wb") as f:
            f.write(self.read(iid))

    def change_password(self, old, new):
        self.unlock(old)
        if len(new) < 6:
            raise ValueError("Mật khẩu mới cần ít nhất 6 ký tự")
        salt = os.urandom(16)
        key = self._derive(new, salt)
        old_key = self.key
        for e in self.index:   # mã hóa lại toàn bộ bằng khóa mới
            for suf in (".enc", ".t.enc"):
                p = self._p(e["id"] + suf)
                self.key = old_key
                data = self._dec(open(p, "rb").read())
                self.key = key
                open(p, "wb").write(self._enc(data))
        self.key = key
        with open(self.meta_path, "w") as f:
            json.dump({"v": 1, "salt": salt.hex(), "check": self._enc(b"private-picture").hex()}, f)
        self._save_index()

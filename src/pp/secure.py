"""Mật khẩu chính, khóa khôi phục và mã hóa dữ liệu của ứng dụng (AES-256-GCM).

Thiết kế "bọc khóa": một khóa dữ liệu ngẫu nhiên (MK) mã hóa mọi thứ. MK được bọc bằng khóa sinh từ mật khẩu (scrypt)
và, nếu có, bọc thêm bằng khóa khôi phục. Nhờ vậy đổi mật khẩu không cần mã hóa lại dữ liệu.
"""
import base64
import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import dpapi, paths

MAGIC = b"PPE1"
MODES = ("data", "all")


class WrongPassword(Exception):
    pass


class UnlockError(Exception):
    pass


def derive(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def seal(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, None)


def unseal(key: bytes, blob: bytes) -> bytes:
    if blob[:4] != MAGIC:
        raise ValueError("Tệp không đúng định dạng mã hóa")
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], None)
    except InvalidTag:
        raise WrongPassword()


def encode_recovery(raw: bytes) -> str:
    s = base64.b32encode(raw).decode().rstrip("=")
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def decode_recovery(text: str) -> bytes:
    s = "".join(text.split()).replace("-", "").upper()
    s += "=" * (-len(s) % 8)
    try:
        raw = base64.b32decode(s)
    except Exception:
        raise WrongPassword()
    if len(raw) != 32:
        raise WrongPassword()
    return raw


def _rk_kek(raw: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"pp-recovery").derive(raw)


class Secure:
    """Cấu hình bảo mật. Hai công tắc độc lập:
      encrypt  : mã hóa dữ liệu của ứng dụng (cơ sở dữ liệu, ảnh thu nhỏ, mặt, Kho mã hóa)
      password : hỏi mật khẩu khi mở ứng dụng
    Khóa dữ liệu (mk) được bọc bằng mật khẩu, bằng tài khoản Windows (khi bật mã hóa mà tắt mật khẩu) và bằng khóa khôi phục."""

    def __init__(self):
        self.key = None          # khóa dùng để mã hóa tệp; None nghĩa là đang không mã hóa
        self.mk = None           # khóa gốc (có khi bật mã hóa hoặc mật khẩu)
        self.encrypt = False
        self.use_password = False

    @property
    def cfg(self):
        return paths.app_dir() / "security.json"

    def configured(self) -> bool:
        return self.cfg.exists()

    def _read(self) -> dict:
        return json.loads(self.cfg.read_text())

    def _save(self, d):
        tmp = self.cfg.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        os.replace(tmp, self.cfg)

    def _set(self, mk, encrypt, use_password):
        self.mk, self.encrypt, self.use_password = mk, bool(encrypt), bool(use_password)
        self.key = mk if encrypt else None

    def flags(self):
        """(mã hóa, mật khẩu) theo cấu hình đã lưu. Cấu hình đời cũ (v1, v2) luôn là bật cả hai."""
        m = self._read()
        return (m["encrypt"], m["password"]) if m.get("v", 1) >= 3 else (True, True)

    def needs_password(self) -> bool:
        return self.flags()[1]

    def has_recovery(self) -> bool:
        return "wrap_rec" in self._read()

    @staticmethod
    def _make_recovery(mk):
        raw, rsalt = os.urandom(32), os.urandom(16)
        return encode_recovery(raw), {"rsalt": rsalt.hex(), "wrap_rec": seal(_rk_kek(raw, rsalt), mk).hex()}

    @staticmethod
    def _compose(mk, encrypt, use_password, password, rec):
        d = {"v": 3, "encrypt": bool(encrypt), "password": bool(use_password)}
        if mk is not None:
            if use_password:
                salt = os.urandom(16)
                d["salt"] = salt.hex()
                d["wrap_pw"] = seal(derive(password, salt), mk).hex()
            elif encrypt:
                d["wrap_os"] = dpapi.protect(mk).hex()
            if rec:
                d.update(rec)
        return d

    # ------------------------------------------------------------ tạo, mở
    def setup(self, encrypt: bool, use_password: bool, password: str = None):
        """Tạo cấu hình lần đầu. Trả về khóa khôi phục (chỉ hiện một lần) hoặc None nếu không có gì cần khôi phục."""
        if use_password and len(password or "") < 8:
            raise ValueError("Mật khẩu cần ít nhất 8 ký tự")
        mk = os.urandom(32) if (encrypt or use_password) else None
        rk, rec = self._make_recovery(mk) if mk else (None, None)
        self._save(self._compose(mk, encrypt, use_password, password, rec))
        self._set(mk, encrypt, use_password)
        return rk

    def unlock(self, password: str = None):
        m = self._read()
        v = m.get("v", 1)
        if v == 1:       # định dạng cũ: khóa sinh thẳng từ mật khẩu
            key = derive(password or "", bytes.fromhex(m["salt"]))
            if unseal(key, bytes.fromhex(m["check"])) != b"private-picture":
                raise WrongPassword()
            salt = os.urandom(16)
            self._save({"v": 3, "encrypt": True, "password": True, "salt": salt.hex(),
                        "wrap_pw": seal(derive(password, salt), key).hex()})
            self._set(key, True, True)
            return
        enc, pw = self.flags()
        if v == 2 and pw:
            m["v"], m["encrypt"], m["password"] = 3, True, True
            self._save(m)
        if pw:
            mk = unseal(derive(password or "", bytes.fromhex(m["salt"])), bytes.fromhex(m["wrap_pw"]))
        elif enc:
            try:
                mk = dpapi.unprotect(bytes.fromhex(m["wrap_os"]))
            except OSError:
                raise UnlockError("Không mở được bằng tài khoản Windows này. Hãy dùng khóa khôi phục.")
        else:
            mk = None
        self._set(mk, enc, pw)

    def lock(self):
        self.key = None
        self.mk = None

    # ------------------------------------------------------------ mật khẩu, khôi phục, đổi cấu hình
    def _verify_password(self, password):
        m = self._read()
        mk = unseal(derive(password or "", bytes.fromhex(m["salt"])), bytes.fromhex(m["wrap_pw"]))
        if self.mk is not None and mk != self.mk:
            raise WrongPassword()
        return mk

    def change_password(self, old: str, new: str):
        if not self.use_password:
            raise ValueError("Ứng dụng đang không dùng mật khẩu")
        if len(new) < 8:
            raise ValueError("Mật khẩu mới cần ít nhất 8 ký tự")
        mk = self._verify_password(old)
        m = self._read()
        rec = {k: m[k] for k in ("rsalt", "wrap_rec") if k in m}
        self._save(self._compose(mk, self.encrypt, True, new, rec))
        self._set(mk, self.encrypt, True)

    def new_recovery_key(self, password: str = None) -> str:
        """Tạo khóa khôi phục mới; khóa cũ hết hiệu lực."""
        if self.mk is None:
            raise ValueError("Chưa có gì để khôi phục")
        if self.use_password:
            self._verify_password(password)
        rk, rec = self._make_recovery(self.mk)
        m = self._read()
        m.update(rec)
        self._save(m)
        return rk

    def recover(self, recovery_key: str, new_password: str = None):
        """Quên mật khẩu (hoặc mất tài khoản Windows): dùng khóa khôi phục để mở và đặt lại."""
        m = self._read()
        if "wrap_rec" not in m:
            raise WrongPassword()
        enc, pw = self.flags()
        if pw and len(new_password or "") < 8:
            raise ValueError("Mật khẩu mới cần ít nhất 8 ký tự")
        kek = _rk_kek(decode_recovery(recovery_key), bytes.fromhex(m["rsalt"]))
        mk = unseal(kek, bytes.fromhex(m["wrap_rec"]))
        self._save(self._compose(mk, enc, pw, new_password, {k: m[k] for k in ("rsalt", "wrap_rec")}))
        self._set(mk, enc, pw)

    def reconfigure(self, encrypt: bool, use_password: bool, new_password: str = None, current_password: str = None):
        """Đổi hai công tắc khi đang đăng nhập. Trả về khóa khôi phục mới nếu phải tạo (lần đầu cần khóa gốc)."""
        if use_password and not self.use_password and len(new_password or "") < 8:
            raise ValueError("Mật khẩu cần ít nhất 8 ký tự")
        if use_password and self.use_password and new_password and len(new_password) < 8:
            raise ValueError("Mật khẩu cần ít nhất 8 ký tự")
        if self.use_password:
            self._verify_password(current_password)
        m = self._read()
        need_mk = encrypt or use_password
        rk, rec, mk = None, None, self.mk
        if need_mk and mk is None:
            mk = os.urandom(32)
            rk, rec = self._make_recovery(mk)
        elif need_mk:
            rec = {k: m[k] for k in ("rsalt", "wrap_rec") if k in m}
            if not rec:
                rk, rec = self._make_recovery(mk)
        else:
            mk = None
        pw = new_password
        if use_password and self.use_password and not new_password:     # giữ mật khẩu hiện tại
            pw = current_password
        self._save(self._compose(mk, encrypt, use_password, pw, rec))
        self._set(mk, encrypt, use_password)
        return rk

    # ------------------------------------------------------------ ghi và đọc tệp (mã hóa nếu đang bật mã hóa)
    def write_file(self, path, data: bytes):
        with open(path, "wb") as f:
            f.write(seal(self.key, data) if self.key else data)

    def read_file(self, path) -> bytes:
        with open(path, "rb") as f:
            b = f.read()
        return unseal(self.key, b) if (self.key and b[:4] == MAGIC) else b


SEC = Secure()

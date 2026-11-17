"""Bọc khóa bằng tài khoản Windows (DPAPI): chỉ đúng người dùng Windows này mới giải mã được.
Trên hệ khác Windows (chỉ để phát triển, kiểm thử) dùng bản thay thế KHÔNG an toàn."""
import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32, _kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    _crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB), ctypes.c_void_p,
                                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    _crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB), ctypes.c_void_p,
                                            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    _crypt32.CryptProtectData.restype = _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    UI_FORBIDDEN = 0x1

    def _run(fn, data: bytes, *mid) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        src = _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = _BLOB()
        if not fn(ctypes.byref(src), *mid, ctypes.byref(out)):
            raise OSError("Không giải mã được bằng tài khoản Windows này")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def protect(data: bytes) -> bytes:
        return _run(_crypt32.CryptProtectData, data, None, None, None, None, UI_FORBIDDEN)

    def unprotect(blob: bytes) -> bytes:
        return _run(_crypt32.CryptUnprotectData, blob, None, None, None, None, UI_FORBIDDEN)

    SECURE = True
else:
    SECURE = False

    def protect(data: bytes) -> bytes:
        return b"INSECURE" + data

    def unprotect(blob: bytes) -> bytes:
        if blob[:8] != b"INSECURE":
            raise OSError("Không giải mã được")
        return blob[8:]

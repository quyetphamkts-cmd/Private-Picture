"""Chuyển dữ liệu của ứng dụng giữa dạng không mã hóa và dạng mã hóa khi người dùng bật/tắt mã hóa."""
import os
import sqlite3

from . import paths
from .secure import MAGIC, seal, unseal


def _read(path, key):
    with open(path, "rb") as f:
        b = f.read()
    return unseal(key, b) if (key and b[:4] == MAGIC) else b


def _write(path, data, key):
    tmp = str(path) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(seal(key, data) if key else data)
    os.replace(tmp, path)


def convert_files(old_key, new_key, progress=None):
    todo = []
    for d in (paths.thumbs_dir(), paths.faces_dir()):
        todo += [d / n for n in os.listdir(d)]
    tok = paths.app_dir() / "update_token.enc"
    if tok.exists():
        todo.append(tok)
    for i, p in enumerate(todo):
        if p.is_file():
            _write(p, _read(p, old_key), new_key)
        if progress and i % 200 == 0:
            progress(i, len(todo))


def convert_db(old_key, new_key):
    enc, plain = paths.enc_db_path(), paths.db_path()
    if old_key and not new_key and enc.exists():
        con = sqlite3.connect(":memory:")
        con.deserialize(unseal(old_key, enc.read_bytes()))
        data = con.serialize()
        con.close()
        tmp = str(plain) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, plain)
        enc.unlink()
    elif new_key and not old_key and plain.exists():
        con = sqlite3.connect(str(plain))
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("PRAGMA journal_mode=DELETE")      # ảnh chụp trong bộ nhớ không dùng được chế độ WAL
        data = con.serialize()
        con.close()
        _write(enc, data, new_key)
        for suf in ("", "-wal", "-shm"):
            try:
                os.remove(str(plain) + suf)
            except OSError:
                pass


def run(old_key, new_key, progress=None):
    """Chuyển toàn bộ dữ liệu từ khóa cũ sang khóa mới (None nghĩa là không mã hóa)."""
    if (old_key is None) == (new_key is None):
        return
    convert_files(old_key, new_key, progress)
    convert_db(old_key, new_key)

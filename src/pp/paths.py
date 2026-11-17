"""Thư mục dữ liệu của ứng dụng (mô hình, ảnh thu nhỏ, cơ sở dữ liệu)."""
import os
from pathlib import Path


def app_dir() -> Path:
    base = os.environ.get("PP_HOME")
    if base:
        d = Path(base)
    else:
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        d = Path(root) / "PrivatePicture"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sub(name: str) -> Path:
    d = app_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path: return sub("models")
def thumbs_dir() -> Path: return sub("thumbs")
def faces_dir() -> Path: return sub("faces")
def vault_dir() -> Path: return sub("vault2")
def db_path() -> Path: return app_dir() / "library.db"
def enc_db_path() -> Path: return app_dir() / "library.enc"


def resource(rel: str) -> Path:
    """Đường dẫn tới tệp đi kèm ứng dụng (phông chữ…), cả khi chạy từ mã nguồn lẫn bản đóng gói."""
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel

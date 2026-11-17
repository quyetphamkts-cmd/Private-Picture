import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Giữ một QApplication duy nhất sống đến hết phiên kiểm thử (tránh sập khi thoát).
from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def pytest_sessionfinish(session, exitstatus):
    import gc
    gc.collect()



import pytest


@pytest.fixture(autouse=True)
def _reset_scan_gate():
    """Cổng tạm dừng quét chỉ có ý nghĩa trong ứng dụng thật: mỗi bài kiểm thử bắt đầu và kết thúc với cổng tắt (tránh treo bài quét ở bài sau)."""
    from pp import scan
    scan.PAUSE_ENABLED[0] = scan.PAUSED[0] = False
    yield
    scan.PAUSE_ENABLED[0] = scan.PAUSED[0] = False

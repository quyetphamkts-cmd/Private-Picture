import os

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pp.ui import theme
from pp.ui.common import ImageView, JustifiedView, ThumbModel, Viewer, load_qimage

SIZES = [(4000, 3000), (3000, 4000), (6000, 1500), (1000, 1000), (800, 1200), (1920, 1080), (1200, 800), (900, 900),
         (3000, 2000), (2000, 3000), (1600, 900), (1000, 1500)]


@pytest.fixture()
def photos(tmp_path):
    out = []
    rng = np.random.default_rng(5)
    for i, (w, h) in enumerate(SIZES):
        sw, sh = 320, int(320 * h / w) if w >= h else 320
        tw = 320 if w >= h else int(320 * w / h)
        th = int(320 * h / w) if w >= h else 320
        col = rng.integers(60, 220, 3)
        arr = np.tile(col, (th, tw, 1)).astype(np.uint8)
        arr[:, : tw // 2] = np.clip(arr[:, : tw // 2] + 30, 0, 255)
        p = tmp_path / f"t{i}.jpg"
        Image.fromarray(arr).save(p)
        out.append({"id": i, "thumb": str(p), "w": w, "h": h, "cap_title": f"IMG_{i:04d}.jpg", "cap_tag": "05/11/2025", "tip": f"IMG_{i}"})
    return out


def test_justified_keeps_aspect_and_fills_rows(photos):
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 600)
    v.show()
    m.set_items(photos)
    v.relayout()
    W = v.viewport().width()
    rows = {}
    for (x, y, w, h), it in zip(v.rects, photos):
        assert abs(w / h - it["w"] / it["h"]) / (it["w"] / it["h"]) < 0.01      # đúng tỉ lệ gốc
        rows.setdefault(round(y, 1), []).append((x, w))
    ys = sorted(rows)
    for y in ys[:-1]:                                                          # các hàng đầy đủ rộng bằng khung
        r = rows[y]
        assert abs(r[-1][0] + r[-1][1] - W) < 2
    assert v.total_h > 0


def test_selection_and_open(photos):
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 600)
    v.show()
    m.set_items(photos)
    v.relayout()
    opened = []
    v.doubleClicked.connect(lambda ix: opened.append(ix.row()))

    def center(i):
        x, y, w, h = v.rects[i]
        return QPoint(int(x + w / 2), int(y + h / 2) - v.verticalScrollBar().value())
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, center(0))
    assert [i.row() for i in v.selectedIndexes()] == [0]
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.ControlModifier, center(1))
    assert sorted(i.row() for i in v.selectedIndexes()) == [0, 1]
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.ShiftModifier, center(3))
    assert sorted(i.row() for i in v.selectedIndexes()) == [0, 1, 2, 3]   # Shift cộng thêm đoạn từ ảnh vừa chọn (1) đến ảnh 3
    if len(photos) > 7:                                                    # chọn thêm một nhóm khác: Ctrl chọn ảnh mốc, Shift mở rộng
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.ControlModifier, center(6))
        QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.ShiftModifier, center(7))
        assert sorted(i.row() for i in v.selectedIndexes()) == [0, 1, 2, 3, 6, 7]
    QTest.mouseDClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, center(2))
    assert opened == [2]
    v.clear_selection()                                                    # thoát chế độ chọn nhiều
    # cuộn lớn: vẫn trúng đúng ảnh
    v.verticalScrollBar().setValue(v.verticalScrollBar().maximum())
    last = len(photos) - 1
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, center(last))
    assert [i.row() for i in v.selectedIndexes()] == [last]


def test_viewer_zoom_and_navigation(photos, tmp_path):
    big = tmp_path / "big.jpg"
    Image.new("RGB", (3000, 2000), (120, 90, 60)).save(big)
    small = tmp_path / "small.png"
    Image.new("RGB", (120, 80), (10, 20, 30)).save(small)
    items = [{"path": str(big), "cap_title": "big"}, {"path": str(small), "cap_title": "small"}] + photos[:2]
    for it in photos[:2]:
        it["path"] = it["thumb"]
    m = ThumbModel()
    m.set_items(items)
    parent = QApplication.activeWindow()
    v = Viewer(items, 0, lambda it: load_qimage(it["path"]), None, m)
    v.resize(1000, 700)
    v.show()
    QApplication.processEvents()
    iv = v.view
    s_fit = iv.scale_now()
    assert 0 < s_fit < 1.0                       # ảnh lớn: thu nhỏ vừa khung
    iv.zoom(2.0)
    assert iv.scale_now() == pytest.approx(s_fit * 2, rel=1e-3)
    iv.actual()
    assert iv.scale_now() == pytest.approx(1.0)
    assert v.zl.text() == "100%"
    iv.zoom(100)                                  # giới hạn trên 800%
    assert iv.scale_now() <= iv.MAX + 1e-6
    iv.fit()
    QTest.keyClick(v, Qt.Key_Right)
    assert v.i == 1
    assert iv.scale_now() == pytest.approx(1.0)  # ảnh nhỏ: giữ 100%, không phóng to cho vừa khung
    QTest.keyClick(v, Qt.Key_Left)
    assert v.i == 0
    QTest.keyClick(v, Qt.Key_End)
    assert v.i == len(items) - 1
    QTest.keyClick(v, Qt.Key_Escape)
    assert not v.isVisible()


def test_drag_zoom_keeps_point_and_pan(tmp_path):
    big = tmp_path / "big.jpg"
    Image.new("RGB", (3000, 2000), (120, 90, 60)).save(big)
    items = [{"path": str(big), "cap_title": "big"}]
    v = Viewer(items, 0, lambda it: load_qimage(it["path"]), None, None)
    v.resize(1000, 700)
    v.show()
    QApplication.processEvents()
    iv = v.view
    v.set_mode("zoom")                              # mặc định giữ chuột trái = di chuyển; bật nút để kéo thu phóng
    iv.actual()
    vp = iv.viewport()
    press = QPoint(300, 400)
    before = iv.mapToScene(press)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, press)
    QTest.mouseMove(vp, QPoint(300, 300))                        # kéo lên 100 px = phóng to
    s_in = iv.scale_now()
    assert s_in == pytest.approx(1.01 ** 100, rel=0.02)
    after = iv.mapToScene(press)
    assert abs(after.x() - before.x()) < 1.5 and abs(after.y() - before.y()) < 1.5   # điểm bấm đứng yên
    QTest.mouseMove(vp, QPoint(300, 500))                        # kéo xuống = thu nhỏ
    assert iv.scale_now() < 1.0
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(300, 500))
    assert v.isVisible()                                          # kéo không làm đóng khung xem
    assert v.zl.text() == f"{round(iv.scale_now() * 100)}%"
    # di chuyển bằng chuột phải
    iv.actual()
    h0 = iv.horizontalScrollBar().value()
    QTest.mousePress(vp, Qt.RightButton, Qt.NoModifier, QPoint(500, 300))
    QTest.mouseMove(vp, QPoint(420, 300))
    QTest.mouseRelease(vp, Qt.RightButton, Qt.NoModifier, QPoint(420, 300))
    assert iv.horizontalScrollBar().value() == h0 + 80
    # chuyển sang kiểu kéo "di chuyển": kéo trái không đổi mức phóng
    v.toggle_mode()
    assert iv.mode == "pan"
    s0 = iv.scale_now()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(500, 300))
    QTest.mouseMove(vp, QPoint(500, 250))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(500, 250))
    assert iv.scale_now() == pytest.approx(s0)
    v.close()


def test_single_click_opens_and_reveal_scrolls(photos):
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 400)
    v.show()
    m.set_items(photos * 8)
    v.relayout()
    got = []
    v.activated.connect(lambda ix: got.append(ix.row()))
    x, y, w, h = v.rects[0]
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(x + w / 2), int(y + h / 2)))
    assert got == [0]
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.ControlModifier, QPoint(int(x + w / 2), int(y + h / 2)))
    assert got == [0]                                   # Ctrl+bấm chỉ chọn, không mở
    last = len(m.items) - 1
    v.reveal(last)
    for _ in range(40):
        QApplication.processEvents()
        QTest.qWait(20)
    bx, by, bw, bh = v.rects[last]
    off = v.verticalScrollBar().value()
    assert off <= by and by + bh <= off + v.viewport().height() + 1      # ảnh đang xem nằm trong khung nhìn
    assert v.selectedIndexes()[0].row() == last


def test_viewer_prefetch_and_index_signal(photos, tmp_path):
    paths = []
    for k in range(4):
        pth = tmp_path / f"v{k}.png"
        Image.new("RGB", (400, 300), (k * 40, 50, 90)).save(pth)
        paths.append({"path": str(pth), "cap_title": f"v{k}"})
    seen = []
    v = Viewer(paths, 1, lambda it: load_qimage(it["path"]), None, None, seen.append)
    v.resize(800, 600)
    v.show()
    for _ in range(30):
        QApplication.processEvents()
        QTest.qWait(20)
    assert 2 in v.cache and 0 in v.cache                 # ảnh kế bên đã nạp sẵn
    assert seen == []                                    # lần mở đầu không cuộn thư viện
    QTest.keyClick(v, Qt.Key_Right)
    assert v.i == 2 and seen == [2]
    assert v.strip is None                               # không có model: không có dải ảnh
    v.close()


def test_viewer_strip_and_fullscreen_toggle(photos, tmp_path):
    items = []
    for k in range(3):
        pth = tmp_path / f"w{k}.png"
        Image.new("RGB", (300, 200), (k * 60, 80, 80)).save(pth)
        items.append({"path": str(pth), "cap_title": f"w{k}", "thumb": str(pth), "w": 300, "h": 200})
    m = ThumbModel()
    m.set_items(items)
    v = Viewer(items, 0, lambda it: load_qimage(it["path"]), None, m)
    v.resize(900, 600)
    v.show()
    QApplication.processEvents()
    assert v.strip is not None and v.strip.isVisible()
    v.toggle_fullscreen()
    QApplication.processEvents()
    assert v.fs and not v.strip.isVisible()
    QTest.keyClick(v, Qt.Key_Escape)                      # Esc thoát toàn màn hình, chưa đóng
    QApplication.processEvents()
    assert not v.fs and v.strip.isVisible() and v.isVisible()
    QTest.keyClick(v, Qt.Key_Escape)
    assert not v.isVisible()


def test_viewer_minimap_info_fav(tmp_path):
    big = tmp_path / "b.jpg"
    Image.new("RGB", (3000, 2000), (120, 90, 60)).save(big)
    items = [{"path": str(big), "cap_title": "b", "id": 1}]
    fav = {"on": False}

    def fv(it, toggle):
        if toggle:
            fav["on"] = not fav["on"]
        return fav["on"]
    v = Viewer(items, 0, lambda it: load_qimage(it["path"]), None, None, None, lambda it: "<b>thong tin</b>", fv)
    v.resize(1000, 700)
    v.show()
    QApplication.processEvents()
    assert not v.mini.isVisible()                    # vừa khung: chưa cần bản đồ nhỏ
    v.view.zoom(3)
    QApplication.processEvents()
    assert v.mini.isVisible()
    assert v.view.mode == "pan"                      # mặc định giữ chuột trái để di chuyển
    v.toggle_info()
    assert v.panel.isVisible() and "thong tin" in v.panel.text()
    v.toggle_fav()
    assert fav["on"]
    v.view.wheelEvent  # cuộn chuột giữa = thu phóng (đã có sẵn)
    v.close()


def test_selection_circle_multi_mode(photos):
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 600)
    v.show()
    m.set_items(photos)
    v.relayout()
    opened, counts = [], []
    v.activated.connect(lambda ix: opened.append(ix.row()))
    v.selectionChanged.connect(counts.append)

    def pt(i, dx, dy):
        x, y, w, h = v.rects[i]
        return QPoint(int(x + dx), int(y + dy) - v.verticalScrollBar().value())
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pt(0, 18, 18))      # bấm vào vòng tròn: chọn, không mở
    assert opened == [] and v.multi and sorted(i.row() for i in v.selectedIndexes()) == [0]
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pt(2, 60, 60))      # đang chọn nhiều: bấm ảnh = chọn thêm
    assert opened == [] and sorted(i.row() for i in v.selectedIndexes()) == [0, 2]
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pt(0, 18, 18))      # bỏ chọn ảnh 0
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pt(2, 18, 18))      # bỏ chọn ảnh cuối -> thoát chế độ chọn
    assert not v.multi and not v.selectedIndexes() and counts[-1] == 0
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, pt(1, 70, 70))      # lại bình thường: bấm một lần là mở
    assert opened == [1]
    v.select_all()
    assert len(v.selectedIndexes()) == len(photos) and v.multi
    v.clear_selection()
    assert not v.selectedIndexes()


def test_scroll_date_pill_and_order(photos):
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 300)
    v.show()
    items = [dict(it, taken=f"2025-0{5 - i % 3}-1{i % 9} 10:00:00") for i, it in enumerate(photos * 6)]
    m.set_items(items)
    v.relayout()
    from PySide6.QtGui import QImage
    v._fast = True
    img = QImage(v.viewport().size(), QImage.Format_ARGB32)
    v.viewport().render(img)                                   # vẽ có nhãn tháng/năm mà không lỗi
    assert v._fast
    v.verticalScrollBar().setValue(v.verticalScrollBar().maximum() // 2)
    QApplication.processEvents()
    v.viewport().render(img)


def test_refresh_keeps_scroll_position(photos):
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 300)
    v.show()
    items = [dict(it, id=i, taken="2025-05-01 10:00:00") for i, it in enumerate(photos * 10)]
    m.set_items(items)
    v.relayout()
    mid = v.verticalScrollBar().maximum() // 2
    v.verticalScrollBar().setValue(mid)
    first = min(v._ids.index(i["id"]) for i in items if v.rects[items.index(i)][1] + v.rects[items.index(i)][3] > mid)
    before = v.rects[first][1] - v.verticalScrollBar().value()
    m.set_items([dict(it) for it in items])                      # làm mới cùng danh sách (như sau khi gắn nhãn)
    v.relayout()
    assert abs(v.rects[first][1] - v.verticalScrollBar().value() - before) < 2     # ảnh đang xem vẫn ở đúng chỗ
    m.set_items([dict(it, id=10000 + k) for k, it in enumerate(items)])             # danh sách khác hẳn: về đầu
    assert v.verticalScrollBar().value() == 0


def test_zoom_grid_and_quicklook(photos, tmp_path):
    from PySide6.QtGui import QImage
    from pp.ui.common import QuickLook
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 600)
    v.show()
    m.set_items(photos)
    v.relayout()
    h0, got = v.row_h, []
    v.rowHChanged.connect(got.append)
    v.set_row_h(h0 * 2)
    assert v.row_h == min(560, h0 * 2) and got
    v.set_row_h(10)
    assert v.row_h == 90
    v.toggle_sel(1)
    assert v.sel == {1}
    ql = QuickLook(m.items, 0, lambda it: QImage(40, 30, QImage.Format_RGB32), None, v)
    QTest.keyClick(ql, Qt.Key_Right)
    assert ql.i == 1 and "ĐÃ CHỌN" in ql.head.text()
    QTest.keyClick(ql, Qt.Key_X)                               # chọn / bỏ chọn ngay trong khung xem nhanh
    assert v.sel == set()
    QTest.keyClick(ql, Qt.Key_Left)
    assert ql.i == 0


def test_right_click_keeps_selection(photos):
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 600)
    v.show()
    m.set_items(photos)
    v.relayout()

    def center(i):
        x, y, w, h = v.rects[i]
        return QPoint(int(x + w / 2), int(y + h / 2) - v.verticalScrollBar().value())
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, center(0))
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.ControlModifier, center(1))
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.ControlModifier, center(2))
    assert v.sel == {0, 1, 2}
    QTest.mouseClick(v.viewport(), Qt.RightButton, Qt.NoModifier, center(4))     # bấm nhầm chuột phải vào ảnh chưa chọn
    assert v.sel == {0, 1, 2}
    v.clear_selection()
    QTest.mouseClick(v.viewport(), Qt.RightButton, Qt.NoModifier, center(3))     # chưa chọn gì: chuột phải chọn ảnh đó như cũ
    assert v.sel == {3}


def test_viewer_space_marks_images_and_shared_with_grid(photos):
    from PySide6.QtGui import QImage
    from pp.ui.common import Viewer
    m = ThumbModel()
    v = JustifiedView(m)
    v.resize(900, 600)
    v.show()
    m.set_items(photos)
    v.relayout()
    for it in photos[:2]:
        it["path"] = it["thumb"]
    vw = Viewer(m.items, 0, lambda it: QImage(40, 30, QImage.Format_RGB32), None, None, None)
    vw.marks = v.sel
    seen = []
    vw.on_marks = lambda: seen.append(set(v.sel))
    vw.show()
    QTest.keyClick(vw, Qt.Key_Control)                     # đánh dấu ảnh 0
    vw.go(1)
    QTest.keyClick(vw, Qt.Key_Control)                     # đánh dấu ảnh 1
    assert v.sel == {0, 1} and "ĐÃ CHỌN" in vw.cap.text()
    QTest.keyClick(vw, Qt.Key_Control)                     # bỏ dấu ảnh 1
    assert v.sel == {0}


def test_viewer_hover_face_shows_name_and_face_menu(photos):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage
    from pp.ui.common import Viewer
    m = ThumbModel()
    m.set_items(photos[:2])
    menus = []
    faces = lambda it: [{"box": (0.2, 0.2, 0.3, 0.3), "pid": 7, "name": "Anna Nguyen", "fid": 1, "iid": 0}]
    vw = Viewer(m.items, 0, lambda it: QImage(100, 100, QImage.Format_RGB32), None, None, None, faces=faces,
                face_menu=lambda it, f, v: menus.append(f["name"]) or [])
    vw.show()
    vw._hover_face(QPointF(30, 30))                                   # trong khung mặt (0.2–0.5 của ảnh 100x100)
    assert vw.face_box.isVisible() and vw._face_at(QPointF(30, 30))["name"] == "Anna Nguyen"
    vw._hover_face(QPointF(90, 90))                                   # ngoài mặt
    assert not vw.face_box.isVisible() and vw._face_at(QPointF(90, 90)) is None

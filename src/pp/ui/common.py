"""Thành phần giao diện dùng chung: lưới ảnh giữ tỉ lệ gốc, trình xem ảnh có thu phóng, tiện ích."""
import bisect
import io
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys

from PIL import Image, ImageOps
from PySide6.QtCore import (QAbstractListModel, QEasingCurve, QEvent, QModelIndex, QPoint, QPointF, QPropertyAnimation, QRect,
                            QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QShortcut, QCursor)
from PySide6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QDialog, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel, QListView, QPushButton, QSlider, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..secure import SEC
from . import theme


def pil_to_qimage(im: Image.Image) -> QImage:
    im = im.convert("RGBA")
    q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height, QImage.Format_RGBA8888)
    return q.copy()


def load_qimage(src) -> QImage:
    """src là đường dẫn hoặc bytes. Dùng Pillow để đọc được cả HEIC và xoay đúng chiều ảnh."""
    im = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
    return pil_to_qimage(ImageOps.exif_transpose(im))


def reveal(path):
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except Exception:
        pass


class ThumbModel(QAbstractListModel):
    """Mỗi phần tử: dict có 'thumb' (đường dẫn) hoặc 'tbytes' (hàm trả bytes), 'label', 'tip', 'w', 'h'."""

    ready = Signal()                 # có thêm ảnh nhỏ vừa nạp xong (nạp nền, để cuộn không bị khựng)
    _loaded = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.items, self.cache = [], {}
        self._pending = set()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._loaded.connect(self._on_loaded)

    def _fetch(self, key, it):
        img = QImage()
        try:
            if it.get("thumb"):
                img.loadFromData(SEC.read_file(it["thumb"]))
            elif it.get("tbytes"):
                img.loadFromData(it["tbytes"]())
        except Exception:
            pass
        try:
            self._loaded.emit(key, img)
        except RuntimeError:
            pass

    def _on_loaded(self, key, img):
        self._pending.discard(key)
        if len(self.cache) > 4000:
            self.cache.clear()
        self.cache[key] = QPixmap.fromImage(img) if not img.isNull() else QPixmap()
        self.ready.emit()

    def pixmap_async(self, it):
        """Trả về ảnh nhỏ nếu đã có; nếu chưa thì xếp hàng nạp nền và trả về None."""
        key = it.get("key") or it.get("thumb")
        pm = self.cache.get(key)
        if pm is None and key not in self._pending:
            self._pending.add(key)
            self._pool.submit(self._fetch, key, it)
        return pm

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        it = self.items[idx.row()]
        if role == Qt.DecorationRole:
            return QIcon(self.pixmap(it))
        if role == Qt.DisplayRole:
            return it.get("label", "")
        if role == Qt.ToolTipRole:
            return it.get("tip", "")
        if role == Qt.UserRole:
            return it
        return None

    def pixmap(self, it):
        key = it.get("key") or it.get("thumb")
        pm = self.cache.get(key)
        if pm is None:
            pm = QPixmap()
            try:
                if it.get("thumb"):
                    pm.loadFromData(SEC.read_file(it["thumb"]))
                elif it.get("tbytes"):
                    pm.loadFromData(it["tbytes"]())
            except Exception:
                pass
            if len(self.cache) > 4000:
                self.cache.clear()
            self.cache[key] = pm
        return pm


CARD_GAP = 10      # khoảng cách ngang giữa hai thẻ: LUÔN bằng nhau dù phóng to hay thu nhỏ cỡ ảnh
CARD_MIN_PITCH = 72   # bề rộng ô thẻ tối thiểu


def card_size_for(width, cols):
    """Cỡ thẻ (chiều cao ảnh) để đúng `cols` thẻ vừa khít một hàng rộng `width` điểm ảnh, không thừa khoảng trống bên phải."""
    pitch = max(CARD_MIN_PITCH, int(width) // max(1, cols))          # cửa sổ hẹp: thẻ không nhỏ hơn mức này, hàng tự xuống dòng thay vì tràn sang phải
    size = max(30, int((pitch - CARD_GAP) / 0.75) + 1)
    while size > 30 and int(size * 0.75) + CARD_GAP > pitch:
        size -= 1
    return size


def card_dims(size):
    """(bề rộng khung ảnh chân dung, bề rộng ô, chiều cao ô) của thẻ người. Tên và số ảnh nằm ĐÈ lên chân ảnh nên ô chỉ cao hơn ảnh một chút."""
    box = int(size * 0.75)                  # khung ảnh chân dung tỉ lệ 3 : 4 (rộng : cao), mọi người đều bằng nhau
    return box, box + CARD_GAP, size + 10


def heart_rect(cell, size):
    """Vùng bấm của nút trái tim: góc TRÊN bên trái của ảnh trong ô `cell` (không che tên ở chân ảnh)."""
    box_w = card_dims(size)[0]
    left = cell.left() + (cell.width() - box_w) // 2
    d = max(22, min(34, int(size * 0.14)))
    return QRect(left + 6, cell.top() + 5 + 6, d, d)


def on_resize_debounced(widget, fn, ms=45):
    """Gọi fn một lần sau khi ngừng kéo giãn khung (tránh dàn lại cả thư viện ở từng điểm ảnh khi đổi cỡ cửa sổ)."""
    t = getattr(widget, "_rs_timer", None)
    if t is None:
        t = widget._rs_timer = QTimer(widget)
        t.setSingleShot(True)
        t.timeout.connect(fn)
    t.start(ms)


class CardDelegate(QStyledItemDelegate):
    """Vẽ thẻ người: ảnh đại diện 3:4 bo góc; TÊN và số ảnh nằm đè ở chân ảnh (trên nền mờ), kèm nút trái tim yêu thích."""

    def __init__(self, view, size):
        super().__init__(view)
        self.view, self.size = view, size

    def sizeHint(self, option, index):
        return self.view.gridSize()

    def paint(self, p, option, index):
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)                    # ảnh đại diện nét khi thu/phóng
        box_w = card_dims(self.size)[0]
        tgt = QRect(r.left() + (r.width() - box_w) // 2, r.top() + 5, box_w, self.size)
        rad = box_w * 0.18
        clip = QPainterPath()                                              # bo góc mềm theo tỉ lệ logo Xiaomi (bán kính ≈ 18% bề rộng)
        clip.addRoundedRect(QRectF(tgt), rad, rad)
        ic = index.data(Qt.DecorationRole)
        p.save()
        p.setClipPath(clip)
        p.fillRect(tgt, QColor(theme.PLACE))
        if isinstance(ic, QIcon) and not ic.isNull():
            pm = ic.pixmap(QSize(self.size, self.size))
            if not pm.isNull():
                w, h = pm.width(), pm.height()
                k = max(box_w / max(1.0, w), self.size / max(1.0, h))               # phủ kín khung 3x4 rồi cắt phần thừa (giữ phần trên: có mặt)
                sw, sh = box_w / k, self.size / k
                p.drawPixmap(QRectF(tgt), pm, QRectF((w - sw) / 2, max(0.0, min(h - sh, (h - sh) * 0.25)), sw, sh))
        u = float((index.data(Qt.UserRole) or {}).get("unver") or 0.0)     # phần ảnh CHƯA xác minh: "dung dịch" đổ từ đáy lên theo đúng tỉ lệ; 100% xác minh thì ảnh hiện trọn vẹn
        if u > 0.004:
            top = tgt.bottom() - max(4.0, u * tgt.height())
            amp = max(1.5, box_w * 0.012)
            wave = QPainterPath()
            wave.moveTo(tgt.left() - 2, tgt.bottom() + 2)
            wave.lineTo(tgt.left() - 2, top)
            import math
            for k in range(0, 41):
                xx = tgt.left() + box_w * k / 40.0
                wave.lineTo(xx, top + amp * math.sin(k / 40.0 * 2 * math.pi * 1.5))
            wave.lineTo(tgt.right() + 2, tgt.bottom() + 2)
            wave.closeSubpath()
            lg = QLinearGradient(0, top, 0, tgt.bottom())
            lg.setColorAt(0, QColor(60, 150, 190, 120))
            lg.setColorAt(1, QColor(20, 70, 110, 190))
            p.setPen(Qt.NoPen)
            p.setBrush(lg)
            p.drawPath(wave)
            p.setPen(QPen(QColor(190, 235, 255, 150), 1.4))
            p.setBrush(Qt.NoBrush)
            surf = QPainterPath()
            for k in range(0, 41):
                xx = tgt.left() + box_w * k / 40.0
                yy = top + amp * math.sin(k / 40.0 * 2 * math.pi * 1.5)
                surf.moveTo(xx, yy) if k == 0 else surf.lineTo(xx, yy)
            p.drawPath(surf)
        # nền mờ ở chân ảnh cho chữ dễ đọc
        band = QRect(tgt.left(), tgt.bottom() - int(self.size * 0.42), box_w, int(self.size * 0.42) + 1)
        g = QLinearGradient(band.left(), band.top(), band.left(), band.bottom())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(0.55, QColor(0, 0, 0, 150))
        g.setColorAt(1, QColor(0, 0, 0, 215))
        p.fillRect(band, g)
        p.restore()
        sel = bool(option.state & QStyle.State_Selected)
        if sel or (option.state & QStyle.State_MouseOver):
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.BRASS_LIGHT), 3 if sel else 2))
            p.drawPath(clip)
        # tên và số ảnh đè ở chân ảnh
        lines = str(index.data(Qt.DisplayRole) or "").split("\n")
        name, count = " ".join(lines[:-1]) if len(lines) > 1 else lines[0], lines[-1] if len(lines) > 1 else ""
        hr = heart_rect(r, self.size)
        text_w = box_w - 16                                               # heart ở góc trên trái nên tên được dùng cả bề rộng ảnh
        f = p.font()
        base = max(7.0, min(11.0, self.size * 0.07))                      # chữ nhỏ dần khi nhiều thẻ mỗi hàng
        f.setPointSizeF(base)
        f.setBold(False)
        small = QFont(f)
        small.setPointSizeF(max(6.5, base - 1.5))
        fm_small = QFontMetrics(small)
        cnt_rect = QRect(tgt.left() + 8, tgt.bottom() - fm_small.height() - 4, text_w, fm_small.height())
        bold = QFont(f)
        bold.setBold(True)
        name_area = QRect(tgt.left() + 8, tgt.bottom() - int(self.size * 0.40), text_w, max(10, cnt_rect.top() - (tgt.bottom() - int(self.size * 0.40))))
        p.setFont(bold)                                                   # mọi tên cùng cỡ chữ; tên dài thì xuống dòng để hiện ĐỦ, không cắt
        p.setPen(QColor("#FFFFFF"))
        p.drawText(name_area, Qt.AlignLeft | Qt.AlignBottom | Qt.TextWordWrap, name)
        if count:
            p.setFont(small)
            p.setPen(QColor(255, 255, 255, 205))
            p.drawText(cnt_rect, Qt.AlignLeft | Qt.AlignVCenter, count)
        # nút trái tim yêu thích (góc trên trái)
        fav = bool((index.data(Qt.UserRole) or {}).get("fav"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawEllipse(hr)
        _draw_heart(p, QRectF(hr).adjusted(hr.width() * 0.22, hr.height() * 0.24, -hr.width() * 0.22, -hr.height() * 0.2), fav)
        if (index.data(Qt.UserRole) or {}).get("pend"):                       # còn ảnh app đề xuất chưa xác nhận: viền vàng đồng quanh thẻ (giống điện thoại)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#A9793D"), 2.4))
            p.drawRoundedRect(QRectF(tgt).adjusted(1.2, 1.2, -1.2, -1.2), rad, rad)
        p.restore()


def _draw_heart(p, r, filled):
    """Trái tim dùng chung với mọi nơi khác (xem floatbar.draw_heart)."""
    from .floatbar import draw_heart
    draw_heart(p, r, filled)


class CardView(QListView):
    """Lưới thẻ người: bấm vào nút trái tim (góc dưới phải ảnh) thì phát heartClicked thay vì mở người đó."""
    heartClicked = Signal(object)

    def mousePressEvent(self, e):
        ix = self.indexAt(e.position().toPoint())
        d = self.itemDelegate()
        if ix.isValid() and e.button() == Qt.LeftButton and isinstance(d, CardDelegate):
            if heart_rect(self.visualRect(ix), d.size).adjusted(-4, -4, 4, 4).contains(e.position().toPoint()):
                self.heartClicked.emit(ix)
                e.accept()
                self._swallow = True
                return
        self._swallow = False
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if getattr(self, "_swallow", False):                   # nhả chuột sau khi bấm tim: không coi là bấm mở người
            self._swallow = False
            e.accept()
            return
        super().mouseReleaseEvent(e)


def make_grid(model, size=160, text=False):
    """Lưới biểu tượng cố định ô (dùng cho thẻ người, nhóm ảnh tương tự)."""
    v = CardView() if text else QListView()
    v.setViewMode(QListView.IconMode)
    v.setResizeMode(QListView.Adjust)
    v.setMovement(QListView.Static)
    v.setIconSize(QSize(size, size))
    if text:
        bw, cw, ch = card_dims(size)
        v.setGridSize(QSize(cw, ch))                                                     # ô vừa khít ảnh + khoảng cách cố định
    else:
        v.setGridSize(QSize(size + 16, size + 14))
    v.setUniformItemSizes(True)
    v.setSpacing(0 if text else 2)
    v.setWordWrap(True)
    v.setTextElideMode(Qt.ElideNone)                    # không cắt tên bằng dấu …
    v.setLayoutMode(QListView.Batched)
    v.setBatchSize(200)
    v.setSelectionMode(QAbstractItemView.ExtendedSelection)
    v.setEditTriggers(QAbstractItemView.NoEditTriggers)
    v.setModel(model)
    if text:
        v.setItemDelegate(CardDelegate(v, size))
    return v


def set_card_size(view, size):
    """Đổi cỡ thẻ (ảnh đại diện) của lưới tạo bằng make_grid(..., text=True)."""
    view.setIconSize(QSize(size, size))
    bw, cw, ch = card_dims(size)
    view.setGridSize(QSize(cw, ch))
    d = view.itemDelegate()
    if isinstance(d, CardDelegate):
        d.size = size
    view.viewport().update()
    view.doItemsLayout()


def selected_items(view):
    return [i.data(Qt.UserRole) for i in view.selectedIndexes()]


# ====================================================================== lưới ảnh giữ tỉ lệ gốc
FAV_IDS = set()          # mã các ảnh đã gắn ngôi sao Yêu thích (để vẽ ngôi sao nhỏ ở góc ảnh trong lưới, giống điện thoại)


def set_fav_ids(ids):
    FAV_IDS.clear()
    FAV_IDS.update(ids)


class JustifiedView(QAbstractScrollArea):
    """Lưới ảnh xếp hàng đều như thư viện ảnh: mỗi ảnh giữ đúng tỉ lệ gốc (không cắt, không méo).
    Chỉ vẽ phần đang nhìn thấy nên dùng được cho hàng chục nghìn ảnh."""
    doubleClicked = Signal(QModelIndex)
    activated = Signal(QModelIndex)         # bấm chuột trái một lần vào ảnh (không giữ Ctrl/Shift, không kéo)
    selectionChanged = Signal(int)          # số ảnh đang chọn
    CIRCLE = 36                             # vùng bấm hình tròn ở góc trên trái mỗi ảnh để chọn (như Google Ảnh)
    contextRequested = Signal(QPoint)       # vị trí trong viewport
    rowHChanged = Signal(int)
    quickLook = Signal(int)                 # bấm Space: xem nhanh ảnh đang trỏ chuột (hoặc ảnh hiện tại) ở khung lớn

    def __init__(self, model, row_h=190, gap=6):
        super().__init__()
        self.show_stars = True                               # tab Favorite tắt (ở đó ảnh nào cũng đã có sao)
        self.m, self.row_h, self.gap = model, row_h, gap
        self.rects, self.bottoms = [], []
        self.total_h = 0
        self.sel, self.cur, self.hover, self.anchor = set(), -1, -1, -1
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QAbstractScrollArea.NoFrame)
        self.viewport().setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.verticalScrollBar().setSingleStep(48)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        model.modelReset.connect(self._reset)
        self._press = None
        self.outer = None                   # nếu lưới nằm trong một vùng cuộn khác (không tự cuộn): con lăn chuyển cho vùng đó
        self.multi = False                  # đang ở chế độ chọn nhiều: bấm vào ảnh là chọn/bỏ chọn, không mở
        self._target = 0
        self._last_off = 0
        self._corners = None
        self._fast = False                  # đang cuộn: vẽ nhanh, dừng cuộn thì vẽ mịn
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(140)
        self._settle.timeout.connect(self._settled)
        self._upd = QTimer(self)
        self._upd.setSingleShot(True)
        self._upd.setInterval(30)
        self._upd.timeout.connect(self.viewport().update)
        model.ready.connect(lambda: self._upd.start() if not self._upd.isActive() else None)

    def _on_scroll(self, v):
        """Cuộn: dịch phần ảnh đã vẽ rồi chỉ vẽ dải mới lộ ra (thay vì vẽ lại cả khung ở mỗi bước cuộn) cho mượt."""
        self._fast = True
        self._settle.start()
        d = self._last_off - v
        self._last_off = v
        vp = self.viewport()
        if d and abs(d) < vp.height() - 40:
            vp.scroll(0, d)
            vp.update(QRect(0, 0, vp.width(), 60))                 # nhãn tháng/năm nổi ở đầu khung vẽ lại, không để lại vệt
        else:
            vp.update()

    def _settled(self):
        self._fast = False
        self.viewport().update()

    def scroll_to(self, value, animate=True, ms=220):
        vb = self.verticalScrollBar()
        value = max(vb.minimum(), min(vb.maximum(), int(value)))
        self._target = value
        self._anim.stop()
        if not animate or abs(value - vb.value()) < 2:
            vb.setValue(value)
            return
        self._anim.setDuration(ms)
        self._anim.setStartValue(vb.value())
        self._anim.setEndValue(value)
        self._anim.start()

    def show_item(self, i):
        """Cuộn tới ảnh thứ i (đặt giữa khung) KHÔNG đổi vùng chọn: dùng khi thoát khỏi trình xem để không mất dấu ảnh vừa xem.
        Lưới nằm trong khung cuộn chung (nhóm Dressed / Nude…) thì cuộn khung đó."""
        if not 0 <= i < len(self.rects):
            return
        x, y, w, h = self.rects[i]
        self.cur = i
        if self.outer is not None and self.outer.widget() is not None:
            top = self.mapTo(self.outer.widget(), QPoint(0, int(y))).y()
            self.outer.verticalScrollBar().setValue(int(top + h / 2 - self.outer.viewport().height() / 2))
        else:
            self.scroll_to(y + h / 2 - self.viewport().height() / 2, ms=250)
        self.viewport().update()

    def reveal(self, i, center=True):
        """Chọn ảnh thứ i và cuộn tới đó (mặc định đặt ảnh ở giữa khung) để không bị trôi mất khi đang xem."""
        if not 0 <= i < len(self.rects):
            return
        x, y, w, h = self.rects[i]
        self.sel, self.cur, self.anchor = {i}, i, i
        self.multi = False
        self.selectionChanged.emit(1)
        vh = self.viewport().height()
        if center:
            self.scroll_to(y + h / 2 - vh / 2, ms=300)
        else:
            vb = self.verticalScrollBar()
            if y < vb.value():
                self.scroll_to(y - 4)
            elif y + h > vb.value() + vh:
                self.scroll_to(y + h - vh + 4)
        self.viewport().update()

    def set_row_h(self, h):
        """Đổi cỡ ảnh trong lưới (thu phóng), giữ nguyên vị trí cuộn tương đối."""
        h = int(max(90, min(560, h)))
        if h == self.row_h:
            return
        vb = self.verticalScrollBar()
        ratio = vb.value() / max(1, self.total_h)
        self.row_h = h
        self.relayout()
        self.rowHChanged.emit(h)
        vb.setValue(int(ratio * self.total_h))
        self.viewport().update()

    def toggle_sel(self, i):
        if 0 <= i < len(self.rects):
            self.sel ^= {i}
            self.cur = self.anchor = i
            self.multi = bool(self.sel)
            self.selectionChanged.emit(len(self.sel))
            self.viewport().update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:           # Ctrl + cuộn: thu phóng cỡ ảnh trong lưới
            self.set_row_h(self.row_h * 1.12 ** (e.angleDelta().y() / 120.0))
            e.accept()
            return
        if self.outer is not None:
            ob = self.outer.verticalScrollBar()
            ob.setValue(ob.value() - (e.pixelDelta().y() or int(e.angleDelta().y() / 120.0 * 90)))
            e.accept()
            return
        vb = self.verticalScrollBar()
        px = e.pixelDelta().y()
        if px:                                           # bàn di chuột: theo từng điểm ảnh, không cần hiệu ứng
            self._anim.stop()
            vb.setValue(vb.value() - px)
            e.accept()
            return
        d = e.angleDelta().y() / 120.0 * 120
        base = self._target if self._anim.state() == QPropertyAnimation.Running else vb.value()
        self.scroll_to(base - d, ms=240)
        e.accept()

    # ---- API giống QListView để các trang dùng chung ----
    def model(self):
        return self.m

    def selectedIndexes(self):
        return [self.m.index(i) for i in sorted(self.sel) if i < len(self.m.items)]

    def currentIndex(self):
        return self.m.index(self.cur) if 0 <= self.cur < len(self.m.items) else QModelIndex()

    # ---- bố cục ----
    @staticmethod
    def _aspect(it):
        w, h = it.get("w"), it.get("h")
        a = (w / h) if (w and h) else 1.0
        return max(0.35, min(a, 4.0))

    def select_all(self):
        self.sel = set(range(len(self.m.items)))
        self.multi = bool(self.sel)
        self.selectionChanged.emit(len(self.sel))
        self.viewport().update()

    def select_rows(self, rows):
        """Chọn đúng các ảnh có chỉ số `rows` (vào chế độ chọn nhiều)."""
        self.sel = set(int(r) for r in rows)
        self.multi = bool(self.sel)
        self.selectionChanged.emit(len(self.sel))
        self.viewport().update()

    def clear_selection(self):
        self.sel.clear()
        self.multi = False
        self.selectionChanged.emit(0)
        self.viewport().update()

    def _in_circle(self, i, pos):
        x, y, w, h = self.rects[i]
        return pos.x() - x <= self.CIRCLE and pos.y() + self.verticalScrollBar().value() - y <= self.CIRCLE

    @staticmethod
    def _ikey(it):
        return it["id"] if it.get("id") is not None else (it.get("key") or it.get("thumb") or it.get("path"))

    def _reset(self):
        """Danh sách được nạp lại. Nếu vẫn là (phần lớn) cùng các ảnh (vd. vừa gắn nhãn xong) thì giữ nguyên vị trí đang xem;
        nếu là danh sách khác hẳn thì về đầu."""
        old_ids, old_rects, old_off = getattr(self, "_ids", []), list(self.rects), self.verticalScrollBar().value()
        old_bottoms = list(self.bottoms)
        self.multi = False
        self.sel.clear()
        self.selectionChanged.emit(0)
        self.cur = self.hover = self.anchor = -1
        self._anim.stop()
        new_ids = [self._ikey(it) for it in self.m.items]
        self._ids = new_ids
        self.relayout()
        target = 0
        if old_ids and new_ids:
            newpos = {k: i for i, k in enumerate(new_ids)}
            overlap = sum(1 for k in old_ids if k in newpos) / max(1, len(old_ids))
            if overlap >= 0.3:
                i0 = min(bisect.bisect_left(old_bottoms, old_off), len(old_ids) - 1)
                for i in range(i0, len(old_ids)):          # ảnh đầu tiên đang thấy (hoặc ảnh kế tiếp còn tồn tại) làm mốc
                    j = newpos.get(old_ids[i])
                    if j is not None:
                        target = self.rects[j][1] - (old_rects[i][1] - old_off)
                        break
        vb = self.verticalScrollBar()
        vb.setValue(max(0, min(vb.maximum(), int(target))))

    def relayout(self):
        W = max(100, self.viewport().width())
        items, g, H = self.m.items, self.gap, self.row_h
        self.rects, row, row_w = [], [], 0.0
        y = 0

        def flush(last):
            nonlocal y, row, row_w
            if not row:
                return
            ars = [self._aspect(items[i]) for i in row]
            h = H if (last and sum(ars) * H + g * (len(row) - 1) < W) else (W - g * (len(row) - 1)) / sum(ars)
            x = 0.0
            for i, a in zip(row, ars):
                w = a * h
                self.rects.append((i, x, y, w, h))
                x += w + g
            y += h + g
            row, row_w = [], 0.0

        for i, it in enumerate(items):
            row.append(i)
            row_w += self._aspect(it) * H + g
            if row_w - g >= W:
                flush(False)
        flush(True)
        self.rects.sort(key=lambda r: r[0])
        self.rects = [(x, y0, w, h) for _, x, y0, w, h in self.rects]
        self.bottoms = [y0 + h for _, y0, _, h in self.rects]
        self.total_h = max(self.bottoms) if self.bottoms else 0
        vb = self.verticalScrollBar()
        vb.setRange(0, max(0, int(self.total_h) - self.viewport().height()))
        self._last_off = vb.value()
        vb.setPageStep(self.viewport().height())
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if len(self.m.items) > 400:                       # thư viện lớn: dàn lại một lần khi ngừng kéo giãn khung
            on_resize_debounced(self, self.relayout)
        else:
            self.relayout()

    # ---- vẽ ----
    def _corner_pixmaps(self, rad=7):
        """4 góc bo (nền phủ ngoài phần cung tròn) vẽ đè lên ảnh: nhanh hơn nhiều so với cắt từng ảnh bằng đường bo mỗi lần vẽ."""
        key = (theme.CREAM, rad)
        if self._corners is None or self._corners[0] != key:
            img = QImage(rad, rad, QImage.Format_ARGB32_Premultiplied)
            img.fill(QColor(theme.CREAM))
            q = QPainter(img)
            q.setRenderHint(QPainter.Antialiasing)
            q.setCompositionMode(QPainter.CompositionMode_Clear)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(0, 0, 0))
            q.drawEllipse(QPointF(rad, rad), rad, rad)
            q.end()
            tl = QPixmap.fromImage(img)
            self._corners = (key, tl, QPixmap.fromImage(img.mirrored(True, False)), QPixmap.fromImage(img.mirrored(False, True)), QPixmap.fromImage(img.mirrored(True, True)))
        return self._corners[1:]

    def paintEvent(self, e):
        p = QPainter(self.viewport())
        if not self._fast:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
        dirty = e.rect()
        p.fillRect(dirty, QColor(theme.CREAM))
        n = len(self.m.items)
        if n == 0:
            p.setPen(QColor(theme.INK_SOFT))
            p.drawText(self.viewport().rect(), Qt.AlignCenter, "Chưa có ảnh")
            return
        off = self.verticalScrollBar().value()
        i0 = bisect.bisect_left(self.bottoms, off + dirty.top())
        ctl, ctr, cbl, cbr = self._corner_pixmaps()
        for i in range(i0, n):
            x, y, w, h = self.rects[i]
            if y - off > dirty.bottom():                    # chỉ vẽ những ảnh chạm vùng cần vẽ lại
                break
            r = QRectF(x, y - off, w, h)
            it = self.m.items[i]
            pm = self.m.pixmap_async(it)
            if pm is not None and not pm.isNull():
                p.drawPixmap(r, pm, QRectF(pm.rect()))     # cùng tỉ lệ nên không méo
            else:
                p.fillRect(r, QColor(theme.PLACE))
            if i in self.sel:
                p.fillRect(r, QColor(169, 121, 61, 70))
            elif i == self.hover:
                p.fillRect(r, QColor(255, 255, 255, 22))
            if w > 20 and h > 20:                            # bo góc (kể cả khi đang cuộn): bốn góc nền vẽ đè
                p.drawPixmap(QPointF(r.left(), r.top()), ctl)
                p.drawPixmap(QPointF(r.right() - 7, r.top()), ctr)
                p.drawPixmap(QPointF(r.left(), r.bottom() - 7), cbl)
                p.drawPixmap(QPointF(r.right() - 7, r.bottom() - 7), cbr)
            self._circle(p, r, i in self.sel, strong=(i == self.hover or self.multi or i in self.sel))
            if self.show_stars and w > 60 and it.get("id") in FAV_IDS:                  # ảnh đã gắn sao: ngôi sao mập vàng trong hình tròn tối, cạnh ô chọn
                p.save()
                p.setRenderHint(QPainter.Antialiasing)
                sc = QPointF(r.left() + 46, r.top() + 20)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 102))
                p.drawEllipse(sc, 11, 11)
                from .floatbar import draw_fat_star
                draw_fat_star(p, sc, 6.2, QColor(255, 208, 90))
                p.restore()
            if i in self.sel or i == self.cur and self.hasFocus():
                p.setPen(QPen(QColor(theme.BRASS), 3 if i in self.sel else 2))
                p.setBrush(Qt.NoBrush)
                p.setRenderHint(QPainter.Antialiasing)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 7, 7)
        if self._fast or self._anim.state() == QPropertyAnimation.Running:
            self._date_pill(p, off)

    def _circle(self, p, r, on, strong=True):
        c = QPointF(r.left() + 20, r.top() + 20)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if on:
            p.setBrush(QColor(theme.BRASS))
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawEllipse(c, 11, 11)
            p.setPen(QPen(QColor("#FFFFFF"), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(QPointF(c.x() - 5, c.y()), QPointF(c.x() - 1.5, c.y() + 4))
            p.drawLine(QPointF(c.x() - 1.5, c.y() + 4), QPointF(c.x() + 5.5, c.y() - 4))
        else:
            p.setBrush(QColor(0, 0, 0, 70 if strong else 45))
            p.setPen(QPen(QColor(255, 255, 255, 255 if strong else 190), 2))
            p.drawEllipse(c, 11, 11)
        p.restore()

    def _date_pill(self, p, off):
        """Khi đang cuộn: nhãn tháng/năm của hàng ảnh đang ở đầu danh sách (như Google Ảnh)."""
        i0 = min(bisect.bisect_left(self.bottoms, off), len(self.m.items) - 1)
        t = (self.m.items[i0].get("taken") or "")
        txt = f"Th{int(t[5:7])} {t[:4]}" if len(t) >= 7 and t[:4].isdigit() and t[5:7].isdigit() else ""
        if not txt:
            return
        f = QFont("Be Vietnam Pro", 11)
        f.setBold(True)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(txt) + 36
        r = QRectF((self.viewport().width() - w) / 2, 12, w, 38)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(r.translated(0, 2), 19, 19)
        p.setBrush(QColor(255, 255, 255, 245))
        p.drawRoundedRect(r, 19, 19)
        p.setPen(QColor("#1B1812"))
        p.drawText(r, Qt.AlignCenter, txt)
        p.restore()

    def _caption(self, p, r, it):
        g = QLinearGradient(r.left(), r.bottom() - 62, r.left(), r.bottom())
        g.setColorAt(0, QColor(20, 16, 10, 0))
        g.setColorAt(1, QColor(20, 16, 10, 225))
        p.fillRect(QRectF(r.left(), r.bottom() - 62, r.width(), 62), g)
        tag, name = it.get("cap_tag", ""), it.get("cap_title", "")
        f = QFont("Be Vietnam Pro", 7)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(QColor(theme.BRASS_LIGHT))
        p.drawText(QRectF(r.left() + 10, r.bottom() - 40, r.width() - 20, 14), Qt.AlignLeft | Qt.AlignVCenter, tag.upper())
        f2 = QFont("Be Vietnam Pro", 9)
        f2.setWeight(QFont.Medium)
        p.setFont(f2)
        p.setPen(QColor("#FFFFFF"))
        fm = p.fontMetrics()
        p.drawText(QRectF(r.left() + 10, r.bottom() - 26, r.width() - 20, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(name, Qt.ElideMiddle, int(r.width() - 20)))

    # ---- chuột và phím ----
    def _hit(self, pos):
        off = self.verticalScrollBar().value()
        y = pos.y() + off
        i0 = bisect.bisect_left(self.bottoms, y)
        for i in range(i0, min(len(self.rects), i0 + 40)):
            x0, y0, w, h = self.rects[i]
            if y0 > y:
                break
            if x0 <= pos.x() <= x0 + w and y0 <= y <= y0 + h:
                return i
        return -1

    def mousePressEvent(self, e):
        i = self._hit(e.position().toPoint())
        self.setFocus()
        mods = e.modifiers()
        if e.button() == Qt.RightButton:
            if i >= 0 and i not in self.sel and not self.sel:        # chưa chọn gì: chuột phải chọn ảnh đó; đang có ảnh đã chọn thì GIỮ NGUYÊN vùng chọn (bấm nhầm không mất)
                self.sel, self.cur, self.anchor = {i}, i, i
            self.viewport().update()
            if i >= 0:
                self.contextRequested.emit(e.position().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        self._press = None
        if i >= 0 and (mods & Qt.ShiftModifier) and self.anchor >= 0:
            a, b = sorted((self.anchor, i))      # Shift + bấm: chọn cả đoạn từ ảnh vừa chọn đến ảnh này, CỘNG THÊM vào những ảnh đã chọn
            self.sel |= set(range(a, b + 1))
            self.cur = self.anchor = i           # ảnh này thành mốc mới: bấm một ảnh khác rồi Shift + bấm tiếp để chọn thêm nhóm khác
            self.multi = True
        elif i >= 0 and (self._in_circle(i, pos) or (self.multi and not (mods & Qt.ShiftModifier))):
            self.sel ^= {i}                       # bấm vào vòng tròn (hoặc đang chọn nhiều): chọn / bỏ chọn
            self.cur = self.anchor = i
            self.multi = bool(self.sel)
        elif i < 0:
            if not (mods & (Qt.ControlModifier | Qt.ShiftModifier)):
                self.sel.clear()
                self.multi = False
        elif mods & Qt.ControlModifier:
            self.sel ^= {i}
            self.cur = self.anchor = i
            self.multi = bool(self.sel)
        else:
            self.sel, self.cur, self.anchor = {i}, i, i
            self._press = (pos, i)               # bấm thường: chọn và mở xem
        self.selectionChanged.emit(len(self.sel))
        self.viewport().update()

    def mouseReleaseEvent(self, e):
        e.accept()
        pr, self._press = self._press, None
        if pr and e.button() == Qt.LeftButton and pr[1] >= 0:
            pos = e.position().toPoint()
            if (pos - pr[0]).manhattanLength() < 6 and self._hit(pos) == pr[1]:
                self.cur = pr[1]
                self.activated.emit(self.m.index(pr[1]))

    def mouseDoubleClickEvent(self, e):
        i = self._hit(e.position().toPoint())
        if i >= 0 and e.button() == Qt.LeftButton:
            self.cur = i
            self.doubleClicked.emit(self.m.index(i))

    def mouseMoveEvent(self, e):
        i = self._hit(e.position().toPoint())
        if i != self.hover:
            self.hover = i
            self.viewport().update()
            self.viewport().setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            self.viewport().setToolTip("")                          # không hiện chữ khi chỏ vào ảnh nhỏ: thông tin ảnh xem ở mục Info

    def leaveEvent(self, e):
        self.hover = -1
        self.viewport().update()

    def _move(self, d, extend=False):
        n = len(self.m.items)
        if not n:
            return
        i = max(0, min(n - 1, (self.cur if self.cur >= 0 else -1) + d))
        if extend and self.anchor >= 0:
            a, b = sorted((self.anchor, i))
            self.sel = set(range(a, b + 1))
        else:
            self.sel, self.anchor = {i}, i
        self.cur = i
        self.reveal_keep(i)
        self.viewport().update()

    def reveal_keep(self, i):
        x, y, w, h = self.rects[i]
        vb = self.verticalScrollBar()
        if y < vb.value():
            self.scroll_to(y - 4, ms=140)
        elif y + h > vb.value() + self.viewport().height():
            self.scroll_to(y + h - self.viewport().height() + 4, ms=140)

    def keyPressEvent(self, e):
        k, ext = e.key(), bool(e.modifiers() & Qt.ShiftModifier)
        if k == Qt.Key_Right:
            self._move(1, ext)
        elif k == Qt.Key_Left:
            self._move(-1, ext)
        elif k == Qt.Key_Home:
            self._move(-10 ** 9, ext)
        elif k == Qt.Key_End:
            self._move(10 ** 9, ext)
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.cur >= 0:
            self.activated.emit(self.m.index(self.cur))
        elif k == Qt.Key_Space and not e.isAutoRepeat() and (self.hover >= 0 or self.cur >= 0):
            self.quickLook.emit(self.hover if self.hover >= 0 else self.cur)
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.set_row_h(self.row_h * 1.15)
        elif k == Qt.Key_Minus:
            self.set_row_h(self.row_h / 1.15)
        elif k == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self.select_all()
        elif k == Qt.Key_Escape and self.sel:
            self.clear_selection()
        else:
            super().keyPressEvent(e)


class QuickLook(QDialog):
    """Xem nhanh ảnh lớn ngay từ lưới, không rời khỏi danh sách và KHÔNG làm đổi vùng chọn: ← → chuyển ảnh, cuộn chuột hoặc kéo để thu phóng,
    Enter hoặc X chọn / bỏ chọn ảnh này trong lưới, 0 vừa khung, 1 kích thước 100%, Space hoặc Esc đóng."""

    def __init__(self, items, index, loader, parent, grid):
        super().__init__(parent)
        self.items, self.i, self.loader, self.grid, self.cache = items, index, loader, grid, {}
        self.setWindowTitle("Xem nhanh")
        pw = parent.window() if parent is not None else None
        if pw is not None:
            self.resize(int(pw.width() * 0.8), int(pw.height() * 0.85))
        self.setStyleSheet("QDialog{background:#14110d} QLabel{color:#EDE6D6;background:transparent}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.head = QLabel()
        lay.addWidget(self.head)
        self.view = ImageView()
        lay.addWidget(self.view, 1)
        hint = QLabel("← →: ảnh trước / sau   ·   Enter hoặc X: chọn / bỏ chọn   ·   cuộn chuột: thu phóng   ·   0: vừa khung   ·   1: 100%   ·   Space, Esc: đóng")
        hint.setStyleSheet("color:#9a927f;font-size:11px")
        lay.addWidget(hint)
        self.show_current()

    def show_current(self):
        it = self.items[self.i]
        img = self.cache.get(self.i)
        err = ""
        if img is None:
            try:
                img = self.loader(it)
                self.cache = {k: v for k, v in self.cache.items() if abs(k - self.i) <= 2}
                self.cache[self.i] = img
            except Exception as e:
                img = QImage(1, 1, QImage.Format_RGB32)
                err = f"  (không mở được: {e})"
        self.view.show_image(img)
        name = it.get("cap_title") or (it.get("tip", "").splitlines() or [""])[0]
        mark = "  <span style='color:#d9b26a'>✓ ĐÃ CHỌN</span>" if self.i in self.grid.sel else ""
        self.head.setText(f"<b>{name}</b>&nbsp;&nbsp;{self.i + 1} / {len(self.items)}{mark}{err}")

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Space, Qt.Key_Escape):
            self.close()
        elif k == Qt.Key_Right and self.i + 1 < len(self.items):
            self.i += 1
            self.show_current()
        elif k == Qt.Key_Left and self.i > 0:
            self.i -= 1
            self.show_current()
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_X):
            self.grid.toggle_sel(self.i)
            self.show_current()
        elif k == Qt.Key_0:
            self.view.fit()
        elif k == Qt.Key_1:
            self.view.actual()
        else:
            super().keyPressEvent(e)


# ====================================================================== trình xem ảnh
class ImageView(QGraphicsView):
    """Khung xem ảnh: giữ kích thước gốc.
    Thu phóng: cuộn chuột, hoặc nhấn giữ chuột trái rồi kéo lên/xuống (điểm đang bấm giữ nguyên tại chỗ).
    Di chuyển: kéo chuột phải, chuột giữa, hoặc giữ Space rồi kéo (hoặc chuyển sang kiểu kéo "di chuyển")."""
    zoomChanged = Signal(float)
    outsideClicked = Signal()
    contextRequested = Signal(QPoint)       # bấm chuột phải (không kéo): vị trí toàn màn hình để hiện menu
    clickedAt = Signal(QPointF)             # bấm trái (không kéo) lên ảnh: vị trí trong hệ tọa độ ảnh
    hovered = Signal(QPointF)               # chuột di chuyển trên ảnh (không kéo): vị trí trong hệ tọa độ ảnh
    MIN, MAX = 0.05, 8.0

    def __init__(self):
        super().__init__()
        self.sc = QGraphicsScene(self)
        self.setScene(self.sc)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.sc.addItem(self.item)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self.setStyleSheet("background:transparent;border:0")
        self.viewport().setStyleSheet("background:transparent")
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._fit, self._press = True, None
        self.mode = "pan"           # kiểu kéo chuột trái: "pan" (di chuyển, mặc định) hoặc "zoom"
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.space = False
        self.wheeled = False
        self._scrub = self._pan = None
        self._moved = False

    def set_mode(self, mode):
        self.mode = mode
        self.setDragMode(QGraphicsView.ScrollHandDrag if mode == "pan" else QGraphicsView.NoDrag)

    def show_image(self, qimg: QImage):
        self.item.setPixmap(QPixmap.fromImage(qimg))
        r = self.item.boundingRect()      # chừa lề rộng để phóng được tại bất kỳ điểm nào của ảnh
        self.sc.setSceneRect(r.adjusted(-r.width(), -r.height(), r.width(), r.height()))
        self.fit()

    def scale_now(self):
        return self.transform().m11()

    def fit(self):
        """Vừa khung nhưng không phóng to ảnh nhỏ quá 100%."""
        pm = self.item.pixmap()
        self.resetTransform()
        if pm.isNull():
            return
        vp = self.viewport().size()
        s = min(vp.width() / pm.width(), vp.height() / pm.height(), 1.0)
        self.scale(s, s)
        self.centerOn(self.item)
        self._fit = True
        self.zoomChanged.emit(s)

    def actual(self):
        self.resetTransform()
        self.centerOn(self.item)
        self._fit = False
        self.zoomChanged.emit(1.0)

    def zoom(self, f):
        s = self.scale_now()
        f = max(self.MIN / s, min(self.MAX / s, f))
        self.scale(f, f)
        self._fit = False
        self.zoomChanged.emit(self.scale_now())

    def wheelEvent(self, e):
        self.wheeled = True                                # (Ctrl + cuộn là thu phóng, không phải chọn ảnh)
        self.zoom(1.15 ** (e.angleDelta().y() / 120.0))

    def mouseDoubleClickEvent(self, e):
        if self._fit:
            self.actual()
        else:
            self.fit()

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        self._press, self._moved = pos, False
        b = e.button()
        if b in (Qt.RightButton, Qt.MiddleButton) or (b == Qt.LeftButton and self.space):
            hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
            self._pan = (pos, hb.value(), vb.value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        if b == Qt.LeftButton and self.mode == "zoom":
            self._scrub = (pos, self.mapToScene(pos), self.scale_now())
            self.viewport().setCursor(Qt.SizeVerCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        cur = e.position().toPoint()
        if self._press is not None and (cur - self._press).manhattanLength() >= 5:
            self._moved = True
        if self._pan is None and self._scrub is None and not e.buttons():
            self.hovered.emit(self.mapToScene(cur))
        if self._pan is not None:
            p0, h0, v0 = self._pan
            self.horizontalScrollBar().setValue(h0 - (cur.x() - p0.x()))
            self.verticalScrollBar().setValue(v0 - (cur.y() - p0.y()))
            self._fit = False
            return
        if self._scrub is not None:
            p0, anchor, s0 = self._scrub
            s = max(self.MIN, min(self.MAX, s0 * 1.01 ** (p0.y() - cur.y())))   # kéo lên = phóng to
            self.setTransformationAnchor(QGraphicsView.NoAnchor)
            self.resetTransform()
            self.scale(s, s)
            d = self.mapFromScene(anchor) - p0                                   # giữ điểm đang bấm đứng yên
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + d.y())
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self._fit = False
            self.zoomChanged.emit(s)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        was_drag = self._pan is not None or self._scrub is not None
        self._pan = self._scrub = None
        self.viewport().unsetCursor()
        super().mouseReleaseEvent(e)
        if e.button() == Qt.RightButton and not self._moved and self._press is not None:
            self.contextRequested.emit(e.globalPosition().toPoint())
        if e.button() == Qt.LeftButton and not self._moved and self._press is not None and not self.space:
            sp = self.mapToScene(e.position().toPoint())
            if not self.item.boundingRect().contains(sp):
                self.outsideClicked.emit()
            else:
                self.clickedAt.emit(sp)
        self._press = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()


def tool_icon(kind, active=False):
    """Biểu tượng vẽ tay: chuột với nút trái/phải được tô sáng ('left', 'right') hoặc khung vừa ảnh ('fit')."""
    dpr = 2
    pm = QPixmap(26 * dpr, 26 * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    cream, brass = QColor(theme.LIGHT_TEXT), QColor(theme.BRASS_LIGHT)
    pen = QPen(cream, 1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    if kind == "fit":                      # ảnh nằm gọn trong khung
        p.drawRoundedRect(QRectF(3.5, 3.5, 19, 19), 2, 2)
        p.drawRect(QRectF(8.5, 9.5, 9, 7))
    elif kind == "info":
        p.drawEllipse(QRectF(3.5, 3.5, 19, 19))
        p.drawLine(QPointF(13, 11.5), QPointF(13, 18.5))
        p.drawPoint(QPointF(13, 8))
    elif kind in ("star", "star_on"):                  # cùng ngôi sao mập với nút sao ở trang xem ảnh
        from .floatbar import draw_fat_star
        draw_fat_star(p, QPointF(13, 13), 10, QColor(255, 208, 90) if kind == "star_on" else cream, filled=(kind == "star_on"))
    elif kind == "play":
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(8, 21), QPointF(21, 13)]))
    elif kind == "pause":
        p.drawLine(QPointF(9, 5), QPointF(9, 21))
        p.drawLine(QPointF(17, 5), QPointF(17, 21))
    elif kind == "wheel":                  # chuột với con lăn giữa được tô sáng
        body = QRectF(7.5, 2.5, 11, 21)
        path = QPainterPath()
        path.addRoundedRect(body, 5.5, 5.5)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.fillRect(QRectF(11.7, 5, 2.6, 7), brass)
        p.drawLine(QPointF(7.5, 12.5), QPointF(18.5, 12.5))
    elif kind == "full":                   # phóng to toàn màn hình
        for (x, y, dx, dy) in ((4, 4, 1, 1), (22, 4, -1, 1), (4, 22, 1, -1), (22, 22, -1, -1)):
            p.drawLine(x, y, x + 6 * dx, y)
            p.drawLine(x, y, x, y + 6 * dy)
    else:
        body = QRectF(7.5, 2.5, 11, 21)
        path = QPainterPath()
        path.addRoundedRect(body, 5.5, 5.5)
        half = QPainterPath()
        if kind == "left":
            half.addRect(QRectF(7.5, 2.5, 5.5, 9))
        else:
            half.addRect(QRectF(13, 2.5, 5.5, 9))
        p.fillPath(path.intersected(half), brass)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.drawLine(QPointF(13, 2.5), QPointF(13, 11.5))
        p.drawLine(QPointF(7.5, 11.5), QPointF(18.5, 11.5))
    p.end()
    return QIcon(pm)


class MiniMap(QWidget):
    """Bản đồ nhỏ góc trên bên phải khi đang phóng to: khung sáng là vùng đang xem; bấm vào để nhảy tới vùng đó."""

    def __init__(self, view, parent):
        super().__init__(parent)
        self.view = view
        self.setFixedSize(168, 112)
        self.pm = QPixmap()
        self.setCursor(Qt.PointingHandCursor)

    def set_pixmap(self, pm):
        self.pm = pm.scaled(self.width() - 8, self.height() - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pm.isNull() else QPixmap()
        self.update()

    def _img_rect(self):
        w, h = self.pm.width(), self.pm.height()
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 190))
        if self.pm.isNull():
            return
        r = self._img_rect()
        p.drawPixmap(r.topLeft(), self.pm)
        full = self.view.item.boundingRect()
        vis = self.view.mapToScene(self.view.viewport().rect()).boundingRect().intersected(full)
        if full.width() and full.height():
            sx, sy = r.width() / full.width(), r.height() / full.height()
            vr = QRectF(r.left() + (vis.left() - full.left()) * sx, r.top() + (vis.top() - full.top()) * sy, vis.width() * sx, vis.height() * sy)
            p.fillRect(r, QColor(0, 0, 0, 110))
            p.drawPixmap(vr, self.pm, QRectF((vr.left() - r.left()), (vr.top() - r.top()), vr.width(), vr.height()))
            p.setPen(QPen(QColor(theme.BRASS_LIGHT), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRect(vr)

    def _jump(self, pos):
        r, full = self._img_rect(), self.view.item.boundingRect()
        if r.width() <= 0:
            return
        x = full.left() + (pos.x() - r.left()) / r.width() * full.width()
        y = full.top() + (pos.y() - r.top()) / r.height() * full.height()
        self.view.centerOn(QPointF(x, y))
        self.update()

    def mousePressEvent(self, e):
        self._jump(e.position())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._jump(e.position())


class DotSlider(QSlider):
    """Thanh trượt có chấm đánh dấu tại mỗi nấc (kiểu QSS không tự vẽ vạch nấc)."""

    def paintEvent(self, e):
        super().paintEvent(e)
        n = self.maximum() - self.minimum()
        if n < 1:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        half = 7.0                                                  # nửa bề rộng núm kéo
        y = self.height() / 2.0
        for k in range(n + 1):
            x = half + (self.width() - 2 * half) * k / n
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.BRASS) if self.minimum() + k <= self.value() else QColor(theme.INK_SOFT))
            p.drawEllipse(QPointF(x, y), 3.2, 3.2)
        # vẽ lại núm kéo đè lên chấm
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(QPen(QColor(theme.BRASS), 2))
        x = half + (self.width() - 2 * half) * (self.value() - self.minimum()) / n
        p.drawEllipse(QPointF(x, y), 7, 7)


class StripView(QListView):
    """Dải ảnh nhỏ của trình xem: bấm vào ảnh để xem; bấm đúng chấm tròn góc trên trái để tick chọn ảnh đầu tiên,
    sau đó bấm ở BẤT KỲ chỗ nào trên ảnh nhỏ cũng tick / bỏ tick ảnh đó."""

    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        ix = self.indexAt(e.position().toPoint())
        if ix.isValid() and e.button() == Qt.LeftButton:
            r = self.visualRect(ix)
            self.viewer.strip_click(ix.row(), QRect(r.left(), r.top(), 30, 30).contains(e.position().toPoint()))
            return
        super().mousePressEvent(e)


class StripDelegate(QStyledItemDelegate):
    def __init__(self, viewer, view):
        super().__init__(view)
        self.viewer, self.view = viewer, view

    def paint(self, p, option, index):
        r = option.rect.adjusted(2, 2, -2, -2)
        v = self.viewer
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(r), 4, 4)
        p.setClipPath(clip)
        p.fillRect(r, QColor(theme.PLACE))
        ic = index.data(Qt.DecorationRole)
        if isinstance(ic, QIcon) and not ic.isNull():
            pm = ic.pixmap(QSize(96, 96))
            if not pm.isNull():
                w, h = pm.width(), pm.height()
                k = max(r.width() / max(1.0, w), r.height() / max(1.0, h))
                sw, sh = r.width() / k, r.height() / k
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawPixmap(QRectF(r), pm, QRectF((w - sw) / 2, (h - sh) / 2, sw, sh))
        p.setClipping(False)
        row = index.row()
        if row == v.i:                                                   # ảnh đang xem: chỉ hiện khung bao
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.BRASS), 3))
            p.drawRoundedRect(QRectF(r).adjusted(1, 1, -1, -1), 4, 4)
        marks = v.marks
        if marks is not None:
            on = row in marks
            if on or marks or (option.state & QStyle.State_MouseOver):   # đã có ảnh được chọn: mọi ảnh hiện chấm tròn
                c = QPointF(r.left() + 13, r.top() + 13)
                p.setPen(QPen(QColor("#FFFFFF"), 1.6))
                p.setBrush(QColor(theme.BRASS) if on else QColor(0, 0, 0, 110))
                p.drawEllipse(c, 8.5, 8.5)
                if on:
                    p.setPen(QPen(QColor("#FFFFFF"), 2))
                    p.drawPolyline([QPointF(c.x() - 4, c.y()), QPointF(c.x() - 1, c.y() + 3), QPointF(c.x() + 4.5, c.y() - 3)])
        p.restore()

    def sizeHint(self, option, index):
        return QSize(72, 72)


class Viewer(QDialog):
    """Xem ảnh kiểu Google Ảnh: nền tối, ảnh vừa khung, dải ảnh nhỏ phía dưới; nút toàn màn hình (F11) ẩn dải ảnh và thanh công cụ tự ẩn.
    ← → chuyển ảnh (ảnh kế bên được nạp trước nên chuyển tức thì) · cuộn chuột hoặc nhấn giữ chuột trái rồi kéo lên/xuống để thu phóng
    tại điểm bấm · +/- thu phóng · 0 vừa khung · 1 kích thước 100% · kéo chuột phải hoặc giữ Space rồi kéo để di chuyển · Esc để đóng.
    Mỗi lần chuyển ảnh phát tín hiệu indexChanged để thư viện cuộn theo."""
    indexChanged = Signal(int)
    _got = Signal(int, object)

    def __init__(self, items, index, loader, parent=None, model=None, on_index=None, info=None, fav=None, menu=None, link=None, extra=None, faces=None, face_menu=None, add=None, cloth=None, confirm=None):
        super().__init__(parent)
        self.add_fn, self.cloth = add, cloth                  # add(item, viewer): thêm vào người · cloth=(lấy_nhóm(item), đặt_nhóm(item, mã)): phân loại Dressed / Naked ngay khi xem
        self.faces_fn, self.face_menu_fn = faces, face_menu     # faces(item) -> [{box,pid,name,fid}]; face_menu(item, face, viewer) -> menu cho mặt đó
        self.face_list = []
        self.marks = None                                   # tập chỉ số ảnh đánh dấu (dùng chung với lưới): Ctrl bật/tắt dấu chọn ảnh đang xem
        self.on_marks = None
        self._ctrl_clean = False
        self.link_fn, self.extra = link, extra or []       # link(href): bấm tên người trong thông tin ảnh; extra: [(chữ, gợi ý, hàm(item))] nút thêm trên thanh công cụ
        self.items, self.i, self.loader = items, index, loader
        self.model, self._temp = model, None                # _temp: chỉ số ảnh đang hiện tạm bằng ảnh nhỏ, chờ ảnh đầy đủ
        self.menu_fn = menu                         # menu(item, viewer) -> [(tên, hàm)] hoặc [(tên, [(tên, hàm)…])]: menu chuột phải khi xem ảnh
        self.info_fn, self.fav_fn = info, fav       # info(item) -> html;  fav(item, toggle) -> trạng thái yêu thích
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet("QDialog,QWidget{color:%s}" % theme.LIGHT_TEXT)
        self.setMouseTracking(True)
        self.cache, self._want, self._closed, self._first = {}, set(), False, True
        self.pool = ThreadPoolExecutor(max_workers=3)
        self._dir = 1
        self._got.connect(self._on_got)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.view = ImageView()
        lay.addWidget(self.view, 1)
        self.view.viewport().setMouseTracking(True)
        self.view.contextRequested.connect(self._show_menu)
        self.face_box = QGraphicsRectItem()                      # khung sáng quanh khuôn mặt đang rê chuột vào
        _pen = QPen(QColor(theme.BRASS_LIGHT), 3)
        _pen.setCosmetic(True)
        self.face_box.setPen(_pen)
        self.face_box.setZValue(10)
        self.face_box.setVisible(False)
        self.view.sc.addItem(self.face_box)
        self.view.hovered.connect(self._hover_face)
        self.view.clickedAt.connect(self._click_face)
        self.view.viewport().installEventFilter(self)
        # thanh trên: nút tròn nổi như điện thoại (✕, thêm vào người · Dressed | Naked · loại khỏi người, vị trí), tự ẩn khi xem toàn màn hình
        from .floatbar import ClothPill, RoundBtn, TopBar
        self.top = TopBar(self)
        self.top.setObjectName("vtop")
        self.cap = QLabel()                                   # (chân trang: tên ảnh)
        self.zl = QLabel("100%")                              # (không còn hiện trên thanh; giữ để các hàm cũ không lỗi)
        self.zoom_b, self.pan_b, self.full_b, self.info_b, self.star_b, self.play_b = (QPushButton() for _ in range(6))
        for b in (self.zoom_b, self.pan_b, self.info_b):
            b.setCheckable(True)
        self.pan_b.setChecked(True)
        self.btn_close = RoundBtn("close", "Đóng (Esc)")
        self.btn_close.clicked.connect(self.close)
        self.btn_add = RoundBtn("person+", "Thêm ảnh này vào một người…")
        self.btn_add.clicked.connect(lambda: self.add_fn(self.items[self.i], self) if self.add_fn else None)
        self.btn_add.setVisible(add is not None)
        self.top.left.addWidget(self.btn_close)
        self.top.left.addWidget(self.btn_add)
        self.confirm_fn = confirm                             # xem từ trang ảnh đề xuất: ô thứ ba là dấu ✓ xác nhận đúng người
        self.cloth_pill = ClothPill("Dressed / Naked: phân loại ảnh đang xem" + (" · ✓: xác nhận đúng người này" if confirm else ""), third="tick" if confirm else "none")
        self.cloth_pill.intercept = self._classify
        self.cloth_pill.setVisible(cloth is not None or confirm is not None)
        if confirm:
            self.cloth_pill.tickClicked.connect(self._confirm)
        self.top.mid.addWidget(self.cloth_pill)
        self.btn_rm = RoundBtn("person-", "Ảnh này không đúng người: loại khỏi nhóm")
        self.btn_loc = RoundBtn("enter", "Mở vị trí ảnh này trong All")
        self.btn_rm.hide()
        self.btn_loc.hide()
        for text, tip, fn in self.extra:                      # "Loại khỏi nhóm" -> nút người −; "Vị trí" -> nút ↵
            b = self.btn_rm if text.startswith("Loại") else self.btn_loc
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, fn=fn: (fn(self.items[self.i]), self._fill_info()))
            b.show()
        self.top.right.addWidget(self.btn_rm)
        self.top.right.addWidget(self.btn_loc)
        # chân trang: tên + thông tin ảnh (trái), ngôi sao mập + số thứ tự (phải), cùng một độ cao
        self.foot = QWidget(self)
        fl = QHBoxLayout(self.foot)
        fl.setContentsMargins(18, 4, 18, 6)
        self.foot_txt = QLabel()
        self.foot_txt.setTextFormat(Qt.RichText)
        self.foot_txt.setStyleSheet("background:transparent;font-size:13px")
        self.foot_txt.setOpenExternalLinks(False)
        self.foot_txt.linkActivated.connect(lambda h: self._go_person(h))
        fl.addWidget(self.foot_txt, 1)
        self.star_r = RoundBtn("star", "Yêu thích (nhãn “Yêu thích”)")
        self.star_r.setFixedSize(38, 38)
        self.star_r.clicked.connect(self.toggle_fav)
        self.star_r.setVisible(fav is not None)
        fl.addWidget(self.star_r)
        self.cnt = QLabel()
        self.cnt.setStyleSheet("background:transparent;font-size:15px;font-weight:700")
        fl.addWidget(self.cnt)
        self.foot.setStyleSheet("QWidget#vfoot{background:rgba(10,9,7,215)}")
        self.foot.setObjectName("vfoot")
        self.foot.setFixedHeight(58)
        self.view.zoomChanged.connect(lambda s: self.zl.setText(f"{round(s * 100)}%"))
        arrow_css = ("QPushButton{background:rgba(22,19,15,.45);color:%s;border:1px solid rgba(246,241,230,.35);border-radius:24px;"
                     "font-size:22px}QPushButton:hover{background:%s;border-color:%s}" % (theme.LIGHT_TEXT, theme.BRASS, theme.BRASS))
        self.prev_b, self.next_b = QPushButton("‹", self), QPushButton("›", self)
        for b, d in ((self.prev_b, -1), (self.next_b, 1)):
            b.setFixedSize(48, 48)
            b.setStyleSheet(arrow_css)
            b.clicked.connect(lambda _=False, d=d: self.go(d))
        # bản đồ nhỏ, bảng thông tin, trình chiếu
        self.mini = MiniMap(self.view, self)
        self.mini.hide()
        self.panel = QLabel(self)
        self.panel.setWordWrap(True)
        self.panel.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.panel.setTextFormat(Qt.RichText)
        self.panel.setStyleSheet("background:rgba(18,15,11,225);color:%s;padding:16px;font-size:13px" % theme.LIGHT_TEXT)
        self.panel.setFixedWidth(300)
        self.panel.setOpenExternalLinks(False)
        self.panel.linkActivated.connect(self._go_person)
        self.panel.hide()
        self.show_timer = QTimer(self)
        self.show_timer.setInterval(4000)
        self.show_timer.timeout.connect(self._slide)
        self.view.zoomChanged.connect(lambda s: self._sync_mini())
        self.view.horizontalScrollBar().valueChanged.connect(lambda _: self.mini.update())
        self.view.verticalScrollBar().valueChanged.connect(lambda _: self.mini.update())
        self.fs = False                   # đang ở chế độ toàn màn hình (ẩn dải ảnh nhỏ, thanh công cụ tự ẩn)
        self.strip = None
        if model is not None and len(items) > 1:
            self.strip = StripView(self)
            self.strip.setModel(model)
            self.strip.setItemDelegate(StripDelegate(self, self.strip))
            self.strip.setFlow(QListView.LeftToRight)
            self.strip.setWrapping(False)
            self.strip.setIconSize(QSize(72, 72))
            self.strip.setFixedHeight(92)
            self.strip.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.strip.setSpacing(4)
            self.strip.setStyleSheet("QListView{background:rgba(0,0,0,.35);border:0}")
            lay.addWidget(self.strip)
        self.hide_t = QTimer(self)
        self.hide_t.setSingleShot(True)
        self.hide_t.setInterval(2600)
        self.hide_t.timeout.connect(self._hide_controls)
        for key, fn in [("Left", lambda: self.go(-1)), ("Right", lambda: self.go(1)), ("Home", lambda: self.goto(0)),
                        ("End", lambda: self.goto(len(self.items) - 1)), ("+", lambda: self.view.zoom(1.25)),
                        ("=", lambda: self.view.zoom(1.25)), ("-", lambda: self.view.zoom(1 / 1.25)), ("0", self.view.fit),
                        ("F", self.view.fit), ("1", self.view.actual), ("F11", self.toggle_fullscreen), ("I", self.toggle_info), ("Esc", self.on_escape)]:
            QShortcut(QKeySequence(key), self, activated=fn)
        if on_index:
            self.indexChanged.connect(on_index)
        self.anim = None
        self.show_current()

    # ---- thanh điều khiển tự ẩn ----
    def _layout_overlays(self):
        self.top.setGeometry(0, 0, self.width(), self.top.height())
        self.foot.setGeometry(0, (self.view.height() or self.height()) - self.foot.height(), self.width(), self.foot.height())
        self.foot.raise_()
        self.mini.move(self.width() - self.mini.width() - 16 - (300 if self.panel.isVisible() else 0), 84)
        self.panel.setGeometry(self.width() - 300, 76, 300, max(120, (self.view.height() or self.height()) - 76))
        self.mini.raise_()
        self.panel.raise_()
        h = self.view.height() or self.height()
        self.prev_b.move(18, (h - 48) // 2)
        self.next_b.move(self.width() - 66, (h - 48) // 2)
        self.top.raise_()
        self.foot.raise_()
        self.prev_b.raise_()
        self.next_b.raise_()

    def strip_click(self, row, on_tick):
        """Bấm vào ảnh nhỏ: ở chấm tròn góc trên trái thì tick (ảnh đầu tiên); khi đã có ảnh được tick thì bấm đâu trên ảnh nhỏ cũng tick / bỏ tick; chưa có thì chỉ chuyển tới ảnh."""
        if self.marks is not None and (on_tick or self.marks):
            self.marks.symmetric_difference_update({row})
            if self.on_marks:
                self.on_marks()
            if row != self.i:
                self.goto(row)
            else:
                self.show_current()
            return
        self.goto(row)

    def _show_controls(self):
        n = len(self.items)
        if self.fs:                      # toàn màn hình: chỉ còn ảnh; thanh công cụ chỉ hiện khi đưa chuột lên góc trên bên phải
            for w in (self.prev_b, self.next_b, self.panel, self.foot):
                w.hide()
            pos = self.mapFromGlobal(QCursor.pos())
            corner = pos.y() <= 80 and pos.x() >= self.width() * 0.5
            self.top.setVisible(corner)
            return
        self.top.show()
        self.foot.show()
        self.prev_b.setVisible(self.i > 0)
        self.next_b.setVisible(self.i < n - 1)

    def _hide_controls(self):
        if not self.fs:
            return
        if self.top.underMouse() or self.prev_b.underMouse() or self.next_b.underMouse():
            self.hide_t.start()
            return
        for w in (self.top, self.prev_b, self.next_b):
            w.hide()

    def eventFilter(self, o, e):
        if e.type() == QEvent.MouseMove and not self._closed:
            self._show_controls()
        return False

    def mouseMoveEvent(self, e):
        self._show_controls()
        super().mouseMoveEvent(e)

    def set_mode(self, mode):
        self.view.set_mode(mode)
        self.zoom_b.setChecked(mode == "zoom")
        self.pan_b.setChecked(mode == "pan")

    def _sync_mini(self):
        self.mini.setVisible(not self.view._fit and not self.view.item.pixmap().isNull())
        self.mini.update()

    def toggle_info(self):
        on = not self.panel.isVisible()
        self.panel.setVisible(on)
        self.info_b.setChecked(on)
        self._fill_info()
        self._layout_overlays()

    def _face_at(self, scene_pos):
        r = self.view.item.boundingRect()
        if r.width() <= 0 or r.height() <= 0:
            return None
        nx, ny = scene_pos.x() / r.width(), scene_pos.y() / r.height()
        best = None
        for f in self.face_list:
            x, y, w, h = f["box"]
            if x <= nx <= x + w and y <= ny <= y + h:
                if best is None or w * h < best["box"][2] * best["box"][3]:      # mặt nhỏ hơn thắng khi chồng nhau
                    best = f
        return best

    def _go_person(self, href):
        """Bấm tên / khuôn mặt của một người: đóng trình xem và mở album ảnh của người đó."""
        if self.link_fn:
            self.link_fn(href)
            self.close()

    def _click_face(self, scene_pos):
        f = self._face_at(scene_pos)
        if f is not None and f.get("pid") is not None and self.link_fn:
            self._go_person(f"person:{f['pid']}")

    def _hover_face(self, scene_pos):
        """Rê chuột vào một khuôn mặt: khung sáng và hiện tên người để dễ nhận dạng, phát hiện sai sót."""
        from PySide6.QtWidgets import QToolTip
        f = self._face_at(scene_pos)
        if f is None:
            self.face_box.setVisible(False)
            self.view.viewport().unsetCursor()
            QToolTip.hideText()
            return
        if f.get("pid") is not None and self.link_fn:
            self.view.viewport().setCursor(Qt.PointingHandCursor)           # bấm vào mặt để tới album của người đó
        r = self.view.item.boundingRect()
        x, y, w, h = f["box"]
        self.face_box.setRect(QRectF(x * r.width(), y * r.height(), w * r.width(), h * r.height()))
        self.face_box.setVisible(True)
        QToolTip.showText(QCursor.pos() + QPoint(14, 18), f["name"] or "Chưa đặt tên", self.view.viewport())

    def _show_menu(self, gpos):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        face = self._face_at(self.view.mapToScene(self.view.viewport().mapFromGlobal(gpos))) if self.face_menu_fn else None
        if face is not None:                                      # chuột phải vào một khuôn mặt: sửa người của đúng mặt đó
            self._build_menu(m, self.face_menu_fn(self.items[self.i], face, self))
            if self.menu_fn:
                m.addSeparator()
        elif not self.menu_fn:
            return
        if self.menu_fn:
            self._build_menu(m, self.menu_fn(self.items[self.i], self))
        if not m.isEmpty():
            m.exec(gpos)

    def _build_menu(self, m, entries):
        def build(menu, entries):
            for name, act in entries:
                if act is None:
                    menu.addSeparator()
                elif isinstance(act, list):
                    build(menu.addMenu(name), act)
                else:
                    menu.addAction(name, lambda a=act: (a(), self._fill_info(), self._load_faces()))
        build(m, entries)

    def _load_faces(self):
        self.face_box.setVisible(False)
        try:
            self.face_list = self.faces_fn(self.items[self.i]) if self.faces_fn else []
        except Exception:
            self.face_list = []

    def _fill_info(self):
        if self.panel.isVisible() and self.info_fn:
            try:
                self.panel.setText(self.info_fn(self.items[self.i]))
            except Exception as e:
                self.panel.setText(f"Không đọc được thông tin: {e}")

    def toggle_fav(self):
        if self.fav_fn:
            self.star_r.set_on(self.fav_fn(self.items[self.i], True))

    def _confirm(self):
        """✓ ở trang ảnh đề xuất: xác nhận ảnh đang xem đúng là của người này rồi sang ảnh kế (hết ảnh thì đóng)."""
        if not self.confirm_fn:
            return
        it = self.items[self.i]
        self.confirm_fn(it)
        if self.i < len(self.items) - 1:
            self.go(1)
        else:
            self.close()

    def _classify(self, key):
        """Dressed / Naked: phân loại ảnh đang xem (không lọc). Trả về True = đã xử lý."""
        if self.cloth:
            self.cloth[1](self.items[self.i], key)
            self.cloth_pill.value = key
            self.cloth_pill._sync()
        return True

    def toggle_play(self):
        if self.show_timer.isActive():
            self.show_timer.stop()
            self.play_b.setIcon(tool_icon("play"))
        else:
            self.show_timer.start()
            self.play_b.setIcon(tool_icon("pause"))

    def _slide(self):
        if self.i >= len(self.items) - 1:
            self.toggle_play()
        else:
            self.go(1)

    def toggle_mode(self):
        self.set_mode("pan" if self.view.mode == "zoom" else "zoom")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Control:                                       # Ctrl (nhấn rồi thả, không kèm phím / cuộn chuột khác): chọn / bỏ chọn ảnh đang xem
            if not e.isAutoRepeat():
                self._ctrl_clean = True
                self.view.wheeled = False
            return
        self._ctrl_clean = False
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.view.space = True
            self.view.viewport().setCursor(Qt.OpenHandCursor)
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Control and not e.isAutoRepeat():
            if self.marks is not None and self._ctrl_clean and not self.view.wheeled:
                self.marks.symmetric_difference_update({self.i})
                if self.on_marks:
                    self.on_marks()
                self.show_current()
            self._ctrl_clean = False
            return
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.view.space = False
            self.view.viewport().unsetCursor()
            return
        super().keyReleaseEvent(e)

    # ---- nền và toàn màn hình ----
    def paintEvent(self, e):
        QPainter(self).fillRect(self.rect(), QColor(12, 10, 8))

    def _cover_parent(self):
        w = self.parent().window() if self.parent() else None
        if w is not None:
            self.setGeometry(QRect(w.mapToGlobal(QPoint(0, 0)), w.size()))

    def toggle_fullscreen(self):
        self.fs = not self.fs
        if self.strip is not None:
            self.strip.setVisible(not self.fs)              # toàn màn hình: ẩn hết, chỉ còn ảnh
        if self.fs:
            self.showFullScreen()
        else:
            self.showNormal()
            self._cover_parent()
        self._layout_overlays()
        self._show_controls()
        if not self.fs:
            for w in (self.top,):
                w.show()

    def on_escape(self):
        if self.fs:
            self.toggle_fullscreen()      # Esc thoát toàn màn hình trước, bấm lần nữa mới đóng
        else:
            self.close()

    def showMaximized(self):
        """Phủ lên cửa sổ chính (có dải ảnh nhỏ phía dưới) với hiệu ứng hiện dần; nút toàn màn hình để xem to hơn."""
        self._cover_parent()
        self.setWindowOpacity(0.0)
        self.show()
        self.anim = QPropertyAnimation(self, b"windowOpacity", self)
        self.anim.setDuration(180)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.start()
        self.activateWindow()
        self.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_overlays()

    def showEvent(self, e):
        super().showEvent(e)
        self._layout_overlays()
        self._show_controls()

    def closeEvent(self, e):
        self.show_timer.stop()
        self._closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(e)

    def done(self, r):
        self._closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
        super().done(r)

    # ---- nạp trước ảnh kế bên để chuyển ảnh tức thì ----
    def _work(self, j):
        if self._closed:
            return
        try:
            img = self.loader(self.items[j])
        except Exception:
            img = None
        if not self._closed:
            try:
                self._got.emit(j, img)
            except RuntimeError:
                pass

    def _on_got(self, j, img):
        self._want.discard(j)
        if img is not None and abs(j - self.i) <= 3:
            self.cache[j] = img
            if self._temp == j == self.i:                   # ảnh đầy đủ về tới: thay cho ảnh nhỏ đang hiện tạm
                self._temp = None
                self.view.show_image(img)
                self.mini.set_pixmap(self.view.item.pixmap())
                self._sync_mini()

    def _prefetch(self):
        d = getattr(self, "_dir", 1)                               # nạp trước 3 ảnh kế tiếp THEO HƯỚNG đang xem, thêm 1 ảnh phía sau
        for j in (self.i + d, self.i + 2 * d, self.i + 3 * d, self.i - d):
            if 0 <= j < len(self.items) and j not in self.cache and j not in self._want:
                self._want.add(j)
                try:
                    self.pool.submit(self._work, j)
                except RuntimeError:
                    return
        for k in [k for k in self.cache if abs(k - self.i) > 3]:
            del self.cache[k]

    # ---- chuyển ảnh ----
    def go(self, d):
        self.goto(self.i + d)

    def goto(self, i):
        i = max(0, min(len(self.items) - 1, i))
        if i != self.i:
            self._dir = 1 if i > self.i else -1
            self.i = i
            self.show_current()

    def show_current(self):
        it = self.items[self.i]
        err = ""
        img = self.cache.get(self.i)
        self._temp = None
        if img is None and self.model is not None and not self._closed:
            try:
                tp = self.model.pixmap(it)                   # có ảnh nhỏ rồi: hiện ngay, nạp ảnh đầy đủ ở nền cho mượt
            except Exception:
                tp = None
            if tp is not None and not tp.isNull():
                self._temp = self.i
                img = tp.toImage()
                if self.i not in self._want:
                    self._want.add(self.i)
                    try:
                        self.pool.submit(self._work, self.i)
                    except RuntimeError:
                        self._temp, img = None, None
        if img is None:
            try:
                img = self.loader(it)
            except Exception as e:
                img = QImage(1, 1, QImage.Format_RGB32)
                err = f"  (không mở được: {e})"
        self.view.show_image(img)
        self._load_faces()
        n = len(self.items)
        name = it.get("cap_title") or (it.get("tip", "").splitlines() or [""])[0]
        mark = "&nbsp;&nbsp;<span style='color:#E5C07B'>✓ ĐÃ CHỌN</span>" if (self.marks is not None and self.i in self.marks) else \
               ("&nbsp;&nbsp;<span style='color:#9a927f'>Ctrl: chọn</span>" if self.marks is not None else "")
        self.cap.setText(f"<b>{name}</b>&nbsp;&nbsp;<span style='color:{theme.BRASS_LIGHT}'>{self.i + 1} / {n}</span>{mark}{err}")
        tip = (it.get("tip", "") or "").splitlines()
        sub = " · ".join(x for x in tip[1:] if x and "/" not in x and "\\" not in x)[:160]         # bỏ dòng đường dẫn: chỉ ngày, kích thước…
        self.foot_txt.setText(f"<b>{name}</b>{mark}{err}<br><span style='color:#A8A190'>{sub}</span>")
        self.cnt.setText(f"{self.i + 1} / {n}")
        if self.strip is not None:
            ix = self.strip.model().index(self.i)
            self.strip.setCurrentIndex(ix)
            self.strip.scrollTo(ix, QAbstractItemView.PositionAtCenter)
            self.strip.viewport().update()
        self.mini.set_pixmap(self.view.item.pixmap())
        self._sync_mini()
        self._fill_info()
        if self.fav_fn:
            self.star_r.set_on(self.fav_fn(it, False))
        if self.cloth:
            g = self.cloth[0](it)
            self.cloth_pill.value = g if g in ("cloth", "nude") else None
            self.cloth_pill._sync()
        self._show_controls()
        self._prefetch()
        if self._first:
            self._first = False          # lần mở đầu: ảnh vừa bấm đã ở đúng chỗ, không cần cuộn thư viện
        else:
            self.indexChanged.emit(self.i)

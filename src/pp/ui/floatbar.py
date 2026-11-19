"""Thanh nút tròn kiểu điện thoại cho các trang lưới ảnh: nút tròn (←, ✕, hình người, ⋯…) ở hai bên, ô Dressed | Naked | All ở giữa."""
import math

from PySide6.QtCore import QSize, Qt, QPointF, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QWidget

from . import theme

BRASS = QColor("#A9793D")


class RoundBtn(QPushButton):
    """Nút tròn nền đen mờ, viền trắng mảnh, biểu tượng vẽ bằng nét. kind: back, close, dots, person, person+, person-, enter, tick, star."""
    D = 44

    def __init__(self, kind, tip="", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.badge = 0
        self.on = False                      # chỉ dùng cho nút sao: đã yêu thích (sao đầy màu vàng)
        self._blink = False
        self._phase = False
        self._hover = False
        self.setFixedSize(self.D, self.D)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("QPushButton{border:none;background:transparent}")
        self._t = QTimer(self)
        self._t.setInterval(650)
        self._t.timeout.connect(self._tick)

    def set_on(self, on):
        self.on = bool(on)
        self.update()

    def set_badge(self, n, blink=False):
        """Số nhỏ màu vàng đồng ở góc; blink=True thì nút nhấp nháy (chỉ dùng cho nút ảnh đề xuất trên PC)."""
        self.badge = int(n)
        self._blink = bool(blink and n)
        if self._blink and not self._t.isActive():
            self._t.start()
        elif not self._blink:
            self._t.stop()
            self._phase = False
        self.update()

    def _tick(self):
        self._phase = not self._phase
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        glow = self._blink and self._phase
        p.setBrush(QColor(169, 121, 61, 110) if glow else QColor(0, 0, 0, 150 if self._hover else 100))
        p.setPen(QPen(QColor(169, 121, 61) if glow else QColor(255, 255, 255, 190), 2.6 if glow else 1.5))
        p.drawEllipse(r)
        c = r.center()
        u = self.D / 44.0
        pen = QPen(QColor("white"), 2.2 * u)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        k = self.kind
        if k == "back":
            path = QPainterPath(QPointF(c.x() + 4 * u, c.y() - 8 * u))
            path.lineTo(c.x() - 6 * u, c.y())
            path.lineTo(c.x() + 4 * u, c.y() + 8 * u)
            p.drawPath(path)
            p.drawLine(QPointF(c.x() - 6 * u, c.y()), QPointF(c.x() + 9 * u, c.y()))
        elif k == "close":
            p.drawLine(QPointF(c.x() - 7 * u, c.y() - 7 * u), QPointF(c.x() + 7 * u, c.y() + 7 * u))
            p.drawLine(QPointF(c.x() + 7 * u, c.y() - 7 * u), QPointF(c.x() - 7 * u, c.y() + 7 * u))
        elif k == "dots":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white"))
            for d in (-9, 0, 9):
                p.drawEllipse(QPointF(c.x() + d * u, c.y()), 2.5 * u, 2.5 * u)
        elif k.startswith("person"):
            dx = -3.5 * u if k in ("person+", "person-") else 0.0
            p.drawEllipse(QPointF(c.x() + dx, c.y() - 5.5 * u), 5.2 * u, 5.2 * u)
            p.drawArc(QRectF(c.x() + dx - 11.5 * u, c.y() + 1 * u, 23 * u, 22 * u), 0, 180 * 16)
            if k == "person+":
                p.drawLine(QPointF(c.x() + 10 * u, c.y() - 7 * u), QPointF(c.x() + 18 * u, c.y() - 7 * u))
                p.drawLine(QPointF(c.x() + 14 * u, c.y() - 11 * u), QPointF(c.x() + 14 * u, c.y() - 3 * u))
            elif k == "person-":
                p.drawLine(QPointF(c.x() + 10 * u, c.y() - 7 * u), QPointF(c.x() + 18 * u, c.y() - 7 * u))
        elif k == "enter":
            path = QPainterPath(QPointF(c.x() + 7 * u, c.y() - 7 * u))
            path.lineTo(c.x() + 7 * u, c.y() + 2 * u)
            path.lineTo(c.x() - 7 * u, c.y() + 2 * u)
            p.drawPath(path)
            path2 = QPainterPath(QPointF(c.x() - 3 * u, c.y() - 3 * u))
            path2.lineTo(c.x() - 7 * u, c.y() + 2 * u)
            path2.lineTo(c.x() - 3 * u, c.y() + 7 * u)
            p.drawPath(path2)
        elif k == "tick":
            path = QPainterPath(QPointF(c.x() - 8 * u, c.y()))
            path.lineTo(c.x() - 2 * u, c.y() + 6 * u)
            path.lineTo(c.x() + 8 * u, c.y() - 6 * u)
            p.drawPath(path)
        elif k == "star":
            draw_fat_star(p, c, 10.5 * u, QColor(255, 208, 90) if self.on else QColor("white"), filled=self.on)
        if self.badge:
            br = 9.5
            bc = QPointF(self.width() - br - 1, br + 1)
            p.setPen(Qt.NoPen)
            p.setBrush(BRASS)
            p.drawEllipse(bc, br, br)
            p.setPen(QColor("white"))
            f = p.font()
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(bc.x() - br, bc.y() - br, 2 * br, 2 * br), Qt.AlignCenter, str(min(self.badge, 99)))
        p.end()


def draw_fat_star(p, c, r, color, filled=True):
    """Ngôi sao mập như điện thoại: cánh trong lớn (0,56), viền bo tròn dày."""
    path = QPainterPath()
    for k in range(10):
        rr = r if k % 2 == 0 else r * 0.56
        a = math.radians(-90 + k * 36)
        pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a) + r * 0.0955)
        if k == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    pen = QPen(color, r * (0.24 if filled else 0.18))
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(color if filled else Qt.NoBrush)
    p.drawPath(path)


class TopBar(QWidget):
    """Hàng trên cùng: nhóm nút trái, phần giữa (đúng giữa trang), nhóm nút phải. Nền trong suốt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(14, 10, 14, 6)
        g.setSpacing(8)
        self.left, self.mid, self.right = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        for lay in (self.left, self.mid, self.right):
            lay.setSpacing(8)
            lay.setContentsMargins(0, 0, 0, 0)
        g.addLayout(self.left, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        g.addLayout(self.mid, 0, 1, Qt.AlignCenter)
        g.addLayout(self.right, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(2, 1)
        self.setFixedHeight(RoundBtn.D + 18)


class TitlePill(QWidget):
    """Viên thuốc nhỏ: ảnh đại diện tròn + tên người (cạnh nút ← ở trang một người)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLabel
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 4, 16, 4)
        h.setSpacing(8)
        self.av = QLabel()
        self.av.setFixedSize(36, 36)
        self.name = QLabel()
        self.name.setStyleSheet("font-size:15px;font-weight:700;background:transparent")
        h.addWidget(self.av)
        h.addWidget(self.name)
        self.setFixedHeight(RoundBtn.D)

    def set_content(self, text, pixmap=None):
        self.name.setText(text)
        if pixmap is not None and not pixmap.isNull():
            self.av.setPixmap(pixmap.scaled(36, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            self.av.show()
        else:
            self.av.hide()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 100))
        p.setPen(QPen(QColor(255, 255, 255, 190), 1.5))
        r = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.end()


class TextPill(QWidget):
    """Ô dài nhiều lựa chọn chữ (ví dụ '2 người | 3 người | 4 người'): ô đang chọn sáng màu vàng đồng."""
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(3, 3, 3, 3)
        self.h.setSpacing(0)
        self.btns, self.cur = [], -1
        self.setFixedHeight(RoundBtn.D)

    def set_items(self, labels, current=0):
        for b in self.btns:
            b.deleteLater()
        self.btns = []
        for i, t in enumerate(labels):
            b = QPushButton(t)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(RoundBtn.D - 6)
            b.setStyleSheet("QPushButton{border:none;border-radius:19px;background:transparent;color:#FFFFFF;font-weight:700;padding:0 14px}"
                            "QPushButton:checked{background:#A9793D}")
            b.clicked.connect(lambda _=False, k=i: self.select(k))
            self.h.addWidget(b)
            self.btns.append(b)
        self.cur = -1
        if labels:
            self.select(min(current, len(labels) - 1), emit=False)

    def select(self, i, emit=True):
        self.cur = i
        for k, b in enumerate(self.btns):
            b.setChecked(k == i)
        if emit:
            self.currentChanged.emit(i)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 140))
        p.setPen(QPen(QColor(255, 255, 255, 150), 1.5))
        r = QRectF(self.rect()).adjusted(1.2, 1.2, -1.2, -1.2)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.end()


class SelBar(TopBar):
    """Thanh nút tròn của trang lưới ảnh. Khi chưa chọn ảnh: [←] [tên] … [ô giữa] … [⋯]. Khi đang chọn: [✕] [thêm vào người] … [loại khỏi người] [⋯].
    `src` là nguồn ảnh (PhotoGrid hoặc GroupedPhotos): cần selCountChanged, sel_count(), clear_sel(), add_to_person(), run_remove(), remove_fn, fill_menu(menu)."""

    def __init__(self, src=None, back=None):
        super().__init__()
        self.src = None
        self.back_fn = back
        self.menu_extra = None
        self.btn_back = RoundBtn("back", "Quay lại")
        self.btn_close = RoundBtn("close", "Bỏ chọn")
        self.btn_add = RoundBtn("person+", "Thêm các ảnh đã chọn vào một người…")
        self.btn_rm = RoundBtn("person-", "Không phải người này: loại các ảnh đã chọn khỏi nhóm")
        self.btn_dots = RoundBtn("dots", "Thêm tùy chọn")
        self.title = TitlePill()
        self.title.hide()
        for w in (self.btn_back, self.btn_close, self.btn_add):
            self.left.addWidget(w)
        self.left.addWidget(self.title)
        self.right.addWidget(self.btn_rm)
        self.right.addWidget(self.btn_dots)
        self.btn_back.clicked.connect(lambda: self.back_fn() if self.back_fn else None)
        self.btn_close.clicked.connect(lambda: self.src and self.src.clear_sel())
        self.btn_add.clicked.connect(lambda: self.src and self.src.add_to_person())
        self.btn_rm.clicked.connect(lambda: self.src and self.src.run_remove())
        self.btn_dots.clicked.connect(self.show_menu)
        self.has_title = False
        if src is not None:
            self.set_src(src)
        else:
            self.update_state(0)

    def set_src(self, src):
        if self.src is not None:
            try:
                self.src.selCountChanged.disconnect(self.update_state)
            except Exception:
                pass
        self.src = src
        src.selCountChanged.connect(self.update_state)
        self.update_state(src.sel_count())

    def set_center(self, w):
        self.mid.addWidget(w)

    def set_back(self, fn):
        self.back_fn = fn
        self.update_state(self.src.sel_count() if self.src else 0)

    def set_title(self, text, pixmap=None):
        self.has_title = True
        self.title.set_content(text, pixmap)
        self.update_state(self.src.sel_count() if self.src else 0)

    def update_state(self, n=0):
        sel = n > 0
        self.btn_close.setVisible(sel)
        self.btn_add.setVisible(sel)
        self.btn_back.setVisible((not sel) and self.back_fn is not None)
        self.title.setVisible((not sel) and self.has_title)
        self.btn_rm.setVisible(sel and bool(getattr(self.src, "remove_fn", None)))

    def show_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        if self.menu_extra:
            self.menu_extra(m)
        if self.src is not None:
            self.src.fill_menu(m)
        from PySide6.QtCore import QPoint
        m.exec(self.btn_dots.mapToGlobal(QPoint(self.btn_dots.width() - m.sizeHint().width(), self.btn_dots.height())))


class ClothPill(QWidget):
    """Ô dài gộp ba nút Dressed | Naked | All (như Android): rộng đúng ba hình tròn, ô đang chọn là hình tròn sáng màu vàng đồng; bấm lại ô đang chọn để về All.
    Cùng giao diện với ChoiceBox (value, changed, set_options, pick) để thay thế trực tiếp."""
    changed = Signal()
    tickClicked = Signal()                      # chế độ third="tick": ô thứ ba là dấu ✓ (trang ảnh đề xuất), bấm để xác nhận
    D = 44

    def __init__(self, tip="", third="all"):
        super().__init__()
        self.value = None
        self.third = third
        self.intercept = None                   # callable(khóa) -> True nếu việc bấm đã được xử lý riêng (ví dụ phân loại ảnh đang chọn)
        self.setToolTip(tip)
        self.setFixedSize(self.D * (2 if third == "none" else 3) + 2, self.D + 2)
        self.btns = {}
        for k, key in enumerate(("cloth", "nude") if third == "none" else ("cloth", "nude", None)):
            b = QPushButton(self)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setGeometry(1 + k * self.D, 1, self.D, self.D)
            b.setStyleSheet(f"QPushButton{{border:none;border-radius:{self.D // 2}px;background:transparent;color:#FFFFFF;font-weight:700;padding:0}}"
                            f"QPushButton:checked{{background:{theme.BRASS}}}")
            if key is None:
                if third == "tick":
                    b.setText("✓")
                    b.setStyleSheet(b.styleSheet() + "QPushButton{font-size:20px}")
                    b.setToolTip("Xác nhận các ảnh đã chọn là của người này")
                else:
                    b.setText("All")
            else:
                b.setIcon(theme.cloth_icon(key, int(self.D * 0.55)))
                b.setIconSize(QSize(int(self.D * 0.55), int(self.D * 0.55)))
                b.setToolTip({"cloth": "Dressed", "nude": "Naked"}[key])
            b.clicked.connect(lambda _=False, kk=key: self._click(kk))
            self.btns[key] = b
        self._sync()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 140))
        p.setPen(QPen(QColor(255, 255, 255, 150), 1.5))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), self.D / 2 + 1, self.D / 2 + 1)
        p.end()

    def _sync(self):
        for key, b in self.btns.items():
            b.setChecked(key == self.value and not (key is None and self.third == "tick"))       # ô ✓ chỉ là nút bấm, không bao giờ ở trạng thái đang chọn

    def _click(self, key):
        if key is None and self.third == "tick":
            self._sync()
            self.tickClicked.emit()
            return
        if key in ("cloth", "nude") and self.intercept and self.intercept(key):
            self._sync()
            return
        if self.third == "tick":
            self.value = key
        else:
            self.value = None if key == self.value else key
        self._sync()
        self.changed.emit()

    def pick(self, key):
        self.value = key if key in ("cloth", "nude") else None
        self._sync()
        self.changed.emit()

    def set_options(self, options, total=None):
        if self.value not in ("cloth", "nude"):
            self.value = None
        self._sync()

"""Giao diện: bảng màu kem ấm, mực đen và đồng của Việt An; phông Be Vietnam Pro. Phẳng, bo góc mềm, thanh bên có biểu tượng."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from .. import paths

# Bảng màu: nền tối (mặc định, đỡ chói mắt) hoặc nền sáng. set_mode() đổi các biến toàn cục rồi qss() dựng lại giao diện.
LIGHT_P = dict(CREAM="#F5F2EC", WHITE="#FFFFFF", INK="#1A1815", INK_SOFT="#6B665C", LINE="#E4DED2", HOVER="#FAF7F1", PRESS="#F1EBDD",
               DIS_BG="#F7F4EE", DIS_FG="#B3AEA0", BAR="#E9E3D6", FIELD="#CFC8B8", MUTED="#6A665D", PANEL="#EFE7D6", CARD="#FFFBF2",
               PLACE="#E6DFCF", RULE="#E5DDCB", CHK_BG="#1A1815", SCROLL="rgba(26,24,21,.22)")
DARK_P = dict(CREAM="#17140F", WHITE="#221E17", INK="#EDE6D6", INK_SOFT="#A8A190", LINE="#3B342A", HOVER="#2B261E", PRESS="#352E24",
              DIS_BG="#1D1913", DIS_FG="#6F6859", BAR="#2E281F", FIELD="#4A4236", MUTED="#A8A190", PANEL="#2A241B", CARD="#262018",
              PLACE="#2E281F", RULE="#3B342A", CHK_BG="#A9793D", SCROLL="rgba(237,230,214,.28)")
CREAM = WHITE = INK = INK_SOFT = LINE = HOVER = PRESS = DIS_BG = DIS_FG = BAR = FIELD = MUTED = PANEL = CARD = PLACE = RULE = CHK_BG = SCROLL = ""
DARK_MODE = True
DARK = "#0D0B08"        # thanh bên luôn tối
DARK2 = "#221D15"
BRASS = "#A9793D"
BRASS_LIGHT = "#D1A468"
TIP_FG = "#F5F2EC"
LIGHT_TEXT = "#F5F2EC"   # chữ sáng trên nền luôn tối (khung xem ảnh, thanh bên)


def set_mode(dark):
    """Chọn nền tối hoặc sáng (chỉ đổi biến; gọi qss() để dựng lại giao diện)."""
    global DARK_MODE
    DARK_MODE = bool(dark)
    g = globals()
    g.update(DARK_P if dark else LIGHT_P)


def _mode_file():
    return paths.app_dir() / "theme.txt"


def load_mode():
    try:
        return _mode_file().read_text().strip() != "light"
    except Exception:
        return True


def save_mode(dark):
    try:
        _mode_file().write_text("dark" if dark else "light")
    except Exception:
        pass


set_mode(True)
RADIO_URL = ""
TICK_URL = ""          # đường dẫn ảnh dấu tick (tạo lúc khởi động)
CHEVRON_URL = ""       # mũi tên xổ xuống của ô chọn


def qss():
    radio = f"image: url('{RADIO_URL}');" if RADIO_URL else ""
    tick = f"image: url('{TICK_URL}');" if TICK_URL else ""
    chev = f"QComboBox::down-arrow {{ image: url('{CHEVRON_URL}'); width: 12px; height: 12px; }}" if CHEVRON_URL else ""
    return f"""
* {{ font-family: "Be Vietnam Pro", "Segoe UI", sans-serif; }}
QWidget {{ background: {CREAM}; color: {INK}; }}
QLabel, QCheckBox, QRadioButton, QSlider, QProgressBar {{ background: transparent; }}
QMainWindow, QDialog, QMessageBox {{ background: {CREAM}; }}
QToolTip {{ background: {DARK}; color: {TIP_FG}; border: 0; border-radius: 6px; padding: 6px 10px; }}

QListWidget#nav {{ background: transparent; color: #A8A190; border: 0; outline: 0; font-size: 12px; font-weight: 600; padding: 0; }}
QListWidget#nav::item {{ padding: 4px 6px; margin: 0; border-radius: 10px; }}
QListWidget#nav::item:hover {{ background: rgba(255,255,255,.06); }}
QListWidget#nav::item:selected {{ background: transparent; color: #D8A863; }}
QListWidget#nav QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QListWidget#nav QScrollBar::handle:vertical {{ background: rgba(255,255,255,.18); border-radius: 3px; }}
QWidget#sidebar {{ background: {DARK}; border-top: 1px solid rgba(255,255,255,.10); }}
QWidget#sidebar QPushButton {{ background: rgba(255,255,255,.06); color: #E8E1D2; border: 0; border-radius: 10px; margin: 8px 6px; padding: 8px 4px; }}
QWidget#sidebar QPushButton:hover {{ background: {BRASS}; color: #FFFFFF; }}

QPushButton {{ background: {WHITE}; color: {INK}; border: 1px solid {LINE}; border-radius: 10px; padding: 8px 16px; font-weight: 500; }}
QPushButton:hover {{ background: {HOVER}; border-color: {BRASS}; color: {INK}; }}
QPushButton:pressed {{ background: {PRESS}; }}
QPushButton:disabled {{ color: {DIS_FG}; border-color: {LINE}; background: {DIS_BG}; }}
QPushButton:checked {{ background: {CHK_BG}; color: #FFFFFF; border-color: {CHK_BG}; }}
QPushButton[primary="true"] {{ background: {BRASS}; color: #FFFFFF; border: 0; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #B98746; color: #FFFFFF; }}
QPushButton[primary="true"]:disabled {{ background: #7A6648; color: #E8E1D2; }}
QPushButton[pill="true"] {{ border: 1px solid {LINE}; border-radius: 17px; padding: 6px 16px; color: {INK_SOFT}; font-weight: 500; background: {WHITE}; }}
QPushButton[pill="true"]:hover {{ border-color: {BRASS}; color: {INK}; }}
QPushButton[pill="true"]:checked {{ background: {CHK_BG}; border-color: {CHK_BG}; color: #FFFFFF; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ background: {WHITE}; border: 1px solid {LINE};
  border-radius: 10px; padding: 8px 12px; selection-background-color: {BRASS}; selection-color: #FFFFFF; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {BRASS}; }}
QComboBox::drop-down {{ border: 0; width: 28px; }}
{chev}
QComboBox QAbstractItemView {{ background: {WHITE}; border: 1px solid {LINE}; border-radius: 8px; padding: 4px;
  selection-background-color: rgba(169,121,61,.18); selection-color: {INK}; outline: 0; }}
QListWidget, QListView, QTableView {{ background: {WHITE}; border: 1px solid {LINE}; border-radius: 12px; padding: 4px; outline: 0; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
QListWidget::item:selected, QListView::item:selected {{ background: rgba(169,121,61,.18); color: {INK}; }}
QScrollArea {{ border: 0; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 12px; margin-top: 12px; padding-top: 10px; }}

QProgressBar {{ border: 0; border-radius: 8px; text-align: center; background: {BAR}; height: 14px; color: {INK}; }}
QProgressBar::chunk {{ background: {BRASS}; border-radius: 8px; }}
QSlider::groove:horizontal {{ height: 5px; background: {LINE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {BRASS}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {WHITE}; border: 2px solid {BRASS}; width: 14px; height: 14px; margin: -7px 0; border-radius: 9px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 20px; height: 20px; }}
QCheckBox::indicator:checked {{ background: {BRASS}; border: 1px solid {BRASS}; border-radius: 6px; {tick} }}
QCheckBox::indicator:unchecked {{ background: {WHITE}; border: 1.5px solid {FIELD}; border-radius: 6px; }}
QCheckBox::indicator:unchecked:hover {{ border-color: {BRASS}; }}
QRadioButton::indicator {{ border-radius: 10px; border: 1.5px solid {FIELD}; background: {WHITE}; }}
QRadioButton::indicator:checked {{ background: {BRASS}; border: 1px solid {BRASS}; border-radius: 10px; {radio} }}
QRadioButton::indicator:unchecked:hover {{ border-color: {BRASS}; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 4px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: {BRASS}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 4px; min-width: 40px; }}
QScrollBar::handle:horizontal:hover {{ background: {BRASS}; }}
QMenu {{ background: {WHITE}; border: 1px solid {LINE}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 8px 24px; border-radius: 6px; }}
QMenu::item:selected {{ background: rgba(169,121,61,.16); color: {INK}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 6px 8px; }}
"""


QSS = qss()


def _pen(color, w=1.7):
    p = QPen(QColor(color), w)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def nav_icon(kind, size=20):
    """Biểu tượng đường nét cho thanh bên (hai màu: thường và khi được chọn)."""
    icon = QIcon()
    for mode, color in ((QIcon.Normal, "#A8A190"), (QIcon.Selected, "#D8A863")):
        pm = QPixmap(size * 2, size * 2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size * 2 / 24.0, size * 2 / 24.0)
        p.setPen(_pen(color))
        p.setBrush(Qt.NoBrush)
        if kind == "library":
            p.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
            p.drawEllipse(QPointF(8.5, 9.5), 1.6, 1.6)
            p.drawPolyline(QPolygonF([QPointF(4, 18), QPointF(10, 12.5), QPointF(14, 16), QPointF(17, 13), QPointF(20, 17)]))
        elif kind == "people":
            p.drawEllipse(QPointF(12, 8), 3.4, 3.4)
            p.drawArc(QRectF(5, 14, 14, 12), 0, 180 * 16)
        elif kind == "combo":
            p.drawEllipse(QPointF(9, 12), 5.5, 5.5)
            p.drawEllipse(QPointF(15, 12), 5.5, 5.5)
        elif kind == "favorites":                              # Favorite: trái tim viền như thanh dưới của điện thoại
            heart = QPainterPath(QPointF(12, 20.2))
            heart.cubicTo(2.6, 13.6, 4.2, 4.6, 12, 9)
            heart.cubicTo(19.8, 4.6, 21.4, 13.6, 12, 20.2)
            p.drawPath(heart)
        elif kind == "similar":
            p.drawRoundedRect(QRectF(3, 6, 12, 12), 2.5, 2.5)
            p.drawRoundedRect(QRectF(9, 10, 12, 10), 2.5, 2.5)
        elif kind == "dups":
            p.drawRoundedRect(QRectF(4, 4, 11, 11), 2.5, 2.5)
            p.drawRoundedRect(QRectF(9, 9, 11, 11), 2.5, 2.5)
        elif kind == "search":
            p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
            p.drawLine(QPointF(15, 15), QPointF(20, 20))
        elif kind == "labels":
            p.drawPolygon(QPolygonF([QPointF(3, 12), QPointF(12, 3), QPointF(21, 3), QPointF(21, 12), QPointF(12, 21)]))
            p.drawEllipse(QPointF(16.5, 7.5), 1.3, 1.3)
        elif kind == "vault":
            p.drawRoundedRect(QRectF(5, 11, 14, 9), 2.5, 2.5)
            p.drawArc(QRectF(8, 4, 8, 10), 0, 180 * 16)
            p.drawPoint(QPointF(12, 15.5))
        elif kind == "ai3d":
            p.drawPolygon(QPolygonF([QPointF(12, 3), QPointF(20, 7.5), QPointF(20, 16.5), QPointF(12, 21), QPointF(4, 16.5), QPointF(4, 7.5)]))
            p.drawPolyline(QPolygonF([QPointF(4, 7.5), QPointF(12, 12), QPointF(20, 7.5)]))
            p.drawLine(QPointF(12, 12), QPointF(12, 21))
        elif kind == "settings":                               # bánh răng
            import math
            p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
            for k in range(8):
                a = math.radians(k * 45)
                p.drawLine(QPointF(12 + 6.4 * math.cos(a), 12 + 6.4 * math.sin(a)), QPointF(12 + 9.4 * math.cos(a), 12 + 9.4 * math.sin(a)))
        elif kind == "account":
            p.drawEllipse(QPointF(12, 12), 9, 9)
            p.drawEllipse(QPointF(12, 10), 3, 3)
            p.drawArc(QRectF(7, 14, 10, 8), 0, 180 * 16)
        p.end()
        icon.addPixmap(pm, mode)
    return icon


def cloth_icon(kind, size=22, color="#FFFFFF"):
    """Biểu tượng Dressed (áo bơi) và Naked (đường cong cơ thể) vẽ bằng nét, dùng trong ô dài Dressed | Naked | All."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size * 2 / 24.0, size * 2 / 24.0)
    p.setPen(_pen(color))
    if kind == "cloth":
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(7.5, 12.5), QPointF(4, 19), QPointF(10, 19.5)]))
        p.drawPolygon(QPolygonF([QPointF(16.5, 12.5), QPointF(20, 19), QPointF(14, 19.5)]))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(12, 5), QPointF(8, 8.5), QPointF(7.5, 12.5)]))
        p.drawPolyline(QPolygonF([QPointF(12, 5), QPointF(16, 8.5), QPointF(16.5, 12.5)]))
    else:
        p.setBrush(Qt.NoBrush)
        left, right = QPainterPath(), QPainterPath()
        left.moveTo(10.5, 4); left.cubicTo(5, 8, 3.5, 15, 10, 21.5)
        right.moveTo(13.5, 4); right.cubicTo(19, 8, 20.5, 15, 14, 21.5)
        p.drawPath(left)
        p.drawPath(right)
    p.end()
    icon = QIcon()
    icon.addPixmap(pm)
    return icon


def chevron_icon(down=True, size=16):
    """Biểu tượng mũi tên ▾ / ▸ vẽ bằng nét (không phụ thuộc phông chữ) cho nút thu gọn / mở rộng."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(_pen(BRASS_LIGHT, 2.0))
    k = size / 16.0
    if down:
        p.drawPolyline(QPolygonF([QPointF(3 * k, 5.5 * k), QPointF(8 * k, 10.5 * k), QPointF(13 * k, 5.5 * k)]))
    else:
        p.drawPolyline(QPolygonF([QPointF(5.5 * k, 3 * k), QPointF(10.5 * k, 8 * k), QPointF(5.5 * k, 13 * k)]))
    p.end()
    return QIcon(pm)


def _make_tick():
    """Ảnh dấu tick trắng trên nền đồng cho ô chọn và mũi tên xổ xuống (QSS không tự vẽ được)."""
    global TICK_URL, CHEVRON_URL, RADIO_URL
    try:
        f = paths.sub("ui") / "radio.png"
        pr = QPixmap(40, 40)
        pr.fill(Qt.transparent)
        q = QPainter(pr)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(Qt.NoPen)
        q.setBrush(QColor("#FFFFFF"))
        q.drawEllipse(QPointF(20, 20), 7, 7)
        q.end()
        pr.save(str(f), "PNG")
        RADIO_URL = str(f).replace("\\", "/")
    except Exception:
        RADIO_URL = ""
    try:
        d = paths.sub("ui")
        pc = QPixmap(24, 24)
        pc.fill(Qt.transparent)
        q = QPainter(pc)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(QPen(QColor(INK_SOFT), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        q.drawPolyline(QPolygonF([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)]))
        q.end()
        pc.save(str(d / "chevron.png"), "PNG")
        CHEVRON_URL = str(d / "chevron.png").replace("\\", "/")
    except Exception:
        CHEVRON_URL = ""
    try:
        d = paths.sub("ui")
        f = d / "tick.png"
        pm = QPixmap(40, 40)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#FFFFFF"), 4.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(10, 21), QPointF(17, 28), QPointF(30, 12)]))
        p.end()
        pm.save(str(f), "PNG")
        TICK_URL = str(f).replace("\\", "/")
    except Exception:
        TICK_URL = ""


def apply(app):
    """Nạp phông đi kèm và áp dụng giao diện cho toàn ứng dụng."""
    for f in ("Light", "Regular", "Medium", "SemiBold", "Bold"):
        p = paths.resource(f"assets/fonts/BeVietnamPro-{f}.ttf")
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))
    set_mode(load_mode())
    app.setStyle("Fusion")
    app.setFont(QFont("Be Vietnam Pro", 10))
    _make_tick()
    app.setStyleSheet(qss())

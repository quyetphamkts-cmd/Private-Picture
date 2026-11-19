"""Các trang của ứng dụng."""
import os
import re
import time

from PySide6.QtCore import QSize, QThread, Qt, QTimer, Signal
import numpy as np
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QScrollArea, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QProgressBar, QPushButton, QRadioButton, QSlider, QStackedWidget,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import scan as _scan_mod
from .. import __version__, autolabel, clothing, cluster, cover, dup, models, sync, updater, vi, zipimg
from ..db import blob_to_vec
from ..scan import Scanner
from .. import paths
from . import theme
from ..secure import SEC, WrongPassword
from .security import RecoveryShowDialog, SecurityDialog
from .common import DotSlider, JustifiedView, QuickLook, ThumbModel, Viewer, card_size_for, load_qimage, on_resize_debounced, make_grid, reveal, selected_items, set_card_size


def img_item(r, extra=None):
    where = "đã mã hóa trong kho" if r["vid"] else (f"trong file nén {os.path.basename(zipimg.archive_of(r['path']))}" if zipimg.is_zip_path(r["path"]) else r["path"])
    nm = r["name"] or os.path.basename(r["path"])
    taken = (r["taken"] or "")[:10]
    d = {"id": r["id"], "path": r["path"], "vid": r["vid"], "name": r["name"], "thumb": r["thumb"], "taken": r["taken"],
         "w": r["w"], "h": r["h"], "cap_title": nm,
         "cap_tag": ("/".join(reversed(taken.split("-"))) if taken else "") + (" · mã hóa" if r["vid"] else ""),
         "tip": f"{nm}\n{where}\n{(r['taken'] or '')[:16]}"}
    if extra:
        d.update(extra)
    return d


def _viewer_info(ctx, it):
    db = ctx.db
    r = db.one("SELECT * FROM images WHERE id=?", (it.get("id"),)) if it.get("id") is not None else None
    if not r:
        return "Không có thông tin."
    rows = [("Tên", r["name"] or os.path.basename(r["path"])), ("Ngày chụp", (r["taken"] or "")[:16] or "không rõ"),
            ("Kích thước", f"{r['w']} × {r['h']} điểm ảnh" if r["w"] else "")]
    if r["vid"]:
        rows.append(("Lưu ở", "kho mã hóa"))
    elif zipimg.is_zip_path(r["path"]):
        rows.append(("Trong file nén", zipimg.archive_of(r["path"])))
    else:
        try:
            rows.append(("Dung lượng", f"{os.path.getsize(r['path']) / 1048576:.2f} MB"))
        except OSError:
            if db.one("SELECT 1 FROM archived WHERE image_id=?", (r["id"],)):
                rows.append(("Ảnh gốc", "đã giải phóng khỏi PC, chỉ còn bản mã hóa trên Drive"))
        rows.append(("Thư mục", os.path.dirname(r["path"])))
    ppl = {}
    for p in db.q("SELECT DISTINCT p.id id, p.name name FROM faces f JOIN persons p ON p.id=f.person_id WHERE f.image_id=?", (r["id"],)):
        ppl[p["id"]] = p["name"] or "Chưa đặt tên"
    for p in db.q("SELECT p.id id, p.name name FROM person_guess g JOIN persons p ON p.id=g.person_id WHERE g.image_id=? AND g.state=2", (r["id"],)):
        ppl.setdefault(p["id"], p["name"] or "Chưa đặt tên")
    import html as _h
    if ppl:     # tên người là liên kết: bấm để mở trang ảnh của người đó
        rows.append(("Người", ("raw", ", ".join(f"<a href='person:{i}' style='color:#E5C07B'>{_h.escape(n)}</a>" for i, n in ppl.items()))))
    labs = [l["name"] for l in db.q("SELECT l.name FROM labels l JOIN label_images li ON li.label_id=l.id WHERE li.image_id=?", (r["id"],))]
    if labs:
        rows.append(("Nhãn", ", ".join(labs)))
    import html
    return "<h3 style='margin-top:0'>Thông tin</h3>" + "".join(
        f"<p style='margin:0 0 10px 0'><span style='color:#C9A66B;font-size:11px'>{k.upper()}</span><br>"
        f"{v[1] if isinstance(v, tuple) else html.escape(str(v))}</p>" for k, v in rows if v)


def _viewer_menu(ctx, it, viewer=None, cloth=False, pid=None):
    """Menu chuột phải khi đang xem ảnh: phân loại (Dressed / Nude), sửa người của ảnh (gỡ / chuyển sang người khác), chuyển tới vị trí trong Tất cả."""
    db = ctx.db
    iid = it.get("id")
    if iid is None:
        return []
    entries = []
    if cloth:                                                 # phân loại (Dressed / Nude) chỉ có khi đang xem ảnh từ trang một người
        entries.append(("Phân loại", [(label, (lambda c=code: (clothing.set_manual(db, [iid], c), ctx.changed.emit())))
                                                 for code, label in clothing.menu_options(db, [iid])]))
    pers = db.q("""SELECT DISTINCT p.id id, p.name name FROM persons p WHERE p.id IN
                   (SELECT person_id FROM faces WHERE image_id=? AND person_id IS NOT NULL
                    UNION SELECT person_id FROM person_guess WHERE image_id=? AND state=2)""", (iid, iid))
    if pers:
        entries.append((None, None))

    for p in pers:
        entries.append((f"Không phải {p['name'] or 'người trong nhóm này'}", (lambda pid=p["id"]: (cluster.remove_from_person(db, pid, [iid]), ctx.changed.emit()))))

    def move():
        others = [q for q in db.persons() if q["name"] and q["id"] not in {p["id"] for p in pers}]
        if not others:
            QMessageBox.information(viewer, "Chuyển sang người khác", "Chưa có người nào đã đặt tên để chuyển sang. Hãy đặt tên người đó trước.")
            return
        labels = [f"{q['name']} · {q['n']} ảnh" for q in others]
        s, ok = QInputDialog.getItem(viewer, "Chuyển sang người khác", "Ảnh này thuộc người:", labels, 0, False)
        if not ok:
            return
        to = others[labels.index(s)]["id"]
        for p in pers:
            cluster.move_to_person(db, [iid], p["id"], to)
            if db.one("SELECT 1 FROM person_guess WHERE image_id=? AND person_id=? AND state=2", (iid, p["id"])):
                db.x("UPDATE person_guess SET state=1 WHERE image_id=? AND person_id=?", (iid, p["id"]))
        if not pers or not db.one("SELECT 1 FROM faces WHERE image_id=? AND person_id=?", (iid, to)):
            db.x("INSERT OR REPLACE INTO person_guess(image_id,person_id,score,state) VALUES(?,?,1.0,2)", (iid, to))
        ctx.changed.emit()
    entries.append(("Chuyển sang người khác…", move))
    entries.append((None, None))
    entries.append(("Chuyển tới vị trí trong All", lambda: ctx.locate.emit(iid)))
    return entries


def _viewer_faces(ctx, it):
    """Các khuôn mặt của ảnh đang xem: khung chuẩn hóa, người (tên nếu có)."""
    iid = it.get("id")
    if iid is None:
        return []
    return [{"box": (f["x"], f["y"], f["w"], f["h"]), "pid": f["person_id"], "name": f["name"], "fid": f["id"], "iid": iid}
            for f in ctx.db.q("""SELECT f.id,f.x,f.y,f.w,f.h,f.person_id,p.name FROM faces f LEFT JOIN persons p ON p.id=f.person_id
                                 WHERE f.image_id=? AND f.x IS NOT NULL""", (iid,))]


def _viewer_face_menu(ctx, it, face, viewer=None):
    """Menu chuột phải TRÊN một khuôn mặt: xem là ai, đặt tên, loại khỏi người, chuyển sang người khác."""
    db = ctx.db
    pid, iid = face["pid"], face["iid"]
    entries = [(f"Mặt này: {face['name'] or 'Chưa đặt tên'}", [])]
    entries = []

    def rename():
        if pid is None:
            return
        cur = (db.one("SELECT name FROM persons WHERE id=?", (pid,)) or {"name": ""})["name"] or ""
        name, ok = QInputDialog.getText(viewer, "Đặt tên", "Tên người này:", text=cur)
        if ok and name.strip():
            cluster.rename_person(db, pid, name)
            ctx.changed.emit()

    def drop():
        cluster.remove_from_person(db, pid, [iid])
        ctx.changed.emit()

    def move():
        others = [q for q in db.persons() if q["name"] and q["id"] != pid]
        if not others:
            QMessageBox.information(viewer, "Chuyển sang người khác", "Chưa có người nào đã đặt tên để chuyển sang. Hãy đặt tên người đó trước.")
            return
        labels = [f"{q['name']} · {q['n']} ảnh" for q in others]
        s, ok = QInputDialog.getItem(viewer, "Chuyển sang người khác", "Mặt này thuộc người:", labels, 0, False)
        if ok:
            cluster.move_to_person(db, [iid], pid, others[labels.index(s)]["id"])
            ctx.changed.emit()
    label = face["name"] or "Chưa đặt tên"
    if pid is not None:
        entries.append((f"Đặt / sửa tên: {label}…", rename))
        entries.append((f"Mặt này không phải {label}", drop))
        entries.append(("Chuyển mặt này sang người khác…", move))
    return entries


def _viewer_fav(ctx, it, toggle):
    db = ctx.db
    iid = it.get("id")
    if iid is None:
        return False
    r = db.one("SELECT id FROM labels WHERE name='Yêu thích'")
    lid = r["id"] if r else None
    has = bool(lid and db.one("SELECT 1 FROM label_images WHERE label_id=? AND image_id=?", (lid, iid)))
    if toggle:
        if lid is None:
            lid = db.x("INSERT INTO labels(name) VALUES('Yêu thích')").lastrowid
        if has:
            db.x("DELETE FROM label_images WHERE label_id=? AND image_id=?", (lid, iid))
        else:
            db.x("INSERT OR IGNORE INTO label_images VALUES(?,?)", (lid, iid))
        has = not has
    return has


def make_loader(ctx):
    def loader(it):
        if it.get("vid"):
            return load_qimage(ctx.vault.read(it["vid"]))
        if zipimg.is_zip_path(it["path"]):
            try:
                return load_qimage(zipimg.read(it["path"], ctx.zip_passwords.get(zipimg.archive_of(it["path"]))))
            except zipimg.PasswordNeeded:
                raise RuntimeError("file nén cần mật khẩu (nhập ở Thư mục và quét)")
            except Exception:                                  # ảnh đã được dọn khỏi tệp nén (chỉ còn bản mã hóa trên Drive)
                from .. import sync
                return load_qimage(sync.read_archived(ctx.db, it["id"]))
        try:
            return load_qimage(it["path"])
        except FileNotFoundError:                   # ảnh gốc đã giải phóng khỏi PC: xem từ bản mã hóa trong thư mục đồng bộ
            from .. import sync
            return load_qimage(sync.read_archived(ctx.db, it["id"]))
    return loader


def _viewer_cloth(ctx, it):
    """Nhóm trang phục hiện tại của ảnh (do người dùng chỉnh tay thì ưu tiên, không thì do máy phân loại): 'cloth', 'nude' hoặc None."""
    r = ctx.db.one("SELECT grp FROM cloth_manual WHERE image_id=?", (it["id"],)) or ctx.db.one("SELECT grp FROM cloth_group WHERE image_id=?", (it["id"],))
    return r["grp"] if r else None


def open_viewer(parent, items, index, ctx, model=None, on_index=None, cloth=False, pid=None, confirm=None, reject=None):
    loader = make_loader(ctx)
    extra = [("Vị trí", "Mở vị trí ảnh này trong All để xem các ảnh gần nó", lambda it: ctx.locate.emit(it["id"]))]
    if pid is not None:                                       # đang xem ảnh trong nhóm của một người: có nút loại khỏi nhóm
        def drop(it):
            if reject is not None:                            # xem từ trang ảnh đề xuất: "không phải người này" = bỏ đề xuất
                reject(it)
                return
            cluster.remove_from_person(ctx.db, pid, [it["id"]])
            ctx.changed.emit()
        extra.insert(0, ("Loại khỏi nhóm", "Ảnh này không đúng người: loại khỏi nhóm, app tự kiểm tra và xếp lại", drop))
    v = Viewer(items, index, loader, parent, model, on_index, lambda it: _viewer_info(ctx, it), lambda it, t: _viewer_fav(ctx, it, t),
               lambda it, vw: _viewer_menu(ctx, it, vw, cloth, pid), lambda href: ctx.open_person.emit(int(href.split(":")[1])), extra,
               lambda it: _viewer_faces(ctx, it), lambda it, face, vw: _viewer_face_menu(ctx, it, face, vw),
               add=lambda it, vw: assign_dialog(ctx, vw, [it["id"]], pid),
               cloth=(lambda it: _viewer_cloth(ctx, it), lambda it, code: (clothing.set_manual(ctx.db, [it["id"]], code), ctx.changed.emit())),
               confirm=confirm)
    v.showMaximized()
    return v


def title(text, sub=""):
    w = QWidget()
    l = QVBoxLayout(w)
    l.setContentsMargins(0, 0, 0, 4)
    a = QLabel(f"<h2 style='margin:0'>{text}</h2>")
    l.addWidget(a)
    if sub:
        b = QLabel(sub)
        b.setWordWrap(True)
        b.setStyleSheet("color:#666")
        l.addWidget(b)
    return w


class Page(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.v = QVBoxLayout(self)

    def refresh(self):
        pass


from .floatbar import ClothPill, RoundBtn, SelBar, TextPill, TitlePill, draw_fat_star


class PhotoGrid(QWidget):
    """Lưới ảnh có chuột phải: xem, mở thư mục, thêm vào nhãn, chuyển vào Kho riêng tư."""

    selCountChanged = Signal(int)

    def __init__(self, ctx, parent_page, text=False, extra_actions=None, viewer_marks=False, bar=True):
        super().__init__()
        self.ctx, self.page, self.extra = ctx, parent_page, extra_actions or []
        self.legacy = False                          # hàng nút chữ cũ chỉ còn dùng khi chưa có thanh nút tròn
        self.remove_fn = next((fn for n, fn in self.extra if n.startswith("Không phải người này")), None)
        self.confirm_fn = next((fn for n, fn in self.extra if n.startswith("Đúng, thêm vào nhóm này")), None)
        self.viewer_marks = viewer_marks            # mở ảnh ra xem: Ctrl đánh dấu chọn, thoát ra các ảnh đã chọn vẫn được đánh dấu trong danh sách
        self.model = ThumbModel()
        self.grid = JustifiedView(self.model)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row_w = QWidget()
        sb = QHBoxLayout(row_w)
        sb.setContentsMargins(0, 2, 8, 2)
        self.sellab = QLabel()
        self.sellab.setStyleSheet("font-weight:600;color:#A9793D")
        b_all, b_none = QPushButton("Chọn tất cả"), QPushButton("Bỏ chọn")
        b_all.clicked.connect(self.grid.select_all)
        b_none.clicked.connect(self.grid.clear_selection)
        self.sim_c = QComboBox()
        for thr, t in ((0.90, "Rất giống"), (0.85, "Giống"), (0.80, "Khá giống")):
            self.sim_c.addItem(t, thr)
        self.sim_c.setCurrentIndex(1)
        self.sim_c.setToolTip("Mức giống tối thiểu khi chọn ảnh tương tự")
        self.lab_b = QPushButton("Nhãn ▾")
        self.lab_b.setToolTip("Thêm, bỏ hoặc đổi nhãn cho các ảnh đã chọn")
        self.lab_b.clicked.connect(self.label_menu)
        b_sim = QPushButton("Chọn ảnh tương tự")
        b_sim.setToolTip("Chọn thêm các ảnh trong danh sách đang hiện mà giống với những ảnh đã chọn (cùng cảnh, góc nhìn, bộ phận)")
        b_sim.clicked.connect(self.select_similar)
        sb.addWidget(self.sellab)
        # quyết định ngay trên cùng danh sách: đúng / không đúng người, phân loại Dressed / Nude (không cần mở chuột phải)
        short = {"Đúng, thêm vào nhóm này": ("✓ Đúng người này", True), "Không phải người này": ("✗ Không phải người này", False),
                 "Không phải người này (gỡ khỏi nhóm)": ("✗ Không phải người này", False)}
        self.action_btns = []
        for name, fn in self.extra:
            if name in short:
                label, primary = short[name]
                bt = QPushButton(label)
                bt.setProperty("primary", primary)
                bt.clicked.connect(lambda _=False, fn=fn: self._run_extra(fn))
                sb.addWidget(bt)
                self.action_btns.append(bt)
        if isinstance(parent_page, PeoplePage):
            for label, code in (("Dressed", "cloth"), ("Naked", "nude")):
                bt = QPushButton(label)
                bt.setToolTip("Phân loại các ảnh đã chọn")
                bt.clicked.connect(lambda _=False, c=code: self._classify(c))
                sb.addWidget(bt)
                self.action_btns.append(bt)
        self.add_b = QPushButton("Thêm vào người…")
        self.add_b.setToolTip("Tìm tên một người (hoặc nhập tên mới) để thêm các ảnh đã chọn vào đúng người đó; có bước xác nhận")
        self.add_b.clicked.connect(self.add_to_person)
        sb.addWidget(self.add_b)
        self.action_btns.append(self.add_b)
        sb.addWidget(self.lab_b)
        sb.addWidget(self.sim_c)
        sb.addWidget(b_sim)
        sb.addWidget(b_all)
        sb.addWidget(b_none)
        sb.addStretch(1)
        self.selbar = QScrollArea()                              # thanh thao tác: cuộn ngang khi cửa sổ hẹp
        self.selbar.setWidget(row_w)
        self.selbar.setWidgetResizable(True)
        self.selbar.setFrameShape(QFrame.NoFrame)
        self.selbar.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.selbar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.selbar.setFixedHeight(48)
        self.selbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)       # (QScrollArea mặc định giãn cả chiều dọc: làm hàng này phình to, chiếm chỗ ảnh)
        self.selbar.setVisible(False)
        self.zoomw = QWidget()
        self.zoomw.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        zr = QHBoxLayout(self.zoomw)
        zr.setContentsMargins(8, 0, 8, 0)
        zr.addWidget(self.selbar, 1000)                          # các nút thao tác trên ảnh đã chọn nằm CÙNG HÀNG với nút Mở rộng / Cỡ ảnh, ngay sau tên người
        zr.addStretch(1)
        self.expand_b = QPushButton("⤢ Mở rộng")
        self.expand_b.setToolTip("Xem và chọn ảnh trong cửa sổ toàn màn hình")
        self.expand_b.clicked.connect(lambda: self.expand())
        zr.addWidget(self.expand_b)
        self.zoom_lab = QLabel("Cỡ ảnh")
        zr.addWidget(self.zoom_lab)
        self.zoom_s = QSlider(Qt.Horizontal)
        self.zoom_s.setRange(90, 560)
        self.zoom_s.setValue(self.grid.row_h)
        self.zoom_s.setFixedWidth(150)
        self.zoom_s.setToolTip("Phóng to / thu nhỏ ảnh trong danh sách (cũng dùng Ctrl + cuộn chuột, hoặc phím + và −). Space: xem nhanh ảnh lớn.")
        self.zoom_s.valueChanged.connect(self.grid.set_row_h)
        self.grid.rowHChanged.connect(lambda h: (self.zoom_s.blockSignals(True), self.zoom_s.setValue(h), self.zoom_s.blockSignals(False)))
        zr.addWidget(self.zoom_s)
        self.zoomw.setVisible(False)
        self.bar = SelBar(self) if bar else None
        if self.bar is not None:
            lay.addWidget(self.bar)
        lay.addWidget(self.zoomw)
        lay.addWidget(self.grid)
        self.grid.selectionChanged.connect(self._sel_changed)
        self.grid.activated.connect(self._open_viewer)
        self.grid.contextRequested.connect(self.menu)
        self.grid.quickLook.connect(lambda i: QuickLook(self.model.items, i, make_loader(self.ctx), self, self.grid).exec())

    def _open_viewer(self, i):
        pg = self.page
        if self.viewer_marks and not self.grid.multi and self.grid.sel <= {i.row()}:
            self.grid.sel.clear()                        # bấm thường chỉ để mở ảnh xem, không coi là đã chọn ảnh đó (chưa chọn ảnh nào thì bấm vùng bất kỳ vẫn mở ảnh)
            self.grid.selectionChanged.emit(0)
            self.grid.viewport().update()
        v = open_viewer(self.window(), self.model.items, i.row(), self.ctx, self.model, None if self.viewer_marks else self.grid.reveal,
                        isinstance(pg, PeoplePage), getattr(pg, "pid", None) if isinstance(pg, PeoplePage) else None,
                        confirm=(lambda it: self.confirm_fn([it])) if self.confirm_fn else None,
                        reject=(lambda it: self.remove_fn([it])) if (self.confirm_fn and self.remove_fn) else None)
        v.finished.connect(lambda _=0, vw=v: self.grid.show_item(vw.i))        # thoát xem ảnh: danh sách cuộn tới ảnh vừa xem, không mất dấu
        if self.viewer_marks:
            v.marks = self.grid.sel
            self.grid.multi = True

            def refresh_sel():
                self.grid.multi = bool(self.grid.sel)
                self.grid.selectionChanged.emit(len(self.grid.sel))
                self.grid.viewport().update()
            v.on_marks = refresh_sel
            v.finished.connect(lambda _=0: refresh_sel())
            v.show_current()
        return v

    def expand(self, title="Xem và chọn ảnh"):
        """Cửa sổ toàn màn hình cho danh sách này: cùng ảnh, cùng thao tác (chọn, nhãn, chuột phải…), tự cập nhật khi dữ liệu đổi."""
        if getattr(self, "_expanded", False):
            return
        self._expanded = True
        dlg = QDialog(self.window())
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        top = QHBoxLayout()
        lab = QLabel()
        lab.setStyleSheet("font-weight:700;color:#A9793D;font-size:14px")
        closeb = QPushButton("Đóng")
        closeb.clicked.connect(dlg.accept)
        top.addWidget(lab, 1)
        top.addWidget(closeb)
        lay.addLayout(top)
        big = PhotoGrid(self.ctx, self.page, extra_actions=self.extra, viewer_marks=self.viewer_marks)
        big.expand_b.setVisible(False)
        big.zoom_s.setValue(max(self.grid.row_h, 260))
        lay.addWidget(big, 1)

        def fill():
            items = list(self.model.items)
            big.set_items(items)
            lab.setText(f"{title}  ·  {len(items)} ảnh")
        fill()
        self.ctx.changed.connect(fill)

        def done(_):
            self._expanded = False
            try:
                self.ctx.changed.disconnect(fill)
            except Exception:
                pass
        dlg.finished.connect(done)
        dlg.showMaximized()
        dlg.exec()

    def select_similar(self, thr=None):
        """Chọn thêm mọi ảnh trong danh sách đang hiện giống các ảnh đã chọn (so nội dung bằng CLIP)."""
        thr = float(thr) if isinstance(thr, (int, float)) and not isinstance(thr, bool) else float(self.sim_c.currentData())
        sel = [s["id"] for s in self.selected()]
        ids, mat = self.ctx.db.clip_matrix()
        pos = {i: k for k, i in enumerate(ids)}
        rows = [pos[i] for i in sel if i in pos]
        if not rows:
            QMessageBox.information(self, "Chọn ảnh tương tự", "Ảnh đã chọn chưa được phân tích nội dung. Hãy quét ảnh trước.")
            return 0
        proto = cluster.prototype(mat[rows])
        sims = cluster._unit(mat.astype(np.float32)) @ proto
        score = {i: float(sims[k]) for i, k in pos.items()}
        pick = [r for r, it in enumerate(self.model.items) if it.get("id") is not None and (score.get(it["id"], 0) >= thr or it["id"] in sel)]
        self.grid.select_rows(pick)
        n = len(pick) - len(sel)
        self.sellab.setText(f"Đã chọn {len(pick)} ảnh (thêm {max(n, 0)} ảnh giống). Bấm chuột phải để thêm vào nhãn.")
        return max(n, 0)

    def _sel_changed(self, n):
        self.selCountChanged.emit(n if self.grid.multi else 0)
        self.sellab.setText(f"Đã chọn {n} ảnh")

    # --- giao diện cho thanh nút tròn (SelBar)
    def sel_count(self):
        return len(self.grid.sel) if self.grid.multi else 0

    def clear_sel(self):
        self.grid.clear_selection()

    def run_remove(self):
        if self.remove_fn:
            self._run_extra(self.remove_fn)

    def classify_selected(self, code):
        """Đang chọn ảnh: bấm Dressed / Naked để phân loại luôn các ảnh đã chọn. Trả về True nếu đã xử lý (có ảnh được chọn)."""
        ids = [x["id"] for x in self.selected()]
        if not ids:
            return False
        clothing.set_manual(self.ctx.db, ids, code)
        self.ctx.changed.emit()
        return True

    def fill_menu(self, m):
        """Các lựa chọn trong nút ⋯: cỡ ảnh, mở rộng, thao tác trên ảnh đã chọn, chọn tất cả."""
        from PySide6.QtWidgets import QWidgetAction
        wa = QWidgetAction(m)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 4, 12, 4)
        h.addWidget(QLabel("Cỡ ảnh"))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(90, 560)
        sl.setValue(self.grid.row_h)
        sl.setFixedWidth(150)
        sl.valueChanged.connect(self.zoom_s.setValue)
        h.addWidget(sl)
        wa.setDefaultWidget(w)
        m.addAction(wa)
        m.addAction("⤢  Mở rộng toàn màn hình", lambda: self.expand())
        sel = self.selected()
        if sel:
            m.addSeparator()
            self._label_actions(m, sel)
            sm = m.addMenu("Chọn ảnh tương tự")
            for thr, t in ((0.90, "Rất giống"), (0.85, "Giống"), (0.80, "Khá giống")):
                sm.addAction(t, lambda thr=thr: self.select_similar(thr))
            if self.confirm_fn:
                m.addAction("✓  Đúng, thêm vào nhóm này", lambda: self._run_extra(self.confirm_fn))
        m.addSeparator()
        m.addAction("Chọn tất cả", self.grid.select_all)
        m.addAction("Bỏ chọn", self.grid.clear_selection)

    def _run_extra(self, fn):
        sel = self.selected()
        if sel:
            fn(sel)

    def add_to_person(self):
        ids = [x["id"] for x in self.selected()]
        if ids:
            pg = self.page
            assign_dialog(self.ctx, self, ids, getattr(pg, "pid", None) if isinstance(pg, PeoplePage) else None)

    def _classify(self, code):
        ids = [x["id"] for x in self.selected()]
        if ids:
            clothing.set_manual(self.ctx.db, ids, code)
            self.ctx.changed.emit()

    def set_items(self, items):
        self.model.set_items(items)

    def selected(self):
        return [i for i in selected_items(self.grid) if i.get("id") is not None]

    def _label_actions(self, m, sel):
        """Các thao tác nhãn cho ảnh đang chọn: thêm, bỏ, đổi."""
        ids = [s["id"] for s in sel]
        m.addAction("Gắn nhãn", lambda: add_to_label(self.ctx, self, ids))
        have = labels_of(self.ctx.db, ids)
        if have:
            sub = m.addMenu("Bỏ gắn nhãn")
            for lid, name, n in have:
                sub.addAction(f"{name}  ({n} ảnh)", lambda lid=lid: unlabel(self.ctx, ids, lid))
            m.addAction("Đổi nhãn…", lambda: change_label(self.ctx, self, ids, have))

    def label_menu(self):
        sel = self.selected()
        if not sel:
            return
        m = QMenu(self)
        self._label_actions(m, sel)
        m.exec(self.lab_b.mapToGlobal(self.lab_b.rect().bottomLeft()))

    def menu(self, pos):
        sel = self.selected()
        if not sel:
            return
        m = QMenu(self)
        self._label_actions(m, sel)
        m.addAction("Thêm vào người…", self.add_to_person)
        m.addAction("Chọn ảnh tương tự", self.select_similar)
        if len(sel) == 1 and not isinstance(self.page, LibraryPage):
            m.addAction("Chuyển tới vị trí trong All", lambda: self.ctx.locate.emit(sel[0]["id"]))
        ids_sel = [x["id"] for x in sel]
        cm = m.addMenu("Phân loại") if isinstance(self.page, PeoplePage) else None      # chỉ trong trang từng người

        def classify(grp):
            clothing.set_manual(self.ctx.db, ids_sel, grp)
            self.ctx.changed.emit()
        if cm is not None:
            for code, label in clothing.menu_options(self.ctx.db, ids_sel):      # ảnh đang ở nhóm nào thì không hiện lại nhóm đó
                cm.addAction(label, lambda c=code: classify(c))
            if any(self.ctx.db.one("SELECT 1 FROM cloth_manual WHERE image_id=?", (i,)) for i in ids_sel):
                cm.addAction("Để máy tự phân loại lại", lambda: (clothing.clear_manual(self.ctx.db, ids_sel), self.ctx.changed.emit()))
        plain = [x for x in sel if not x.get("vid")]
        enc = [x for x in sel if x.get("vid")]
        if plain:
            m.addAction("Mở thư mục chứa ảnh" if not zipimg.is_zip_path(plain[0]["path"]) else "Mở thư mục chứa file nén",
                        lambda: reveal(zipimg.archive_of(plain[0]["path"])))
            loose = [x for x in plain if not zipimg.is_zip_path(x["path"])]
            if self.ctx.encrypted and loose:
                m.addAction("Mã hóa và chuyển vào kho…", lambda: move_to_vault(self.ctx, self, loose))
        arch = [x["id"] for x in sel if self.ctx.db.one("SELECT 1 FROM archived WHERE image_id=?", (x["id"],))]
        if arch:
            m.addAction("Khôi phục ảnh gốc từ Drive…", lambda: restore_archived(self.ctx, self, arch))
        if enc:
            m.addAction("Xuất ảnh giải mã ra thư mục…", lambda: export_from_vault(self.ctx, self, enc))
            m.addAction("Xóa khỏi kho…", lambda: delete_from_vault(self.ctx, self, enc))
        for name, fn in self.extra:
            m.addSeparator()
            m.addAction(name, lambda fn=fn: fn(sel))
        m.exec(self.grid.viewport().mapToGlobal(pos))


def restore_archived(ctx, parent, ids):
    """Khôi phục ảnh gốc từ bản mã hóa trên Drive: về đúng vị trí cũ hoặc vào thư mục khác."""
    from .. import sync
    box = QMessageBox(parent)
    box.setWindowTitle("Khôi phục ảnh gốc")
    box.setText(f"Khôi phục {len(ids)} ảnh gốc từ bản mã hóa trên Drive?")
    box.setInformativeText("Ảnh được giải mã đúng từng byte, chất lượng giống hệt ảnh gốc.")
    here = box.addButton("Về vị trí cũ", QMessageBox.AcceptRole)
    other = box.addButton("Chọn thư mục khác…", QMessageBox.ActionRole)
    box.addButton("Hủy", QMessageBox.RejectRole)
    box.exec()
    b = box.clickedButton()
    if b is not here and b is not other:
        return
    out = None
    if b is other:
        out = QFileDialog.getExistingDirectory(parent, "Thư mục lưu ảnh gốc")
        if not out:
            return
    n, errs = sync.restore(ctx.db, ids, out)
    ctx.changed.emit()
    QMessageBox.information(parent, "Khôi phục", f"Đã khôi phục {n} ảnh." + (f"\nLỗi {len(errs)} ảnh:\n" + "\n".join(errs[:4]) if errs else ""))


def labels_of(db, ids):
    """[(id nhãn, tên, số ảnh trong lựa chọn có nhãn đó)] cho các ảnh đang chọn."""
    if not ids:
        return []
    qs = ",".join("?" * len(ids))
    return [(r["id"], r["name"], r["n"]) for r in db.q(
        f"""SELECT l.id,l.name,COUNT(*) n FROM labels l JOIN label_images li ON li.label_id=l.id
            WHERE li.image_id IN ({qs}) GROUP BY l.id ORDER BY l.name""", ids)]


def unlabel(ctx, ids, lid):
    from .. import autolabel
    autolabel.reject(ctx.db, lid, ids)
    qs = ",".join("?" * len(ids))
    ctx.db.x(f"DELETE FROM label_images WHERE label_id=? AND image_id IN ({qs})", [lid, *ids])
    ctx.changed.emit()


def change_label(ctx, parent, ids, have):
    """Chuyển các ảnh đang chọn từ nhãn này sang nhãn khác (có sẵn hoặc gõ tên mới)."""
    db = ctx.db
    if len(have) == 1:
        old = have[0][0]
    else:
        names = [f"{n}  ({c} ảnh)" for _, n, c in have]
        s, ok = QInputDialog.getItem(parent, "Đổi nhãn", "Đổi từ nhãn:", names, 0, False)
        if not ok:
            return
        old = have[names.index(s)][0]
    others = [r["name"] for r in db.labels() if r["id"] != old]
    name, ok = QInputDialog.getItem(parent, "Đổi nhãn", "Sang nhãn (chọn sẵn có hoặc gõ tên mới):", others, 0, True)
    name = name.strip()
    if not ok or not name:
        return
    r = db.one("SELECT id FROM labels WHERE name=?", (name,))
    new = r["id"] if r else db.x("INSERT INTO labels(name) VALUES(?)", (name,)).lastrowid
    if new == old:
        return
    qs = ",".join("?" * len(ids))
    from .. import autolabel
    autolabel.reject(db, old, ids)
    for (iid,) in [(x["image_id"],) for x in db.q(f"SELECT image_id FROM label_images WHERE label_id=? AND image_id IN ({qs})", [old, *ids])]:
        db.c.execute("INSERT OR IGNORE INTO label_images VALUES(?,?)", (new, iid))
    db.c.execute(f"DELETE FROM label_images WHERE label_id=? AND image_id IN ({qs})", [old, *ids])
    db.commit()
    ctx.changed.emit()


def add_to_label(ctx, parent, ids):
    db = ctx.db
    names = [r["name"] for r in db.labels()]
    name, ok = QInputDialog.getItem(parent, "Thêm vào nhãn", "Chọn nhãn có sẵn hoặc gõ tên nhãn mới:", names, 0, True)
    name = name.strip()
    if not ok or not name:
        return
    r = db.one("SELECT id FROM labels WHERE name=?", (name,))
    lid = r["id"] if r else db.x("INSERT INTO labels(name) VALUES(?)", (name,)).lastrowid
    for i in ids:
        db.c.execute("INSERT OR IGNORE INTO label_images VALUES(?,?)", (lid, i))
    db.commit()
    ctx.changed.emit()


def move_to_vault(ctx, parent, sel):
    v = ctx.vault
    if not v.unlocked():
        QMessageBox.information(parent, "Kho mã hóa", "Hãy mở khóa (hoặc tạo) Kho riêng tư trước, rồi thử lại.")
        ctx.goto.emit("vault")
        return
    box = QMessageBox(parent)
    box.setWindowTitle("Mã hóa và chuyển vào kho")
    box.setText(f"Mã hóa {len(sel)} ảnh vào kho.\n\nẢnh gốc có thể bị XÓA VĨNH VIỄN khỏi máy (không vào Thùng rác). "
                "Quên mật khẩu thì không lấy lại được ảnh.")
    b1 = box.addButton("Mã hóa và xóa ảnh gốc", QMessageBox.DestructiveRole)
    b2 = box.addButton("Chỉ mã hóa, giữ ảnh gốc", QMessageBox.AcceptRole)
    box.addButton("Hủy", QMessageBox.RejectRole)
    box.exec()
    c = box.clickedButton()
    if c not in (b1, b2):
        return
    try:
        n = ctx.move_to_vault(sel, delete_original=(c is b1))
    except Exception as e:
        QMessageBox.warning(parent, "Lỗi", str(e))
        return
    QMessageBox.information(parent, "Xong", f"Đã chuyển {n} ảnh vào kho.")


def export_from_vault(ctx, parent, items):
    d = QFileDialog.getExistingDirectory(parent, "Xuất ảnh giải mã tới thư mục")
    if not d:
        return
    n = 0
    for it in items:
        name = it.get("name") or (it["vid"] + ".jpg")
        dest = os.path.join(d, name)
        k = 1
        while os.path.exists(dest):
            base, ext = os.path.splitext(name)
            dest = os.path.join(d, f"{base} ({k}){ext}")
            k += 1
        ctx.vault.export(it["vid"], dest)
        n += 1
    QMessageBox.information(parent, "Xong", f"Đã xuất {n} ảnh (không còn mã hóa) vào thư mục đã chọn.")


def delete_from_vault(ctx, parent, items):
    if QMessageBox.question(parent, "Xóa khỏi kho", f"Xóa {len(items)} ảnh khỏi kho? Không thể khôi phục.") == QMessageBox.Yes:
        ctx.delete_from_vault(items)


# ---------------------------------------------------------------- Thư viện
class ChoiceBox(QComboBox):
    """Ô chọn xổ xuống gọn thay cho hàng nút: cùng giao diện lập trình với PillRow (set_options, value, changed)."""
    changed = Signal()

    def __init__(self, tip=""):
        super().__init__()
        self.value = None
        self.setToolTip(tip)
        self.setMinimumWidth(190)
        self.currentIndexChanged.connect(self._picked)

    def _picked(self, _):
        self.value = self.currentData()
        self.changed.emit()

    def pick(self, key):
        i = self.findData(key)
        if i >= 0:
            self.setCurrentIndex(i)

    def set_options(self, options, total=None):
        keys = [k for k, _ in options]
        if self.value not in keys:
            self.value = None
        self.blockSignals(True)
        self.clear()
        self.addItem("Tất cả" if total is None else f"Tất cả  ({total})", None)
        for k, text in options:
            self.addItem(text, k)
        self.setCurrentIndex(max(0, self.findData(self.value)))
        self.blockSignals(False)


class OverlayHost(QWidget):
    """Trang có nút nổi cố định ở giữa mép dưới (nút hình người báo ảnh đề xuất)."""

    def __init__(self):
        super().__init__()
        self._floaters = []

    def add_bottom_center(self, w):
        w.setParent(self)
        self._floaters.append(w)
        w.raise_()
        self._place()

    def _place(self):
        for w in self._floaters:
            w.move((self.width() - w.width()) // 2, self.height() - w.height() - 18)
            w.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()


class PillRow(QWidget):
    """Một hàng bộ lọc dạng viên thuốc (chọn một giá trị hoặc “Tất cả”)."""
    changed = Signal()

    def __init__(self, caption):
        super().__init__()
        self.value = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(caption.upper())
        lab.setStyleSheet("color:#A9793D;font-size:11px;font-weight:700;letter-spacing:1px")
        lab.setFixedWidth(64)
        outer.addWidget(lab)
        self.inner = QWidget()
        self.il = QHBoxLayout(self.inner)
        self.il.setContentsMargins(0, 0, 0, 0)
        self.il.setSpacing(8)
        self.il.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.inner)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setFixedHeight(40)
        self.inner.setObjectName("pillInner")
        self.inner.setStyleSheet("QWidget#pillInner{background:transparent}")
        sc.viewport().setObjectName("pillViewport")
        sc.viewport().setStyleSheet("QWidget#pillViewport{background:transparent}")
        outer.addWidget(sc, 1)
        self.grp = QButtonGroup(self)
        self.grp.setExclusive(True)

    def set_options(self, options, total=None):
        """options: [(khóa, nhãn)]. Giữ lựa chọn hiện tại nếu còn."""
        keys = [k for k, _ in options]
        if self.value not in keys:
            self.value = None
        for b in list(self.grp.buttons()):
            self.grp.removeButton(b)
            self.il.removeWidget(b)
            b.hide()
            b.setParent(None)
            b.deleteLater()
        for k, text in [(None, "Tất cả" if total is None else f"Tất cả  ({total})")] + list(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("pill", True)
            b.setChecked(k == self.value)
            b.clicked.connect(lambda _=False, k=k: self.pick(k))
            self.grp.addButton(b)
            self.il.insertWidget(self.il.count() - 1, b)
        self.setVisible(bool(options))

    def pick(self, k):
        if k != self.value:
            self.value = k
            self.changed.emit()


class FilterSlot:
    """Một kiểu phân loại trong FilterBar (giữ các giá trị lọc và lựa chọn hiện tại)."""

    def __init__(self, bar, key, label):
        self.bar, self.key, self.label = bar, key, label
        self.value, self.options, self.total = None, [], None

    def set_options(self, options, total=None):
        self.options, self.total = list(options), total
        if self.value not in [k for k, _ in self.options]:
            self.value = None
        self.bar._sync()

    def pick(self, k):
        self.bar._pick(self, k)

    def isVisible(self):
        return bool(self.options)


class FilterBar(QWidget):
    """Thanh lọc gọn gồm hai ô chọn: kiểu phân loại (Tất cả, Năm, Người, Nhãn, Trang phục…) và giá trị của kiểu đó (kèm số ảnh)."""
    changed = Signal()

    def __init__(self, kinds):
        super().__init__()
        self.slots = {k: FilterSlot(self, k, label) for k, label in kinds}
        self.active = None
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        lab = QLabel("PHÂN LOẠI")
        lab.setStyleSheet("color:#A9793D;font-size:11px;font-weight:700;letter-spacing:1px")
        self.kind_c = QComboBox()
        self.val_c = QComboBox()
        self.kind_c.setMinimumWidth(170)
        self.val_c.setMinimumWidth(260)
        self.val_c.setMaxVisibleItems(18)
        self.clear_b = QPushButton("Bỏ lọc")
        self.clear_b.clicked.connect(lambda: self._pick(None, None))
        h.addWidget(lab)
        h.addWidget(self.kind_c)
        h.addWidget(self.val_c)
        h.addWidget(self.clear_b)
        h.addStretch(1)
        self.kind_c.currentIndexChanged.connect(self._kind_changed)
        self.val_c.currentIndexChanged.connect(self._val_changed)
        self._sync()

    def _sync(self):
        """Dựng lại hai ô chọn theo dữ liệu hiện có (không phát tín hiệu changed)."""
        self.kind_c.blockSignals(True)
        self.val_c.blockSignals(True)
        self.kind_c.clear()
        self.kind_c.addItem("Tất cả", None)
        for s in self.slots.values():
            if s.options:
                self.kind_c.addItem(s.label, s.key)
        if self.active is not None and not self.slots[self.active].options:
            self.active = None
        i = self.kind_c.findData(self.active)
        self.kind_c.setCurrentIndex(max(0, i))
        self.val_c.clear()
        if self.active is None:
            self.val_c.addItem("—", None)
            self.val_c.setEnabled(False)
        else:
            s = self.slots[self.active]
            self.val_c.setEnabled(True)
            self.val_c.addItem("Tất cả" if s.total is None else f"Tất cả  ({s.total})", None)
            for k, t in s.options:
                self.val_c.addItem(t, k)
            self.val_c.setCurrentIndex(max(0, self.val_c.findData(s.value)))
        self.clear_b.setEnabled(self.active is not None and self.slots[self.active].value is not None)
        self.kind_c.blockSignals(False)
        self.val_c.blockSignals(False)

    def _pick(self, slot, value):
        for s in self.slots.values():          # mỗi lần chỉ một kiểu phân loại
            s.value = None
        self.active = slot.key if slot is not None else None
        if slot is not None:
            slot.value = value
        self._sync()
        self.changed.emit()

    def _kind_changed(self, _):
        key = self.kind_c.currentData()
        for s in self.slots.values():
            s.value = None
        self.active = key
        self._sync()
        self.changed.emit()

    def _val_changed(self, _):
        if self.active is not None:
            self.slots[self.active].value = self.val_c.currentData()
            self._sync()
            self.changed.emit()


class LibraryPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        # một thanh gọn: chọn KIỂU phân loại (Năm, Người, Nhãn, Trang phục) rồi chọn giá trị, thay cho bốn hàng nút xếp chồng
        self.fbar = FilterBar([("y", "Năm"), ("p", "Người"), ("l", "Nhãn")])
        self.rows = self.fbar.slots
        self.fbar.changed.connect(self.refresh)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Lọc theo tên tệp, thư mục hoặc ngày (ví dụ 2024-05)…")
        self.q.textChanged.connect(self.refresh)
        self.count = QLabel()
        self.order_c = QComboBox()                              # xếp theo thời gian chụp
        self.order_c.addItem("Mới nhất trước", "new")
        self.order_c.addItem("Cũ nhất trước", "old")
        self.order_c.setToolTip("Sắp xếp theo thời gian chụp (ảnh không rõ ngày nằm cuối)")
        self.order_c.currentIndexChanged.connect(lambda _: self.refresh())
        self.show_dup = QCheckBox("Hiện cả ảnh trùng")
        self.show_dup.setToolTip("Mặc định các bản trùng lặp bị ẩn, chỉ hiện bản tốt nhất. Xem ở mục Ảnh trùng lặp.")
        self.show_dup.toggled.connect(self.refresh)
        self.hide_lab = QCheckBox("Ẩn ảnh đã gắn nhãn")
        self.hide_lab.setToolTip("Chỉ hiện ảnh chưa có nhãn nào, để dễ lọc và gắn nhãn tiếp")
        self.hide_lab.toggled.connect(self.refresh)
        self.cloth = ClothPill("Lọc ảnh: Dressed / Naked / All")
        self.cloth.changed.connect(self.refresh)
        self.grid = PhotoGrid(ctx, self)
        self.cloth.intercept = lambda key: self.grid.classify_selected(key)       # đang chọn ảnh: Dressed / Naked phân loại luôn các ảnh đã chọn
        self.grid.bar.set_center(self.cloth)
        self.panel = QWidget()                                   # bộ lọc và tìm kiếm: mặc định ẩn cho gọn, mở trong nút ⋯
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(14, 0, 14, 4)
        pl.addWidget(self.fbar)
        bar = QHBoxLayout()
        bar.addWidget(self.q, 1)
        bar.addWidget(self.order_c)
        bar.addWidget(self.show_dup)
        bar.addWidget(self.hide_lab)
        bar.addWidget(self.count)
        pl.addLayout(bar)
        self.panel.setVisible(False)
        self.grid.layout().insertWidget(1, self.panel)
        self.grid.bar.menu_extra = lambda m: (m.addAction("Bộ lọc và tìm kiếm…", lambda: self.panel.setVisible(not self.panel.isVisible())), m.addSeparator())
        self.v.addWidget(self.grid, 1)
        self.v.setContentsMargins(0, 0, 0, 0)

    def show_image(self, iid):
        """Bỏ mọi bộ lọc rồi cuộn tới ảnh `iid` và chọn nó."""
        self.fbar._pick(None, None)
        for w, on in ((self.show_dup, self.show_dup.isChecked() or self._is_dup_hidden(iid)), (self.hide_lab, False)):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)
        self.q.blockSignals(True)
        self.q.setText("")
        self.q.blockSignals(False)
        self.refresh()
        for k, it in enumerate(self.grid.model.items):
            if it.get("id") == iid:
                self.grid.grid.reveal(k)
                self.grid.grid.setFocus()
                return

    def _is_dup_hidden(self, iid):
        return iid in dup.hidden_ids(self.ctx.db)

    def refresh(self):
        db = self.ctx.db
        order = "taken IS NULL, taken ASC, id ASC" if self.order_c.currentData() == "old" else "taken IS NULL, taken DESC, id DESC"
        rows = [r for r in db.images(order) if r["thumb"]]
        if getattr(self, "fav_only", False):                       # tab Favorite: chỉ ảnh có nhãn "Yêu thích"
            lab = db.one("SELECT id FROM labels WHERE name='Yêu thích'")
            starred = set(db.label_ids(lab["id"])) if lab else set()
            rows = [r for r in rows if r["id"] in starred]
        dup_n = 0
        if not self.show_dup.isChecked():
            hid = dup.hidden_ids(db)
            dup_n = sum(1 for r in rows if r["id"] in hid)
            rows = [r for r in rows if r["id"] not in hid]
        years = {}
        for r in rows:
            if r["taken"]:
                years[r["taken"][:4]] = years.get(r["taken"][:4], 0) + 1
        tot = len(rows)
        self.rows["y"].set_options([(y, f"{y}  ({n})") for y, n in sorted(years.items(), reverse=True)], tot)
        self.rows["p"].set_options([(p["id"], f"{p['name'] or 'Chưa đặt tên'}  ({p['n']})") for p in db.persons()[:300]], tot)
        self.rows["l"].set_options([(l["id"], f"{l['name']}  ({l['n']})") for l in db.labels()], tot)
        y, p, l = (self.rows[k].value for k in ("y", "p", "l"))
        if y:
            rows = [r for r in rows if (r["taken"] or "")[:4] == y]
        if p is not None:
            ids = {r["id"] for r in db.person_images(p)}
            rows = [r for r in rows if r["id"] in ids]
        if l is not None:
            ids = set(db.label_ids(l))
            rows = [r for r in rows if r["id"] in ids]
        if self.cloth.value:
            keep = clothing.ids_in_group(db, self.cloth.value)
            rows = [r for r in rows if r["id"] in keep]
        t = self.q.text().strip().lower()
        if t:
            rows = [r for r in rows if t in (r["name"] or r["path"]).lower() or t in r["path"].lower() or t in (r["taken"] or "")]
        hidden = 0
        if self.hide_lab.isChecked():
            labeled = {x["image_id"] for x in db.q("SELECT DISTINCT image_id FROM label_images")}
            n0 = len(rows)
            rows = [r for r in rows if r["id"] not in labeled]
            hidden = n0 - len(rows)
        self.count.setText(f"{len(rows)} ảnh" + (f" (ẩn {hidden} ảnh đã có nhãn)" if hidden else "") + (f" (ẩn {dup_n} ảnh trùng)" if dup_n else ""))
        who = {}                                              # tên người của từng ảnh: hiện ở chú thích và chú giải để biết ảnh gần đó của ai
        for r in db.q("""SELECT x.image_id i, p.name n FROM (SELECT image_id, person_id FROM faces WHERE person_id IS NOT NULL
                         UNION SELECT image_id, person_id FROM person_guess WHERE state=2) x JOIN persons p ON p.id=x.person_id
                         WHERE p.name IS NOT NULL"""):
            who.setdefault(r["i"], []).append(r["n"])
        items = []
        for r in rows:
            it = img_item(r)
            names = sorted(set(who.get(r["id"], [])))
            if names:
                it["cap_tag"] = (it["cap_tag"] + " · " if it["cap_tag"] else "") + ", ".join(names)
                it["tip"] += "\nNgười: " + ", ".join(names)
            items.append(it)
        self.grid.set_items(items)


# ---------------------------------------------------------------- Người
class MergeSuggestDialog(QDialog):
    """Các cặp nhóm có thể là cùng một người, xếp cạnh nhau để đối chiếu: bấm Gộp hoặc Khác người."""

    def __init__(self, ctx, parent=None, focus=None):
        super().__init__(parent)
        self.ctx, self.focus = ctx, focus
        self.setWindowTitle("Gợi ý gộp người")
        self.resize(900, 640)
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Có thể là cùng một người</h2>Mỗi hàng là hai nhóm có khuôn mặt giống nhau. Bấm <b>Gộp</b> nếu đúng là một người "
                           "(giữ nhóm đã có tên, hoặc nhóm nhiều ảnh hơn); bấm <b>Khác người</b> để không đề xuất lại."))
        self.sc = QScrollArea()
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QScrollArea.NoFrame)
        self.body = QWidget()
        self.bl = QVBoxLayout(self.body)
        self.sc.setWidget(self.body)
        l.addWidget(self.sc, 1)
        foot = QHBoxLayout()
        self.all_b = QPushButton("Gộp tất cả gợi ý chắc chắn")
        self.all_b.clicked.connect(self.merge_strong)
        close = QPushButton("Đóng")
        close.clicked.connect(self.accept)
        foot.addWidget(self.all_b)
        foot.addStretch(1)
        foot.addWidget(close)
        l.addLayout(foot)
        self.reload()

    def _cover(self, pid):
        db = self.ctx.db
        r = db.one("SELECT thumb FROM faces WHERE person_id=? ORDER BY locked DESC, score*px DESC LIMIT 1", (pid,))
        pm = QPixmap()
        if r and r["thumb"]:
            try:
                pm.loadFromData(SEC.read_file(r["thumb"]))
            except Exception:
                pass
        n = db.one("SELECT COUNT(DISTINCT image_id) n FROM faces WHERE person_id=?", (pid,))["n"]
        name = db.one("SELECT name FROM persons WHERE id=?", (pid,))["name"]
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        im = QLabel()
        im.setAlignment(Qt.AlignCenter)
        im.setFixedSize(150, 150)
        if not pm.isNull():
            im.setPixmap(pm.scaled(146, 146, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        t = QLabel(f"<b>{name or 'Chưa đặt tên'}</b><br>{n} ảnh")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(im)
        v.addWidget(t)
        return box

    def reload(self):
        while self.bl.count():
            it = self.bl.takeAt(0)
            if it.widget() is not None:
                it.widget().setParent(None)
                it.widget().deleteLater()
        self.sug = [d for d in cluster.suggest_merges(self.ctx.db) if self.focus is None or self.focus in (d["a"], d["b"])]
        if not self.sug:
            self.bl.addWidget(QLabel("Không còn gợi ý nào."))
        for d in self.sug[:60]:
            row = QFrame()
            row.setStyleSheet(f"QFrame{{border:1px solid {theme.RULE};border-radius:8px;background:{theme.CARD}}}")
            h = QHBoxLayout(row)
            h.addWidget(self._cover(d["a"]))
            mid = QVBoxLayout()
            tag = QLabel(f"<b>giống {int(d['score'] * 100)}%</b>" + ("<br><span style='color:#2e7d32'>rất chắc</span>" if d["strong"] else ""))
            tag.setAlignment(Qt.AlignCenter)
            tag.setStyleSheet("border:0")
            mid.addWidget(tag)
            yes = QPushButton("Gộp")
            yes.setProperty("primary", True)
            yes.clicked.connect(lambda _=False, d=d: self.merge(d))
            no = QPushButton("Khác người")
            no.clicked.connect(lambda _=False, d=d: self.reject(d))
            mid.addWidget(yes)
            mid.addWidget(no)
            h.addLayout(mid)
            h.addWidget(self._cover(d["b"]))
            self.bl.addWidget(row)
        self.bl.addStretch(1)
        self.all_b.setEnabled(any(d["strong"] for d in self.sug))

    def merge(self, d):
        cluster.merge_pair(self.ctx.db, d["a"], d["b"])
        self.reload()

    def reject(self, d):
        cluster.reject_merge(self.ctx.db, d["a"], d["b"])
        self.reload()

    def merge_strong(self):
        n = cluster.auto_merge(self.ctx.db)
        QMessageBox.information(self, "Gộp người", f"Đã gộp {n} cặp.")
        self.reload()


COL_STEPS = [5, 10, 20]     # các nấc số ảnh mỗi hàng của thanh trượt
THIGH_MAX_COLS = 0                    # (không còn dùng kiểu từ đùi lên)
NAVEL_MAX_COLS = 10


_COVER_CACHE = {}                     # ảnh đại diện đã cắt: đổi nấc phóng to qua lại không phải cắt lại từ ảnh gốc


COVER_W = {5: 640, 10: 640, 20: 640}      # bề rộng ảnh đại diện cắt sẵn theo số thẻ mỗi hàng: đủ nét mà không tốn bộ nhớ


def _cover_cached(key, fn, th, box, original, out_w, fetch):
    b = _COVER_CACHE.get(key)
    if b is None:
        b = fn(th, box, original, out_w, fetch)
        if b is not None:
            if len(_COVER_CACHE) > 3000:
                _COVER_CACHE.clear()
            _COVER_CACHE[key] = b
    return b


def cover_kind(cols):
    return "navel"                    # chỉ MỘT kiểu ảnh đại diện (từ rốn lên) cho mọi nấc: đổi nấc không phải cắt lại ảnh


class LetterTabs(QScrollArea):
    """Hàng tab chữ cái A–Z phía trên danh sách người: chữ đang xem sáng lên, bấm một chữ để nhảy tới mục đó; chữ chưa có ai thì mờ đi."""
    picked = Signal(str)
    LETTERS = ["♥", "All"] + [chr(c) for c in range(65, 91)] + ["#"]          # All: hiện đủ mọi tên theo bảng chữ cái; chọn một chữ thì chỉ hiện tên bắt đầu bằng chữ đó

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setFixedHeight(46)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(2, 4, 2, 4)
        row.setSpacing(4)
        self.btns = {}
        for ch in self.LETTERS:
            b = QPushButton(ch)
            b.setCheckable(True)
            b.setFixedSize(44 if ch == "All" else 34, 32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{border-radius:16px;font-weight:700;padding:0}}"
                            f"QPushButton:checked{{background:{theme.BRASS};color:#FFFFFF;border-color:{theme.BRASS}}}")
            b.clicked.connect(lambda _=False, c=ch: self.picked.emit(c))
            row.addWidget(b)
            self.btns[ch] = b
        row.addStretch(1)
        self.setWidget(w)
        self.cur = None

    def set_letters(self, counts):
        for ch, b in self.btns.items():
            n = counts.get(ch, 0)
            b.setEnabled(n > 0)
            b.setToolTip(f"{n} người" if n else "Không có")

    def set_current(self, ch):
        self.cur = ch
        for c, b in self.btns.items():
            b.setChecked(c == ch)
        b = self.btns.get(ch)
        if b is not None:
            self.ensureWidgetVisible(b, 60, 0)


class LetterSections(QScrollArea):
    """Danh sách người đã có tên chia theo chữ cái đầu như sổ danh bạ: A, B, C… mỗi chữ một mục có tiêu đề và lưới thẻ riêng."""
    clicked = Signal(object)
    menu = Signal(object, object)
    heart = Signal(object)
    lettersChanged = Signal(object)                            # {chữ: số người}
    currentLetter = Signal(str)                                # chữ của mục đang ở đầu vùng nhìn

    def __init__(self, size=128):
        super().__init__()
        self.size = size
        self.heads = {}
        self.setWidgetResizable(True)
        self.verticalScrollBar().valueChanged.connect(self._spy)
        self.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(4, 0, 4, 8)
        self.lay.setSpacing(0)
        self.lay.addStretch(1)
        self.setWidget(self.body)
        self.sections = []                                     # [(lưới, mô hình)]

    def scroll_to(self, letter):
        lab = self.heads.get(letter)
        if lab is not None:
            self.verticalScrollBar().setValue(lab.y())

    def _spy(self, _=None):
        v, cur = self.verticalScrollBar().value() + 6, None
        for ch, lab in self.heads.items():
            if lab.y() <= v:
                cur = ch
        if cur is None and self.heads:
            cur = next(iter(self.heads))
        sb = self.verticalScrollBar()
        if self.heads and sb.maximum() > 0 and sb.value() >= sb.maximum() - 2:
            cur = list(self.heads)[-1]                       # cuối danh sách: mục cuối cùng có thể không kéo lên tới đầu vùng nhìn
        if cur is not None:
            self.currentLetter.emit(cur)

    def set_groups(self, groups):
        for lab, grid, _ in getattr(self, "_w", []):
            lab.deleteLater()
            grid.deleteLater()
        self._w, self.sections, self.heads = [], [], {}
        for k, (letter, items) in enumerate(groups):
            lab = QLabel(f"{letter}   ·   {len(items)}")
            lab.setStyleSheet("font-weight:800;font-size:16px;color:#A9793D;padding:10px 2px 2px 2px;border-bottom:1px solid " + theme.RULE)
            model = ThumbModel()
            model.set_items(items)
            grid = make_grid(model, self.size, True)
            grid.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            grid.setFrameShape(QFrame.NoFrame)
            grid.setStyleSheet("QListView{background:transparent}")
            grid.clicked.connect(lambda ix: self.clicked.emit(ix))
            grid.heartClicked.connect(lambda ix: self.heart.emit(ix))
            grid.setContextMenuPolicy(Qt.CustomContextMenu)
            grid.customContextMenuRequested.connect(lambda pos, g=grid: self.menu.emit(pos, g))
            self.lay.insertWidget(self.lay.count() - 1, lab)
            self.lay.insertWidget(self.lay.count() - 1, grid)
            self._w.append((lab, grid, model))
            self.sections.append((grid, model))
            self.heads[letter] = lab
        self._fit()
        self.lettersChanged.emit({letter: len(items) for letter, items in groups})
        QTimer.singleShot(0, self._spy)

    def set_cols(self, cols):
        self.cols = cols
        self._fit()

    def _fit(self):
        avail = max(300, self.viewport().width() - 40)          # chừa lề + thanh cuộn để đủ số thẻ mỗi hàng
        size = card_size_for(avail, getattr(self, "cols", 10))
        for grid, model in self.sections:
            set_card_size(grid, size)
            cw, ch = grid.gridSize().width(), grid.gridSize().height()
            per = max(1, avail // cw)
            rows = -(-model.rowCount() // per)
            grid.setFixedHeight(rows * ch + 6)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        on_resize_debounced(self, self._fit)


class GroupedPhotos(QWidget):
    """Ảnh của một người chia theo cụm: Dressed, Nude, Chưa phân loại. Cụm nào hết ảnh (nhất là 'Chưa phân loại' khi đã phân loại xong) tự biến mất.
    Có một thanh trượt chung để phóng to / thu nhỏ ảnh preview của mọi cụm."""
    GROUPS = [("cloth", "Dressed"), ("nude", "Naked"), ("unclear", "Chưa phân loại")]

    selCountChanged = Signal(int)

    def __init__(self, ctx, page, extra_actions=None, bar=True):
        super().__init__()
        self.ctx, self.page = ctx, page
        self.parts = {}
        self.remove_fn = next((fn for n, fn in (extra_actions or []) if n.startswith("Không phải người này")), None)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.zoom_s = QSlider(Qt.Horizontal, self)               # cỡ ảnh chung của mọi cụm (chỉnh trong nút ⋯, Ctrl + cuộn chuột)
        self.zoom_s.setRange(90, 560)
        self.zoom_s.setValue(190)
        self.zoom_s.valueChanged.connect(self._zoom)
        self.zoom_s.hide()
        self.bar = SelBar(self) if bar else None
        if self.bar is not None:
            outer.addWidget(self.bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll, 1)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 0, 4, 8)
        lay.setSpacing(2)
        self.parts = {}
        for key, name in self.GROUPS:
            lab = QLabel()
            lab.setStyleSheet("font-weight:800;font-size:15px;color:#A9793D;padding:8px 2px 2px 2px;border-bottom:1px solid " + theme.RULE)
            pg = PhotoGrid(ctx, page, extra_actions=extra_actions, viewer_marks=bool(extra_actions), bar=False)
            pg.sel_only = True                                   # cụm ảnh: thanh nút tròn là của cả trang (GroupedPhotos), không phải của từng cụm
            pg.selCountChanged.connect(self._sel_changed)
            pg.grid.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            pg.grid.outer = self.scroll
            pg.grid.rowHChanged.connect(self._grid_zoomed)
            pg.grid.set_row_h(self.zoom_s.value())
            lay.addWidget(lab)
            lay.addWidget(pg)
            self.parts[key] = (lab, pg, name)
            lab.setVisible(False)
            pg.setVisible(False)
        lay.addStretch(1)
        self.scroll.setWidget(body)

    # --- giao diện cho thanh nút tròn (SelBar): gộp ảnh đã chọn ở mọi cụm
    def _sel_changed(self, _=0):
        self.selCountChanged.emit(self.sel_count())

    def sel_count(self):
        return sum(pg.sel_count() for _, pg, _ in self.parts.values())

    def selected(self):
        out = []
        for _, pg, _ in self.parts.values():
            out += pg.selected() if pg.sel_count() else []
        return out

    def clear_sel(self):
        for _, pg, _ in self.parts.values():
            pg.clear_sel()

    def add_to_person(self):
        ids = [x["id"] for x in self.selected()]
        if ids:
            assign_dialog(self.ctx, self, ids, getattr(self.page, "pid", None) if isinstance(self.page, PeoplePage) else None)

    def run_remove(self):
        sel = self.selected()
        if sel and self.remove_fn:
            self.remove_fn(sel)

    def fill_menu(self, m):
        from PySide6.QtWidgets import QWidgetAction
        wa = QWidgetAction(m)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 4, 12, 4)
        h.addWidget(QLabel("Cỡ ảnh"))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(90, 560)
        sl.setValue(self.zoom_s.value())
        sl.setFixedWidth(150)
        sl.valueChanged.connect(self.zoom_s.setValue)
        h.addWidget(sl)
        wa.setDefaultWidget(w)
        m.addAction(wa)
        sel = self.selected()
        first = next((pg for _, pg, _ in self.parts.values() if pg.sel_count()), None)
        if sel and first is not None:
            m.addSeparator()
            first._label_actions(m, sel)
        m.addSeparator()
        m.addAction("Chọn tất cả", lambda: [pg.grid.select_all() for _, pg, _ in self.parts.values() if not pg.isHidden()])
        m.addAction("Bỏ chọn", self.clear_sel)

    def _zoom(self, h):
        for _, pg, _ in self.parts.values():
            pg.grid.blockSignals(True)
            pg.grid.set_row_h(h)
            pg.grid.blockSignals(False)
        self.fit()

    def _grid_zoomed(self, h):
        """Ctrl + cuộn trong một cụm: đưa cả thanh trượt và các cụm khác về cùng cỡ."""
        if h != self.zoom_s.value():
            self.zoom_s.setValue(h)

    def set_groups(self, groups):
        """groups: {mã cụm: [ảnh]}"""
        for key, (lab, pg, name) in self.parts.items():
            items = groups.get(key, [])
            pg.set_items(items)
            lab.setText(f"{name}   ·   {len(items)} ảnh")
            lab.setVisible(bool(items))
            pg.setVisible(bool(items))
        QTimer.singleShot(0, self.fit)
        self.fit()

    def fit(self):
        for lab, pg, _ in self.parts.values():
            if not pg.isHidden():
                pg.grid.relayout()
                pg.grid.setFixedHeight(max(40, int(pg.grid.total_h) + 8))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        on_resize_debounced(self, self.fit)


class ComboPage(Page):
    """Mashup: ảnh chụp KẾT HỢP từ 2 người trở lên. Chia tab theo SỐ NGƯỜI trong ảnh (2, 3, 4…); mỗi tab hiện mọi ảnh có đúng số người đó,
    chia thành Dressed và Nude. Không chứa ảnh cá nhân từng người."""

    def __init__(self, ctx):
        super().__init__(ctx)
        self.by_count, self.keys = {}, []
        self.v.setContentsMargins(0, 0, 0, 0)
        self.grouped = GroupedPhotos(ctx, self)
        self.pill = TextPill()                                   # ô dài "2 người | 3 người | 4 người" ở giữa thanh nút tròn (như điện thoại)
        self.pill.currentChanged.connect(self.show_tab)
        self.grouped.bar.set_center(self.pill)
        self.head = QLabel()
        self.head.setStyleSheet("color:" + theme.MUTED + ";padding:0 16px")
        self.head.setWordWrap(True)
        self.grouped.layout().insertWidget(1, self.head)
        self.v.addWidget(self.grouped, 1)

    def refresh(self):
        self.by_count = cluster.mashup_by_count(self.ctx.db)
        keys = sorted(self.by_count)
        cur = self.keys[self.pill.cur] if self.keys and 0 <= self.pill.cur < len(self.keys) else None
        self.keys = keys
        self.pill.set_items([f"{k} người" for k in keys], keys.index(cur) if cur in keys else 0)
        self.pill.setVisible(bool(keys))
        if keys:
            self.show_tab(self.pill.cur)
        else:
            self.head.setText("Chưa có ảnh nào chụp chung từ 2 người trở lên.")
            self.grouped.set_groups({"cloth": [], "nude": [], "unclear": []})

    def show_tab(self, ix):
        k = self.keys[ix] if 0 <= ix < len(self.keys) else None
        if k is None:
            return
        rows = [r for r in self.ctx.db.images_by_ids(self.by_count.get(k, [])) if r["thumb"]]
        rows.sort(key=lambda r: r["taken"] or "", reverse=True)
        self.head.setText(f"{len(rows)} ảnh có {k} người")
        grp = {r["image_id"]: r["grp"] for r in self.ctx.db.q("SELECT image_id,grp FROM cloth_group WHERE grp IS NOT NULL")}
        man = {r["image_id"]: r["grp"] for r in self.ctx.db.q("SELECT image_id,grp FROM cloth_manual")}
        parts = {"cloth": [], "nude": [], "unclear": []}
        for r in rows:
            g = man[r["id"]] if r["id"] in man else grp.get(r["id"])
            parts[g if g in ("cloth", "nude") else "unclear"].append(img_item(r))
        self.grouped.set_groups(parts)


class FavoritesPage(LibraryPage):
    """Favorite: các ẢNH đã bấm ngôi sao Yêu thích khi xem ảnh (như tab Favorite của Android). Người được yêu thích bằng trái tim nằm ở nút ♥ đầu hàng chữ cái của Model."""
    fav_only = True

    def refresh(self):
        super().refresh()


class PeoplePage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.pid = None
        self.stack = QStackedWidget()
        self.v.addWidget(self.stack, 1)
        # danh sách người
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(25, 70)
        self.sl.setValue(int(cluster.default_thr(ctx.db) * 100))
        self.sl.setFixedWidth(160)
        self.sl.setToolTip("Thấp: gom nhiều ảnh vào cùng một người (dễ nhầm). Cao: tách nhỏ hơn (một người bị chia nhiều nhóm).")
        self.thr = QLabel()
        self.sl.valueChanged.connect(lambda v: self.thr.setText(f"{v / 100:.2f}"))
        self.thr.setText(f"{self.sl.value() / 100:.2f}")
        b = QPushButton("Gom lại khuôn mặt")
        b.clicked.connect(self.recluster)
        # lọc danh sách (có thể hàng nghìn người): tìm tên, bảng chữ cái A–Z, màu tóc, cách xếp
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm tên…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(90)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(lambda _=None: self.refresh())
        self.letter = None
        self.az_b = QPushButton("A – Z  ▾")
        self.az_b.setToolTip("Lọc theo chữ cái đầu của tên")
        self.az_b.clicked.connect(self.pick_letter)
        self.hair_c = QComboBox()
        self.hair_c.setToolTip("Lọc theo màu tóc (ước lượng gần đúng từ ảnh)")
        self.hair_c.currentIndexChanged.connect(lambda _=None: self.refresh())
        self.sort_c = QComboBox()
        for k, t in (("az", "Tên A–Z (theo họ tên)"), ("given", "Tên A–Z (theo tên gọi)"), ("n", "Nhiều ảnh nhất")):      # như sổ danh bạ: mặc định A–Z
            self.sort_c.addItem(t, k)
        self.sort_c.currentIndexChanged.connect(lambda _=None: self.refresh())
        mg = QPushButton("Gợi ý gộp người…")
        mg.setToolTip("Tìm các nhóm có thể là cùng một người (bị tách vì khác góc mặt, tuổi, ánh sáng) để gộp lại")
        mg.clicked.connect(lambda: self.suggest_merges())
        self.cnt = QLabel()
        self.multi = QCheckBox("Ẩn nhóm chỉ có 1 ảnh")
        self.multi.setChecked(True)
        self.multi.toggled.connect(lambda _=None: self.refresh())
        # (độ chặt khi gom, nút gom lại / gợi ý gộp, ô ẩn nhóm 1 ảnh, cách xếp, số nhóm: không dùng đến nên không hiện cho đỡ tốn chỗ; giữ giá trị mặc định)
        fbar = QHBoxLayout()
        self.hair_c.setMinimumContentsLength(3)
        self.hair_c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.tabs = LetterTabs()                               # MỘT hàng: tab chữ cái, ô tìm kiếm, thanh trượt cỡ thẻ
        fbar.addWidget(self.tabs, 1)
        self.search.setMaximumWidth(190)
        fbar.addWidget(self.search)
        self.az_b.hide()                                       # (thay bằng hàng tab chữ cái)
        # (ô lọc màu tóc không hiện nữa: giữ ở mức "Tất cả")
        self.card_s = DotSlider(Qt.Horizontal)
        self.card_s.setRange(0, len(COL_STEPS) - 1)             # nấc: 5, 10, 20 ảnh mỗi hàng; thẻ tự chia đều cho vừa chiều ngang
        self.card_s.setTickInterval(1)
        self.card_s.setTickPosition(QSlider.TicksBelow)
        self.card_s.setPageStep(1)
        self.card_s.setValue(COL_STEPS.index(10))
        self._kind = cover_kind(10)                                # 3, 5 ảnh/hàng: từ đùi lên; 10: từ rốn lên
        self.card_s.setFixedWidth(110)
        self.card_s.setFixedHeight(24)
        self.card_s.valueChanged.connect(self.set_card_size_all)
        fbar.addWidget(self.card_s)
        l.addLayout(fbar)
        # hai khu vực: người đã đặt tên (đáng tin 100%) và người chưa đặt tên
        from PySide6.QtWidgets import QSplitter
        self.pmodel, self.smodel, self.umodel = ThumbModel(), ThumbModel(), ThumbModel()
        self.pgrid, self.sgrid, self.ugrid = (make_grid(m, 128, True) for m in (self.pmodel, self.smodel, self.umodel))
        self.sec_s = QLabel()
        self.split = QSplitter(Qt.Vertical)
        self.sec_n, self.sec_u = QLabel(), QLabel()
        self.sec_boxes = []
        self.alpha = LetterSections(128)                       # người đã có tên: chia theo chữ cái A, B, C…
        self.alpha.clicked.connect(self.open_person)
        self.alpha.menu.connect(lambda pos, g: self.person_menu(pos, g))
        self.alpha.heart.connect(self.toggle_heart)
        self.tabs.picked.connect(self.pick_letter_tab)
        self.sec_toggle = {}
        for key, lab, grid in (("named", self.sec_n, self.alpha), ("guess", self.sec_s, self.sgrid), ("unnamed", self.sec_u, self.ugrid)):
            lab.setStyleSheet("font-weight:700;font-size:14px;color:#A9793D;padding:6px 2px 2px 2px")
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            head = QHBoxLayout()
            head.addWidget(lab)
            tb = QPushButton()                                      # nút thu gọn / mở rộng khu vực
            tb.setCursor(Qt.PointingHandCursor)
            tb.setFixedSize(34, 26)
            head.addWidget(tb)                                      # nút nằm ngay cạnh tên mục
            head.addStretch(1)
            bl.addLayout(head)
            if grid is self.alpha:                                   # danh sách theo chữ cái đã là "đã có tên": bỏ dòng tiêu đề và nút thu gọn
                lab.hide()
                tb.hide()
            bl.addWidget(grid, 1)
            self.sec_toggle[key] = (tb, box, grid)
            tb.clicked.connect(lambda _=False, k=key: self.toggle_section(k))
            if grid is not self.alpha:
                grid.clicked.connect(self.open_person)         # bấm một lần là mở
                grid.heartClicked.connect(self.toggle_heart)
                grid.setContextMenuPolicy(Qt.CustomContextMenu)
                grid.customContextMenuRequested.connect(lambda pos, g=grid: self.person_menu(pos, g))
            self.split.addWidget(box)
            self.sec_boxes.append(box)
        self.split.setChildrenCollapsible(False)
        self.split.setStretchFactor(0, 4)
        l.addWidget(self.split, 1)
        self.stack.addWidget(w)
        # ảnh của một người: thanh nút tròn (←, tên, Dressed | Naked | All, ⋯), lưới ảnh, nút hình người nhấp nháy nếu còn ảnh đề xuất
        w2 = OverlayHost()
        l2 = QVBoxLayout(w2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(0)
        self.pavatar, self.pname = QLabel(), QLabel()              # (chỉ giữ để lưu tên / ảnh đại diện; hiển thị ở viên thuốc tên trên thanh nút)
        self.pavatar.hide()
        self.pname.hide()
        self.pbar = SelBar(None, back=self.back)
        self.cloth_row = ClothPill("Lọc ảnh của người này: Dressed / Naked / All")
        self.cloth_row.changed.connect(self.show_person)
        self.cloth_row.intercept = lambda key: self.cur_grid().classify_selected(key)       # đang chọn ảnh: bấm Dressed / Naked để phân loại luôn ảnh đã chọn
        self.pbar.set_center(self.cloth_row)

        def person_menu_items(m):
            m.addAction("Đặt tên…", self.rename)
            m.addAction("Gộp vào người khác…", self.merge)
            m.addAction("Ẩn người này", self.hide)
            m.addSeparator()
        self.pbar.menu_extra = person_menu_items
        l2.addWidget(self.pbar)
        self.sug_bar = QWidget()                                   # tên do app đoán: xem ảnh bên trong rồi mới xác nhận
        sbl = QHBoxLayout(self.sug_bar)
        sbl.setContentsMargins(14, 2, 14, 2)
        self.sug_lab = QLabel()
        self.sug_lab.setWordWrap(True)
        self.sug_yes = QPushButton()
        self.sug_yes.setProperty("primary", True)
        self.sug_yes.clicked.connect(self.accept_suggestion)
        self.sug_no = QPushButton("Không đúng")
        self.sug_no.clicked.connect(self.reject_suggestion)
        sbl.addWidget(self.sug_lab, 1)
        self.cand_box = QHBoxLayout()                              # tối đa 3 tên có khả năng nhất khi app chưa đủ chắc để đề xuất một tên
        sbl.addLayout(self.cand_box)
        sbl.addWidget(self.sug_yes)
        sbl.addWidget(self.sug_no)
        self.sug_bar.setVisible(False)
        l2.addWidget(self.sug_bar)
        self.undo_bar = QWidget()                                  # sau khi loại ảnh khỏi người: nút Hoàn tác (phòng bấm nhầm)
        ubl = QHBoxLayout(self.undo_bar)
        ubl.setContentsMargins(14, 2, 14, 2)
        self.undo_lab = QLabel()
        ub = QPushButton("↶ Hoàn tác")
        ub.clicked.connect(self.undo_remove)
        ubl.addWidget(self.undo_lab)
        ubl.addWidget(ub)
        ubl.addStretch(1)
        self.undo_bar.setVisible(False)
        self.undo_t = QTimer(self)
        self.undo_t.setSingleShot(True)
        self.undo_t.timeout.connect(lambda: self.undo_bar.setVisible(False))
        self._undo = None
        l2.addWidget(self.undo_bar)
        self.photos = PhotoGrid(ctx, self, extra_actions=[("Không phải người này (gỡ khỏi nhóm)", self.remove_sel)], viewer_marks=True, bar=False)
        self.grouped = GroupedPhotos(ctx, self, extra_actions=[("Không phải người này (gỡ khỏi nhóm)", self.remove_sel)], bar=False)
        self.pstack = QStackedWidget()                            # Tất cả: chia cụm; chọn một nhóm trong ô lọc: lưới thường
        self.pstack.addWidget(self.grouped)
        self.pstack.addWidget(self.photos)
        self.pstack.currentChanged.connect(lambda _: self.pbar.set_src(self.cur_grid()))
        self.pbar.set_src(self.grouped)
        l2.addWidget(self.pstack, 1)
        self.sug_btn = RoundBtn("person", "Ảnh app chưa chắc là của người này: bấm để xem và xác nhận đúng / sai")      # nút hình người nhấp nháy: chỉ hiện khi còn ảnh đề xuất
        self.sug_btn.clicked.connect(self.open_suggest)
        w2.add_bottom_center(self.sug_btn)
        self.sug_btn.hide()
        for g in (self.grouped, self.photos):
            g.selCountChanged.connect(lambda n: self.sug_btn.setVisible(n == 0 and self._n_guess > 0))
        self._n_guess = 0
        self.stack.addWidget(w2)
        # trang ảnh đề xuất của một người: ← | Dressed | Naked | ✓ (xác nhận ảnh đã chọn)
        w3 = QWidget()
        l3 = QVBoxLayout(w3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.setSpacing(0)
        self.guess = PhotoGrid(ctx, self, extra_actions=[("Đúng, thêm vào nhóm này", self.accept_guess),
                                                          ("Không phải người này", self.reject_guess)], viewer_marks=True)
        self.tick_pill = ClothPill("Dressed / Naked: phân loại ảnh đã chọn · ✓: xác nhận ảnh đã chọn là của người này", third="tick")
        self.tick_pill.intercept = lambda key: self.guess.classify_selected(key)
        self.tick_pill.tickClicked.connect(lambda: self.guess._run_extra(self.accept_guess))
        self.guess.bar.set_center(self.tick_pill)
        self.guess.bar.set_back(self.close_suggest)
        self.glabel = QLabel()
        self.glabel.setStyleSheet("font-weight:700;color:#A9793D;font-size:14px;padding:0 16px 4px 16px")
        self.guess.layout().insertWidget(1, self.glabel)
        l3.addWidget(self.guess, 1)
        self.stack.addWidget(w3)

    def refresh(self):
        # mặt mới đủ rõ chưa thuộc nhóm nào (vừa quét thêm ảnh): gán nhanh cho người giống nhất; gom nhóm đầy đủ chạy sau mỗi lần quét.
        # Mặt người dùng đã loại khỏi một người, hoặc đã khóa, không tính là "chờ gom" (nếu không, mỗi lần làm mới lại gom lại toàn bộ và treo giao diện).
        db = self.ctx.db
        rows = db.q("""SELECT id FROM faces WHERE person_id IS NULL AND locked=0 AND px>=?
                       AND id NOT IN (SELECT face_id FROM face_reject)""", (cluster.MIN_FACE_PX,))
        pend = [r["id"] for r in rows]
        if pend and len(pend) != getattr(self, "_pend_seen", -1) and not getattr(self, "_busy", False):
            self._busy = True
            try:
                if len(pend) <= 300:
                    cluster.attach_to_named(db)
                    cluster.reassign_faces(db, pend)
                else:
                    cluster.cluster_faces(db, self.sl.value() / 100)
            finally:
                self._busy = False
                self._pend_seen = db.one("""SELECT COUNT(*) c FROM faces WHERE person_id IS NULL AND locked=0 AND px>=?
                                            AND id NOT IN (SELECT face_id FROM face_reject)""", (cluster.MIN_FACE_PX,))["c"]
        if self.pid is not None and self.stack.currentIndex() in (1, 2):
            self.show_person()                    # đang mở trang một người: chỉ làm mới trang đó; danh sách người dựng lại khi quay về (nhanh hơn nhiều)
            return
        ps = self.ctx.db.persons()
        total = len(ps)
        if self.multi.isChecked():
            ps = [p for p in ps if p["name"] or p["n"] >= 2]
        # --- lọc: tìm tên, chữ cái đầu, màu tóc
        given = self.sort_c.currentData() == "given"
        self._letters = {}
        for p in ps:
            k = cluster.letter_key(p["name"], given) if p["name"] else "#"            # người chưa đặt tên nằm trong mục #
            self._letters[k] = self._letters.get(k, 0) + 1
        self._letters["All"] = len(ps)
        self._letters["♥"] = sum(1 for p in ps if p["favorite"])                       # trang riêng của những người đã bấm trái tim (đứng trước chữ A)
        q = cluster.fold(self.search.text())
        if q:
            ps = [p for p in ps if q in cluster.fold(p["name"] or "chua dat ten")]
        if self.letter == "♥":
            ps = [p for p in ps if p["favorite"]]
        elif self.letter == "#":
            ps = [p for p in ps if not p["name"] or cluster.letter_key(p["name"], given) == "#"]
        elif self.letter:
            ps = [p for p in ps if p["name"] and cluster.letter_key(p["name"], given) == self.letter]
        hair = self._hair_map()
        counts = {}
        for p in ps:
            h = hair.get(p["id"])
            if h:
                counts[h] = counts.get(h, 0) + 1
        sel = self.hair_c.currentData()
        self.hair_c.blockSignals(True)
        self.hair_c.clear()
        self.hair_c.addItem("Tất cả", None)
        for code, name in cluster.HAIR:
            if counts.get(code):
                self.hair_c.addItem(f"{name}  ({counts[code]})", code)
        self.hair_c.setCurrentIndex(max(0, self.hair_c.findData(sel)))
        self.hair_c.blockSignals(False)
        if sel:
            ps = [p for p in ps if hair.get(p["id"]) == sel]
        mode = self.sort_c.currentData()
        if mode in ("az", "given"):
            ps = sorted(ps, key=lambda p: (not p["name"], cluster.fold(p["name"] or "").split()[-1] if (mode == "given" and p["name"]) else cluster.fold(p["name"] or ""), -p["n"]))
        self.az_b.setText(f"A – Z  ▾" if not self.letter else f"Chữ {self.letter}  ✕")
        filt = bool(q or self.letter or sel)
        self.cnt.setText(f"{len(ps)} nhóm" + (f" (ẩn {total - len(ps)} nhóm chỉ có 1 ảnh)" if (not filt and len(ps) != total) else ""))
        refwarn = {r["person_id"] for r in self.ctx.db.q("SELECT person_id FROM ref_flag")}
        def items(rows):
            out = []
            for p in rows:
                warn = p["id"] in refwarn
                it = {"thumb": p["cover"], "pid": p["id"], "key": f"p{p['id']}{p['cover']}{p['favorite']}{warn}{int(p['pend'] > 0)}", "label": f"{'⚠ ' if warn else ''}{p['name'] or 'Chưa đặt tên'}\n{p['n']} ảnh",
                      "tip": f"{p['name'] or 'Chưa đặt tên'} · {p['n']} ảnh · đã xác minh {round(100 * p['ver'] / max(1, p['n'] + p['pend']))}%" + ("\n⚠ Khuôn mặt trong nhóm khác xa ảnh tham chiếu trên internet của người này: nên kiểm tra lại tên" if warn else ""),
                      "fav": bool(p["favorite"]), "pend": p["pend"] > 0, "unver": max(0.0, 1.0 - p["ver"] / max(1, p["n"] + p["pend"]))}       # ảnh app đề xuất mà chưa xác minh cũng tính là chưa hoàn thành
                pick = self.ctx.db.cover_pick(p["id"], self._kind) if self._kind != "face" else None
                if pick:                                                              # thẻ lớn: toàn thân (5–10/hàng), bán thân (15/hàng)
                    box = (pick["x"], pick["y"], pick["w"], pick["h"])
                    it.pop("thumb")
                    fn = cover.thigh_bytes if self._kind == "thigh" else (lambda th, b, op, ow, fe, db=self.ctx.db, fid=pick["fid"]: cover.navel_cached(db, fid, th, b, op, ow, fe))      # ảnh đã làm sẵn khi máy rảnh thì dùng ngay
                    ow = COVER_W.get(self.cols(), 520)
                    it["key"] = f"p{p['id']}{self._kind}{ow}{pick['thumb']}{box}"
                    ckey = it["key"]
                    it["key"] += f"|{int(p['pend'] > 0)}{int(bool(p['favorite']))}"
                    fetch = (lambda row={"id": pick["iid"], "path": pick["path"]}: sync.read_original_any(self.ctx.db, row))
                    it["tbytes"] = (lambda th=pick["thumb"], b=box, fn=fn, op=pick["path"], k=ckey, ow=ow, fe=fetch: _cover_cached(k, fn, th, b, op, ow, fe))
                out.append(it)
            return out
        sug = {r["person_id"]: r for r in self.ctx.db.q("SELECT person_id,name,n_arch FROM person_suggest")}
        named = [p for p in ps if p["name"]]
        guessed = [p for p in ps if not p["name"] and p["id"] in sug]
        unnamed = [p for p in ps if not p["name"] and p["id"] not in sug]
        self.pmodel.set_items(items(named))                    # (giữ để các chỗ khác dùng; hiển thị là self.alpha)
        groups, byletter = [], {}
        for p in named:
            byletter.setdefault(cluster.letter_key(p["name"], given), []).append(p)
        for letter in sorted(byletter, key=lambda c: (c == "#", c)):
            rows = sorted(byletter[letter], key=lambda p: ((cluster.fold(p["name"]).split()[-1] if given else cluster.fold(p["name"])), -p["n"]))
            if mode == "n":
                rows = sorted(rows, key=lambda p: -p["n"])
            groups.append((letter, items(rows)))
        guessed.sort(key=lambda p: -p["n"])
        unnamed.sort(key=lambda p: -p["n"])
        gi = items(guessed)
        for it in gi:
            it["label"] = f"Có thể là {sug[it['pid']]['name']}\n" + it["label"].split("\n", 1)[1]
        ui = items(unnamed)
        if gi or ui:                                           # người chưa đặt tên (kể cả tên app đoán) nằm trong mục "#", xếp từ nhiều ảnh nhất xuống
            cand = {r["person_id"]: r["m"] for r in self.ctx.db.q("SELECT person_id, MAX(score) m FROM person_candidates GROUP BY person_id")}
            nimg = {p["id"]: p["n"] for p in guessed + unnamed}

            def likelihood(it):                                # app đoán chắc nhất lên đầu: có tên đề xuất > có tên ứng viên (điểm cao trước) > còn lại; cùng mức thì nhiều ảnh hơn trước
                pid = it["pid"]
                if pid in sug:
                    return (2, sug[pid]["n_arch"] or 0, nimg.get(pid, 0))
                return (1, cand[pid], nimg.get(pid, 0)) if pid in cand else (0, 0, nimg.get(pid, 0))
            both = sorted(gi + ui, key=likelihood, reverse=True)
            hash_items = (dict(groups).pop("#", []) if any(g[0] == "#" for g in groups) else []) + both
            groups = [g for g in groups if g[0] != "#"] + [("#", hash_items)]
        self.alpha.set_groups(groups)
        self.tabs.set_letters(self._letters)
        self.tabs.set_current(self.letter or "All")
        self.smodel.set_items(gi)
        self.umodel.set_items(ui)
        self.sec_n.setText(f"Đã có tên  ({len(named)})")
        self.sec_s.setText(f"App suy đoán từ các tệp nén  ({len(guessed)})  ·  bấm chuột phải để xác nhận tên")
        self.sec_u.setText(f"Chưa đặt tên  ({len(unnamed)})")
        self.sec_boxes[0].setVisible(True)
        self.sec_boxes[1].setVisible(False)                    # (hai khu vực riêng cũ không còn hiện: gộp vào danh sách theo chữ cái, mục #)
        self.sec_boxes[2].setVisible(False)
        for k in self.sec_toggle:
            self._apply_collapse(k)
        self._rebalance()
        if self.pid is not None:
            self.show_person()

    def toggle_section(self, key, collapsed=None):
        """Thu gọn / mở rộng một khu vực (Đã có tên, App suy đoán, Chưa đặt tên); trạng thái được nhớ."""
        tb, box, grid = self.sec_toggle[key]
        cur = self.ctx.db.get_meta(f"people_collapsed_{key}", "0") == "1"
        new = (not cur) if collapsed is None else collapsed
        self.ctx.db.set_meta(f"people_collapsed_{key}", "1" if new else "0")
        self._apply_collapse(key)
        self._rebalance()

    def _rebalance(self):
        """Phần đã thu gọn chỉ còn dải tiêu đề; chỗ trống nhường hết cho các khu vực đang mở."""
        total = max(100, self.split.height())
        keys = ["named", "guess", "unnamed"]
        sizes, weights, used = [], [], 0
        for k, box in zip(keys, self.sec_boxes):
            coll = self.ctx.db.get_meta(f"people_collapsed_{k}", "0") == "1"
            if not box.isVisibleTo(self.split):
                sizes.append(0)
                weights.append(0)
            elif coll:
                sizes.append(46)
                weights.append(0)
                used += 46
            else:
                sizes.append(0)
                weights.append(3 if k == "named" else 1)
        free = max(0, total - used)
        wsum = sum(weights) or 1
        sizes = [int(free * w / wsum) if w else sz for sz, w in zip(sizes, weights)]
        self.split.setSizes(sizes)

    def _apply_collapse(self, key):
        tb, box, grid = self.sec_toggle[key]
        coll = self.ctx.db.get_meta(f"people_collapsed_{key}", "0") == "1"
        grid.setVisible(not coll)
        tb.setIcon(theme.chevron_icon(down=not coll))                  # chỉ ký hiệu (mũi tên xuống = đang mở, sang phải = đang thu gọn); chú thích khi rê chuột
        tb.setIconSize(QSize(16, 16))
        tb.setText("")
        tb.setToolTip("Hiện lại danh sách" if coll else "Thu gọn khu vực này xuống một dòng")
        box.setMaximumHeight(46 if coll else 16777215)               # thu gọn: chỉ còn dòng tiêu đề, chỗ trống dành cho khu vực khác

    def toggle_heart(self, ix):
        """Bấm trái tim trên thẻ: thêm / bỏ người đó khỏi danh sách Yêu thích."""
        pid = ix.data(Qt.UserRole)["pid"]
        self.ctx.db.toggle_favorite(pid)
        self.ctx.changed.emit()

    def cols(self):
        return COL_STEPS[max(0, min(len(COL_STEPS) - 1, self.card_s.value()))]

    def set_card_size_all(self, _=None):
        cols = self.cols()
        kind = cover_kind(cols)
        if kind != self._kind or COVER_W.get(cols) != getattr(self, "_cover_w", None):       # đổi kiểu / độ nét ảnh đại diện theo độ phóng to
            self._kind, self._cover_w = kind, COVER_W.get(cols)
            on_resize_debounced(self, self.refresh, 90)                 # kéo thanh trượt liên tục chỉ nạp lại ảnh đại diện một lần
        self.alpha.set_cols(cols)
        for g in (self.sgrid, self.ugrid):
            w = g.viewport().width() - 6
            if w > 100:
                set_card_size(g, card_size_for(w, cols))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        on_resize_debounced(self, self.set_card_size_all)

    def showEvent(self, e):
        super().showEvent(e)
        self.set_card_size_all()

    def _hair_map(self):
        """Màu tóc của từng người, tính lại khi dữ liệu đặc trưng khuôn mặt thay đổi."""
        db = self.ctx.db
        key = (db.one("SELECT COUNT(*) c FROM face_attr")["c"], db.one("SELECT COUNT(*) c FROM faces")["c"])
        if getattr(self, "_hair_key", None) != key:
            self._hair_cache = cluster.person_hair(db)
            self._hair_key = key
        return self._hair_cache

    def pick_letter_tab(self, ch):
        """Bấm tab chữ cái: All = hiện hết; một chữ = chỉ hiện tên bắt đầu bằng chữ đó (ít thẻ hơn nên mượt hơn)."""
        self.letter = None if ch == "All" else ch
        self.refresh()

    def pick_letter(self):
        """Bảng chữ cái A–Z (chữ không có người nào thì mờ đi); bấm lại nút để bỏ lọc."""
        if self.letter:
            self.letter = None
            self.refresh()
            return
        from PySide6.QtWidgets import QGridLayout, QWidgetAction
        m = QMenu(self)
        box = QWidget()
        g = QGridLayout(box)
        g.setContentsMargins(10, 10, 10, 10)
        g.setSpacing(4)
        letters = [chr(c) for c in range(65, 91)] + ["#"]
        for k, ch in enumerate(letters):
            b = QPushButton(ch)
            b.setFixedSize(40, 34)
            n = self._letters.get(ch, 0)
            b.setEnabled(n > 0)
            b.setToolTip(f"{n} người" if n else "Không có")
            b.clicked.connect(lambda _=False, ch=ch: (setattr(self, "letter", ch), m.close(), self.refresh()))
            g.addWidget(b, k // 5, k % 5)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(box)
        m.addAction(wa)
        m.exec(self.az_b.mapToGlobal(self.az_b.rect().bottomLeft()))

    def recluster(self):
        n = cluster.cluster_faces(self.ctx.db, self.sl.value() / 100)
        merged = cluster.auto_merge(self.ctx.db)                 # tự gộp các nhóm rất chắc là một người
        self.ctx.changed.emit()
        QMessageBox.information(self, "Xong", f"Đã gom thành {max(n - merged, 0)} nhóm người" + (f" (tự gộp {merged} cặp nhóm rất giống nhau)" if merged else "") +
                                ". Nếu còn người bị tách làm đôi, bấm “Gợi ý gộp người…”.")

    def suggest_merges(self, focus=None):
        MergeSuggestDialog(self.ctx, self, focus).exec()
        self.ctx.changed.emit()

    def open_person(self, idx):
        self.pid = idx.data(Qt.UserRole)["pid"]
        self.show_person()

    def accept_suggestion(self):
        sg = self.ctx.db.one("SELECT name FROM person_suggest WHERE person_id=?", (self.pid,))
        if sg:
            cluster.rename_person(self.ctx.db, self.pid, sg["name"])
            self.ctx.db.x("DELETE FROM person_suggest WHERE person_id=?", (self.pid,))
            self.ctx.changed.emit()

    def reject_suggestion(self):
        self.ctx.db.x("DELETE FROM person_suggest WHERE person_id=?", (self.pid,))
        self.ctx.db.x("DELETE FROM person_candidates WHERE person_id=?", (self.pid,))
        self.ctx.changed.emit()

    def accept_candidate(self, name):
        cluster.rename_person(self.ctx.db, self.pid, name)
        self.ctx.db.x("DELETE FROM person_candidates WHERE person_id=?", (self.pid,))
        self.ctx.changed.emit()

    def cur_grid(self):
        """Nguồn ảnh đang hiện ở trang một người (lưới chia cụm hoặc lưới thường)."""
        return self.pstack.currentWidget()

    def open_suggest(self):
        self.stack.setCurrentIndex(2)

    def close_suggest(self):
        self.stack.setCurrentIndex(1)

    def show_person(self):
        r = self.ctx.db.one("SELECT name FROM persons WHERE id=?", (self.pid,))
        if not r:
            self.back()
            return
        sg = self.ctx.db.one("SELECT name,n_arch FROM person_suggest WHERE person_id=?", (self.pid,)) if not r["name"] else None
        cands = self.ctx.db.q("SELECT name,score FROM person_candidates WHERE person_id=? ORDER BY score DESC LIMIT 3", (self.pid,)) if (not r["name"] and not sg) else []
        while self.cand_box.count():
            w = self.cand_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.sug_bar.setVisible(bool(sg) or bool(cands))
        self.sug_yes.setVisible(bool(sg))
        if sg:
            self.sug_lab.setText(f"App đoán người này là <b>{sg['name']}</b> (theo tên trên {sg['n_arch']} tệp nén). Xem các ảnh bên dưới, đúng thì bấm xác nhận.")
            self.sug_yes.setText(f"✓ Xác nhận là {sg['name']}")
        elif cands:
            self.sug_lab.setText("App chưa đủ chắc về tên. Các tên có khả năng nhất (xem ảnh bên dưới rồi chọn tên đúng):")
            for c in cands:
                b = QPushButton(f"✓ {c['name']}  ·  {round(100 * c['score'])}%")
                b.setProperty("primary", True)
                b.clicked.connect(lambda _=False, n=c["name"]: self.accept_candidate(n))
                self.cand_box.addWidget(b)
        self.pname.setText(f"<span style='font-size:18px;font-weight:700'>{r['name'] or 'Chưa đặt tên'}</span>")
        self._title = r["name"] or "Chưa đặt tên"
        cv_t = self.ctx.db.person_cover(self.pid)
        pm = QPixmap()
        if cv_t:
            try:
                pm.loadFromData(SEC.read_file(cv_t))
            except Exception:
                pass
        circ = None
        if not pm.isNull():                                    # ảnh đại diện tròn như thẻ danh bạ
            from PySide6.QtGui import QPainter, QPainterPath
            sq = pm.scaled(36, 36, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            circ = QPixmap(36, 36)
            circ.fill(Qt.transparent)
            pt = QPainter(circ)
            pt.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addEllipse(0, 0, 36, 36)
            pt.setClipPath(path)
            pt.drawPixmap((36 - sq.width()) // 2, (36 - sq.height()) // 2, sq)
            pt.end()
        self.pbar.set_title(self._title, circ)
        imgs = self.ctx.db.person_images(self.pid)
        cc = clothing.group_counts(self.ctx.db, [x["id"] for x in imgs])
        self.cloth_row.blockSignals(True)
        self.cloth_row.set_options(clothing.options(cc, len(imgs)), len(imgs))
        self.cloth_row.blockSignals(False)
        if self.cloth_row.value == clothing.UNCLEAR[0]:
            known = clothing.known_ids(self.ctx.db)
            imgs = [x for x in imgs if x["id"] not in known]
        elif self.cloth_row.value:
            keep = clothing.ids_in_group(self.ctx.db, self.cloth_row.value)
            imgs = [x for x in imgs if x["id"] in keep]
        self.photos.set_items([img_item(x) for x in imgs])
        if self.cloth_row.value is None:
            grp = {r["image_id"]: r["grp"] for r in self.ctx.db.q("SELECT image_id,grp FROM cloth_group WHERE grp IS NOT NULL")}
            parts = {"cloth": [], "nude": [], "unclear": []}
            for x in imgs:
                parts[grp.get(x["id"], "unclear")].append(img_item(x))
            self.grouped.set_groups(parts)
            self.pstack.setCurrentIndex(0)
        else:
            self.pstack.setCurrentIndex(1)
        gs = self.ctx.db.person_guesses(self.pid)
        self._n_guess = len(gs)
        self.sug_btn.set_badge(len(gs), blink=True)                  # nhấp nháy trên PC; hết ảnh đề xuất thì nút tự ẩn
        self.sug_btn.setVisible(bool(gs) and self.cur_grid().sel_count() == 0)
        self.glabel.setText(f"Có thể là {self._title}  ·  {len(gs)} ảnh app chưa chắc chắn")
        self.guess.set_items([img_item(x, {"cap_tag": f"khớp {int(x['score'] * 100)}%"}) for x in gs])
        self.stack.setCurrentIndex(2 if (self.stack.currentIndex() == 2 and gs) else 1)

    def back(self):
        self.pid = None
        self.stack.setCurrentIndex(0)
        self.refresh()

    def person_menu(self, pos, grid=None):
        grid = grid or self.pgrid
        ix = grid.indexAt(pos)
        if not ix.isValid():
            return
        pid = ix.data(Qt.UserRole)["pid"]
        m = QMenu(self)
        sg = self.ctx.db.one("SELECT name FROM person_suggest WHERE person_id=?", (pid,))
        if sg:
            m.addAction(f"Xác nhận là {sg['name']}", lambda: (cluster.rename_person(self.ctx.db, pid, sg["name"]),
                                                              self.ctx.db.x("DELETE FROM person_suggest WHERE person_id=?", (pid,)), self.ctx.changed.emit()))
        m.addAction("Đặt tên…", lambda: self.rename(pid))
        m.addAction("Gộp với nhóm giống nhóm này…", lambda: self.suggest_merges(pid))
        m.exec(grid.viewport().mapToGlobal(pos))

    def rename(self, pid=None):
        # nút bấm truyền vào False/True (tín hiệu clicked), không phải mã người: chỉ nhận số nguyên thật
        pid = pid if (isinstance(pid, int) and not isinstance(pid, bool)) else self.pid
        r = self.ctx.db.one("SELECT name FROM persons WHERE id=?", (pid,))
        name, ok = QInputDialog.getText(self, "Đặt tên", "Tên người này:", text=(r["name"] or "") if r else "")
        if ok:
            cluster.rename_person(self.ctx.db, pid, name)
            self.ctx.changed.emit()

    def merge(self):
        others = [p for p in self.ctx.db.persons() if p["id"] != self.pid]
        if not others:
            return
        labels = [f"{p['name'] or 'Chưa đặt tên'} · {p['n']} ảnh · #{p['id']}" for p in others]
        s, ok = QInputDialog.getItem(self, "Gộp", "Gộp nhóm này vào:", labels, 0, False)
        if ok:
            cluster.merge_persons(self.ctx.db, self.pid, others[labels.index(s)]["id"])
            self.pid = None
            self.stack.setCurrentIndex(0)
            self.ctx.changed.emit()

    def hide(self):
        self.ctx.db.x("UPDATE persons SET hidden=1 WHERE id=?", (self.pid,))
        self.pid = None
        self.stack.setCurrentIndex(0)
        self.ctx.changed.emit()

    def expand_main(self):
        """Toàn màn hình cho ảnh của người này (giữ nguyên cách chia cụm khi đang ở 'Tất cả')."""
        if self.cloth_row.value is not None:
            self.photos.expand(self.pname.text() and "Ảnh của người này")
            return
        dlg = QDialog(self.window())
        dlg.setWindowTitle("Ảnh của người này")
        lay = QVBoxLayout(dlg)
        top = QHBoxLayout()
        top.addStretch(1)
        closeb = QPushButton("Đóng")
        closeb.clicked.connect(dlg.accept)
        top.addWidget(closeb)
        lay.addLayout(top)
        big = GroupedPhotos(self.ctx, self, extra_actions=[("Không phải người này (gỡ khỏi nhóm)", self.remove_sel)])
        lay.addWidget(big, 1)

        def fill():
            big.set_groups({k: [it for it in pg.model.items] for k, (_, pg, _) in self.grouped.parts.items()})
        fill()
        self.ctx.changed.connect(fill)
        dlg.finished.connect(lambda _: self.ctx.changed.disconnect(fill))
        dlg.showMaximized()
        dlg.exec()

    def expand_guess(self):
        self.guess.expand("Có thể cũng là người này")

    def accept_guess(self, sel):
        ids = [s["id"] for s in sel] if sel else [x["id"] for x in self.ctx.db.person_guesses(self.pid)]
        cluster.accept_guesses(self.ctx.db, self.pid, ids)
        self.ctx.changed.emit()

    def reject_guess(self, sel):
        cluster.reject_guesses(self.ctx.db, self.pid, [s["id"] for s in sel])
        self.ctx.changed.emit()

    def remove_sel(self, sel):
        ids = [s["id"] for s in sel]
        cluster.remove_from_person(self.ctx.db, self.pid, ids)
        self._undo = (self.pid, ids)                           # bấm nhầm thì "Hoàn tác" trong 30 giây; sau đó vẫn lấy lại được bằng Thêm vào người…
        self.undo_lab.setText(f"Đã loại {len(ids)} ảnh khỏi người này.")
        self.undo_bar.setVisible(True)
        self.undo_t.start(30000)
        self.ctx.changed.emit()

    def undo_remove(self):
        if getattr(self, "_undo", None):
            pid, ids = self._undo
            cluster.restore_to_person(self.ctx.db, ids, pid)
            self._undo = None
            self.undo_bar.setVisible(False)
            self.ctx.changed.emit()


# ---------------------------------------------------------------- Ảnh trùng lặp
class DupWorker(QThread):
    done = Signal(object)

    def __init__(self, db):
        super().__init__()
        self.db = db

    def run(self):
        try:
            self.done.emit(dup.find_groups(self.db))
        except Exception as e:
            self.done.emit(str(e))


class DuplicatesPage(Page):
    """Danh sách các cụm ảnh trùng, ảnh xem trước lớn để đối chiếu. Loại ảnh không trùng khỏi cụm, rồi xác nhận xóa bản thừa."""
    PER_PAGE = 8

    def __init__(self, ctx):
        super().__init__(ctx)
        self.groups, self.worker, self.page_no = [], None, 0
        self.v.addWidget(title("Ảnh trùng lặp", "Mỗi khung là một cụm ảnh giống nhau. Ảnh có độ phân giải cao nhất được giữ lại (viền xanh), các bản còn lại sẽ bị xóa. "
                                                "Ảnh nào không thật sự trùng thì bấm “Không trùng” để loại khỏi cụm; kiểm tra xong bấm “Xác nhận xóa”."))
        bar = QHBoxLayout()
        self.find_b = QPushButton("Tìm lại ảnh trùng")
        self.find_b.clicked.connect(self.find)
        self.prev_b, self.next_b = QPushButton("‹ Trang trước"), QPushButton("Trang sau ›")
        self.prev_b.clicked.connect(lambda: self.go(-1))
        self.next_b.clicked.connect(lambda: self.go(1))
        self.pg = QLabel()
        self.auto = QCheckBox("Tự ẩn ảnh trùng sau mỗi lần quét")
        self.auto.setChecked(ctx.db.get_meta("dup_auto", "1") == "1")
        self.auto.toggled.connect(lambda c: ctx.db.set_meta("dup_auto", "1" if c else "0"))
        for x in (self.find_b, self.prev_b, self.pg, self.next_b, self.auto):
            bar.addWidget(x)
        bar.addStretch(1)
        self.v.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.body = QWidget()
        self.bl = QVBoxLayout(self.body)
        self.bl.setSpacing(18)
        self.scroll.setWidget(self.body)
        self.v.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        self.cnt = QLabel()
        self.cnt.setStyleSheet("font-weight:600")
        self.hide_b = QPushButton("Chỉ ẩn, không xóa")
        self.hide_b.clicked.connect(self.hide_only)
        self.restore_b = QPushButton("Bỏ ẩn tất cả")
        self.restore_b.clicked.connect(self.restore_all)
        self.del_b = QPushButton("Xác nhận xóa bản thừa…")
        self.del_b.setProperty("primary", True)
        self.del_b.clicked.connect(self.confirm_delete)
        foot.addWidget(self.cnt, 1)
        for x in (self.restore_b, self.hide_b, self.del_b):
            foot.addWidget(x)
        self.v.addLayout(foot)

    # ---- dữ liệu ----
    def refresh(self):
        if not self.groups and not (self.worker and self.worker.isRunning()):
            self.find()
        else:
            self.render()

    def find(self):
        if self.worker and self.worker.isRunning():
            return
        self.cnt.setText("Đang tìm ảnh trùng…")
        self.worker = DupWorker(self.ctx.db)
        self.worker.done.connect(self.on_found)
        self.worker.start()

    def on_found(self, res):
        if isinstance(res, str):
            self.cnt.setText("Lỗi: " + res)
            return
        self.groups = res
        if self.ctx.db.get_meta("dup_auto", "1") == "1":
            dup.apply(self.ctx.db, self.groups)
        self.page_no = 0
        self.render()

    def go(self, d):
        n = max(1, (len(self.groups) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page_no = max(0, min(n - 1, self.page_no + d))
        self.render()

    # ---- giao diện ----
    @staticmethod
    def _clear(layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _sizes(self, ids):
        out = {}
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            for r in self.ctx.db.q(f"SELECT id,size FROM images WHERE id IN ({','.join('?' * len(part))})", part):
                out[r["id"]] = r["size"] or 0
        return out

    def render(self):
        self._clear(self.bl)
        n_pages = max(1, (len(self.groups) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page_no = min(self.page_no, n_pages - 1)
        self.pg.setText(f"Trang {self.page_no + 1}/{n_pages}")
        self.prev_b.setEnabled(self.page_no > 0)
        self.next_b.setEnabled(self.page_no < n_pages - 1)
        extra = sum(len(g["members"]) - 1 for g in self.groups)
        items, skipped = dup.confirmed_items(self.ctx.db, self.groups)
        mb = sum(s for _, _, s in items) / 1048576
        self.cnt.setText(f"{len(self.groups)} cụm · {extra} ảnh thừa · sẽ xóa {len(items)} tệp (≈ {mb:.0f} MB)" + (f" · {skipped} ảnh trong file nén/Kho không xóa được" if skipped else ""))
        self.del_b.setEnabled(bool(items))
        if not self.groups:
            self.bl.addWidget(QLabel("Không có ảnh trùng nào."))
        start = self.page_no * self.PER_PAGE
        for k, g in enumerate(self.groups[start:start + self.PER_PAGE], start + 1):
            self.bl.addWidget(self._card(k, g))
        self.bl.addStretch(1)

    def _card(self, k, g):
        db = self.ctx.db
        imgs = db.images_by_ids(g["members"])
        sizes = self._sizes(g["members"])
        total = sum(sizes[i["id"]] for i in imgs if i["id"] != g["keep"]) / 1048576
        card = QFrame()
        card.setObjectName("dupcard")
        card.setStyleSheet(f"QFrame#dupcard{{border:2px solid #A9793D;border-radius:8px;background:{theme.CARD}}}")
        v = QVBoxLayout(card)
        head = QHBoxLayout()
        t = QLabel(f"<b>Cụm {k}</b> · {len(imgs)} ảnh giống nhau · giải phóng ≈ {total:.1f} MB")
        t.setStyleSheet("border:0")
        nb = QPushButton("Cả cụm không trùng")
        nb.clicked.connect(lambda _=False, g=g: self.drop_group(g))
        head.addWidget(t, 1)
        head.addWidget(nb)
        v.addLayout(head)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setFixedHeight(380)
        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setSpacing(12)
        for r in imgs:
            row.addWidget(self._tile(g, imgs, r, sizes))
        row.addStretch(1)
        sc.setWidget(inner)
        sc.setStyleSheet("QScrollArea{border:0;background:transparent}")
        v.addWidget(sc)
        return card

    def _tile(self, g, imgs, r, sizes):
        keep = r["id"] == g["keep"]
        w = QFrame()
        w.setObjectName("duptile")
        w.setStyleSheet("QFrame#duptile{border:3px solid %s;border-radius:6px;background:#fff}" % ("#2e7d32" if keep else "#c0392b"))
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 6, 6, 6)
        pm = QPixmap()
        try:
            pm.loadFromData(SEC.read_file(r["thumb"]))
        except Exception:
            pass
        im = QLabel()
        im.setAlignment(Qt.AlignCenter)
        im.setFixedSize(300, 220)
        im.setStyleSheet("border:0;background:" + theme.PLACE)
        if not pm.isNull():
            im.setPixmap(pm.scaled(292, 212, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        im.setCursor(Qt.PointingHandCursor)
        idx = [x["id"] for x in imgs].index(r["id"])
        items = [img_item(x) for x in imgs]
        im.mousePressEvent = lambda e, items=items, idx=idx: open_viewer(self.window(), items, idx, self.ctx)
        v.addWidget(im)
        name = r["name"] or os.path.basename(r["path"])
        lab = QLabel(f"<b>{name}</b><br>{r['w']} × {r['h']} · {sizes.get(r['id'], 0) / 1048576:.2f} MB<br><span style='color:{theme.MUTED}'>{(r['taken'] or '')[:10]}</span>")
        lab.setStyleSheet("border:0")
        lab.setWordWrap(True)
        lab.setFixedWidth(292)
        v.addWidget(lab)
        tag = QLabel("GIỮ LẠI · độ phân giải cao nhất" if keep else "SẼ XÓA")
        tag.setStyleSheet("border:0;font-weight:700;color:%s" % ("#2e7d32" if keep else "#c0392b"))
        v.addWidget(tag)
        b = QPushButton("Không trùng, loại khỏi cụm")
        b.clicked.connect(lambda _=False, g=g, i=r["id"]: self.drop_image(g, i))
        v.addWidget(b)
        return w

    # ---- thao tác ----
    def drop_image(self, g, iid):
        dup.restore(self.ctx.db, [iid])                       # ảnh trở lại bình thường và không bị gom lại lần sau
        g["members"] = [i for i in g["members"] if i != iid]
        if len(g["members"]) < 2:
            self.groups = [x for x in self.groups if x is not g]
        else:
            dup.rekeep(self.ctx.db, g)
            dup.apply(self.ctx.db, self.groups)
        self.ctx.changed.emit()

    def drop_group(self, g):
        dup.restore(self.ctx.db, g["members"])
        self.groups = [x for x in self.groups if x is not g]
        self.ctx.changed.emit()

    def hide_only(self):
        dup.apply(self.ctx.db, self.groups)
        self.ctx.changed.emit()

    def restore_all(self):
        dup.restore_all(self.ctx.db)
        self.ctx.changed.emit()

    def confirm_delete(self):
        items, skipped = dup.confirmed_items(self.ctx.db, self.groups)
        if not items:
            QMessageBox.information(self, "Xóa bản thừa", "Không có tệp nào xóa được (ảnh trong file nén hoặc Kho mã hóa không xóa được từ đây).")
            return
        mb = sum(s for _, _, s in items) / 1048576
        box = QMessageBox(self)
        box.setWindowTitle("Xác nhận xóa bản thừa")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Xóa <b>{len(items)}</b> ảnh thừa trong thư mục gốc (khoảng {mb:.0f} MB)? Mỗi cụm chỉ giữ lại ảnh có độ phân giải cao nhất.")
        box.setInformativeText("Tệp được chuyển vào Thùng rác của Windows nên khôi phục được. Hãy chắc bạn đã loại các ảnh không thật sự trùng khỏi cụm."
                               + (f"\n{skipped} ảnh trong file nén hoặc Kho mã hóa sẽ không bị xóa." if skipped else ""))
        yes = box.addButton("Xóa bản thừa", QMessageBox.DestructiveRole)
        box.addButton("Hủy", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        n, errs = dup.trash_images(self.ctx.db, items)
        self.ctx.db.snapshot()
        self.groups = []
        self.ctx.changed.emit()
        msg = f"Đã chuyển {n} tệp vào Thùng rác."
        if errs:
            msg += f"\n{len(errs)} tệp không xóa được:\n" + "\n".join(errs[:5])
        QMessageBox.information(self, "Xong", msg)
        self.find()


# ---------------------------------------------------------------- Ảnh tương tự
class SimilarPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.groups = []
        self.v.addWidget(title("Ảnh tương tự", "Gom các ảnh cùng cảnh, cùng góc nhìn hoặc gần giống nhau (kể cả ảnh chụp liên tiếp)."))
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Độ giống:"))
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(75, 99)
        self.sl.setValue(90)
        self.sl.setFixedWidth(180)
        self.lab = QLabel("0.90")
        self.sl.valueChanged.connect(lambda v: self.lab.setText(f"{v / 100:.2f}"))
        b = QPushButton("Gom nhóm")
        b.clicked.connect(self.run)
        self.info = QLabel()
        for x in (self.sl, self.lab, b):
            bar.addWidget(x)
        bar.addStretch(1)
        bar.addWidget(self.info)
        self.v.addLayout(bar)
        self.stack = QStackedWidget()
        self.v.addWidget(self.stack, 1)
        self.gmodel = ThumbModel()
        self.ggrid = make_grid(self.gmodel, 140, True)
        self.ggrid.clicked.connect(self.open_group)
        self.stack.addWidget(self.ggrid)
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        back = QPushButton("← Quay lại")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        l.addWidget(back, 0, Qt.AlignLeft)
        self.photos = PhotoGrid(ctx, self)
        l.addWidget(self.photos, 1)
        self.stack.addWidget(w)

    def run(self):
        ids, mat = self.ctx.db.clip_matrix()
        if not ids:
            QMessageBox.information(self, "Chưa có dữ liệu", "Cần tải mô hình và quét ảnh (mục Cài đặt) trước.")
            return
        self.groups = cluster.group_similar(ids, mat, self.sl.value() / 100)
        self.info.setText(f"{len(self.groups)} nhóm")
        items = []
        for k, g in enumerate(self.groups):
            r = self.ctx.db.images_by_ids(g[:1])[0]
            items.append({"thumb": r["thumb"], "key": f"g{k}{r['thumb']}", "gi": k, "label": f"{len(g)} ảnh"})
        self.gmodel.set_items(items)
        self.stack.setCurrentIndex(0)

    def open_group(self, idx):
        g = self.groups[idx.data(Qt.UserRole)["gi"]]
        self.photos.set_items([img_item(r) for r in self.ctx.db.images_by_ids(g)])
        self.stack.setCurrentIndex(1)


# ---------------------------------------------------------------- Tìm kiếm
class SearchPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Mô tả ảnh cần tìm (ví dụ: phía sau, bàn chân, biển, family photo)…")
        self.q.setToolTip("Gõ mô tả bằng tiếng Việt hoặc tiếng Anh. Bộ nhận dạng hiểu tiếng Anh tốt nhất; một số từ tiếng Việt thông dụng được dịch tự động.")
        self.q.setMinimumWidth(420)
        self.q.setFixedHeight(RoundBtn.D)
        self.q.setStyleSheet("QLineEdit{border-radius:22px;padding:0 16px;background:rgba(0,0,0,110);border:1.5px solid rgba(255,255,255,150)}")
        self.q.returnPressed.connect(self.run)
        go = RoundBtn("enter", "Tìm")
        go.clicked.connect(self.run)
        panel = QWidget()                                         # từ khóa gợi ý và tùy chọn: mặc định ẩn cho gọn, mở trong nút ⋯
        panel_l = QVBoxLayout(panel)
        panel_l.setContentsMargins(14, 0, 14, 4)
        self.people_only = QCheckBox("Chỉ ảnh có người")
        self.people_only.setChecked(True)
        self.people_only.setToolTip("Bỏ qua ảnh phong cảnh, nội thất… khi tìm theo tư thế, dáng người, trang phục")
        panel_l.addWidget(self.people_only)
        self.chips = {}                                           # từ khóa gợi ý theo nhóm (tư thế, dáng người, bộ phận, trang phục…): bấm để thêm / bỏ khỏi ô tìm
        for cat, items in vi.CATALOG.items():
            row = QHBoxLayout()
            lab = QLabel(cat)
            lab.setFixedWidth(84)
            lab.setStyleSheet("font-weight:700;color:#A9793D")
            row.addWidget(lab)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            for word, _en in items:
                b = QPushButton(word)
                b.setCheckable(True)
                b.setStyleSheet("QPushButton{padding:3px 10px;border-radius:12px}")
                b.clicked.connect(lambda _=False, w=word: self.toggle_word(w))
                hl.addWidget(b)
                self.chips[word] = b
            hl.addStretch(1)
            sc = QScrollArea()
            sc.setWidget(holder)
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setFixedHeight(40)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            row.addWidget(sc, 1)
            panel_l.addLayout(row)
        panel.setVisible(False)
        self.info = QLabel()
        self.info.setStyleSheet("padding:0 16px")
        self.grid = PhotoGrid(ctx, self)
        holder = QWidget()
        hh = QHBoxLayout(holder)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(8)
        hh.addWidget(self.q, 1)
        hh.addWidget(go)
        self.grid.bar.set_center(holder)
        self.grid.layout().insertWidget(1, panel)
        self.grid.layout().insertWidget(2, self.info)
        self.grid.bar.menu_extra = lambda m: (m.addAction("Từ khóa gợi ý và tùy chọn…", lambda: panel.setVisible(not panel.isVisible())), m.addSeparator())
        self.v.addWidget(self.grid, 1)


    def toggle_word(self, word):
        words = [w.strip() for w in re.split(r"[,;+]", self.q.text()) if w.strip()]
        if word in words:
            words.remove(word)
        else:
            words.append(word)
        self.q.setText(", ".join(words))
        for w, b in self.chips.items():
            b.setChecked(w in words)
        self.run()

    def run(self):
        text = self.q.text().strip()
        if not text:
            return
        clip = self.ctx.clip()
        if clip is None:
            QMessageBox.information(self, "Chưa có mô hình", "Cần tải mô hình ở mục Cài đặt trước.")
            return
        prompts = vi.prompts_for(text)
        en = ", ".join(vi.phrases(text))
        ids, mat = self.ctx.db.clip_matrix()
        if not ids:
            self.info.setText("Chưa có ảnh nào được phân tích.")
            return
        if self.people_only.isChecked():                          # chỉ giữ ảnh chụp người (gần "a photo of a person" hơn "phong cảnh, nội thất…")
            pos, neg = clip.text("a photo of a person"), clip.text("a photo of a landscape, a building, a room or an object")
            m = cluster._unit(mat.astype("float32"))
            keep = (m @ cluster._unit(pos)) - (m @ cluster._unit(neg)) > 0.0
            ids, mat = [i for i, k in zip(ids, keep) if k], mat[keep]
        qv = cluster.prototype(np.stack([clip.text(p) for p in prompts]))                 # trung bình nhiều câu mô tả cho ổn định
        res = cluster.rank(ids, mat, qv, top=200)
        rows = {r["id"]: r for r in self.ctx.db.images_by_ids([i for i, _ in res])}
        self.info.setText(f"Đang tìm theo: “{en}”" if en != text else "")
        self.grid.set_items([img_item(rows[i], {"tip": f"{rows[i]['path']}\nđộ khớp {s:.2f}"}) for i, s in res if i in rows])


# ---------------------------------------------------------------- Nhãn
class AutoLabelDialog(QDialog):
    """Xem các gợi ý phân loại tự động theo từng nhãn rồi chọn thêm vào nhãn; có thể bật tự gán khi rất chắc và hoàn tác."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Tự động phân loại ảnh")
        self.resize(1100, 700)
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Tự động phân loại</h2>Dựa trên những ảnh bạn đã gắn vào từng nhãn (cần ít nhất 3 ảnh mẫu mỗi nhãn), "
                           "ứng dụng đề xuất nhãn cho các ảnh chưa có nhãn. Bạn xem lại, bỏ chọn ảnh sai rồi thêm vào nhãn."))
        self.sug = {}
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setFixedWidth(260)
        self.list.currentRowChanged.connect(self.show_label)
        row.addWidget(self.list)
        right = QVBoxLayout()
        bar = QHBoxLayout()
        self.cap = QLabel()
        self.add_b = QPushButton("Thêm ảnh đã chọn vào nhãn")
        self.add_b.clicked.connect(self.add_selected)
        self.all_b = QPushButton("Chọn tất cả ảnh của nhãn này")
        self.all_b.clicked.connect(lambda: self.grid.grid.select_all())
        self.no_b = QPushButton("Không phải nhãn này (đừng gợi ý nữa)")
        self.no_b.clicked.connect(self.reject_selected)
        bar.addWidget(self.cap, 1)
        for x in (self.all_b, self.add_b, self.no_b):
            bar.addWidget(x)
        right.addLayout(bar)
        self.grid = PhotoGrid(ctx, parent if isinstance(parent, Page) else Page(ctx))
        right.addWidget(self.grid, 1)
        row.addLayout(right, 1)
        l.addLayout(row, 1)
        foot = QHBoxLayout()
        self.auto_cb = QCheckBox("Tự gán nhãn khi rất chắc (từ 92%) sau mỗi lần quét")
        self.auto_cb.setChecked(ctx.db.get_meta("label_auto", "1") == "1")
        self.auto_cb.toggled.connect(lambda c: ctx.db.set_meta("label_auto", "1" if c else "0"))
        undo = QPushButton("Hoàn tác các nhãn đã tự gán")
        undo.clicked.connect(self.undo)
        close = QPushButton("Đóng")
        close.clicked.connect(self.accept)
        foot.addWidget(self.auto_cb)
        foot.addWidget(undo)
        foot.addStretch(1)
        foot.addWidget(close)
        l.addLayout(foot)
        self.reload()

    def reload(self):
        db = self.ctx.db
        self.sug = autolabel.suggest(db)
        names = {r["id"]: r["name"] for r in db.labels()}
        self.lids = sorted(self.sug, key=lambda k: -len(self.sug[k]))
        self.list.blockSignals(True)
        self.list.clear()
        for lid in self.lids:
            v = self.sug[lid]
            self.list.addItem(f"{names.get(lid, '?')}  ·  {len(v)} ảnh  ·  TB {int(sum(s for _, s in v) / len(v) * 100)}%")
        self.list.blockSignals(False)
        if self.lids:
            self.list.setCurrentRow(0)
        else:
            self.grid.set_items([])
            self.cap.setText("Chưa có gợi ý. Cần nhãn có từ 3 ảnh mẫu trở lên và ảnh chưa có nhãn giống chúng.")
        self.show_label()

    def cur(self):
        r = self.list.currentRow()
        return self.lids[r] if 0 <= r < len(self.lids) else None

    def show_label(self, *_):
        lid = self.cur()
        if lid is None:
            return
        v = self.sug[lid]
        imgs = {r["id"]: r for r in self.ctx.db.images_by_ids([i for i, _ in v])}
        self.cap.setText(f"<b>{len(v)}</b> ảnh gợi ý. Bấm vòng tròn ở góc ảnh để chọn, hoặc “Chọn tất cả”.")
        self.grid.set_items([img_item(imgs[i], {"cap_tag": f"giống {int(s * 100)}%", "tip": f"{imgs[i]['path']}\nđộ giống {s:.2f}"}) for i, s in v])

    def add_selected(self):
        lid, sel = self.cur(), self.grid.selected()
        if lid and sel:
            autolabel.apply(self.ctx.db, lid, [s["id"] for s in sel])
            self.reload()

    def reject_selected(self):
        lid, sel = self.cur(), self.grid.selected()
        if lid and sel:
            autolabel.reject(self.ctx.db, lid, [s["id"] for s in sel])
            self.reload()

    def undo(self):
        n = autolabel.undo_auto(self.ctx.db)
        QMessageBox.information(self, "Hoàn tác", f"Đã gỡ {n} nhãn tự gán.")
        self.reload()


class LabelsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.v.addWidget(title("Nhãn (góc nhìn, bộ phận…)", "Tạo nhãn như “phía trước”, “phía sau”, “bàn chân”. Chọn vài ảnh mẫu (chuột phải ở mục All → Thêm vào nhãn), rồi bấm “Gợi ý” để ứng dụng tìm các ảnh giống mẫu."))
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setFixedWidth(220)
        self.list.currentRowChanged.connect(self.show_label)
        row.addWidget(self.list)
        right = QVBoxLayout()
        bar = QHBoxLayout()
        self.cap = QLabel()
        nb = QPushButton("Nhãn mới")
        nb.clicked.connect(self.new)
        self.sug = QPushButton("Gợi ý ảnh giống")
        self.sug.clicked.connect(self.suggest)
        self.addb = QPushButton("Thêm ảnh đã chọn vào nhãn")
        self.addb.clicked.connect(self.add_sel)
        rm = QPushButton("Gỡ ảnh đã chọn khỏi nhãn")
        rm.clicked.connect(self.rm_sel)
        dl = QPushButton("Xóa nhãn")
        dl.clicked.connect(self.delete)
        rn = QPushButton("Đổi tên nhãn")
        rn.clicked.connect(self.rename)
        self.auto_b = QPushButton("Tự động phân loại…")
        self.auto_b.setToolTip("Gợi ý nhãn cho các ảnh chưa có nhãn, dựa trên những ảnh bạn đã gắn")
        self.auto_b.clicked.connect(self.auto_classify)
        bar.addWidget(self.cap, 1)
        for x in (nb, rn, self.auto_b, self.sug, self.addb, rm, dl):
            bar.addWidget(x)
        right.addLayout(bar)
        hr = QHBoxLayout()
        hr.addWidget(QLabel("Khi gợi ý, ẩn ảnh đã gắn nhãn:"))
        self.hide_c = QComboBox()
        for k, t in (("none", "không ẩn"), ("this", "đã có trong nhãn này"), ("any", "đã có trong bất kỳ nhãn nào")):
            self.hide_c.addItem(t, k)
        self.hide_c.setCurrentIndex(1)
        self.hide_c.currentIndexChanged.connect(lambda _: self.suggesting and self.suggest())
        hr.addWidget(self.hide_c)
        hr.addSpacing(18)
        hr.addWidget(QLabel("Chọn nhanh ảnh giống từ"))
        self.pick_c = QComboBox()
        for thr, t in ((0.90, "90% trở lên"), (0.85, "85% trở lên"), (0.80, "80% trở lên"), (0.75, "75% trở lên")):
            self.pick_c.addItem(t, thr)
        self.pick_c.setCurrentIndex(1)
        hr.addWidget(self.pick_c)
        self.pick_b = QPushButton("Chọn ảnh tương tự")
        self.pick_b.setToolTip("Chọn các ảnh gợi ý có độ giống đạt mức này, rồi bấm “Thêm … vào nhãn”")
        self.pick_b.clicked.connect(self.pick_similar)
        hr.addWidget(self.pick_b)
        hr.addStretch(1)
        right.addLayout(hr)
        self.grid = PhotoGrid(ctx, self)
        self.grid.grid.selectionChanged.connect(lambda n: self.addb.setText(f"Thêm {n} ảnh đã chọn vào nhãn" if n else "Thêm ảnh đã chọn vào nhãn"))
        right.addWidget(self.grid, 1)
        row.addLayout(right, 1)
        self.v.addLayout(row, 1)
        self.lids, self.suggesting = [], False
        self.sug_scores = {}

    def refresh(self):
        cur = self.list.currentRow()
        ls = self.ctx.db.labels()
        self.lids = [r["id"] for r in ls]
        self.list.blockSignals(True)
        self.list.clear()
        for r in ls:
            self.list.addItem(f"{r['name']}  ({r['n']})")
        self.list.blockSignals(False)
        if self.lids:
            self.list.setCurrentRow(min(max(cur, 0), len(self.lids) - 1))
        self.show_label()

    def cur(self):
        r = self.list.currentRow()
        return self.lids[r] if 0 <= r < len(self.lids) else None

    def show_label(self, *_):
        lid = self.cur()
        self.suggesting = False
        if lid is None:
            self.cap.setText("Chưa có nhãn nào.")
            self.grid.set_items([])
            return
        ids = self.ctx.db.label_ids(lid)
        self.cap.setText(f"<b>{len(ids)}</b> ảnh trong nhãn")
        self.grid.set_items([img_item(r) for r in self.ctx.db.images_by_ids(ids)] if ids else [])

    def new(self):
        name, ok = QInputDialog.getText(self, "Nhãn mới", "Tên nhãn:")
        if ok and name.strip():
            self.ctx.db.x("INSERT OR IGNORE INTO labels(name) VALUES(?)", (name.strip(),))
            self.ctx.changed.emit()

    def auto_classify(self):
        AutoLabelDialog(self.ctx, self).exec()
        self.ctx.changed.emit()

    def rename(self):
        lid = self.cur()
        if lid is None:
            return
        old = self.ctx.db.one("SELECT name FROM labels WHERE id=?", (lid,))["name"]
        name, ok = QInputDialog.getText(self, "Đổi tên nhãn", "Tên mới:", text=old)
        name = name.strip()
        if not ok or not name or name == old:
            return
        if self.ctx.db.one("SELECT 1 FROM labels WHERE name=? AND id<>?", (name, lid)):
            QMessageBox.warning(self, "Trùng tên", f"Đã có nhãn tên “{name}”. Hãy chọn tên khác.")
            return
        self.ctx.db.x("UPDATE labels SET name=? WHERE id=?", (name, lid))
        self.ctx.changed.emit()

    def delete(self):
        lid = self.cur()
        if lid and QMessageBox.question(self, "Xóa nhãn", "Xóa nhãn này? (ảnh không bị xóa)") == QMessageBox.Yes:
            self.ctx.db.x("DELETE FROM label_images WHERE label_id=?", (lid,))
            self.ctx.db.x("DELETE FROM labels WHERE id=?", (lid,))
            self.ctx.changed.emit()

    def suggest(self):
        lid = self.cur()
        if lid is None:
            return
        members = self.ctx.db.label_ids(lid)
        ids, mat = self.ctx.db.clip_matrix()
        pos = {i: k for k, i in enumerate(ids)}
        rows = [pos[i] for i in members if i in pos]
        if not rows:
            QMessageBox.information(self, "Chưa có mẫu", "Hãy thêm vài ảnh mẫu vào nhãn trước (chuột phải ở ảnh → Thêm vào nhãn).")
            return
        res = cluster.rank(ids, mat, cluster.prototype(mat[rows]), top=len(ids))
        mode = self.hide_c.currentData()
        if mode == "any":
            skip = {x["image_id"] for x in self.ctx.db.q("SELECT DISTINCT image_id FROM label_images")}
        elif mode == "this":
            skip = set(members)
        else:
            skip = set()
        res = [(i, s) for i, s in res if i not in skip and i not in set(members)][:200]
        imgs = {r["id"]: r for r in self.ctx.db.images_by_ids([i for i, _ in res])}
        self.suggesting = True
        self.cap.setText("<b>Gợi ý</b>: bấm vào vòng tròn ở góc những ảnh đúng (hoặc “Chọn tất cả”), rồi bấm “Thêm … vào nhãn”")
        self.sug_scores = {i: s for i, s in res}
        self.grid.set_items([img_item(imgs[i], {"tip": f"{imgs[i]['path']}\nđộ giống {s:.2f}", "cap_tag": f"giống {int(s * 100)}%"}) for i, s in res])

    def pick_similar(self):
        """Trong danh sách gợi ý: chọn sẵn mọi ảnh có độ giống đạt mức đã chọn (nếu chưa gợi ý thì gợi ý trước)."""
        if not self.suggesting:
            self.suggest()
        if not self.suggesting:
            return
        thr = float(self.pick_c.currentData())
        rows = [r for r, it in enumerate(self.grid.model.items) if self.sug_scores.get(it.get("id"), 0) >= thr]
        self.grid.grid.select_rows(rows)
        self.cap.setText(f"<b>Gợi ý</b>: đã chọn sẵn {len(rows)} ảnh giống từ {int(thr * 100)}%. Bỏ chọn ảnh sai rồi bấm “Thêm … vào nhãn”")

    def add_sel(self):
        lid, sel = self.cur(), self.grid.selected()
        if lid and sel:
            keep = self.suggesting
            for s in sel:
                self.ctx.db.c.execute("INSERT OR IGNORE INTO label_images VALUES(?,?)", (lid, s["id"]))
            self.ctx.db.commit()
            self.ctx.changed.emit()
            if keep:                       # đang xem gợi ý: tiếp tục với danh sách gợi ý mới (đã bỏ các ảnh vừa thêm)
                self.suggest()

    def rm_sel(self):
        lid, sel = self.cur(), self.grid.selected()
        if lid and sel and not self.suggesting:
            autolabel.reject(self.ctx.db, lid, [s["id"] for s in sel])
            for s in sel:
                self.ctx.db.c.execute("DELETE FROM label_images WHERE label_id=? AND image_id=?", (lid, s["id"]))
            self.ctx.db.commit()
            self.ctx.changed.emit()


# ---------------------------------------------------------------- Kho riêng tư
class VaultPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.v.addWidget(title("Kho riêng tư", "Ảnh được mã hóa AES-256 bằng mật khẩu của bạn. Khi xem, ảnh chỉ được giải mã trong bộ nhớ, không lưu ra ổ đĩa."))
        self.stack = QStackedWidget()
        self.v.addWidget(self.stack, 1)
        # màn hình khóa
        w = QWidget()
        l = QVBoxLayout(w)
        l.addStretch(1)
        self.msg = QLabel()
        self.msg.setAlignment(Qt.AlignCenter)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Mật khẩu")
        self.pw.setFixedWidth(280)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.Password)
        self.pw2.setPlaceholderText("Nhập lại mật khẩu (khi tạo kho)")
        self.pw2.setFixedWidth(280)
        self.go = QPushButton()
        self.go.setFixedWidth(280)
        self.go.clicked.connect(self.unlock)
        self.pw.returnPressed.connect(self.unlock)
        self.err = QLabel()
        self.err.setStyleSheet("color:#c0392b")
        self.err.setAlignment(Qt.AlignCenter)
        for x in (self.msg, self.pw, self.pw2, self.go, self.err):
            l.addWidget(x, 0, Qt.AlignHCenter)
        l.addStretch(2)
        self.stack.addWidget(w)
        # nội dung
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.count = QLabel()
        bar.addWidget(self.count, 1)
        self.legacy_btns = []
        for text, fn in [("Thêm ảnh…", self.add_files), ("Thêm cả thư mục…", self.add_folder),
                         ("Xuất ảnh đã chọn…", self.export), ("Xóa ảnh đã chọn", self.delete),
                         ("Đổi mật khẩu", self.chpw), ("Khóa kho", self.lock)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
            if text in ("Đổi mật khẩu", "Khóa kho"):
                self.legacy_btns.append(b)
        l2.addLayout(bar)
        self.model = ThumbModel()
        self.grid = JustifiedView(self.model)
        self.grid.activated.connect(lambda i: Viewer(self.model.items, i.row(),
                                                     lambda it: load_qimage(self.ctx.vault.read(it["vid"])), self.window(),
                                                     self.model, self.grid.reveal).showMaximized())
        l2.addWidget(self.grid, 1)
        self.stack.addWidget(w2)
        self.timer = QTimer(self)
        self.timer.setInterval(10 * 60 * 1000)   # tự khóa sau 10 phút không thao tác
        self.timer.timeout.connect(self.lock)
        self.grid.viewport().installEventFilter(self)

    def eventFilter(self, o, e):
        if self.ctx.vault.unlocked() and not self.ctx.attached:
            self.timer.start()
        return False

    def refresh(self):
        v = self.ctx.vault
        if not v.unlocked():
            self.stack.setCurrentIndex(0)
            if v.exists():
                self.msg.setText("Kho đang khóa. Nhập mật khẩu để mở.")
                self.go.setText("Mở khóa")
                self.pw2.hide()
            else:
                self.msg.setText("Chưa có Kho riêng tư. Đặt mật khẩu (ít nhất 6 ký tự) để tạo.\nQuên mật khẩu thì KHÔNG thể lấy lại ảnh.")
                self.go.setText("Tạo kho")
                self.pw2.show()
            return
        self.stack.setCurrentIndex(1)
        for b in self.legacy_btns:
            b.setVisible(not self.ctx.attached)
        if not self.ctx.attached:
            self.timer.start()
        self.count.setText(f"{len(v.index)} ảnh trong kho" if v.index else
                           "Kho đang trống. Ảnh vào Kho khi: (1) bạn quét một thư mục ở mức “mã hóa cả ảnh gốc”, hoặc (2) chuột phải ảnh → "
                           "“Mã hóa và chuyển vào kho”. Ảnh ở thư mục “giữ ảnh gốc tại chỗ” hiện ở mục All, không nằm trong Kho.")
        self.count.setWordWrap(True)
        items = []
        for e in sorted(v.index, key=lambda e: e["added"], reverse=True):
            items.append({"id": None, "vid": e["id"], "key": "v" + e["id"], "tip": f"{e['name']}\nthêm {e['added']}",
                          "w": e.get("w"), "h": e.get("h"), "cap_title": e["name"], "cap_tag": e["added"][:10],
                          "tbytes": (lambda i=e["id"]: v.thumb(i))})
        self.model.set_items(items)

    def unlock(self):
        v = self.ctx.vault
        self.err.setText("")
        try:
            if v.exists():
                v.unlock(self.pw.text())
            else:
                if self.pw.text() != self.pw2.text():
                    self.err.setText("Hai lần nhập mật khẩu không khớp.")
                    return
                v.create(self.pw.text())
        except WrongPassword:
            self.err.setText("Sai mật khẩu.")
            return
        except Exception as e:
            self.err.setText(str(e))
            return
        self.pw.clear()
        self.pw2.clear()
        self.refresh()

    def lock(self):
        self.ctx.vault.lock()
        self.model.set_items([])
        self.timer.stop()
        self.refresh()

    def add_paths(self, paths):
        n = 0
        for p in paths:
            try:
                self.ctx.vault.add(p)
                n += 1
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"{os.path.basename(p)}: {e}")
        self.refresh()
        if n:
            QMessageBox.information(self, "Xong", f"Đã mã hóa {n} ảnh. Ảnh gốc vẫn còn nguyên, bạn tự xóa nếu muốn.")

    def add_files(self):
        ps, _ = QFileDialog.getOpenFileNames(self, "Chọn ảnh", "", "Ảnh (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.heic *.heif)")
        if ps:
            self.add_paths(ps)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
        if d:
            from ..scan import iter_files
            self.add_paths([p for p, _, _ in iter_files([d])])

    def sel(self):
        return [i for i in selected_items(self.grid)]

    def export(self):
        sel = self.sel()
        if not sel:
            return
        d = QFileDialog.getExistingDirectory(self, "Xuất ảnh giải mã tới thư mục")
        if d:
            names = {e["id"]: e["name"] for e in self.ctx.vault.index}
            for s in sel:
                self.ctx.vault.export(s["vid"], os.path.join(d, names[s["vid"]]))

    def delete(self):
        sel = self.sel()
        if sel and QMessageBox.question(self, "Xóa", f"Xóa {len(sel)} ảnh khỏi kho? Không thể khôi phục.") == QMessageBox.Yes:
            for s in sel:
                self.ctx.vault.remove(s["vid"])
            self.refresh()

    def chpw(self):
        old, ok = QInputDialog.getText(self, "Đổi mật khẩu", "Mật khẩu hiện tại:", QLineEdit.Password)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, "Đổi mật khẩu", "Mật khẩu mới (ít nhất 6 ký tự):", QLineEdit.Password)
        if ok:
            try:
                self.ctx.vault.change_password(old, new)
                QMessageBox.information(self, "Xong", "Đã đổi mật khẩu.")
            except WrongPassword:
                QMessageBox.warning(self, "Lỗi", "Mật khẩu hiện tại không đúng.")
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", str(e))


# ---------------------------------------------------------------- Cài đặt / quét
LEVELS = {"data": "Giữ ảnh gốc tại chỗ (mã hóa dữ liệu phân tích)",
          "all": "Mã hóa cả ảnh gốc (nhập vào kho)"}


def scan_summary(db, r, stopped=False, auto=False):
    """Câu tóm tắt sau khi quét: bao nhiêu ảnh, và xem ở đâu."""
    parts = []
    for key, text in (("added", "{} ảnh mới"), ("updated", "{} ảnh thay đổi"), ("removed", "{} ảnh không còn trong thư mục (đã bỏ khỏi thư viện)"),
                      ("imported", "{} ảnh đã mã hóa vào Kho"), ("errors", "{} ảnh không đọc được")):
        if r.get(key):
            parts.append(text.format(r[key]))
    n = db.one("SELECT COUNT(*) c FROM images")["c"]
    e = db.one("SELECT COUNT(*) c FROM images WHERE vid IS NOT NULL")["c"]
    head = "Tự động cập nhật: " if auto else "Xong: "
    body = ", ".join(parts) if parts else "không có ảnh nào mới hoặc thay đổi"
    if r.get("locked_zips"):
        parts.append(f"{len(r['locked_zips'])} file nén có mật khẩu chưa quét được (bấm “Nhập mật khẩu file nén”)")
    tail = ". Thư viện hiện có " + count_note(db) + (f", {e} đã mã hóa trong Kho" if e else "") + ". Xem ở mục “All”."
    return head + body + tail + (" (đã dừng)" if stopped else "")


class BackupWorker(QThread):
    done = Signal(str, str)         # đường dẫn tệp (hoặc ""), lỗi (hoặc "")

    def __init__(self, db, dest, include_vault, keep):
        super().__init__()
        self.db, self.dest, self.include_vault, self.keep = db, dest, include_vault, keep

    def run(self):
        from .. import backup
        try:
            self.done.emit(backup.make_backup(self.db, self.dest, self.include_vault, self.keep), "")
        except Exception as e:
            self.done.emit("", str(e))


class SyncWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object, str)

    def __init__(self, db, dest, password, originals, vault, zip_pw):
        super().__init__()
        self.db, self.dest, self.password, self.originals, self.vault, self.zip_pw = db, dest, password, originals, vault, zip_pw
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        from .. import sync
        try:
            st = sync.run(self.db, self.dest, self.password, self.originals, self.vault, self.zip_pw,
                          lambda d, t, n: self.progress.emit(d, t, n), lambda: self._stop)
            self.db.snapshot()
            self.done.emit(st, "")
        except sync.Cancelled:
            self.done.emit(None, "Đã dừng")
        except Exception as e:
            self.done.emit(None, str(e) or type(e).__name__)


class RefWorker(QThread):
    """Chạy nền: tải ảnh tham chiếu (chỉ gửi TÊN người) cho những người đã đặt tên, tạo vectơ rồi áp dụng vào cảnh báo / gợi ý tên."""
    done = Signal(int)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        n = 0
        try:
            from .. import models, refimg
            if models.ready():
                eng = models.FaceEngine(threads=1)
                try:
                    n = refimg.run(self.db, eng, stop=lambda: self._stop)
                finally:
                    eng.close()
        except Exception:
            pass
        self.done.emit(n)


class BodyWorker(QThread):
    """Chạy nền: tải mô hình phát hiện người (một lần, khoảng 20 MB), phát hiện người cho ảnh chưa xử lý rồi tự hiệu chỉnh ngưỡng đếm người của Mashup."""
    done = Signal(int)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        n = 0
        try:
            from .. import models, cluster
            if not models.have(models.BODY_FILES):
                models.download(models.BODY_FILES, cancel=lambda: self._stop)
            if models.have(models.BODY_FILES):
                eng = models.BodyEngine()
                n = cluster.ensure_bodies(self.db, eng, stop=lambda: self._stop)
                if n and not self._stop:
                    cluster.calibrate_mashup(self.db)
        except Exception:
            pass
        self.done.emit(n)


class CoverPoolWorker(QThread):
    """Chạy nền khi máy rảnh: làm sẵn ảnh profile cho mọi người theo vòng (mỗi người 1 ảnh, rồi 2, 3… tới hết), ảnh đánh dấu sao trước."""
    done = Signal(int)

    def __init__(self, db):
        super().__init__()
        self.db = db
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        n = 0
        try:
            from .. import cover as _cv
            n = _cv.ensure_pool(self.db, lambda: self._stop, lambda: _scan_mod.wait_idle(lambda: self._stop, quiet=2.0, max_wait=10.0),
                                lambda row: (lambda: sync.read_original_any(self.db, row)))
        except Exception:
            pass
        self.done.emit(n)


class RefDialog(QDialog):
    """Ảnh tham chiếu từ internet: bật / tắt, khóa tìm kiếm web (tùy chọn) và chạy ngay."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        db = ctx.db
        self.setWindowTitle("Ảnh tham chiếu từ internet")
        self.resize(560, 360)
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Ảnh tham chiếu từ internet</h2>"))
        t = QLabel("Với những người đã có tên (đa phần là người nổi tiếng), app tự tìm vài ảnh chân dung công khai trên <b>Wikimedia Commons</b>, tạo vectơ khuôn mặt "
                   "rồi bỏ ảnh. Sau đó dùng để cảnh báo nhóm có thể gán nhầm tên, gợi ý tên cho nhóm chưa có tên và tăng độ chắc cho đề xuất.<br><br>"
                   "<b>Chỉ TÊN người được gửi ra ngoài</b>, không bao giờ gửi ảnh nào của bạn. App không tự sửa gì, chỉ cảnh báo và gợi ý. "
                   "Ảnh nào có nhiều người hoặc các ảnh không khớp nhau thì bị bỏ để tránh lấy nhầm người khác.")
        t.setWordWrap(True)
        l.addWidget(t)
        self.auto = QCheckBox("Tự động tìm ảnh tham chiếu cho người mới đặt tên")
        self.auto.setChecked(db.get_meta("refimg_auto", "1") == "1")
        l.addWidget(self.auto)
        l.addWidget(QLabel("Tìm thêm trên web bằng Google Programmable Search (tùy chọn, người nào không có trên Wikimedia Commons):"))
        self.key = QLineEdit(db.get_meta("refimg_key", ""))
        self.key.setPlaceholderText("Khóa API (API key)")
        self.key.setEchoMode(QLineEdit.Password)
        self.cx = QLineEdit(db.get_meta("refimg_cx", ""))
        self.cx.setPlaceholderText("Mã công cụ tìm kiếm (cx)")
        l.addWidget(self.key)
        l.addWidget(self.cx)
        self.status = QLabel()
        self.status.setWordWrap(True)
        l.addWidget(self.status)
        row = QHBoxLayout()
        self.run_b = QPushButton("Tìm ngay")
        self.run_b.clicked.connect(self.run_now)
        close = QPushButton("Lưu và đóng")
        close.clicked.connect(self.save_close)
        row.addWidget(self.run_b)
        row.addStretch(1)
        row.addWidget(close)
        l.addLayout(row)
        self.refresh()

    def refresh(self):
        db = self.ctx.db
        have = db.one("SELECT COUNT(DISTINCT person_id) c FROM person_ref")["c"]
        tried = db.one("SELECT COUNT(*) c FROM ref_state")["c"]
        named = db.one("SELECT COUNT(*) c FROM persons WHERE name IS NOT NULL AND hidden=0")["c"]
        flags = db.one("SELECT COUNT(*) c FROM ref_flag")["c"]
        self.status.setText(f"Đã có ảnh tham chiếu cho {have} người (đã thử {tried} / {named} người có tên). Đang cảnh báo nghi nhầm tên: {flags} nhóm.")

    def save(self):
        db = self.ctx.db
        db.set_meta("refimg_auto", "1" if self.auto.isChecked() else "0")
        db.set_meta("refimg_key", self.key.text().strip())
        db.set_meta("refimg_cx", self.cx.text().strip())

    def run_now(self):
        self.save()
        self.w = RefWorker(self.ctx.db)
        self.w.done.connect(lambda n: (self.run_b.setEnabled(True), self.refresh(), self.ctx.changed.emit()))
        self.run_b.setEnabled(False)
        self.status.setText("Đang tìm ảnh tham chiếu…")
        self.w.start()

    def save_close(self):
        self.save()
        self.accept()


class ArchiveCleanWorker(QThread):
    """Dọn các tệp nén đã đồng bộ lên Drive: xóa ảnh bên trong (đã kiểm chứng giống hệt bản mã hóa), giữ tệp nén rỗng cùng tên."""
    done = Signal(int, int)           # số ảnh đã dọn, số tệp nén
    progress = Signal(int, int, str)

    def __init__(self, db, dest, password, zip_pw, min_age=1800):
        super().__init__()
        self.db, self.dest, self.password, self.zip_pw, self.min_age = db, dest, password, zip_pw, min_age
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        from .. import sync
        imgs = arcs = 0
        try:
            self.why = {}
            cands = sync.archive_clean_candidates(self.db, self.dest, self.min_age, self.why)
            for k, (arch, items) in enumerate(cands, 1):
                if self._stop:
                    break
                self.progress.emit(k, len(cands), os.path.basename(arch))
                n = sync.clean_archive(self.db, self.dest, self.password, arch, items, self.zip_pw, st["why"])
                if n:
                    imgs += n
                    arcs += 1
        except Exception:
            pass
        self.done.emit(imgs, arcs)


class FreeWorker(QThread):
    """Giải phóng dung lượng PC: xóa ảnh gốc rời (vào Thùng rác) VÀ ảnh gốc bên trong tệp nén (.zip, .7z), mỗi ảnh chỉ sau khi giải mã bản trên Drive và so sánh từng byte."""
    progress = Signal(int, int, str)
    done = Signal(object, str)

    def __init__(self, db, dest, password, zip_pw=None, min_age=0):
        super().__init__()
        self.db, self.dest, self.password, self.zip_pw, self.min_age = db, dest, password, zip_pw, min_age         # min_age: chạy tự động thì chờ 30 phút để Drive kịp tải lên

    def run(self):
        from .. import sync
        try:
            st = sync.free_local(self.db, self.dest, self.password, lambda k, t, n: self.progress.emit(k, t, n), min_age=self.min_age)
            st.update({"arch_imgs": 0, "arch_files": 0, "why": {}})
            cands = sync.archive_clean_candidates(self.db, self.dest, self.min_age, st["why"])
            for k, (arch, items) in enumerate(cands, 1):
                self.progress.emit(k, len(cands), os.path.basename(arch))
                n = sync.clean_archive(self.db, self.dest, self.password, arch, items, self.zip_pw)
                if n:
                    st["arch_imgs"] += n
                    st["arch_files"] += 1
            self.done.emit(st, "")
        except Exception as e:
            self.done.emit(None, str(e) or type(e).__name__)


class RestoreWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object, str)

    def __init__(self, db, dest, secret, out):
        super().__init__()
        self.db, self.dest, self.secret, self.out = db, dest, secret, out

    def run(self):
        from .. import sync
        try:
            st = sync.restore_library(self.db, self.dest, self.secret, self.out, lambda k, t, n: self.progress.emit(k, t, n))
            self.done.emit(st, "")
        except WrongPassword:
            self.done.emit(None, "Mật khẩu hoặc khóa khôi phục không đúng.")
        except Exception as e:
            self.done.emit(None, str(e))


class SyncDialog(QDialog):
    """Đồng bộ lên thư mục Google Drive (Drive for Desktop) để điện thoại đọc khi PC tắt. Mọi thứ được mã hóa bằng mật khẩu đồng bộ."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.worker = ctx, None
        self.setWindowTitle("Đồng bộ với điện thoại")
        self.setMinimumWidth(640)
        db = ctx.db
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Đồng bộ với điện thoại (qua Google Drive)</h2>"))
        info = QLabel("Cài <b>Google Drive cho máy tính</b>, chọn một thư mục nằm trong ổ Drive (ví dụ <i>G:\\My Drive\\PrivatePicture</i>). Ứng dụng ghi thư viện "
                      "vào đó, Drive tự đưa lên mạng, app Android đọc lại từ Drive. Dữ liệu được <b>mã hóa trước khi lên Drive</b> bằng mật khẩu đồng bộ "
                      "(Google không đọc được). Điện thoại cũng gửi lại tên người và nhãn qua thư mục này.")
        info.setWordWrap(True)
        l.addWidget(info)
        row = QHBoxLayout()
        from pathlib import Path
        self.dir = QLineEdit(db.get_meta("sync_dir", str(Path.home() / "Documents" / "PrivatePicture-drive")))
        pick = QPushButton("Chọn…")
        pick.clicked.connect(self.pick)
        row.addWidget(self.dir, 1)
        row.addWidget(pick)
        l.addLayout(row)
        pr = QHBoxLayout()
        pr.addWidget(QLabel("Mật khẩu đồng bộ"))
        self.pw = QLineEdit(db.get_meta("sync_pw", ""))
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("Nhập một lần, cũng nhập mật khẩu này vào app Android")
        pr.addWidget(self.pw, 1)
        l.addLayout(pr)
        self.orig = QCheckBox("Đồng bộ cả ảnh gốc (nặng; bỏ chọn thì chỉ gồm ảnh nhỏ và thông tin)")
        self.orig.setChecked(db.get_meta("sync_orig", "1") == "1")
        l.addWidget(self.orig)
        self.clean_cb = QCheckBox("Tự giải phóng dung lượng PC sau khi đồng bộ: xóa ảnh gốc đã có bản mã hóa giống hệt trên Drive (ảnh rời vào Thùng rác, ảnh trong tệp nén xóa khỏi tệp)")
        self.clean_cb.setToolTip("Chỉ xóa ảnh đã có bản mã hóa trên Drive và đã kiểm chứng giống hệt từng byte, sau ít nhất 30 phút để Drive kịp tải lên. "
                                 "Chỉ làm với tệp .zip và .7z; tệp .rar không xóa bớt được. Ảnh vẫn xem được và khôi phục lại được từ Drive.")
        self.clean_cb.setChecked(db.get_meta("sync_clean_archives", "1") == "1")

        def toggle_clean(on):
            if on and QMessageBox.question(self, "Tự dọn tệp nén", "Sau khi đồng bộ, ảnh BÊN TRONG các tệp nén (.zip, .7z) sẽ bị xóa khỏi tệp, chỉ giữ lại tệp nén rỗng "
                                           "cùng tên để bạn không tải trùng. Chỉ xóa khi bản mã hóa trên Drive đã có từ ít nhất 30 phút và giống hệt từng byte.\n\n"
                                           "Lưu ý: sau đó bản mã hóa trên Drive là bản duy nhất của các ảnh đó. Mất mật khẩu đồng bộ hoặc mất tệp trên Drive thì không lấy lại được. "
                                           "Bật?") != QMessageBox.Yes:
                self.clean_cb.blockSignals(True)
                self.clean_cb.setChecked(False)
                self.clean_cb.blockSignals(False)
        self.clean_cb.toggled.connect(toggle_clean)
        l.addWidget(self.clean_cb)
        self.after_scan = QCheckBox("Tự đồng bộ ngay sau mỗi lần quét xong có ảnh mới")
        self.after_scan.setChecked(db.get_meta("sync_after_scan", "1") == "1")
        l.addWidget(self.after_scan)
        self.auto = QCheckBox("Tự động đồng bộ (khi mở ứng dụng và mỗi 15 phút)")
        self.auto.setChecked(db.get_meta("sync_auto", "1") == "1")
        l.addWidget(self.auto)
        last = db.get_meta("sync_last")
        if last:
            import time
            l.addWidget(QLabel("Lần đồng bộ gần nhất: " + time.strftime("%d/%m/%Y %H:%M", time.localtime(float(last)))))
        self.stats_l = QLabel()
        self.stats_l.setWordWrap(True)
        self.stats_l.setStyleSheet(f"background:{theme.PANEL};padding:8px;border-radius:6px")
        l.addWidget(self.stats_l)
        warn = QLabel("Mật khẩu đồng bộ được lưu trong thư viện của ứng dụng. Hãy bấm “Khóa khôi phục…” và cất khóa ở nơi an toàn: nếu quên mật khẩu, khóa này vẫn mở được dữ liệu trên Drive. "
                      "Ảnh ở Kho mã hóa chỉ được đồng bộ khi Kho đang mở khóa.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:" + theme.MUTED)
        l.addWidget(warn)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        l.addWidget(self.bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        l.addWidget(self.status)
        br = QHBoxLayout()
        self.go = QPushButton("Đồng bộ ngay")
        self.go.setProperty("primary", True)
        self.go.clicked.connect(self.start)
        save = QPushButton("Lưu cài đặt")
        save.clicked.connect(lambda: (self.save(), self.accept()))
        close = QPushButton("Đóng")
        close.clicked.connect(self.reject)
        self.free_b = QPushButton("Giải phóng dung lượng PC…")
        self.free_b.setToolTip("Xóa ảnh gốc trên PC (ảnh rời vào Thùng rác; ảnh trong tệp nén .zip/.7z xóa khỏi tệp) đã có bản mã hóa trên Drive, sau khi đối chiếu từng byte")
        self.free_b.clicked.connect(self.free_space)
        br.addWidget(self.free_b)
        rk_b = QPushButton("Khóa khôi phục…")
        rk_b.clicked.connect(self.show_recovery)
        rs_b = QPushButton("Khôi phục thư viện từ Drive…")
        rs_b.clicked.connect(self.restore_library)
        br.addWidget(rk_b)
        br.addWidget(rs_b)
        br.addStretch(1)
        for b in (close, save, self.go):
            br.addWidget(b)
        l.addLayout(br)
        self.refresh_stats()

    @staticmethod
    def fmt(n):
        return f"{n / 1073741824:.2f} GB" if n >= 1073741824 else f"{n / 1048576:.1f} MB"

    def refresh_stats(self):
        from .. import sync
        d = self.dir.text().strip()
        if not d or not os.path.isdir(sync.root_of(d)):
            self.stats_l.setText("Chưa có dữ liệu đồng bộ trong thư mục này.")
            return
        s = sync.stats(d)
        db = self.ctx.db
        local = db.one("SELECT COALESCE(SUM(size),0) n, COUNT(*) c FROM images WHERE vid IS NULL AND path NOT LIKE 'zip://%'")
        arch = db.one("SELECT COUNT(*) c FROM archived")["c"]
        self.stats_l.setText(
            f"<b>Dung lượng đang chiếm trên Drive: {self.fmt(s['total'])}</b><br>"
            f"Ảnh gốc mã hóa: {s['orig'][0]} tệp, {self.fmt(s['orig'][1])} · Ảnh nhỏ: {s['thumbs'][0]} tệp, {self.fmt(s['thumbs'][1])} · "
            f"Khác (danh mục, vectơ nội dung, app Android): {self.fmt(s['other'] + s['app'][1] + s['inbox'][1])}<br>"
            f"Ảnh gốc mã hóa chỉ nặng hơn ảnh gốc khoảng 32 byte mỗi ảnh (giải mã ra đúng từng byte). "
            f"Ảnh gốc trong thư viện trên PC: {local['c']} tệp, {self.fmt(local['n'])}. Đã giải phóng khỏi PC: {arch} ảnh."
            + (f"<br><b>Lần giải phóng gần nhất:</b> {db.get_meta('free_report')}" if db.get_meta("free_report") else ""))

    def show_recovery(self):
        from .. import sync
        d, pw = self.dir.text().strip(), self.pw.text()
        if not d or not pw:
            self.status.setText("Hãy chọn thư mục và nhập mật khẩu đồng bộ trước.")
            return
        try:
            self.save()
            rk = sync.recovery_key(d, pw)
        except Exception as e:
            self.status.setText(f"Không tạo được khóa khôi phục: {e}")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Khóa khôi phục")
        box.setText("Khóa khôi phục của thư mục đồng bộ:")
        box.setInformativeText(f"<p style='font-size:15px'><b>{rk}</b></p>Chép khóa này ra giấy hoặc trình quản lý mật khẩu, KHÔNG để trên Drive. "
                               "Ai có khóa này đọc được toàn bộ ảnh trên Drive; khi quên mật khẩu hoặc cài lại máy, nhập khóa này thay mật khẩu "
                               "trong “Khôi phục thư viện từ Drive”.")
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cp = box.addButton("Sao chép", QMessageBox.ActionRole)
        box.addButton("Đóng", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is cp:
            QApplication.clipboard().setText(rk)

    def restore_library(self):
        """Máy mới: nhập thư mục Drive và mật khẩu (hoặc khóa khôi phục), chọn nơi lưu ảnh; ảnh gốc được giải mã về đó rồi quét lại."""
        d = self.dir.text().strip()
        if not d:
            self.status.setText("Hãy chọn thư mục đồng bộ (thư mục chứa PrivatePicture-Sync) trước.")
            return
        secret, ok = QInputDialog.getText(self, "Khôi phục thư viện", "Mật khẩu đồng bộ hoặc khóa khôi phục:", QLineEdit.Password, self.pw.text())
        if not ok or not secret:
            return
        out = QFileDialog.getExistingDirectory(self, "Chọn thư mục để lưu ảnh khôi phục (cần đủ dung lượng)")
        if not out:
            return
        self.rw = RestoreWorker(self.ctx.db, d, secret.strip(), out)
        self.rw.progress.connect(lambda k, t, n: (self.bar.setRange(0, max(1, t)), self.bar.setValue(k), self.status.setText(f"Đang giải mã {k}/{t}: {n}")))
        self.rw.done.connect(lambda st, err, sec=secret.strip(): self.on_restored(st, err, sec))
        self.go.setEnabled(False)
        self.status.setStyleSheet("")
        self.bar.setVisible(True)
        self.rw.start()

    def on_restored(self, st, err, secret):
        self.bar.setVisible(False)
        self.go.setEnabled(True)
        if err:
            self.status.setStyleSheet("color:#c0392b")
            self.status.setText("Không khôi phục được: " + err)
            return
        db = self.ctx.db
        if not self.pw.text():                          # nhập đúng mật khẩu thì giữ để đồng bộ tiếp (khóa khôi phục thì không)
            from .. import sync
            try:
                sync.setup(self.dir.text().strip(), secret)
                self.pw.setText(secret)
            except Exception:
                pass
        self.save()
        self.ctx.changed.emit()
        self.status.setStyleSheet("color:#2e7d32")
        self.status.setText(f"Đã khôi phục {st['restored']} ảnh" + (f"; {st['missing']} ảnh không có bản gốc trên Drive" if st["missing"] else "") +
                            (f"; {st['errors']} lỗi" if st["errors"] else "") + ". Thư mục đã được thêm vào thư viện: vào Công cụ → Cài đặt → Quét để dựng lại "
                            "danh sách người, nhãn và tên (tự áp lại sau lần quét).")

    def free_space(self):
        from .. import sync
        d, pw = self.dir.text().strip(), self.pw.text()
        if not d or not pw:
            self.status.setText("Hãy chọn thư mục và nhập mật khẩu đồng bộ.")
            return
        why = {}
        try:
            cands = sync.free_candidates(self.ctx.db, d)
            acands = sync.archive_clean_candidates(self.ctx.db, d, 0, why)
        except Exception as e:
            self.status.setText(f"Không đọc được thư mục đồng bộ: {e}")
            return
        names = {"rar": "ảnh trong tệp .rar hoặc định dạng không xóa bớt được", "ro": "ảnh trong tệp chỉ đọc / không ghi được", "ml": "ảnh chưa phân tích xong (đang quét)",
                 "sync": "ảnh chưa có bản mã hóa trên Drive (cần bật Đồng bộ cả ảnh gốc rồi đồng bộ lại)"}
        skipped = [f"{v} {names[k]}" for k, v in why.items() if v and k in names]
        n_arch = sum(len(items) for _, items in acands)
        if not cands and not acands:
            QMessageBox.information(self, "Giải phóng dung lượng", "Chưa có ảnh gốc nào trên PC đủ điều kiện (có bản mã hóa trên Drive, đã phân tích xong)." +
                                    ("\n\nChưa dọn được:\n- " + "\n- ".join(skipped) if skipped else "") +
                                    "\n\nHãy bật “Đồng bộ cả ảnh gốc” và đồng bộ trước.")
            return
        total = sum(c[2] for c in cands)
        box = QMessageBox(self)
        box.setWindowTitle("Giải phóng dung lượng PC")
        box.setIcon(QMessageBox.Warning)
        lines = []
        if cands:
            lines.append(f"<b>{len(cands)}</b> ảnh gốc rời ({self.fmt(total)}) sẽ chuyển vào Thùng rác")
        if acands:
            lines.append(f"<b>{n_arch}</b> ảnh bên trong <b>{len(acands)}</b> tệp nén sẽ bị xóa khỏi tệp (tệp nén còn lại giữ nguyên tên)")
        box.setText("Giải phóng dung lượng PC:<br>" + "<br>".join(lines))
        box.setInformativeText("Mỗi ảnh chỉ bị xóa sau khi app giải mã bản trên Drive và so sánh từng byte với ảnh trên PC; ảnh nào không khớp thì được giữ lại. "
                               "Ảnh vẫn xem được trong thư viện (đọc từ Drive) và khôi phục lại được bất cứ lúc nào.\n\n"
                               "Lưu ý: sau đó bản trên Drive (mã hóa) là bản duy nhất ngoài Thùng rác. Nếu mất mật khẩu đồng bộ hoặc mất tệp trên Drive "
                               "thì không còn cách lấy lại ảnh." + ("\n\nChưa dọn (không đủ điều kiện):\n- " + "\n- ".join(skipped) if skipped else ""))
        cb = QCheckBox("Google Drive đã tải lên xong và tôi đã lưu mật khẩu đồng bộ ở nơi an toàn")
        box.setCheckBox(cb)
        yes = box.addButton("Giải phóng", QMessageBox.DestructiveRole)
        box.addButton("Hủy", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        if not cb.isChecked():
            QMessageBox.information(self, "Giải phóng dung lượng", "Hãy tích xác nhận (Drive đã tải lên xong và đã lưu mật khẩu) rồi thử lại.")
            return
        self.save()
        self.fw = FreeWorker(self.ctx.db, d, pw, self.ctx.zip_passwords)
        self.fw.progress.connect(lambda k, t, n: (self.bar.setRange(0, max(1, t)), self.bar.setValue(k), self.status.setText(f"Đang kiểm chứng và xóa {k}/{t}: {n}")))
        self.fw.done.connect(self.on_freed)
        self.free_b.setEnabled(False)
        self.go.setEnabled(False)
        self.bar.setVisible(True)
        self.fw.start()

    def on_freed(self, st, err):
        self.bar.setVisible(False)
        self.free_b.setEnabled(True)
        self.go.setEnabled(True)
        if err:
            self.status.setStyleSheet("color:#c0392b")
            self.status.setText("Không giải phóng được: " + err)
            return
        self.ctx.db.snapshot()
        self.ctx.changed.emit()
        self.refresh_stats()
        self.status.setStyleSheet("color:#2e7d32")
        self.status.setText(f"Đã giải phóng {self.fmt(st['freed'])} ({st['files']} ảnh rời vào Thùng rác" + (f", {st['arch_imgs']} ảnh trong {st['arch_files']} tệp nén" if st.get("arch_imgs") else "") + ")" +
                            (f"; {st['mismatch']} ảnh không khớp bản Drive nên được giữ lại" if st["mismatch"] else "") +
                            (f"; {st['errors']} lỗi" if st["errors"] else "") + ".")

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "Thư mục đồng bộ (trong ổ Google Drive)", self.dir.text())
        if d:
            self.dir.setText(d)
            self.refresh_stats()

    def save(self):
        db = self.ctx.db
        db.set_meta("sync_dir", self.dir.text().strip())
        db.set_meta("sync_pw", self.pw.text())
        db.set_meta("sync_orig", "1" if self.orig.isChecked() else "0")
        db.set_meta("sync_auto", "1" if self.auto.isChecked() else "0")
        db.set_meta("sync_after_scan", "1" if self.after_scan.isChecked() else "0")
        db.set_meta("sync_clean_archives", "1" if self.clean_cb.isChecked() else "0")

    def start(self):
        if not self.dir.text().strip() or not self.pw.text():
            self.status.setText("Hãy chọn thư mục và nhập mật khẩu đồng bộ.")
            return
        self.save()
        self.worker = SyncWorker(self.ctx.db, self.dir.text().strip(), self.pw.text(), self.orig.isChecked(),
                                 self.ctx.vault if self.ctx.vault.unlocked() else None, self.ctx.zip_passwords)
        self.worker.progress.connect(lambda d, t, n: (self.bar.setRange(0, max(1, t)), self.bar.setValue(d), self.status.setText(f"Đang đồng bộ {d}/{t}: {n}")))
        self.worker.done.connect(self.on_done)
        self.go.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setStyleSheet("")
        self.worker.start()

    def on_done(self, st, err):
        import time
        self.bar.setVisible(False)
        self.go.setEnabled(True)
        if err:
            self.status.setStyleSheet("color:#c0392b")
            self.status.setText("Không đồng bộ được: " + ("Mật khẩu đồng bộ không đúng với thư mục này." if "Wrong" in err or not err.strip() else err))
            return
        self.ctx.db.set_meta("sync_last", time.time())
        self.ctx.changed.emit()
        self.refresh_stats()
        self.status.setStyleSheet("color:#2e7d32")
        self.status.setText(f"Xong: {st['thumbs']} ảnh nhỏ và {st['orig']} ảnh gốc mới, dọn {st['removed']} tệp cũ, "
                            f"áp dụng {st['inbox']} thay đổi từ điện thoại" + (f", {st['errors']} lỗi" if st["errors"] else "") +
                            (f", {st['skipped_big']} ảnh quá lớn bị bỏ qua" if st["skipped_big"] else "") +
                            ". Chờ Google Drive tải lên xong rồi mở app trên điện thoại.")


class BackupDialog(QDialog):
    """Sao lưu vào một thư mục, ví dụ thư mục Google Drive (Drive for Desktop) hay OneDrive đồng bộ trên máy."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.worker = ctx, None
        self.setWindowTitle("Sao lưu dữ liệu")
        self.setMinimumWidth(620)
        db = ctx.db
        l = QVBoxLayout(self)
        l.addWidget(QLabel("<h2 style='margin:0'>Sao lưu dữ liệu</h2>"))
        info = QLabel("Chọn một thư mục để lưu các bản sao lưu (tệp .zip). Muốn đưa lên <b>Google Drive</b>: cài Google Drive cho máy tính, "
                      "rồi chọn một thư mục nằm trong ổ Drive (ví dụ <i>G:\\My Drive\\PrivatePicture-backup</i>), Drive sẽ tự đồng bộ lên mạng. "
                      "OneDrive hoạt động tương tự.")
        info.setWordWrap(True)
        l.addWidget(info)
        row = QHBoxLayout()
        from pathlib import Path
        self.dir = QLineEdit(db.get_meta("backup_dir", str(Path.home() / "Documents" / "PrivatePicture-backup")))
        pick = QPushButton("Chọn…")
        pick.clicked.connect(self.pick)
        row.addWidget(self.dir, 1)
        row.addWidget(pick)
        l.addLayout(row)
        self.vault = QCheckBox("Gồm cả Kho mã hóa (ảnh đã mã hóa; có thể rất nặng)")
        self.vault.setChecked(db.get_meta("backup_vault", "1") == "1")
        l.addWidget(self.vault)
        kr = QHBoxLayout()
        kr.addWidget(QLabel("Giữ lại"))
        self.keep = QSpinBox()
        self.keep.setRange(1, 50)
        self.keep.setValue(int(db.get_meta("backup_keep", "5")))
        kr.addWidget(self.keep)
        kr.addWidget(QLabel("bản sao lưu gần nhất"))
        kr.addStretch(1)
        l.addLayout(kr)
        self.auto = QCheckBox("Tự động sao lưu mỗi 7 ngày khi mở ứng dụng")
        self.auto.setChecked(db.get_meta("backup_auto", "0") == "1")
        l.addWidget(self.auto)
        last = db.get_meta("backup_last")
        if last:
            import time
            l.addWidget(QLabel("Lần sao lưu gần nhất: " + time.strftime("%d/%m/%Y %H:%M", time.localtime(float(last)))))
        warn = QLabel()
        warn.setWordWrap(True)
        if ctx.encrypted:
            warn.setText("Bản sao lưu giữ nguyên mã hóa: người khác lấy được tệp cũng không đọc được nếu không có mật khẩu hoặc khóa khôi phục. "
                         "Khóa API và mã truy cập cập nhật không được đưa vào bản sao lưu. Ảnh ở thư mục mức “giữ ảnh gốc” không nằm trong bản sao lưu này.")
        else:
            warn.setText("<span style='color:#b03a2e'>Bạn đang tắt mã hóa dữ liệu: bản sao lưu sẽ KHÔNG được mã hóa (gồm tên người, nhãn, ảnh thu nhỏ). "
                         "Nếu lưu lên Drive, Google có thể đọc được. Hãy bật mã hóa trong “Thay đổi bảo mật…” trước khi đưa lên mạng.</span>")
        l.addWidget(warn)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setVisible(False)
        l.addWidget(self.bar)
        self.status = QLabel()
        self.status.setWordWrap(True)
        l.addWidget(self.status)
        row = QHBoxLayout()
        self.go = QPushButton("Sao lưu ngay")
        self.go.setProperty("primary", True)
        self.go.clicked.connect(self.start)
        save = QPushButton("Lưu cài đặt")
        save.clicked.connect(lambda: (self.save(), self.accept()))
        close = QPushButton("Đóng")
        close.clicked.connect(self.reject)
        row.addStretch(1)
        for b in (close, save, self.go):
            row.addWidget(b)
        l.addLayout(row)

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, "Thư mục lưu bản sao lưu", self.dir.text())
        if d:
            self.dir.setText(d)

    def save(self):
        db = self.ctx.db
        db.set_meta("backup_dir", self.dir.text().strip())
        db.set_meta("backup_vault", "1" if self.vault.isChecked() else "0")
        db.set_meta("backup_keep", self.keep.value())
        db.set_meta("backup_auto", "1" if self.auto.isChecked() else "0")

    def start(self):
        if not self.dir.text().strip():
            self.status.setText("Hãy chọn thư mục lưu.")
            return
        self.save()
        self.worker = BackupWorker(self.ctx.db, self.dir.text().strip(), self.vault.isChecked(), self.keep.value())
        self.worker.done.connect(self.on_done)
        self.go.setEnabled(False)
        self.bar.setVisible(True)
        self.status.setStyleSheet("")
        self.status.setText("Đang sao lưu…")
        self.worker.start()

    def on_done(self, path, err):
        import time
        self.bar.setVisible(False)
        self.go.setEnabled(True)
        if err:
            self.status.setStyleSheet("color:#c0392b")
            self.status.setText("Không sao lưu được: " + err)
            return
        self.ctx.db.set_meta("backup_last", time.time())
        mb = os.path.getsize(path) / 1048576
        self.status.setStyleSheet("color:#2e7d32")
        self.status.setText(f"Đã sao lưu ({mb:.1f} MB):\n{path}")

    def reject(self):
        if self.worker and self.worker.isRunning():
            return
        super().reject()


class ScanWorker(QThread):
    progress = Signal(int, int, str)
    msg = Signal(str)
    done = Signal(str)

    locked = Signal(list)

    def __init__(self, db, rows, vault, download, auto=False, zip_pw=None):
        super().__init__()
        self.db, self.rows, self.vault, self.download, self.auto, self._stop = db, rows, vault, download, auto, False
        self.zip_pw = zip_pw if zip_pw is not None else {}

    def stop(self):
        self._stop = True

    def run(self):
        try:
            names = models.FACE_FILES + models.CLIP_FILES
            dl_error = None
            if not models.have(names):           # tự tải mô hình ở lần quét đầu tiên (một lần, lưu trong máy); thiếu ArcFace thì thử tải để nâng cấp
                self.msg.emit("Đang tải mô hình nhận diện (chỉ lần đầu, cần mạng)…")
                try:
                    models.download(names, lambda n, d, t: self.msg.emit(f"Tải mô hình {n}: {d // 1048576}/{max(1, t // 1048576)} MB"),
                                    lambda: self._stop)
                except Exception as e:
                    dl_error = str(e)
            faces = clip = None
            if models.ready():
                self.msg.emit("Đang nạp mô hình…")
                nt = max(1, (os.cpu_count() or 4) // (4 if self.auto else 2))          # quét nền dùng ít luồng tính toán hơn: giao diện còn chỗ chạy mượt
                faces, clip = models.FaceEngine(nt), models.ClipEngine(nt)
                # đổi sang mô hình nhận dạng mới: quét lại để tính lại vectơ khuôn mặt (người đã đặt tên được giữ nguyên)
                if self.db.get_meta("face_model") != faces.name:
                    if self.db.get_meta("face_model") is not None or self.db.one("SELECT 1 FROM faces LIMIT 1"):
                        self.msg.emit(f"Nâng cấp nhận diện mặt ({faces.name}): quét lại ảnh để tính lại khuôn mặt…")
                        self.db.x("UPDATE images SET ml=0 WHERE vid IS NULL")
                    self.db.set_meta("face_model", faces.name)
            else:
                self.msg.emit("Chưa tải được mô hình nhận diện" + (f" ({dl_error})" if dl_error else "") +
                              ": tạm thời chỉ lập danh mục ảnh, lần quét sau ứng dụng sẽ tự thử tải lại.")
            sc = Scanner(self.db, faces, clip, lambda d, t, p: self.progress.emit(d, t, p), lambda: self._stop, self.vault, self.zip_pw)
            sc.throttle = 0.03 if self.auto else 0.01
            r = sc.run_folders(self.rows)
            self.locked.emit(r.get("locked_zips", []))
            n_new = (r.get("added") or 0) + (r.get("updated") or 0)
            self.n_changed = n_new + (r.get("removed") or 0)                      # có thay đổi thì sau khi quét xong sẽ tự đồng bộ cho điện thoại
            if self.auto and not n_new and not r.get("removed"):                # quét nền mà không có gì thay đổi: xong ngay, không tốn sức máy
                self.db.snapshot()
                self.done.emit(scan_summary(self.db, r, self._stop, self.auto))
                return
            if clip and not self._stop:
                try:
                    from .. import art
                    _scan_mod.wait_idle(lambda: self._stop); self.msg.emit("Đang nhận biết tranh vẽ, hình minh họa…")
                    art.detect(self.db, clip.text)
                except Exception:
                    pass
            if faces and not self._stop:
                _scan_mod.wait_idle(lambda: self._stop); self.msg.emit("Đang gom khuôn mặt…")
                if self.auto and n_new <= 300:                                 # quét nền ít ảnh mới: cập nhật nhẹ, không gom lại cả thư viện
                    left = cluster.cluster_incremental(self.db)
                    if left >= 25:                                             # đủ nhiều mặt lạ mới thì mới gom đầy đủ để lập nhóm người mới
                        cluster.cluster_faces(self.db)
                else:
                    cluster.cluster_faces(self.db)
                _scan_mod.wait_idle(lambda: self._stop); self.msg.emit("Đang phân tích ảnh không thấy mặt…")
                try:
                    pos, neg = clip.text("a photo of a person"), clip.text("a photo of a landscape, a building, a room or an object")
                    cluster.guess_faceless(self.db, lambda v: float(v @ pos) - float(v @ neg) > 0.0)
                except Exception:
                    pass
            if not self._stop:
                try:
                    _scan_mod.wait_idle(lambda: self._stop); self.msg.emit("Đang chia ảnh trong file nén có nhiều người…")
                    cluster.assign_by_sequence(self.db)
                    cluster.infer_names(self.db, auto=True)
                    cluster.infer_candidates(self.db)
                    cluster.apply_refs(self.db)                       # ảnh tham chiếu từ internet: cảnh báo nhầm tên, gợi ý tên, tăng độ chắc
                    cluster.assign_by_session(self.db)                 # chia buổi chụp theo giờ, gợi ý người cho ảnh chưa rõ trong buổi
                    cluster.claim_single_name_archives(self.db)
                except Exception:
                    pass
            if clip and not self._stop:
                try:
                    _scan_mod.wait_idle(lambda: self._stop)
                    clothing.analyze(self.db, clip.text)
                except Exception:
                    pass
            if not self._stop and self.db.get_meta("label_auto", "1") == "1":
                try:
                    _scan_mod.wait_idle(lambda: self._stop); self.msg.emit("Đang tự phân loại ảnh theo nhãn…")
                    autolabel.run_auto(self.db)
                except Exception:
                    pass
            if not self._stop and self.db.get_meta("dup_auto", "1") == "1":
                try:
                    _scan_mod.wait_idle(lambda: self._stop); self.msg.emit("Đang tìm ảnh trùng lặp…")
                    groups = dup.find_groups(self.db)
                    dup.apply(self.db, groups)
                    if self.db.get_meta("dup_autodelete", "1") == "1":     # (tùy chọn) tự xóa bản trùng y hệt trong thư mục, vào Thùng rác
                        _scan_mod.wait_idle(lambda: self._stop); self.msg.emit("Đang xóa bản trùng y hệt vào Thùng rác…")
                        dup.trash_images(self.db, dup.exact_items(self.db, groups))
                except Exception:
                    pass
            if not self._stop and self.db.get_meta("restore_pending"):
                try:
                    from .. import sync as _sync
                    _sync.apply_restore_meta(self.db)             # áp lại tên người, nhãn sau khi khôi phục từ Drive
                except Exception:
                    pass
            self.db.snapshot()
            self.done.emit(scan_summary(self.db, r, self._stop, self.auto))
        except Exception as e:
            self.done.emit(f"Lỗi: {e}")


class UpdateWorker(QThread):
    found = Signal(object)
    ready = Signal(str)
    progress = Signal(int, int)
    done = Signal(str)

    def __init__(self, token, info=None):
        super().__init__()
        self.token, self.info = token, info

    def run(self):
        try:
            if self.info is None:
                self.found.emit(updater.latest(self.token))
            else:
                inst = updater.install_dir()
                if inst:                                    # bản đã cài: thử chỉ tải các tệp thay đổi (nhẹ hơn nhiều); lỗi gì thì tải cả bản như trước
                    try:
                        out = str(paths.app_dir() / "update" / "new" / "PrivatePicture")
                        updater.delta_download(self.info, self.token, inst, out, lambda d, t: self.progress.emit(d, t))
                        self.ready.emit(out)
                        return
                    except updater.UpdateError as e:
                        if "hủy" in str(e):
                            raise
                    except Exception:
                        pass
                zp = str(paths.app_dir() / "update.zip")
                updater.download(self.info, self.token, zp, lambda d, t: self.progress.emit(d, t))
                src = updater.prepare(zp)
                os.remove(zp)
                self.ready.emit(src)
        except updater.UpdateError as e:
            self.done.emit(str(e))
        except Exception as e:
            self.done.emit(f"Lỗi: {e}")


TOKEN_HELP = ("Để ứng dụng tự cập nhật từ repo riêng tư, bạn tạo một mã truy cập chỉ-đọc trên GitHub (làm một lần):\n\n"
              "1. Mở github.com → ảnh đại diện → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.\n"
              "2. Token name: PrivatePicture. Expiration: 1 năm (hết hạn thì tạo mã mới).\n"
              "3. Repository access: Only select repositories → chọn Private-Picture.\n"
              "4. Permissions → Repository permissions → Contents: Read-only. Các quyền khác để No access.\n"
              "5. Generate token, sao chép mã (bắt đầu bằng github_pat_) rồi dán vào ô tiếp theo.\n\n"
              "Mã được lưu mã hóa trong ứng dụng và chỉ có quyền đọc.")


class FolderDialog(QDialog):
    """Chọn thư mục và mức mã hóa cho thư mục đó."""

    def __init__(self, parent, path, allow_keep=True, allow_all=True):
        super().__init__(parent)
        self.setWindowTitle("Mức mã hóa cho thư mục")
        self.setMinimumWidth(520)
        l = QVBoxLayout(self)
        t = QLabel(f"<b>{path}</b>")
        t.setWordWrap(True)
        l.addWidget(t)
        self.r1 = QRadioButton(LEVELS["data"])
        d1 = QLabel("Ảnh nằm nguyên trong thư mục, mở được bằng mọi phần mềm. Ứng dụng chỉ lưu danh mục, ảnh thu nhỏ, "
                    "khuôn mặt (đã mã hóa bằng mật khẩu chính).")
        self.r2 = QRadioButton(LEVELS["all"])
        d2 = QLabel("Từng ảnh được mã hóa AES-256 vào kho của ứng dụng; chỉ xem được khi mở ứng dụng bằng mật khẩu. "
                    "Ảnh không còn mở được bằng phần mềm khác (xuất ra khi cần).")
        for d in (d1, d2):
            d.setWordWrap(True)
            d.setStyleSheet("color:#555;margin-left:22px")
        self.r1.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r1)
        grp.addButton(self.r2)
        self.dele = QCheckBox("Xóa ảnh gốc sau khi mã hóa (xóa vĩnh viễn, không vào Thùng rác)")
        self.dele.setEnabled(False)
        self.r2.toggled.connect(self.dele.setEnabled)
        for w in (self.r1, d1, self.r2, d2, self.dele):
            l.addWidget(w)
        if not allow_keep:
            self.r1.setEnabled(False)
            self.r2.setChecked(True)
        if not allow_all:
            self.r2.setEnabled(False)
            self.r2.setToolTip("Cần bật mã hóa dữ liệu (Cài đặt → Tài khoản và dữ liệu → Thay đổi bảo mật)")
            d2.setText("Mức này cần bật mã hóa dữ liệu. Vào “Thay đổi bảo mật…” để bật.")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def result_level(self):
        return ("all" if self.r2.isChecked() else "data"), self.r2.isChecked() and self.dele.isChecked()


class AccountPage(Page):
    """Tài khoản, bảo mật, sao lưu, đồng bộ điện thoại và cập nhật ứng dụng (tách riêng khỏi thư mục ảnh)."""
    updateIdle = Signal()                   # việc kiểm tra / tải cập nhật lúc mở app đã xong (hoặc không có gì để cập nhật): lúc này mới quét ảnh

    def __init__(self, ctx):
        super().__init__(ctx)
        self.worker = None                  # (không dùng) tác vụ quét nằm ở trang Thư mục và quét
        self.state = QLabel()
        self.state.setWordWrap(True)
        self.state.setStyleSheet("font-weight:600")
        self.v.addWidget(self.state)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        h1 = QLabel("<b>Bảo mật và dữ liệu</b>")
        self.v.addWidget(h1)
        sec = QHBoxLayout()
        self.sec_btns = {}
        for key, text, fn in [("pw", "Đổi mật khẩu…", self.change_pw), ("rec", "Tạo khóa khôi phục mới…", self.new_recovery),
                              ("cfg", "Thay đổi bảo mật…", self.change_security)]:          # sao lưu và đồng bộ điện thoại chạy hoàn toàn tự động, không còn nút
            b = QPushButton(text)
            b.clicked.connect(fn)
            sec.addWidget(b)
            self.sec_btns[key] = b
        self.rec = QLabel()
        sec.addWidget(self.rec, 1)
        self.v.addLayout(sec)
        upd = QHBoxLayout()
        b = QPushButton("Đồng bộ điện thoại…")
        b.setToolTip("Thư mục Google Drive, mật khẩu đồng bộ, dung lượng trên Drive, giải phóng dung lượng PC, khóa khôi phục")
        b.clicked.connect(self.sync_phone)
        upd.addWidget(b)
        b = QPushButton("Sao lưu…")
        b.clicked.connect(self.backup)
        upd.addWidget(b)
        b = QPushButton("Mã truy cập cập nhật…")
        b.clicked.connect(self.set_token)
        upd.addWidget(b)
        b = QPushButton("Ảnh tham chiếu…")
        b.setToolTip("Ảnh chân dung công khai trên internet của những người đã có tên, dùng để cảnh báo nhầm tên và gợi ý tên (chỉ gửi tên, không gửi ảnh)")
        b.clicked.connect(lambda: RefDialog(self.ctx, self).exec())
        upd.addWidget(b)
        b = QPushButton("Kiểm tra cập nhật")
        b.clicked.connect(lambda: self.check_updates(False))
        upd.addWidget(b)
        self.ver = QLabel(f"Phiên bản: {__version__}")
        upd.addWidget(self.ver, 1)
        self.v.addLayout(upd)
        self.uw = None
        self.v.addWidget(self.status)
        self.v.addWidget(self.bar)
        self.v.addStretch(1)

    def _scan_running(self):
        try:
            w = self.window().pages["settings"].worker
            return bool(w and w.isRunning())
        except Exception:
            return False

    def refresh(self):
        if self.ctx.attached:
            self.sec_btns["pw"].setVisible(SEC.use_password)
            self.sec_btns["rec"].setVisible(SEC.mk is not None)
            state = ("Mã hóa " + ("BẬT" if SEC.encrypt else "TẮT") + " · Mật khẩu " + ("BẬT" if SEC.use_password else "TẮT"))
            extra = ""
            if SEC.mk is not None:
                extra = " · Khóa khôi phục: " + ("đã có" if SEC.has_recovery() else "<b style='color:#b03a2e'>CHƯA CÓ</b>")
            self.rec.setText(state + extra)
            self.state.setText(state + extra)
        else:
            for k in ("pw", "rec", "cfg"):
                self.sec_btns[k].setVisible(False)

    def set_token(self):
        QMessageBox.information(self, "Mã truy cập cập nhật", TOKEN_HELP)
        t, ok = QInputDialog.getText(self, "Mã truy cập cập nhật", "Dán mã (github_pat_…):", QLineEdit.Password)
        if ok and t.strip():
            updater.save_token(t)
            QMessageBox.information(self, "Xong", "Đã lưu mã truy cập (mã hóa). Bấm “Kiểm tra cập nhật” để thử.")

    def auto_check(self):
        if updater.load_token() and not self.uw:                    # luôn tự kiểm tra cập nhật khi mở ứng dụng
            self.check_updates(True)
        else:
            self.updateIdle.emit()

    def check_updates(self, silent):
        tok = updater.load_token()
        if not tok:
            if not silent:
                self.set_token()
            return
        if self.uw and self.uw.isRunning():
            return
        self.silent = silent
        self.manual = not silent                  # bấm "Kiểm tra cập nhật" thì mới hỏi khởi động lại; tự động lúc mở app thì lặng lẽ cài khi thoát
        self.uw = UpdateWorker(tok)
        self.uw.found.connect(self.on_found)
        self.uw.done.connect(self.on_update_error)
        self.uw.start()

    def on_update_error(self, text):
        self.uw = None
        self.updateIdle.emit()
        self.bar.setVisible(False)
        if not self.silent:
            QMessageBox.warning(self, "Cập nhật", text)
        else:
            self.status.setText("Không kiểm tra được cập nhật: " + text)

    def on_found(self, info):
        self.uw = None
        if not updater.is_newer(info["version"]):
            self.updateIdle.emit()
            if not self.silent:
                QMessageBox.information(self, "Cập nhật", f"Bạn đang dùng bản mới nhất (v{__version__}).")
            return
        if not self.silent and QMessageBox.question(self, "Có bản mới", f"Có phiên bản mới v{info['version']} (đang dùng v{__version__}).\n"
                                                    "Tải ngầm ngay bây giờ? Bạn vẫn dùng ứng dụng bình thường trong lúc tải; tải xong sẽ hỏi khởi động lại. "
                                                    "Dữ liệu và mật khẩu của bạn được giữ nguyên.") != QMessageBox.Yes:
            self.updateIdle.emit()
            return
        self.new_version = info["version"]
        self.uw = UpdateWorker(updater.load_token(), info)
        self.uw.progress.connect(lambda d, t: (self.bar.setVisible(True), self.bar.setRange(0, max(1, t)), self.bar.setValue(d),
                                               self.status.setText(f"Đang tải bản cập nhật {d // 1048576}/{max(1, t // 1048576)} MB")))
        self.uw.ready.connect(self.on_ready)
        self.uw.done.connect(self.on_update_error)
        self.silent = True                       # tải ngầm: lỗi chỉ báo ở dòng trạng thái, không bật hộp thoại làm gián đoạn
        self.uw.start()

    def on_ready(self, src):
        self.uw = None
        self.updateIdle.emit()
        self.bar.setVisible(False)
        w = self.window()
        w.pending_update = src                   # nếu để sau: tự cài khi thoát ứng dụng
        self.status.setText(f"Đã tải xong bản v{getattr(self, 'new_version', '')}: sẽ tự cập nhật khi bạn thoát ứng dụng.")
        box = QMessageBox(self)
        box.setWindowTitle("Cập nhật sẵn sàng")
        box.setText(f"Bản mới v{getattr(self, 'new_version', '')} đã tải xong.")
        box.setInformativeText("Khởi động lại: cài ngay và mở lại app. Để sau: bạn cứ làm việc tiếp, app tự cập nhật khi bạn thoát. Thoát: cài bản mới và đóng app (không mở lại).")
        now = box.addButton("Khởi động lại", QMessageBox.AcceptRole)
        later = box.addButton("Để sau", QMessageBox.RejectRole)
        quit_b = box.addButton("Thoát", QMessageBox.DestructiveRole)
        if self._scan_running():
            now.setEnabled(False)                # đang quét: không khởi động lại giữa chừng (Thoát vẫn dừng quét an toàn rồi cài)
        box.setDefaultButton(later)
        box.exec()
        if box.clickedButton() is quit_b:
            w.close()                            # đóng app: bản mới đã tải được cài khi thoát, không mở lại
            return
        if box.clickedButton() is not now:
            return
        w.pending_update = None
        try:
            updater.apply(src)
        except updater.UpdateError as e:
            self.bar.setVisible(False)
            QMessageBox.warning(self, "Cập nhật", str(e))
            return
        if hasattr(w, "quit_for_update"):
            w.quit_for_update()          # thoát hẳn tiến trình, không để luồng nền giữ lại
        else:
            w.close()

    def change_security(self):
        dlg = SecurityDialog(self)
        if dlg.exec():
            self.ctx.security_change.emit(dlg.values())

    def change_pw(self):
        old, ok = QInputDialog.getText(self, "Đổi mật khẩu", "Mật khẩu hiện tại:", QLineEdit.Password)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, "Đổi mật khẩu", "Mật khẩu mới (ít nhất 8 ký tự):", QLineEdit.Password)
        if not ok:
            return
        again, ok = QInputDialog.getText(self, "Đổi mật khẩu", "Nhập lại mật khẩu mới:", QLineEdit.Password)
        if not ok:
            return
        if new != again:
            QMessageBox.warning(self, "Lỗi", "Hai lần nhập mật khẩu mới không khớp.")
            return
        try:
            SEC.change_password(old, new)
            QMessageBox.information(self, "Xong", "Đã đổi mật khẩu. Dữ liệu không cần mã hóa lại.")
        except WrongPassword:
            QMessageBox.warning(self, "Lỗi", "Mật khẩu hiện tại không đúng.")
        except ValueError as e:
            QMessageBox.warning(self, "Lỗi", str(e))

    def new_recovery(self):
        pw = None
        if SEC.use_password:
            pw, ok = QInputDialog.getText(self, "Khóa khôi phục mới", "Nhập mật khẩu hiện tại (khóa khôi phục cũ sẽ hết hiệu lực):", QLineEdit.Password)
            if not ok:
                return
        try:
            rk = SEC.new_recovery_key(pw)
        except WrongPassword:
            QMessageBox.warning(self, "Lỗi", "Mật khẩu không đúng.")
            return
        RecoveryShowDialog(rk).exec()
        self.refresh()

    def backup(self):
        BackupDialog(self.ctx, self).exec()

    def sync_phone(self):
        SyncDialog(self.ctx, self).exec()




class SettingsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.worker = None
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.v.addWidget(self.list, 1)
        bar = QHBoxLayout()
        for text, fn in [("Thêm thư mục…", self.add), ("Bỏ thư mục đã chọn", self.remove)]:          # không còn nút nâng mức mã hóa: quét, phân loại, mã hóa, tải lên Drive và xóa ảnh gốc đều tự động
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        self.v.addLayout(bar)
        self.auto_cb = QCheckBox("Tự động cập nhật khi bạn thêm, xóa hoặc đổi tên ảnh trong các thư mục này (và khi mở ứng dụng)")
        self.auto_cb.setChecked(ctx.db.get_meta("auto_scan", "1") == "1")
        self.auto_cb.toggled.connect(lambda on: (ctx.db.set_meta("auto_scan", "1" if on else "0"), ctx.changed.emit()))
        self.v.addWidget(self.auto_cb)
        self.dupdel_cb = QCheckBox("Tự xóa ảnh trùng hoàn toàn (từng điểm ảnh giống hệt) trong thư mục gốc, chuyển vào Thùng rác, giữ lại bản chất lượng cao nhất")
        self.dupdel_cb.setToolTip("Chỉ xóa bản có TỪNG ĐIỂM ẢNH giống hệt ảnh giữ lại (kể cả khác dung lượng), là tệp rời trên ổ đĩa. Ảnh chỉ giống nhau (khác độ phân giải, nén lại làm đổi điểm ảnh) thì không tự xóa; "
                                  "xử lý ở mục Ảnh trùng lặp. Thùng rác của Windows khôi phục lại được.")
        self.dupdel_cb.setChecked(ctx.db.get_meta("dup_autodelete", "1") == "1")

        def toggle_dupdel(on):
            if on and QMessageBox.question(self, "Tự xóa ảnh trùng", "Từ lần quét sau, mỗi bản ảnh trùng Y HỆT (cùng từng byte) với một ảnh khác sẽ được chuyển vào Thùng rác "
                                           "của Windows, chỉ giữ một bản (bản có độ phân giải cao nhất, ưu tiên tệp rời). Có thể khôi phục từ Thùng rác. Bật?") != QMessageBox.Yes:
                self.dupdel_cb.blockSignals(True)
                self.dupdel_cb.setChecked(False)
                self.dupdel_cb.blockSignals(False)
                return
            ctx.db.set_meta("dup_autodelete", "1" if on else "0")
        self.dupdel_cb.toggled.connect(toggle_dupdel)
        self.v.addWidget(self.dupdel_cb)
        self._rescan = False
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.v.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.v.addWidget(self.bar)
        row = QHBoxLayout()
        self.locked_zips = []
        self.zip_b = QPushButton("Nhập mật khẩu file nén…")
        self.zip_b.setVisible(False)
        self.zip_b.clicked.connect(self.ask_zip_passwords)
        self.view_b = QPushButton("Xem ảnh")
        self.view_b.setVisible(False)
        self.view_b.clicked.connect(lambda: ctx.goto.emit("library"))
        self.b1 = QPushButton("Quét ảnh")
        self.b1.setProperty("primary", True)
        self.b1.setToolTip("Quét ảnh, tự tải mô hình nhận diện ở lần đầu (một lần duy nhất, cần mạng)")
        self.b1.clicked.connect(lambda: self.scan(True))
        self.b3 = QPushButton("Dừng")
        self.b3.clicked.connect(lambda: self.worker and self.worker.stop())
        self.b3.setEnabled(False)
        for x in (self.b1, self.b3, self.view_b, self.zip_b):
            row.addWidget(x)
        row.addStretch(1)
        self.v.addLayout(row)
        self.note = QLabel("Lần đầu tải mô hình khoảng 150 MB (cần mạng, sau đó chạy hoàn toàn offline). Thư viện hàng chục nghìn ảnh có thể quét vài giờ; bạn có thể dừng và quét tiếp, phần đã xong được giữ lại. "
                           "Thư mục mức “mã hóa cả ảnh gốc” luôn cần mô hình để nhập.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#666")
        self.v.addWidget(self.note)

    def refresh(self):
        self.list.clear()
        for r in self.ctx.db.folder_rows():
            it = QListWidgetItem(f"{r['path']}\n    → {LEVELS.get(r['level'], r['level'])}" + ("  · xóa ảnh gốc sau khi nhập" if r["del_orig"] else ""))
            it.setData(Qt.UserRole, r["path"])
            self.list.addItem(it)
        n = self.ctx.db.one("SELECT COUNT(*) c FROM images")["c"]
        e = self.ctx.db.one("SELECT COUNT(*) c FROM images WHERE vid IS NOT NULL")["c"]
        m = self.ctx.db.one("SELECT COUNT(*) c FROM images WHERE ml=1 AND err IS NULL")["c"]
        f = self.ctx.db.one("SELECT COUNT(*) c FROM faces")["c"]
        self.status.setText(f"Trong thư viện: {count_note(self.ctx.db)}" + (f", {e} đã mã hóa vào kho" if e else "") + f" · đã phân tích nội dung: {m} · khuôn mặt: {f} · mô hình: "
                            + ("đã tải" if self.ctx.models_ready() else "chưa tải"))

    # ---- cập nhật ----
    def add(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh")
        if not d:
            return
        dlg = FolderDialog(self, d, allow_all=self.ctx.encrypted)
        if dlg.exec():
            level, dele = dlg.result_level()
            self.ctx.db.add_folder(d, level, dele)
            self.ctx.changed.emit()
            if self.ctx.db.get_meta("auto_scan", "1") == "1":
                self.auto_scan([d])               # thêm thư mục xong là tự quét luôn

    def upgrade(self):
        if not self.ctx.encrypted:
            QMessageBox.information(self, "Cần bật mã hóa", "Mức “mã hóa cả ảnh gốc” cần bật mã hóa dữ liệu. Dùng “Thay đổi bảo mật…” để bật.")
            return
        sel = [i.data(Qt.UserRole) for i in self.list.selectedItems()]
        rows = {r["path"]: r for r in self.ctx.db.folder_rows()}
        for p in sel:
            if rows[p]["level"] == "all":
                continue
            dlg = FolderDialog(self, p, allow_keep=False)
            if dlg.exec():
                level, dele = dlg.result_level()
                self.ctx.db.set_folder_level(p, level, dele)
        self.refresh()

    def remove(self):
        for it in self.list.selectedItems():
            self.ctx.db.del_folder(it.data(Qt.UserRole))
        self.ctx.changed.emit()

    def scan(self, download):
        rows = [(r["path"], r["level"], r["del_orig"]) for r in self.ctx.db.folder_rows()]
        if not rows:
            QMessageBox.information(self, "Chưa có thư mục", "Hãy thêm ít nhất một thư mục ảnh.")
            return
        dels = [r[0] for r in rows if r[1] == "all" and r[2]]
        if dels and QMessageBox.question(self, "Xóa ảnh gốc",
                                         "Các thư mục sau sẽ bị XÓA ẢNH GỐC vĩnh viễn sau khi mã hóa:\n\n" + "\n".join(dels) +
                                         "\n\nTiếp tục?") != QMessageBox.Yes:
            return
        self._start_scan(rows, download, False)

    def _start_scan(self, rows, download, auto):
        self.view_b.setVisible(False)
        self.worker = ScanWorker(self.ctx.db, rows, self.ctx.vault if self.ctx.vault.unlocked() else None, download, auto, self.ctx.zip_passwords)
        self.worker.locked.connect(self.on_locked)
        self.worker.msg.connect(lambda t: (self.status.setText(t), self.ctx.scan_status.emit(t.rstrip("… ")) if t.startswith("Đang") and len(t) < 48 else None))      # dòng ngắn ở thanh bên: bước đang xử lý
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.b1.setEnabled(False)
        self.b3.setEnabled(True)
        self.worker.start(QThread.LowPriority if auto else QThread.NormalPriority)           # quét nền: ưu tiên thấp để vẫn dùng app mượt

    def on_progress(self, d, t, p):
        self.bar.setRange(0, max(1, t))
        self.bar.setValue(d)
        self.status.setText(f"Đang xử lý {d}/{t}: {os.path.basename(p)}")
        self.ctx.scan_status.emit(f"Đang quét {d}/{t}")
        now = time.time()
        if now - getattr(self, "_last_emit", 0) > 20:                     # làm mới giao diện tối đa 20 giây một lần (đang quét không làm giật)
            self._last_emit = now
            self.ctx.changed.emit()

    def on_done(self, text):
        self.ctx.scan_status.emit("Quét gặp lỗi" if text.startswith("Lỗi") else ("Đã dừng quét" if "(đã dừng)" in text else "Đã quét xong"))      # hiện ~3 giây rồi tự ẩn
        self.bar.setVisible(False)
        self.b1.setEnabled(True)
        self.b3.setEnabled(False)
        self.ctx.changed.emit()
        self.status.setStyleSheet("color:#c0392b" if text.startswith("Lỗi") else "")
        self.status.setText(text)
        self.view_b.setVisible(not text.startswith("Lỗi"))
        w = self.window()
        if getattr(self.worker, "n_changed", 0) > 0 and not text.startswith("Lỗi") and "(đã dừng)" not in text and hasattr(w, "sync_after_scan"):
            QTimer.singleShot(1500, w.sync_after_scan)                          # quét xong có ảnh mới: tự đẩy lên cho điện thoại
        if self._rescan:                       # có thay đổi mới trong lúc đang quét
            self._rescan = False
            self.auto_scan()

    def on_locked(self, zips):
        self.locked_zips = list(zips)
        self.zip_b.setVisible(bool(zips))

    def ask_zip_passwords(self):
        ok_any = False
        for zp in list(self.locked_zips):
            pw, ok = QInputDialog.getText(self, "Mật khẩu file nén", f"Nhập mật khẩu của file nén:\n{zp}", QLineEdit.Password)
            if not ok:
                break
            try:
                zipimg.verify(zp, pw)
            except zipimg.PasswordNeeded:
                QMessageBox.warning(self, "Sai mật khẩu", f"Mật khẩu không đúng cho {os.path.basename(zp)}.")
                continue
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", str(e))
                continue
            self.ctx.set_zip_password(zp, pw)
            ok_any = True
        if ok_any:
            self.locked_zips = [z for z in self.locked_zips if z not in self.ctx.zip_passwords]
            self.zip_b.setVisible(bool(self.locked_zips))
            self.auto_scan()

    def auto_scan(self, roots=None):
        """Cập nhật thư viện sau khi thư mục thay đổi (hoặc lúc mở ứng dụng). Không hỏi gì; không tải mô hình; không xóa ảnh gốc."""
        if self.ctx.db.get_meta("auto_scan", "1") != "1":
            return
        rows = [(r["path"], r["level"], r["del_orig"]) for r in self.ctx.db.folder_rows() if roots is None or r["path"] in roots]
        keep, notes = [], []
        for r in rows:
            if r[1] == "all":
                if r[2]:
                    notes.append(f"{r[0]}: có thay đổi, bấm “Quét ảnh” để mã hóa (thư mục này xóa ảnh gốc sau khi mã hóa)")
                    continue
                if not (self.ctx.models_ready() and self.ctx.vault.unlocked()):
                    notes.append(f"{r[0]}: có thay đổi, cần tải mô hình rồi bấm “Quét ảnh” để mã hóa")
                    continue
            keep.append(r)
        if self.worker and self.worker.isRunning():
            self._rescan = True
            return
        if notes:
            self.status.setStyleSheet("")
            self.status.setText("; ".join(notes))
        if keep:
            self._start_scan(keep, False, True)

    def wipe(self):
        if QMessageBox.question(self, "Xóa dữ liệu phân tích", "Xóa danh mục ảnh, ảnh thu nhỏ, khuôn mặt, tên người và nhãn? Ảnh gốc ở thư mục thường KHÔNG bị ảnh hưởng. "
                                "Ảnh đã mã hóa trong kho vẫn còn nhưng sẽ phải nhập lại để hiện trong thư viện.") != QMessageBox.Yes:
            return
        import shutil
        from .. import paths
        for t in ("images", "faces", "persons", "labels", "label_images", "imported"):
            self.ctx.db.c.execute(f"DELETE FROM {t}")
        self.ctx.db.commit()
        for d in (paths.thumbs_dir(), paths.faces_dir()):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
        self.ctx.changed.emit()


def assign_dialog(ctx, parent, image_ids, from_pid=None):
    """Thêm các ảnh đã chọn vào một người: gõ tên để tìm (gợi ý theo tên đã có) hoặc nhập tên mới; có bước xác nhận trước khi thực hiện."""
    db = ctx.db
    people = [p for p in db.persons() if p["name"]]
    dlg = QDialog(parent)
    dlg.setWindowTitle("Thêm ảnh vào người")
    dlg.resize(520, 520)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(f"Đã chọn <b>{len(image_ids)}</b> ảnh. Gõ tên người cần thêm vào (chọn từ gợi ý, hoặc nhập tên mới nếu chưa có):"))
    ed = QLineEdit()
    ed.setPlaceholderText("Tên người…")
    lay.addWidget(ed)
    sug = QListWidget()                                          # gợi ý theo tên đã có, kèm ảnh người đó để so sánh
    sug.setIconSize(QSize(64, 64))
    sug.setMinimumHeight(260)
    lay.addWidget(sug, 1)
    icons = {}

    def icon_of(p):
        if p["id"] not in icons:
            pm = QPixmap()
            try:
                if p["cover"]:
                    pm.loadFromData(SEC.read_file(p["cover"]))
            except Exception:
                pass
            icons[p["id"]] = QIcon(pm.scaled(64, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)) if not pm.isNull() else QIcon()
        return icons[p["id"]]

    def fill_sug():
        t = cluster.fold(ed.text().strip())
        sug.clear()
        hits = [p for p in people if t and t in cluster.fold(p["name"])] if t else sorted(people, key=lambda p: -p["n"])
        for p in hits[:8]:
            it = QListWidgetItem(icon_of(p), f"{p['name']}\n{p['n']} ảnh")
            it.setData(Qt.UserRole, p["name"])
            sug.addItem(it)
    sug.itemClicked.connect(lambda it: ed.setText(it.data(Qt.UserRole)))
    info = QLabel()
    info.setWordWrap(True)
    lay.addWidget(info)
    ok_b, cancel_b = QPushButton("Tiếp tục…"), QPushButton("Hủy")
    ok_b.setProperty("primary", True)
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(cancel_b)
    row.addWidget(ok_b)
    lay.addLayout(row)

    def match():
        t = ed.text().strip()
        return next((p for p in people if cluster.fold(p["name"]) == cluster.fold(t)), None) if t else None

    def refresh(_=None):
        t, m = ed.text().strip(), match()
        ok_b.setEnabled(bool(t))
        info.setText("" if not t else (f"Người có sẵn: <b>{m['name']}</b> ({m['n']} ảnh)." if m else f"Chưa có người tên “{t}”: sẽ tạo người mới."))
    ed.textChanged.connect(lambda _=None: (refresh(), fill_sug()))
    refresh()
    fill_sug()
    cancel_b.clicked.connect(dlg.reject)
    ok_b.clicked.connect(dlg.accept)
    if not dlg.exec():
        return False
    t, m = ed.text().strip(), match()
    if m is not None and from_pid is not None and m["id"] == from_pid:
        QMessageBox.information(parent, "Thêm ảnh vào người", "Các ảnh này đã thuộc người đó.")
        return False
    msg = (f"Thêm {len(image_ids)} ảnh đã chọn vào <b>{m['name']}</b>?" if m else f"Tạo người mới <b>{t}</b> và thêm {len(image_ids)} ảnh đã chọn vào?")
    if QMessageBox.question(parent, "Xác nhận", msg) != QMessageBox.Yes:                   # bước xác nhận: tránh bấm nhầm
        return False
    to = m["id"] if m else db.x("INSERT INTO persons(name) VALUES(?)", (t,)).lastrowid
    cluster.assign_images_to_person(db, image_ids, to, from_pid)
    ctx.changed.emit()
    return True


def library_counts(db):
    """(tổng ảnh trong thư viện, số ảnh hiện ở Tất cả, số bản trùng đã ẩn, số ảnh không đọc được) để hai chỗ thống kê giải thích khớp nhau."""
    n = db.one("SELECT COUNT(*) c FROM images")["c"]
    shown = db.one("SELECT COUNT(*) c FROM images WHERE thumb IS NOT NULL AND id NOT IN (SELECT image_id FROM dup_hidden)")["c"]
    dup_n = db.one("SELECT COUNT(*) c FROM images WHERE thumb IS NOT NULL AND id IN (SELECT image_id FROM dup_hidden)")["c"]
    return n, shown, dup_n, n - shown - dup_n


def count_note(db):
    n, shown, dup_n, bad = library_counts(db)
    return f"{n} ảnh (hiện ở All: {shown}" + (f"; {dup_n} bản trùng đã ẩn" if dup_n else "") + (f"; {bad} ảnh chưa đọc được" if bad else "") + ")"


def coverage_dialog(ctx, parent):
    """Kiểm tra tệp nén nhiều tên: số tên so với số người nhận ra, tên nào chưa thấy ảnh, còn bao nhiêu nhóm mặt chưa có tên (dấu '...')."""
    from PySide6.QtWidgets import QTextBrowser
    rows = cluster.archive_coverage(ctx.db)
    dlg = QDialog(parent)
    dlg.setWindowTitle("Kiểm tra tệp nhiều tên")
    dlg.resize(760, 520)
    lay = QVBoxLayout(dlg)
    tb = QTextBrowser()
    lay.addWidget(tb)
    if not rows:
        tb.setHtml("Chưa có tệp nén nào mang nhiều tên người.")
    else:
        bad = sum(1 for r in rows if r["missing"])
        h = [f"<p><b>{len(rows)} tệp nhiều tên</b>; {bad} tệp có tên chưa thấy ảnh.</p>"]
        for r in rows:
            found = len(r["names"]) - len(r["missing"])
            head = f"<b>{os.path.basename(r['archive'])}</b><br>{len(r['names'])} tên · {found} người đã có ảnh · {r['images']} ảnh"
            if r["missing"]:
                head += f"<br><span style='color:#c0392b'>Chưa thấy ảnh: {', '.join(r['missing'])}</span>"
            if r["more"]:
                head += (f"<br>Tên tệp có “…” (còn người chưa ghi tên): hiện có <b>{r['unnamed']}</b> nhóm mặt chưa có tên trong tệp này."
                         if r["unnamed"] else "<br>Tên tệp có “…” (còn người chưa ghi tên): chưa thấy nhóm mặt nào chưa có tên.")
            elif r["unnamed"]:
                head += f"<br>Có {r['unnamed']} nhóm mặt chưa có tên ngoài các tên đã ghi (có thể là người chụp chung)."
            h.append("<p>" + head + "</p>")
        tb.setHtml("".join(h))
    close = QPushButton("Đóng")
    close.clicked.connect(dlg.accept)
    lay.addWidget(close)
    dlg.exec()

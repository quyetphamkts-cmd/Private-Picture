import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
from PIL import Image

from test_core import FakeClip, FakeFaces


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    pics = tmp_path / "pics"
    pics.mkdir()
    rng = np.random.default_rng(2)
    for i, base in enumerate([(220, 20, 20)] * 4 + [(20, 20, 220)] * 4):
        arr = np.clip(np.array(base) + rng.integers(-10, 10, (300, 400, 3)), 0, 255).astype(np.uint8)
        Image.fromarray(arr).save(pics / f"p{i}.jpg")
    from pp import cluster, paths, scan
    from pp.db import DB
    from pp.ui.ctx import AppContext
    db = DB(paths.db_path())
    scan.Scanner(db, FakeFaces(), FakeClip()).run([str(pics)])
    db.add_folder(str(pics))
    cluster.cluster_faces(db)
    return app, AppContext(db=db), tmp_path, monkeypatch, QInputDialog


def test_pages(app_env):
    app, ctx, tmp, mp, QID = app_env
    from pp.ui.main import MainWindow
    ctx.db.set_meta("dup_auto", "0")          # kiểm thử giao diện không muốn ẩn ảnh trùng
    w = MainWindow(ctx)
    w.show()
    for key, page in w.pages.items():
        w.goto(key)
        page.refresh()
        app.processEvents()
        w.grab().save(str(tmp / f"{key}.png"))
    lib = w.pages["library"]
    assert lib.grid.model.rowCount() == 8
    # người
    ppl = w.pages["people"]
    w.goto("people")
    assert ppl.pmodel.rowCount() + ppl.umodel.rowCount() == 2
    ppl.pid = ctx.db.persons()[0]["id"]
    mp.setattr(QID, "getText", staticmethod(lambda *a, **k: ("Lan", True)))
    ppl.rename()
    assert ctx.db.one("SELECT COUNT(*) c FROM persons WHERE name='Lan'")["c"] == 1
    # tương tự
    sim = w.pages["similar"]
    sim.sl.setValue(95)
    sim.run()
    assert len(sim.groups) == 2
    # nhãn
    ids = [r["id"] for r in ctx.db.images()][:2]
    mp.setattr(QID, "getItem", staticmethod(lambda *a, **k: ("phía trước", True)))
    from pp.ui.pages import add_to_label
    add_to_label(ctx, w, ids)
    lab = w.pages["labels"]
    w.goto("labels")
    lab.suggest()
    assert lab.suggesting and lab.grid.model.rowCount() > 0
    # kho riêng tư
    vp = w.pages["vault"]
    w.goto("vault")
    vp.pw.setText("matkhau1")
    vp.pw2.setText("matkhau1")
    vp.unlock()
    assert ctx.vault.unlocked()
    from pp.ui.pages import move_to_vault
    from PySide6.QtWidgets import QMessageBox
    item = lib.grid.model.items[0]
    victim = item["path"]
    n_before = lib.grid.model.rowCount()

    class FakeBox(QMessageBox):
        def exec(self):
            self._c = [b for b in self.buttons() if b.text().startswith("Mã hóa và xóa")][0]
        def clickedButton(self):
            return self._c
    mp.setattr("pp.ui.pages.QMessageBox", FakeBox)
    move_to_vault(ctx, w, [item])
    assert not os.path.exists(victim)
    assert len(ctx.vault.index) == 1
    w.goto("library")
    lib.refresh()
    assert lib.grid.model.rowCount() == n_before        # ảnh vẫn nằm trong thư viện, nhưng đã mã hóa
    moved = ctx.db.one("SELECT vid,path FROM images WHERE vid IS NOT NULL")
    assert moved["path"].startswith("vault://")
    assert [i for i in lib.grid.model.items if i["vid"]]
    w.goto("vault")
    vp.refresh()
    assert vp.model.rowCount() == 1
    assert not vp.model.data(vp.model.index(0), 1).isNull()
    vp.lock()
    assert not ctx.vault.unlocked()
    w.close()


def test_library_hide_labeled_and_rename_label(tmp_path, monkeypatch):
    import os
    from pp import db as dbm, paths
    from pp.ui.pages import LabelsPage, LibraryPage
    from pp.ui.ctx import AppContext
    monkeypatch.setenv("PP_HOME", str(tmp_path / "h"))
    ctx = AppContext()
    for i in range(3):
        ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb) VALUES(?,?,?,?,?,?,?)", (f"/x/{i}.jpg", 1, 1, 100, 100, "2024-01-0%d 10:00:00" % (i + 1), "t%d" % i))
    lid = ctx.db.x("INSERT INTO labels(name) VALUES('A')").lastrowid
    first = ctx.db.one("SELECT id FROM images ORDER BY id LIMIT 1")["id"]
    ctx.db.x("INSERT INTO label_images VALUES(?,?)", (lid, first))
    lib = LibraryPage(ctx)
    lib.refresh()
    assert len(lib.grid.model.items) == 3
    lib.hide_lab.setChecked(True)
    assert len(lib.grid.model.items) == 2 and "ẩn 1" in lib.count.text()
    lp = LabelsPage(ctx)
    lp.refresh()
    lp.list.setCurrentRow(0)
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Phía trước", True)))
    lp.rename()
    assert ctx.db.one("SELECT name FROM labels WHERE id=?", (lid,))["name"] == "Phía trước"


def test_unlabel_and_change_label(tmp_path, monkeypatch):
    from pp.ui import pages
    from pp.ui.ctx import AppContext
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setenv("PP_HOME", str(tmp_path / "h2"))
    ctx = AppContext()
    ids = [ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/y/{i}.jpg", 1, 1, 10, 10, "t")).lastrowid for i in range(3)]
    a = ctx.db.x("INSERT INTO labels(name) VALUES('A')").lastrowid
    for i in ids:
        ctx.db.x("INSERT INTO label_images VALUES(?,?)", (a, i))
    have = pages.labels_of(ctx.db, ids[:2])
    assert have == [(a, "A", 2)]
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *x, **k: ("B", True)))
    pages.change_label(ctx, None, ids[:2], have)
    b = ctx.db.one("SELECT id FROM labels WHERE name='B'")["id"]
    assert sorted(ctx.db.label_ids(b)) == sorted(ids[:2]) and ctx.db.label_ids(a) == [ids[2]]
    pages.unlabel(ctx, ids[:1], b)
    assert ctx.db.label_ids(b) == [ids[1]]


def test_duplicates_page_cards_and_actions(tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image
    from pp import dup, scan
    from pp.ui.ctx import AppContext
    from pp.ui.pages import DuplicatesPage
    from test_core import FakeFaces, FakeClip
    monkeypatch.setenv("PP_HOME", str(tmp_path / "hd"))
    pics = tmp_path / "pp"
    pics.mkdir()
    rng = np.random.default_rng(3)
    base = rng.integers(0, 255, (400, 600, 3)).astype(np.uint8)
    Image.fromarray(base).save(pics / "goc.jpg", quality=95)
    Image.fromarray(base).resize((300, 200)).save(pics / "nho.jpg", quality=85)
    Image.fromarray(base[::-1].copy()).resize((290, 190)).save(pics / "khac.jpg", quality=85)   # ảnh khác, bị nhầm là trùng
    ctx = AppContext()
    scan.Scanner(ctx.db, FakeFaces(), FakeClip(), lambda *a: None, lambda: False).run_folders([(str(pics), "data", 0)])
    ids = {os.path.basename(r["path"]): r["id"] for r in ctx.db.q("SELECT id,path FROM images")}
    page = DuplicatesPage(ctx)
    page.groups = [{"keep": ids["goc.jpg"], "members": [ids["goc.jpg"], ids["nho.jpg"], ids["khac.jpg"]]}]
    dup.rekeep(ctx.db, page.groups[0])
    assert page.groups[0]["keep"] == ids["goc.jpg"]
    page.render()
    assert "sẽ xóa 2 tệp" in page.cnt.text()
    page.drop_image(page.groups[0], ids["khac.jpg"])              # loại ảnh không trùng khỏi cụm
    page.render()
    assert "sẽ xóa 1 tệp" in page.cnt.text()
    assert ids["khac.jpg"] not in dup.hidden_ids(ctx.db)
    items, skipped = dup.confirmed_items(ctx.db, page.groups)
    assert [os.path.basename(p) for _, p, _ in items] == ["nho.jpg"] and skipped == 0


def test_select_similar_and_label_quick_pick(tmp_path, monkeypatch):
    import numpy as np
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import LabelsPage, LibraryPage
    monkeypatch.setenv("PP_HOME", str(tmp_path / "hs"))
    ctx = AppContext()
    base = np.random.default_rng(1).normal(size=512).astype(np.float32)
    other = np.random.default_rng(2).normal(size=512).astype(np.float32)

    def mk(i, v):
        v = v / np.linalg.norm(v)
        return ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb,clip) VALUES(?,?,?,?,?,?,?,?)",
                        (f"/s/{i}.jpg", 1, 1, 100, 100, "2024-01-01 00:00:00", "t", vec_to_blob(v))).lastrowid
    a = [mk(i, base + np.random.default_rng(10 + i).normal(size=512).astype(np.float32) * 0.05) for i in range(4)]
    b = [mk(10 + i, other + np.random.default_rng(20 + i).normal(size=512).astype(np.float32) * 0.05) for i in range(3)]
    lib = LibraryPage(ctx)
    lib.refresh()
    items = lib.grid.model.items
    first = next(r for r, it in enumerate(items) if it["id"] == a[0])
    lib.grid.grid.select_rows([first])
    n = lib.grid.select_similar(0.85)
    got = {items[r]["id"] for r in (i.row() for i in lib.grid.grid.selectedIndexes())}
    assert got == set(a) and n == 3                    # chọn thêm đúng 3 ảnh giống, không lẫn ảnh khác
    # trang Nhãn: nhãn có ảnh mẫu -> chọn nhanh ảnh giống trong danh sách gợi ý
    lid = ctx.db.x("INSERT INTO labels(name) VALUES('Mau')").lastrowid
    ctx.db.x("INSERT INTO label_images VALUES(?,?)", (lid, a[0]))
    lp = LabelsPage(ctx)
    lp.refresh()
    lp.list.setCurrentRow(0)
    lp.pick_c.setCurrentIndex(1)
    lp.pick_similar()
    ids = {it["id"] for r, it in enumerate(lp.grid.model.items) if r in {i.row() for i in lp.grid.grid.selectedIndexes()}}
    assert ids == set(a[1:])


def test_autolabel_suggest_apply_undo(tmp_path, monkeypatch):
    import numpy as np
    from pp import autolabel
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    monkeypatch.setenv("PP_HOME", str(tmp_path / "al"))
    ctx = AppContext()
    rng = np.random.default_rng(4)
    A, B = rng.normal(size=512), rng.normal(size=512)

    def mk(i, base, noise=0.04):
        v = base + rng.normal(size=512) * noise
        v = (v / np.linalg.norm(v)).astype(np.float32)
        return ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb,clip) VALUES(?,?,?,?,?,?,?,?)",
                        (f"/a/{i}.jpg", 1, 1, 10, 10, "2024-01-01 00:00:00", "t", vec_to_blob(v))).lastrowid
    la = ctx.db.x("INSERT INTO labels(name) VALUES('Truoc')").lastrowid
    lb = ctx.db.x("INSERT INTO labels(name) VALUES('Sau')").lastrowid
    for i in range(4):
        ctx.db.x("INSERT INTO label_images VALUES(?,?)", (la, mk(i, A)))
        ctx.db.x("INSERT INTO label_images VALUES(?,?)", (lb, mk(10 + i, B)))
    new_a = [mk(100 + i, A, 0.06) for i in range(3)]
    new_b = [mk(200 + i, B, 0.06) for i in range(2)]
    odd = mk(300, rng.normal(size=512), 0.0)                       # ảnh lạ: không được gợi ý
    s = autolabel.suggest(ctx.db)
    assert {i for i, _ in s[la]} == set(new_a) and {i for i, _ in s[lb]} == set(new_b) and odd not in {i for v in s.values() for i, _ in v}
    n = autolabel.run_auto(ctx.db, thr=0.5)
    assert n == 5 and set(ctx.db.label_ids(la)) >= set(new_a)
    assert autolabel.undo_auto(ctx.db) == 5 and not (set(ctx.db.label_ids(la)) & set(new_a))
    assert not autolabel.suggest(ctx.db).get(la)                    # đã hoàn tác: không tự gán lại các ảnh đó


def test_autolabel_dialog_smoke(tmp_path, monkeypatch):
    import numpy as np
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import AutoLabelDialog
    monkeypatch.setenv("PP_HOME", str(tmp_path / "ald"))
    ctx = AppContext()
    rng = np.random.default_rng(8)
    base = rng.normal(size=512)
    lid = ctx.db.x("INSERT INTO labels(name) VALUES('L')").lastrowid
    for i in range(5):
        v = (base + rng.normal(size=512) * 0.03).astype(np.float32)
        iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb,clip) VALUES(?,?,?,?,?,?,?,?)", (f"/d/{i}.jpg", 1, 1, 9, 9, "2024-01-01 00:00:00", "t", vec_to_blob(v / np.linalg.norm(v)))).lastrowid
        if i < 3:
            ctx.db.x("INSERT INTO label_images VALUES(?,?)", (lid, iid))
    d = AutoLabelDialog(ctx)
    assert d.list.count() == 1 and "2 ảnh" in d.list.item(0).text()
    d.grid.grid.select_all()
    d.add_selected()
    assert len(ctx.db.label_ids(lid)) == 5 and d.list.count() == 0


def test_clothing_classify_and_library_filter(tmp_path, monkeypatch):
    import numpy as np
    from pp import clothing
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import LibraryPage
    monkeypatch.setenv("PP_HOME", str(tmp_path / "cl"))
    ctx = AppContext()
    rng = np.random.default_rng(3)
    prompts = [p for _, _, ps in clothing.CATS for p in ps]
    by_prompt = dict(zip(prompts, rng.normal(size=(len(prompts), 512)).astype(np.float32)))
    first = lambda code: next(ps[0] for c, _, ps in clothing.CATS if c == code)
    ids = {}
    for name, p in (("a", first("short")), ("b", first("long")), ("n", first("nude")), ("x", first("none"))):
        v = (by_prompt[p] + rng.normal(size=512) * 0.05).astype(np.float32)
        ids[name] = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb,clip) VALUES(?,?,?,?,?,?,?,?)",
                             (f"/c/{name}.jpg", 1, 1, 9, 9, "2024-01-01 00:00:00", "t", vec_to_blob(v / np.linalg.norm(v)))).lastrowid
    assert clothing.analyze(ctx.db, lambda s: by_prompt[s]) == 4
    cnt = clothing.group_counts(ctx.db)
    assert cnt == {"cloth": 2, "nude": 1}                           # đồ ngắn + đồ dài = mặc đồ; nude = không mặc đồ; ảnh không người: không thuộc nhóm nào
    assert clothing.analyze(ctx.db, lambda s: by_prompt[s]) == 0         # đã phân loại: không làm lại
    lib = LibraryPage(ctx)
    lib.refresh()
    assert len(lib.grid.model.items) == 4
    assert "c" not in lib.rows                                       # Tất cả không còn bộ lọc trang phục (chỉ ở trang từng người)
    assert not ctx.db.labels()                                       # và phân loại không tạo nhãn ảnh


def test_person_page_cloth_filter(tmp_path, monkeypatch):
    import numpy as np
    from pp import clothing
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    monkeypatch.setenv("PP_HOME", str(tmp_path / "pc"))
    ctx = AppContext()
    pid = ctx.db.x("INSERT INTO persons(name) VALUES('X')").lastrowid
    imgs = []
    for i, g in enumerate(["cloth", "cloth", "nude"]):
        iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb) VALUES(?,?,?,?,?,?,?)", (f"/p/{i}.jpg", 1, 1, 9, 9, "2024-01-01 00:00:00", "t")).lastrowid
        ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)",
                 (iid, 0.1, 0.1, 0.2, 0.2, 0.95, 80, vec_to_blob(np.ones(128, np.float32)), pid))
        ctx.db.x("INSERT INTO cloth_group(image_id,grp,p) VALUES(?,?,?)", (iid, g, 0.9))
        imgs.append(iid)
    page = PeoplePage(ctx)
    page.pid = pid
    page.show_person()
    assert len(page.photos.model.items) == 3
    parts = {k: [it["id"] for it in pg.model.items] for k, (_, pg, _) in page.grouped.parts.items()}
    assert parts == {"cloth": [imgs[0], imgs[1]], "nude": [imgs[2]], "unclear": []}       # Tất cả: chia cụm
    assert page.grouped.parts["unclear"][1].isHidden()                                       # cụm trống tự ẩn
    from pp import clothing
    ctx.db.x("DELETE FROM cloth_group WHERE image_id=?", (imgs[1],))
    page.show_person()
    assert [it["id"] for it in page.grouped.parts["unclear"][1].model.items] == [imgs[1]] and not page.grouped.parts["unclear"][1].isHidden()
    clothing.set_manual(ctx.db, [imgs[1]], "cloth")                                          # phân loại xong thì cụm "Chưa phân loại" biến mất
    page.show_person()
    assert page.grouped.parts["unclear"][1].isHidden()
    page.cloth_row.pick("nude")
    assert [it["id"] for it in page.photos.model.items] == [imgs[2]]
    page.cloth_row.pick("cloth")
    assert {it["id"] for it in page.photos.model.items} == {imgs[0], imgs[1]}


def test_sync_dialog_stats_and_free_button(tmp_path, monkeypatch):
    from pp import sync
    from pp.ui.ctx import AppContext
    from pp.ui.pages import SyncDialog
    monkeypatch.setenv("PP_HOME", str(tmp_path / "sd"))
    ctx = AppContext()
    dest = str(tmp_path / "drive")
    ctx.db.set_meta("sync_dir", dest)
    d = SyncDialog(ctx)
    assert "Chưa có dữ liệu" in d.stats_l.text()
    sync.setup(dest, "pw")
    d.dir.setText(dest)
    d.refresh_stats()
    assert "Dung lượng đang chiếm trên Drive" in d.stats_l.text()
    assert d.free_b.text().startswith("Giải phóng")


def test_dialogs_opened_from_pages_are_readable(tmp_path, monkeypatch):
    """Hộp thoại mở từ một trang phải có nền sáng (không thừa hưởng nền trong suốt của khung cuộn) để đọc được chữ."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from pp.ui import theme
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    from pp.ui.pages import SyncDialog
    monkeypatch.setenv("PP_HOME", str(tmp_path / "rd"))
    theme.apply(QApplication.instance())
    ctx = AppContext()
    w = MainWindow(ctx)
    w.show()
    w.goto("account")
    page = w.pages["account"]
    d = SyncDialog(ctx, page)                       # tạo như khi bấm nút trong trang
    d.show()
    QApplication.processEvents()
    img = d.grab().toImage()
    px = QColor(img.pixel(img.width() // 2, img.height() - 8))        # vùng nền trống phía dưới hộp thoại
    assert px.name().lower() == theme.CREAM.lower(), px.name()           # đúng màu nền của giao diện, không phải đen mặc định
    d.close()


def test_rename_person_via_button_and_menu(tmp_path, monkeypatch):
    """Nút 'Đặt tên' (tín hiệu clicked gửi False) và menu chuột phải (gửi mã người) đều phải đặt đúng tên."""
    import numpy as np
    from PySide6.QtWidgets import QInputDialog, QPushButton
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    monkeypatch.setenv("PP_HOME", str(tmp_path / "rn"))
    ctx = AppContext()
    iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES('/r/1.jpg',1,1,9,9,'t')").lastrowid
    pid = ctx.db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)",
             (iid, 0.1, 0.1, 0.2, 0.2, 0.95, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    page = PeoplePage(ctx)
    page.refresh()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Nguyen Van A", True)))
    page.pid = pid
    btn = next(b for b in page.findChildren(QPushButton) if b.text() == "⋯")
    next(a for a in btn.menu().actions() if a.text().startswith("Đặt tên")).trigger()      # như khi người dùng chọn trong menu ⋯
    assert ctx.db.one("SELECT name FROM persons WHERE id=?", (pid,))["name"] == "Nguyen Van A"
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Tran B", True)))
    page.rename(pid)                                                     # như khi chọn trong menu chuột phải
    assert ctx.db.one("SELECT name FROM persons WHERE id=?", (pid,))["name"] == "Tran B"


def test_filter_bar_dropdowns(tmp_path, monkeypatch):
    from pp.ui.ctx import AppContext
    from pp.ui.pages import LibraryPage
    monkeypatch.setenv("PP_HOME", str(tmp_path / "fb"))
    ctx = AppContext()
    for i, y in enumerate(["2024", "2024", "2023"]):
        ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb) VALUES(?,?,?,?,?,?,?)", (f"/f/{i}.jpg", 1, 1, 9, 9, f"{y}-05-0{i + 1} 10:00:00", "t"))
    lid = ctx.db.x("INSERT INTO labels(name) VALUES('L1')").lastrowid
    ctx.db.x("INSERT INTO label_images SELECT ?,id FROM images WHERE path LIKE '%/0.jpg'", (lid,))
    lib = LibraryPage(ctx)
    lib.refresh()
    fb = lib.fbar
    kinds = [fb.kind_c.itemText(i) for i in range(fb.kind_c.count())]
    assert kinds[0] == "Tất cả" and "Năm" in kinds and "Nhãn" in kinds        # chỉ hiện kiểu phân loại đang có dữ liệu
    assert not fb.val_c.isEnabled()
    fb.kind_c.setCurrentIndex(fb.kind_c.findData("y"))                            # chọn kiểu: Năm
    assert fb.val_c.isEnabled() and any("2023" in fb.val_c.itemText(i) for i in range(fb.val_c.count()))
    fb.val_c.setCurrentIndex(fb.val_c.findData("2023"))                           # chọn giá trị: 2023
    assert len(lib.grid.model.items) == 1
    fb.kind_c.setCurrentIndex(fb.kind_c.findData("l"))                            # đổi sang Nhãn: bộ lọc năm tự bỏ
    assert len(lib.grid.model.items) == 3 and fb.slots["y"].value is None
    fb.val_c.setCurrentIndex(fb.val_c.findData(lid))
    assert len(lib.grid.model.items) == 1
    fb.clear_b.click()
    assert len(lib.grid.model.items) == 3 and fb.active is None


def test_people_filters_search_letter_hair(tmp_path, monkeypatch):
    import numpy as np
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    monkeypatch.setenv("PP_HOME", str(tmp_path / "pf"))
    ctx = AppContext()
    names = ["Nguyễn Văn An", "Trần Thị Bé", "Lê Đức", None, "Phạm Anh"]
    hairs = [(15, 1, 2), (72, 3, 26), (15, 1, 2), (45, 10, 18), (72, 3, 26)]
    for i, (nm, hv) in enumerate(zip(names, hairs)):
        pid = ctx.db.x("INSERT INTO persons(name) VALUES(?)", (nm,)).lastrowid
        for j in range(2):
            iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/pp/{i}{j}.jpg", 1, 1, 9, 9, "t")).lastrowid
            fid = ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)",
                           (iid, 0.1, 0.1, 0.2, 0.2, 0.95, 80, vec_to_blob(np.ones(128, np.float32)), pid)).lastrowid
            ctx.db.x("INSERT INTO face_attr(face_id,sk_l,sk_a,sk_b,hr_l,hr_a,hr_b,sharp) VALUES(?,?,?,?,?,?,?,?)", (fid, 70, 12, 20, *hv, 3))
    page = PeoplePage(ctx)
    page.refresh()
    assert page.pmodel.rowCount() + page.umodel.rowCount() == 5
    assert page.pmodel.rowCount() == 4 and page.umodel.rowCount() == 1
    heads = [lab.text().split()[0] for lab, _, _ in page.alpha._w]
    assert heads[-1] == "#" and heads[:-1] == sorted(heads[:-1]) and len(heads) >= 3     # chia theo chữ cái đầu A, B, C…; người chưa đặt tên nằm ở mục #
    assert sum(g.model().rowCount() for g, _ in page.alpha.sections) == 5
    page.search.setText("tran")                                                   # tìm không phân biệt dấu
    assert [it["label"].split("\n")[0] for it in page.pmodel.items] == ["Trần Thị Bé"]
    page.search.setText("")
    page.letter = "N"
    page.refresh()
    assert [it["label"].split("\n")[0] for it in page.pmodel.items] == ["Nguyễn Văn An"]
    page.letter = None
    page.sort_c.setCurrentIndex(page.sort_c.findData("given"))                    # theo tên gọi: An, Anh, Bé, Đức, (chưa đặt tên)
    page.letter = "B"
    page.refresh()
    assert [it["label"].split("\n")[0] for it in page.pmodel.items] == ["Trần Thị Bé"]
    page.letter = None
    page.sort_c.setCurrentIndex(page.sort_c.findData("n"))
    page.refresh()
    items = [page.hair_c.itemText(i) for i in range(page.hair_c.count())]
    assert any("Đen" in t for t in items) and any("Vàng" in t for t in items)
    page.hair_c.setCurrentIndex(page.hair_c.findData("blonde"))
    assert {it["label"].split("\n")[0] for it in page.pmodel.items} == {"Trần Thị Bé", "Phạm Anh"}



def test_expand_guess_dialog(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "eg"))
    shown = []
    monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(self) or 0)
    monkeypatch.setattr(QDialog, "showMaximized", lambda self: shown.append("max"))
    ctx = AppContext()
    page = PeoplePage(ctx)
    page.expand_guess()
    assert "max" in shown and any(isinstance(d, QDialog) for d in shown)
    page.photos.expand("Ảnh")                                  # khung ảnh chính của người cũng mở rộng được
    assert shown.count("max") == 2


def test_locate_image_in_library_and_names_on_items(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import LibraryPage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "loc"))
    ctx = AppContext()
    pid = ctx.db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    ids = []
    for i in range(30):
        iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,taken,thumb) VALUES(?,?,?,?,?,?,?)", (f"/l/{i}.jpg", i, 1, 9, 9, f"2024-01-{i % 28 + 1:02d} 10:00:00", "t")).lastrowid
        ids.append(iid)
        if i == 7:
            ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .95, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    lib = LibraryPage(ctx)
    lib.resize(800, 500)
    lib.show()
    lib.q.setText("zzz")                                      # một bộ lọc đang bật làm ảnh biến mất
    lib.refresh()
    assert not lib.grid.model.items
    lib.show_image(ids[7])                                    # bỏ lọc và chuyển tới ảnh
    assert len(lib.grid.model.items) == 30 and lib.q.text() == ""
    k = next(i for i, it in enumerate(lib.grid.model.items) if it["id"] == ids[7])
    assert lib.grid.grid.sel == {k}
    assert "Anna Nguyen" in lib.grid.model.items[k]["cap_tag"] and "Anna Nguyen" in lib.grid.model.items[k]["tip"]


def test_viewer_context_menu_entries(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import _viewer_menu
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "vm"))
    ctx = AppContext()
    a = ctx.db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    b = ctx.db.x("INSERT INTO persons(name) VALUES('Bella Tran')").lastrowid
    iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES('/v/1.jpg',1,1,9,9,'t')").lastrowid
    for pid in (a, b):
        ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .95, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    assert "Phân loại" not in [n for n, _ in _viewer_menu(ctx, {"id": iid})]     # không hiện khi không mở từ trang một người
    items = _viewer_menu(ctx, {"id": iid}, None, True)
    names = [n for n, _ in items if n]
    assert "Phân loại" in names and "Không phải Anna Nguyen" in names and "Không phải Bella Tran" in names
    assert "Chuyển tới vị trí trong All" in names
    got = []
    ctx.locate.connect(got.append)
    next(f for n, f in items if n == "Chuyển tới vị trí trong All")()
    assert got == [iid]
    next(f for n, f in items if n == "Không phải Anna Nguyen")()
    assert not ctx.db.one("SELECT 1 FROM faces WHERE image_id=? AND person_id=?", (iid, a))


def test_viewer_info_person_links_and_extra_buttons(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import _viewer_info
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "vl"))
    ctx = AppContext()
    pid = ctx.db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES('/v/1.jpg',1,1,9,9,'t')").lastrowid
    ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .95, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    html = _viewer_info(ctx, {"id": iid})
    assert f"href='person:{pid}'" in html and "Anna Nguyen" in html
    got = []
    ctx.open_person.connect(got.append)
    ctx.open_person.emit(pid)
    assert got == [pid]


def test_library_counts_explain_difference(tmp_path, monkeypatch):
    from pp.ui.ctx import AppContext
    from pp.ui.pages import count_note, library_counts
    monkeypatch.setenv("PP_HOME", str(tmp_path / "lc"))
    ctx = AppContext()
    ids = [ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/c/{i}.jpg", 1, 1, 9, 9, "t" if i < 9 else None)).lastrowid for i in range(10)]
    ctx.db.x("INSERT INTO dup_hidden(image_id,keep_id) VALUES(?,?)", (ids[0], ids[1]))
    assert library_counts(ctx.db) == (10, 8, 1, 1)
    assert "hiện ở All: 8" in count_note(ctx.db) and "1 bản trùng đã ẩn" in count_note(ctx.db)


def test_people_cards_fill_row_by_column_count(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp.ui.common import card_dims, card_size_for
    QApplication.instance() or QApplication([])
    for width in (900, 1500):
        for cols in (2, 3, 5, 10, 20):
            size = card_size_for(width, cols)
            cw = card_dims(size)[1]
            want = max(1, min(cols, width // 72))                                   # cửa sổ hẹp: ít cột hơn, hàng tự xuống dòng
            assert width // cw == want and (want < cols or width - cols * cw < cols + 12)
            bw, _, _ = card_dims(size)
            assert abs(bw / size - 0.75) < 0.01                                      # 3 : 4


def test_cover_is_thigh_up_only_when_cards_are_large(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage, COL_STEPS
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "bu"))
    ctx = AppContext()
    pid = ctx.db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    for j in range(2):
        iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/b/{j}.jpg", 1, 1, 300, 400, "imgthumb")).lastrowid
        ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,thumb) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (iid, .4, .15, .2, .12, .95, 80, vec_to_blob(np.ones(128, np.float32)), pid, "facethumb"))
    page = PeoplePage(ctx)
    page.refresh()
    assert page.cols() == 10 and "navel" in page.pmodel.items[0]["key"] and "tbytes" in page.pmodel.items[0]      # mặc định 10 ảnh/hàng: từ rốn lên
    for step, kind in ((0, "navel"), (1, "navel"), (2, "navel")):          # nấc 5, 10, 20: cùng một kiểu ảnh (từ rốn lên)
        page.card_s.setValue(step)
        from PySide6.QtTest import QTest
        QTest.qWait(200)                                            # nạp lại ảnh đại diện được dồn một lần sau khi ngừng kéo
        assert page.cols() == COL_STEPS[step]
        it = page.pmodel.items[0]
        if kind == "face":
            assert it.get("thumb") == "facethumb" and "tbytes" not in it
        else:
            assert "tbytes" in it and kind in it["key"]


def test_scan_status_line_shows_progress_then_hides(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "ss"))
    ctx = AppContext()
    w = MainWindow(ctx)
    w.show()
    ctx.scan_status.emit("Đang quét 5/9")
    assert w.scan_l.isVisible() and w.scan_l.text() == "Đang quét 5/9" and not w._scan_hide.isActive()
    ctx.scan_status.emit("Đã quét xong")
    assert w.scan_l.text() == "Đã quét xong" and w._scan_hide.isActive() and w._scan_hide.interval() == 3000
    w._scan_hide.timeout.emit()                                                              # sau 3 giây: ẩn
    assert not w.scan_l.isVisible()


def test_sync_after_scan_starts_sync_when_configured(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp.ui import pages
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "sa"))
    ctx = AppContext()
    w = MainWindow(ctx)
    started = []
    monkeypatch.setattr(pages.SyncWorker, "start", lambda self: started.append(self.dest))
    w.sync_after_scan()
    assert not started                                                   # chưa cấu hình đồng bộ: không làm gì
    ctx.db.set_meta("sync_dir", str(tmp_path / "drive"))
    ctx.db.set_meta("sync_pw", "pw")
    w.sync_after_scan()
    assert started == [str(tmp_path / "drive")]                         # đã cấu hình: tự đồng bộ sau khi quét
    ctx.db.set_meta("sync_after_scan", "0")
    started.clear()
    w._sw = None
    w.sync_after_scan()
    assert not started                                                   # đã tắt tùy chọn


def test_people_toolbar_fits_narrow_window_and_slider_snaps(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "nw"))
    ctx = AppContext()
    page = PeoplePage(ctx)
    assert page.stack.widget(0).minimumSizeHint().width() <= 470                  # thanh lọc không ép trang rộng hơn cửa sổ hẹp
    assert page.card_s.maximum() == 2 and page.cols() == 10                         # các nấc 5, 10, 20
    page.card_s.setValue(0)
    assert page.cols() == 5


def test_single_instance_guard(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp.ui import main as m
    QApplication.instance() or QApplication([])
    name = f"PrivatePicture-test-{tmp_path.name}"
    first = m._single_instance(name)
    assert first is not None                                                        # bản đầu tiên chạy được
    second = m._single_instance(name)
    assert second is None                                                           # bản thứ hai thấy đã có bản đang chạy
    first.close()


def test_favorites_tab_lists_hearted_people(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    from pp.ui.common import heart_rect
    from PySide6.QtCore import QRect, QPoint
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "fv"))
    ctx = AppContext()
    pids = []
    for nm in ("Anna Nguyen", "Bella Tran"):
        pid = ctx.db.x("INSERT INTO persons(name) VALUES(?)", (nm,)).lastrowid
        pids.append(pid)
        for j in range(2):
            iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/f/{pid}{j}.jpg", 1, 1, 9, 9, "t")).lastrowid
            ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    w = MainWindow(ctx)
    w.show()
    assert "favorites" in w.keys and any(w.nav.item(i).text().startswith("Favorite") for i in range(w.nav.count()))
    fav = w.pages["favorites"]
    fav.refresh()
    assert fav.grid.model.rowCount() == 0                                              # chưa có ảnh nào được gắn ngôi sao
    iid = ctx.db.one("SELECT id FROM images LIMIT 1")["id"]
    lid = ctx.db.x("INSERT INTO labels(name) VALUES('Yêu thích')").lastrowid
    ctx.db.x("INSERT INTO label_images VALUES(?,?)", (lid, iid))
    fav.refresh()
    assert [it["id"] for it in fav.grid.model.items] == [iid]                          # chỉ ảnh đã bấm ngôi sao
    ctx.db.toggle_favorite(pids[1])                                                    # người được yêu thích (trái tim) xuất hiện ở nút ♥ của Model
    ctx.changed.emit()
    pp = w.pages["people"]
    pp.letter = "♥"
    pp.refresh()
    assert pp.tabs.btns["♥"].isEnabled()
    r = heart_rect(QRect(0, 0, 150, 210), 200)                                        # vùng bấm trái tim nằm trong thẻ, góc trên trái
    assert QRect(0, 0, 150, 210).contains(r) and r.left() < 40 and r.top() < 40


def test_selection_bar_has_decision_and_classify_buttons(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication, QPushButton
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "sb"))
    ctx = AppContext()
    pid = ctx.db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    iids = []
    for j in range(2):
        iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/s/{j}.jpg", 1, 1, 9, 9, "t")).lastrowid
        iids.append(iid)
        ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    page = PeoplePage(ctx)
    page.pid = pid
    page.show_person()
    names = lambda g: [b.text() for b in g.selbar.findChildren(QPushButton)]
    assert "✗ Không phải người này" in names(page.photos) and "Dressed" in names(page.photos) and "Naked" in names(page.photos)
    assert "✓ Đúng người này" in names(page.guess) and "✗ Không phải người này" in names(page.guess)
    g = page.photos
    g.grid.sel, g.grid.multi = {0}, True
    g.grid.selectionChanged.emit(1)
    next(b for b in g.selbar.findChildren(QPushButton) if b.text() == "Naked").click()      # phân loại ngay từ thanh trên cùng
    assert ctx.db.one("SELECT grp FROM cloth_group WHERE image_id=?", (g.model.items[0]["id"],))["grp"] == "nude"


def test_cover_random_from_nude_group(tmp_path):
    from pp.db import DB
    import pp.db as dbm
    db = DB(str(tmp_path / "c.db"))
    pid = db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    ids = []
    for j in range(8):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/x/{j}.jpg", 1, 1, 300, 400, f"t{j}")).lastrowid
        # mặt nhìn thẳng (khung gần vuông trên ảnh), nhỏ, ở phía trên: còn đủ thân bên dưới
        fy = .15 if j != 7 else .8                                   # ảnh 7: mặt thấp, không còn thân bên dưới
        db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,thumb) VALUES(?,?,?,?,?,?,?,?,?,?)", (iid, .4, fy, .133, .1, .95, 80, b"", pid, "f"))
        db.x("INSERT INTO cloth_group(image_id,grp,p) VALUES(?,?,1)", (iid, "nude" if j >= 2 else "cloth"))
        ids.append(iid)
    ok = set(ids[2:7])                                               # nude + đủ thân; ảnh 0, 1 là Dressed, ảnh 7 thiếu thân
    order = []
    for run in range(10):                                            # mỗi lần khởi động app
        dbm._SESSION_COVER.clear()
        r = db.cover_pick(pid, "thigh")
        assert r["iid"] in ok
        assert db.cover_pick(pid, "thigh")["iid"] == r["iid"]         # trong cùng một lần chạy không đổi
        order.append(r["iid"])
    assert set(order[:5]) == ok                                       # đi hết 5 ảnh rồi mới lặp lại
    assert set(order[5:]) == ok


def test_letter_tabs_follow_scroll_and_jump(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from pp.ui.pages import LetterSections, LetterTabs
    QApplication.instance() or QApplication([])
    ls, tabs = LetterSections(128), LetterTabs()
    ls.lettersChanged.connect(tabs.set_letters)
    ls.currentLetter.connect(tabs.set_current)
    tabs.picked.connect(ls.scroll_to)
    ls.resize(500, 300)
    ls.show()
    groups = [(c, [{"thumb": None, "pid": 100 * k + j, "key": f"{c}{j}", "label": f"{c}{j}\n1 ảnh"} for j in range(12)]) for k, c in enumerate("ABC")]
    ls.set_groups(groups)
    QTest.qWait(250)
    ls._spy()
    assert tabs.btns["A"].isEnabled() and not tabs.btns["Z"].isEnabled()
    assert tabs.cur == "A" and tabs.btns["A"].isChecked()
    tabs.btns["C"].click()                                         # bấm chữ C: danh sách nhảy tới mục C, tab C sáng
    QTest.qWait(250)
    ls._spy()
    assert tabs.cur == "C" and ls.verticalScrollBar().value() > 0
    ls.verticalScrollBar().setValue(0)
    QTest.qWait(250)
    ls._spy()
    assert tabs.cur == "A"


def test_person_album_hides_duplicate_copies(tmp_path):
    from pp.db import DB, vec_to_blob
    import numpy as np
    db = DB(str(tmp_path / "d.db"))
    pid = db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    ids = []
    for j in range(3):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/d/{j}.jpg", 1, 1, 9, 9, "t")).lastrowid
        db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(np.ones(128, np.float32)), pid))
        ids.append(iid)
    db.x("INSERT INTO dup_hidden(image_id,keep_id) VALUES(?,?)", (ids[1], ids[0]))
    assert {r["id"] for r in db.person_images(pid)} == {ids[0], ids[2]}            # bản trùng đã ẩn không còn trong album


def test_grid_show_item_scrolls_without_changing_selection():
    from PySide6.QtWidgets import QApplication
    from pp.ui.common import JustifiedView, ThumbModel
    QApplication.instance() or QApplication([])
    m = ThumbModel()
    m.set_items([{"key": f"k{i}", "thumb": None, "w": 300, "h": 200} for i in range(400)])
    v = JustifiedView(m)
    v.resize(600, 400)
    v.show()
    v.relayout()
    v.sel = {2, 5}
    v.show_item(300)
    from PySide6.QtTest import QTest
    QTest.qWait(400)
    assert v.verticalScrollBar().value() > 0 and v.sel == {2, 5} and v.cur == 300      # cuộn tới ảnh vừa xem, giữ nguyên các ảnh đã chọn


def test_selection_row_does_not_swallow_photo_area(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PhotoGrid, Page
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "sr"))
    ctx = AppContext()
    pg = PhotoGrid(ctx, Page(ctx))
    pg.model.set_items([{"id": i, "key": f"k{i}", "thumb": None, "w": 300, "h": 200} for i in range(50)])
    pg.resize(1000, 700)
    pg.show()
    pg.grid.sel = {0, 1, 2}
    pg.grid.multi = True
    pg._sel_changed(3)
    QTest.qWait(100)
    assert pg.zoomw.height() <= 90 and pg.grid.height() > 500                       # hàng thao tác chỉ cao một dòng, phần còn lại dành cho ảnh


def test_scan_pauses_while_user_in_main_sections(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp import scan
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "pg"))
    ctx = AppContext()
    w = MainWindow(ctx)
    w.show()
    w.activateWindow()
    QApplication.processEvents()
    scan.PAUSE_ENABLED[0] = True
    monkeypatch.setattr(QApplication, "applicationState", staticmethod(lambda: __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ApplicationActive))
    w.goto("library")
    w.update_scan_gate()
    assert scan.PAUSED[0] is True                                   # đang ở All: quét tạm dừng
    w.goto("settings")
    w.update_scan_gate()
    assert scan.PAUSED[0] is False                                  # ra ngoài các mục chính: quét chạy tiếp
    scan.PAUSED[0] = False
    scan.PAUSE_ENABLED[0] = False


def test_mashup_tabs_by_number_of_people_split_dressed_nude(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import ComboPage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "mt"))
    ctx = AppContext()
    rng = np.random.default_rng(3)
    pids = [ctx.db.x("INSERT INTO persons(name) VALUES(?)", (n,)).lastrowid for n in ("A", "B", "C")]
    vecs = [rng.normal(size=128).astype("float32") for _ in pids]
    def photo(n, who, grp):
        iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/mt/{n}.jpg", 1, 1, 100, 100, "t")).lastrowid
        for k in who:
            ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1 + .3 * k, .1, .2, .2, .95, 80, vec_to_blob(vecs[k]), pids[k]))
        ctx.db.x("INSERT INTO cloth_group(image_id,grp,p) VALUES(?,?,1)", (iid, grp))
    for n in range(3):
        photo(f"a{n}", [0, 1], "cloth" if n else "nude")               # 3 ảnh 2 người
    for n in range(2):
        photo(f"t{n}", [0, 1, 2], "nude")                              # 2 ảnh 3 người
    page = ComboPage(ctx)
    page.refresh()
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == ["2 người (3)", "3 người (2)"]
    assert [(k, len(v)) for k, v in sorted(page.by_count.items())] == [(2, 3), (3, 2)]
    parts = {k: pg.model.rowCount() for k, (lab, pg, _) in page.grouped.parts.items()}
    assert parts["cloth"] == 2 and parts["nude"] == 1                    # tab 2 người: chia Dressed / Nude
    page.tabs.setCurrentIndex(1)
    assert page.grouped.parts["nude"][1].model.rowCount() == 2


def test_letter_tab_all_shows_everyone_and_letter_filters(tmp_path, monkeypatch):
    import numpy as np
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    monkeypatch.setenv("PP_HOME", str(tmp_path / "lt"))
    ctx = AppContext()
    for i, nm in enumerate(["Anna", "Bella", "Bianca", None]):
        pid = ctx.db.x("INSERT INTO persons(name) VALUES(?)", (nm,)).lastrowid
        for j in range(2):
            iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/lt/{i}{j}.jpg", 1, 1, 9, 9, "t")).lastrowid
            ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    page = PeoplePage(ctx)
    page.refresh()
    total = lambda: sum(g.model().rowCount() for g, _ in page.alpha.sections)
    assert page.tabs.btns["All"].isChecked() and total() == 4 and page.tabs.btns["B"].isEnabled() and not page.tabs.btns["Z"].isEnabled()
    page.tabs.btns["B"].click()                                                 # chọn B: chỉ còn Bella, Bianca
    assert total() == 2 and page.tabs.btns["B"].isChecked() and not page.tabs.btns["All"].isChecked()
    page.tabs.btns["#"].click()                                                 # #: người chưa đặt tên
    assert total() == 1
    page.tabs.btns["All"].click()
    assert total() == 4


def test_app_opens_on_settings_page_even_with_photos(tmp_path, monkeypatch):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from pp.db import vec_to_blob
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "os"))
    ctx = AppContext()
    pid = ctx.db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    iid = ctx.db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", ("/o/1.jpg", 1, 1, 9, 9, "t")).lastrowid
    ctx.db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(np.ones(128, np.float32)), pid))
    w = MainWindow(ctx)
    assert w.keys[w.stack.currentIndex()] == "settings"                 # có ảnh và có người, vẫn mở ở Cài đặt


def test_search_keywords_cover_pose_body_clothing_and_build_prompts():
    from pp import vi
    assert set(vi.CATALOG) >= {"Tư thế", "Dáng người", "Bộ phận", "Trang phục"}
    assert vi.phrases("ngồi, váy") == ["sitting", "wearing a skirt or dress"]                 # từ khóa trong bảng người
    assert vi.phrases("Quay lưng + đồ bơi") == ["back turned to the camera", "swimwear"]       # không phân biệt hoa thường, dấu
    p = vi.prompts_for("nằm sấp, bikini")
    assert p[0].startswith("a photo of a person") and "lying on stomach" in p[0] and "bikini swimsuit" in p[0] and len(p) == 3
    assert vi.phrases("beach") == ["beach"]                                                   # gõ thẳng tiếng Anh vẫn được


def test_search_page_chips_add_keywords_and_run(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp.ui.ctx import AppContext
    from pp.ui.pages import SearchPage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "sq"))
    page = SearchPage(AppContext())
    ran = []
    monkeypatch.setattr(SearchPage, "run", lambda self: ran.append(self.q.text()))
    page.chips["ngồi"].click()
    page.chips["váy"].click()
    assert page.q.text() == "ngồi, váy" and ran[-1] == "ngồi, váy"
    page.chips["ngồi"].click()                                                                # bấm lại để bỏ từ khóa
    assert page.q.text() == "váy" and not page.chips["ngồi"].isChecked()


def test_cover_never_uses_group_photo(tmp_path):
    from pp.db import DB
    import pp.db as dbm
    db = DB(str(tmp_path / "s.db"))
    pid = db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    other = db.x("INSERT INTO persons(name) VALUES('B')").lastrowid
    # ảnh 1: chụp chung 2 người (mặt đẹp hơn); ảnh 2: ảnh cá nhân (mặt kém hơn)
    g = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES('/x/g.jpg',1,1,300,400,'tg')").lastrowid
    s = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES('/x/s.jpg',1,1,300,400,'ts')").lastrowid
    db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,thumb,locked) VALUES(?,?,?,?,?,?,?,?,?,?,1)", (g, .2, .15, .133, .1, .99, 90, b"", pid, "f"))
    db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,thumb) VALUES(?,?,?,?,?,?,?,?,?,?)", (g, .6, .15, .133, .1, .99, 90, b"", other, "f2"))
    db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,thumb) VALUES(?,?,?,?,?,?,?,?,?,?)", (s, .4, .15, .133, .1, .92, 60, b"", pid, "f3"))
    for run in range(3):
        dbm._SESSION_COVER.clear()
        assert db.cover_pick(pid, "navel")["iid"] == s
    only = db.x("INSERT INTO persons(name) VALUES('C')").lastrowid
    db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,thumb) VALUES(?,?,?,?,?,?,?,?,?,?)", (g, .5, .5, .1, .1, .9, 50, b"", only, "f4"))
    assert db.cover_pick(only, "navel") is None                       # chỉ có ảnh chụp chung: không dùng ảnh chung làm đại diện


def test_library_change_triggers_sync_and_phone_inbox_is_polled(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from pp import sync
    from pp.ui import pages
    from pp.ui.ctx import AppContext
    from pp.ui.main import MainWindow
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "ps"))
    ctx = AppContext()
    w = MainWindow(ctx)
    started = []
    monkeypatch.setattr(pages.SyncWorker, "start", lambda self: started.append(1))
    drive = tmp_path / "drive"
    ctx.db.set_meta("sync_dir", str(drive))
    ctx.db.set_meta("sync_pw", "pw")
    w.sync_if_changed()                                              # thư viện đổi so với lần đồng bộ trước (chưa có chữ ký): tự đồng bộ
    assert started == [1]
    w._sw = None
    started.clear()
    ctx.db.set_meta("sync_sig", ctx.db.library_sig())
    w.sync_if_changed()
    assert not started                                               # không có gì mới
    inbox = drive / sync.FOLDER / "inbox"
    inbox.mkdir(parents=True)
    w.poll_phone()
    assert not started                                               # inbox trống
    (inbox / "android-1.pe").write_bytes(b"x")
    w.poll_phone()
    assert started == [1]                                            # điện thoại vừa gửi chỉnh sửa: nhận ngay

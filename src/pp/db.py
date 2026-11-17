"""Cơ sở dữ liệu SQLite của thư viện ảnh (mỗi luồng một kết nối)."""
import random
import os
import sqlite3
import threading

import numpy as np

from .secure import seal, unseal

SCHEMA = """
CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, mtime REAL, size INTEGER,
  w INTEGER, h INTEGER, taken TEXT, thumb TEXT, clip BLOB, ml INTEGER DEFAULT 0, err TEXT,
  vid TEXT, name TEXT);
CREATE INDEX IF NOT EXISTS ix_img_taken ON images(taken);
CREATE TABLE IF NOT EXISTS persons(id INTEGER PRIMARY KEY, name TEXT, hidden INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS faces(
  id INTEGER PRIMARY KEY, image_id INTEGER NOT NULL, x REAL, y REAL, w REAL, h REAL,
  score REAL, px REAL, vec BLOB, person_id INTEGER, locked INTEGER DEFAULT 0, thumb TEXT);
CREATE INDEX IF NOT EXISTS ix_face_img ON faces(image_id);
CREATE INDEX IF NOT EXISTS ix_face_person ON faces(person_id);
CREATE TABLE IF NOT EXISTS folders(path TEXT PRIMARY KEY, level TEXT DEFAULT 'data', del_orig INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS labels(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS label_images(label_id INTEGER, image_id INTEGER, PRIMARY KEY(label_id, image_id));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS imported(src TEXT PRIMARY KEY, mtime REAL, size INTEGER, vid TEXT);
CREATE TABLE IF NOT EXISTS person_guess(image_id INTEGER, person_id INTEGER, score REAL, state INTEGER DEFAULT 0,
  PRIMARY KEY(image_id, person_id));
CREATE INDEX IF NOT EXISTS ix_guess_person ON person_guess(person_id, state);
CREATE INDEX IF NOT EXISTS ix_label_img ON label_images(image_id);
CREATE TABLE IF NOT EXISTS face_attr(face_id INTEGER PRIMARY KEY, sk_l REAL, sk_a REAL, sk_b REAL, hr_l REAL, hr_a REAL, hr_b REAL, sharp REAL);
CREATE TABLE IF NOT EXISTS edit_ts(k TEXT PRIMARY KEY, ts REAL);
CREATE TRIGGER IF NOT EXISTS t_lm_ins AFTER INSERT ON label_images BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('lm:'||NEW.label_id||'|'||NEW.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_lm_del AFTER DELETE ON label_images BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('lm:'||OLD.label_id||'|'||OLD.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_label_upd AFTER UPDATE OF name ON labels BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('label:'||NEW.id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_label_del AFTER DELETE ON labels BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('label:'||OLD.id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_pname AFTER UPDATE OF name ON persons BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('pname:'||NEW.id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_phide AFTER UPDATE OF hidden ON persons BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('person:'||NEW.id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_pdel AFTER DELETE ON persons BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('person:'||OLD.id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_pimg AFTER UPDATE OF person_id ON faces WHEN OLD.person_id IS NOT NULL AND OLD.person_id IS NOT NEW.person_id BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('pimg:'||OLD.person_id||'|'||NEW.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TABLE IF NOT EXISTS label_auto(label_id INTEGER, image_id INTEGER, ts REAL, PRIMARY KEY(label_id,image_id));
CREATE TABLE IF NOT EXISTS label_reject(label_id INTEGER, image_id INTEGER, PRIMARY KEY(label_id,image_id));
CREATE TABLE IF NOT EXISTS person_nomerge(a INTEGER, b INTEGER, PRIMARY KEY(a,b));
CREATE TABLE IF NOT EXISTS person_profile(id INTEGER PRIMARY KEY, person_id INTEGER, dim INTEGER, vec BLOB);
CREATE INDEX IF NOT EXISTS ix_profile_person ON person_profile(person_id);
CREATE TABLE IF NOT EXISTS archived(image_id INTEGER PRIMARY KEY, uid TEXT);
CREATE TABLE IF NOT EXISTS image_art(image_id INTEGER PRIMARY KEY, p REAL, art INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS person_suggest(person_id INTEGER PRIMARY KEY, name TEXT, n_arch INTEGER, n_img INTEGER);
CREATE TABLE IF NOT EXISTS face_reject(face_id INTEGER, person_id INTEGER, PRIMARY KEY(face_id, person_id));
CREATE TABLE IF NOT EXISTS person_ref(id INTEGER PRIMARY KEY, person_id INTEGER, dim INTEGER, vec BLOB, src TEXT);
CREATE INDEX IF NOT EXISTS ix_ref_person ON person_ref(person_id);
CREATE TABLE IF NOT EXISTS ref_state(person_id INTEGER PRIMARY KEY, ts REAL, n INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS ref_flag(person_id INTEGER PRIMARY KEY, sim REAL, n INTEGER);
CREATE TABLE IF NOT EXISTS person_candidates(person_id INTEGER, name TEXT, score REAL, PRIMARY KEY(person_id, name));
CREATE TABLE IF NOT EXISTS cover_used(person_id INTEGER, kind TEXT, face_id INTEGER, PRIMARY KEY(person_id, kind, face_id));
CREATE TABLE IF NOT EXISTS cloth_manual(image_id INTEGER PRIMARY KEY, grp TEXT);
CREATE TABLE IF NOT EXISTS inbox_done(name TEXT PRIMARY KEY, ts REAL);             -- tên các tệp thao tác của điện thoại PC đã xử lý: đưa vào danh mục để điện thoại biết chắc thao tác nào đã được nhận
CREATE TRIGGER IF NOT EXISTS t_cloth_ins AFTER INSERT ON cloth_manual BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('cloth:'||NEW.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_cloth_upd AFTER UPDATE ON cloth_manual BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('cloth:'||NEW.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_cloth_del AFTER DELETE ON cloth_manual BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('cloth:'||OLD.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_guess_upd AFTER UPDATE OF state ON person_guess BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('pimg:'||NEW.person_id||'|'||NEW.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_guess_ins AFTER INSERT ON person_guess WHEN NEW.state<>0 BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('pimg:'||NEW.person_id||'|'||NEW.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TRIGGER IF NOT EXISTS t_pimg_new AFTER UPDATE OF person_id ON faces WHEN NEW.person_id IS NOT NULL AND OLD.person_id IS NOT NEW.person_id BEGIN
  INSERT OR REPLACE INTO edit_ts VALUES('pimg:'||NEW.person_id||'|'||NEW.image_id, (julianday('now') - 2440587.5) * 86400.0); END;
CREATE TABLE IF NOT EXISTS cloth_group(image_id INTEGER PRIMARY KEY, grp TEXT, p REAL);
CREATE TABLE IF NOT EXISTS clothing(image_id INTEGER PRIMARY KEY, cat TEXT, prob REAL);
CREATE TABLE IF NOT EXISTS dup_hidden(image_id INTEGER PRIMARY KEY, keep_id INTEGER);
CREATE TABLE IF NOT EXISTS dup_ignore(image_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS ai3d_jobs(id INTEGER PRIMARY KEY, provider TEXT, kind TEXT, task_id TEXT, endpoint TEXT, opts TEXT,
  out_dir TEXT, status TEXT, error TEXT, created TEXT, n_images INTEGER, files TEXT);
"""


def vec_to_blob(v) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def blob_to_vec(b) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


_SESSION_COVER = {}        # (người, kiểu) -> mặt đã chọn làm ảnh đại diện trong lần chạy này; khởi động lại thì chọn ảnh mới

class DB:
    """Một kết nối dùng chung giữa các luồng (có khóa). Có khóa mã hóa: dữ liệu nằm trong bộ nhớ và được
    lưu xuống đĩa dạng mã hóa bằng snapshot(); không có khóa: dùng tệp SQLite thường."""

    def __init__(self, path, key=None):
        self.path, self.key = str(path), key
        self.lock = threading.RLock()
        if key is not None:
            self.con = sqlite3.connect(":memory:", check_same_thread=False)
            if os.path.exists(self.path):
                with open(self.path, "rb") as f:
                    self.con.deserialize(unseal(key, f.read()))
        else:
            self.con = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
            self.con.execute("PRAGMA journal_mode=WAL")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(images)")}
        for c in ("vid", "name"):
            if c not in cols:
                self.con.execute(f"ALTER TABLE images ADD COLUMN {c} TEXT")
        fcols = {r["name"] for r in self.con.execute("PRAGMA table_info(folders)")}
        if "level" not in fcols:
            self.con.execute("ALTER TABLE folders ADD COLUMN level TEXT DEFAULT 'data'")
        if "del_orig" not in fcols:
            self.con.execute("ALTER TABLE folders ADD COLUMN del_orig INTEGER DEFAULT 0")
        if "favorite" not in {r["name"] for r in self.con.execute("PRAGMA table_info(persons)")}:
            self.con.execute("ALTER TABLE persons ADD COLUMN favorite INTEGER DEFAULT 0")      # người được đánh dấu yêu thích (trái tim)
        if "cover_mode" not in {r["name"] for r in self.con.execute("PRAGMA table_info(persons)")}:
            self.con.execute("ALTER TABLE persons ADD COLUMN cover_mode TEXT")          # 'face' (chỉ gương mặt, mặc định) hoặc 'bust' (bán thân)
        if "cover_face" not in {r["name"] for r in self.con.execute("PRAGMA table_info(persons)")}:
            self.con.execute("ALTER TABLE persons ADD COLUMN cover_face INTEGER")      # (không còn dùng: ảnh đại diện hoàn toàn tự động)
        self.con.execute("UPDATE persons SET cover_face=NULL WHERE cover_face IS NOT NULL")      # bỏ các lựa chọn tay cũ
        if "lsrc" not in {r["name"] for r in self.con.execute("PRAGMA table_info(faces)")}:
            self.con.execute("ALTER TABLE faces ADD COLUMN lsrc TEXT")          # 'user' = người dùng tự chỉnh tay (không bao giờ bị app sửa lại)
        self.con.execute("""CREATE TRIGGER IF NOT EXISTS t_pfav AFTER UPDATE OF favorite ON persons BEGIN
            INSERT OR REPLACE INTO edit_ts VALUES('fav:'||NEW.id, (julianday('now') - 2440587.5) * 86400.0); END""")             # trái tim người: bên nào bấm sau cùng thì thắng (PC <-> điện thoại)
        self.con.commit()

    @property
    def c(self) -> sqlite3.Connection:
        return self.con

    def library_sig(self):
        """Chữ ký gọn của những gì điện thoại hiển thị (ảnh, mặt thuộc người nào, tên, nhãn, phân loại, yêu thích...): đổi thì cần đồng bộ lại cho điện thoại."""
        one = lambda q: tuple(self.one(q))
        return repr((
            one("SELECT COUNT(*) a, COALESCE(MAX(id),0) b FROM images"),
            one("SELECT COUNT(*) a, COALESCE(SUM(COALESCE(person_id,0)),0) b, COALESCE(SUM(locked),0) c FROM faces"),
            one("SELECT COUNT(*) a, COUNT(name) b, COALESCE(SUM(hidden),0) c, COALESCE(SUM(favorite),0) d FROM persons"),
            one("SELECT COUNT(*) a FROM label_images"), one("SELECT COUNT(*) a FROM labels"),
            one("SELECT COUNT(*) a FROM cloth_group"), one("SELECT COUNT(*) a FROM cloth_manual"),
            one("SELECT COUNT(*) a, COALESCE(SUM(state),0) b FROM person_guess"), one("SELECT COUNT(*) a FROM dup_hidden"),
            one("SELECT COUNT(*) a, COALESCE(SUM(grp='nude'),0) b FROM cloth_group"), one("SELECT COUNT(*) a, COALESCE(SUM(grp='nude'),0) b FROM cloth_manual"),
            one("SELECT COUNT(*) a, COALESCE(MAX(ts),0) b FROM edit_ts")))          # mọi chỉnh sửa của người dùng đều đóng dấu thời gian: đổi bất kỳ thứ gì (kể cả đổi loại ảnh, từ chối đề xuất) là chữ ký đổi

    def snapshot(self):
        """Ghi dữ liệu xuống đĩa (mã hóa nếu có khóa). Dữ liệu không đổi kể từ lần ghi trước thì bỏ qua (tránh mã hóa và ghi lại cả tệp hàng trăm MB vô ích)."""
        with self.lock:
            self.con.commit()
            if self.key is not None and getattr(self, "_snap_changes", None) == self.con.total_changes and os.path.exists(self.path):
                return
            if self.key is None:
                try:
                    self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")      # để tệp .db có đủ dữ liệu khi sao lưu
                except sqlite3.Error:
                    pass
                return
            data = self.con.serialize()
            self._snap_changes = self.con.total_changes
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(seal(self.key, data))
        os.replace(tmp, self.path)

    def close(self):
        self.snapshot()
        with self.lock:
            self.con.close()

    def q(self, sql, args=()):
        with self.lock:
            return self.c.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.lock:
            return self.c.execute(sql, args).fetchone()

    def x(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur

    def commit(self):
        self.c.commit()

    # ---- tác vụ tạo mô hình 3D ----
    def ai3d_add(self, provider, kind, opts, out_dir, n_images):
        import json
        import time
        return self.x("INSERT INTO ai3d_jobs(provider,kind,opts,out_dir,status,created,n_images) VALUES(?,?,?,?,?,?,?)",
                      (provider, kind, json.dumps(opts), str(out_dir), "dang-xu-ly", time.strftime("%Y-%m-%d %H:%M"), n_images)).lastrowid

    def ai3d_update(self, jid, **kw):
        cols = ", ".join(f"{k}=?" for k in kw)
        self.x(f"UPDATE ai3d_jobs SET {cols} WHERE id=?", [*kw.values(), jid])

    def ai3d_jobs(self):
        return self.q("SELECT * FROM ai3d_jobs ORDER BY id DESC")

    # ---- cài đặt nhỏ ----
    def get_meta(self, k, default=None):
        r = self.one("SELECT v FROM meta WHERE k=?", (k,))
        return r["v"] if r else default

    def set_meta(self, k, v):
        self.x("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))

    # ---- thư mục ----
    def folders(self):
        return [r["path"] for r in self.q("SELECT path FROM folders ORDER BY path")]

    def folder_rows(self):
        return self.q("SELECT path,level,del_orig FROM folders ORDER BY path")

    def add_folder(self, p, level="data", del_orig=0):
        self.x("INSERT OR REPLACE INTO folders(path,level,del_orig) VALUES(?,?,?)", (p, level, int(del_orig)))

    def set_folder_level(self, p, level, del_orig=0):
        self.x("UPDATE folders SET level=?, del_orig=? WHERE path=?", (level, int(del_orig), p))

    def del_folder(self, p):
        self.x("DELETE FROM folders WHERE path=?", (p,))

    # ---- ảnh ----
    def images(self, order="taken DESC"):
        return self.q(f"SELECT id,path,thumb,taken,w,h,vid,name FROM images WHERE thumb IS NOT NULL ORDER BY {order}")

    def images_by_ids(self, ids):
        ids = list(ids)
        out = []
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            qs = ",".join("?" * len(part))
            out += self.q(f"SELECT id,path,thumb,taken,w,h,vid,name FROM images WHERE id IN ({qs})", part)
        order = {v: k for k, v in enumerate(ids)}
        out.sort(key=lambda r: order[r["id"]])
        return out

    def clip_matrix(self):
        rows = self.q("SELECT id,clip FROM images WHERE clip IS NOT NULL")
        if not rows:
            return [], np.zeros((0, 1), np.float32)
        ids = [r["id"] for r in rows]
        return ids, np.stack([blob_to_vec(r["clip"]) for r in rows])

    # ---- người ----
    def persons(self, hidden=0):
        return self.q("""SELECT p.id,p.name,p.hidden,COALESCE(p.favorite,0) favorite,
            (SELECT COUNT(*) FROM (SELECT image_id FROM faces WHERE person_id=p.id
                                   UNION SELECT image_id FROM person_guess WHERE person_id=p.id AND state=2)) n,
            (SELECT COUNT(*) FROM (SELECT image_id FROM faces WHERE person_id=p.id AND locked=1
                                   UNION SELECT image_id FROM person_guess WHERE person_id=p.id AND state=2)) ver,
            (SELECT COUNT(*) FROM person_guess g WHERE g.person_id=p.id AND g.state=0
                AND g.image_id NOT IN (SELECT image_id FROM faces WHERE person_id=p.id)) pend,
            COALESCE((SELECT thumb FROM faces WHERE id=p.cover_face AND person_id=p.id),
                     (SELECT thumb FROM faces WHERE person_id=p.id ORDER BY locked DESC, score*px DESC LIMIT 1)) cover,
            p.cover_mode,
            (SELECT i.thumb FROM images i WHERE i.id=(SELECT image_id FROM faces WHERE id=COALESCE((SELECT id FROM faces WHERE id=p.cover_face AND person_id=p.id),
                     (SELECT id FROM faces WHERE person_id=p.id ORDER BY locked DESC, score*px DESC LIMIT 1)))) cover_img,
            (SELECT x||','||y||','||w||','||h FROM faces WHERE id=COALESCE((SELECT id FROM faces WHERE id=p.cover_face AND person_id=p.id),
                     (SELECT id FROM faces WHERE person_id=p.id ORDER BY locked DESC, score*px DESC LIMIT 1))) cover_box
            FROM persons p WHERE p.hidden=? AND EXISTS(SELECT 1 FROM faces f WHERE f.person_id=p.id)
            ORDER BY (p.name IS NULL), n DESC""", (hidden,))

    def toggle_favorite(self, pid):
        """Bật / tắt trái tim yêu thích của một người. Trả về trạng thái mới."""
        self.x("UPDATE persons SET favorite=1-COALESCE(favorite,0) WHERE id=?", (pid,))
        r = self.one("SELECT COALESCE(favorite,0) f FROM persons WHERE id=?", (pid,))
        return bool(r and r["f"])

    def person_cover(self, pid):
        """Đường dẫn ảnh nhỏ làm ảnh đại diện của người: ảnh người dùng chọn, không có thì khuôn mặt tốt nhất."""
        r = self.one("""SELECT COALESCE((SELECT thumb FROM faces WHERE id=p.cover_face AND person_id=p.id),
                                        (SELECT thumb FROM faces WHERE person_id=p.id ORDER BY locked DESC, score*px DESC LIMIT 1)) t
                        FROM persons p WHERE p.id=?""", (pid,))
        return r["t"] if r else None

    def _cover_random(self, pid, kind, cols, lo, hi):
        """Ảnh đại diện đổi mỗi lần khởi động app, lấy từ nhóm Nude: ảnh chỉ có một người, đủ thân (đủ chỗ cắt từ giữa đùi / rốn lên), mặt nhìn thẳng (khung mặt gần vuông,
        điểm tin cậy cao, đủ lớn), mặt nằm trọn trong ảnh. Không lặp lại ảnh nào cho tới khi đã đi hết các ảnh hợp lệ của người đó (rồi mới vòng lại)."""
        key = (pid, kind)
        if key in _SESSION_COVER:
            return self.one(f"SELECT {cols} FROM faces f JOIN images i ON i.id=f.image_id WHERE f.id=?", (_SESSION_COVER[key],))
        need = 5.1 if kind == "thigh" else 3.1                      # chiều cao khung cắt tính theo chiều cao mặt (đã trừ phần chừa phía trên đầu)
        rows = self.q(f"""SELECT f.id fid, f.x x, f.y y, f.w w, f.h h, i.w iw, i.h ih, i.thumb thumb, i.path path, i.id iid
                          FROM faces f JOIN images i ON i.id=f.image_id
                          LEFT JOIN cloth_manual m ON m.image_id=i.id LEFT JOIN cloth_group g ON g.image_id=i.id
                          WHERE f.person_id=? AND f.score>=0.93 AND f.px>=48 AND f.h BETWEEN ? AND ? AND i.thumb IS NOT NULL
                            AND f.y>=0.04 AND f.x>=0.02 AND f.x+f.w<=0.98
                            AND (CASE WHEN m.image_id IS NOT NULL THEN m.grp ELSE g.grp END)='nude'
                            AND (SELECT COUNT(*) FROM faces z WHERE z.image_id=i.id)=1
                            AND i.id NOT IN (SELECT image_id FROM dup_hidden)""", (pid, lo, hi))
        ok = []
        for r in rows:
            fw, fh = r["w"] * (r["iw"] or 1), r["h"] * (r["ih"] or 1)
            ratio = fw / max(1.0, fh)
            if 0.72 <= ratio <= 1.12 and r["y"] + need * r["h"] <= 1.0:          # mặt nhìn thẳng; còn đủ thân phía dưới
                ok.append(r)
        if not ok:
            return None
        used = {x["face_id"] for x in self.q("SELECT face_id FROM cover_used WHERE person_id=? AND kind=?", (pid, kind))}
        fresh = [r for r in ok if r["fid"] not in used]
        if not fresh:                                                # đã đi hết một vòng: bắt đầu vòng mới
            self.x("DELETE FROM cover_used WHERE person_id=? AND kind=?", (pid, kind))
            fresh = ok
        r = random.choice(fresh)
        self.x("INSERT OR IGNORE INTO cover_used(person_id,kind,face_id) VALUES(?,?,?)", (pid, kind, r["fid"]))
        _SESSION_COVER[key] = r["fid"]
        return r

    def cover_pick(self, pid, kind):
        """Chọn khuôn mặt/ảnh làm ảnh đại diện hoàn toàn TỰ ĐỘNG (không có chọn tay): lấy ảnh có khuôn mặt vừa phải
        (toàn thân: mặt nhỏ trong khung, thấy cả người; bán thân: mặt cỡ vừa) thay vì ảnh cận mặt. Trả về dòng (x,y,w,h,thumb,path) hoặc None."""
        cols = "f.x x, f.y y, f.w w, f.h h, i.thumb thumb, i.path path, i.id iid"
        lo, hi = {"thigh": (0.06, 0.17), "navel": (0.08, 0.23), "full": (0.05, 0.25)}.get(kind, (0.13, 0.40))
        if self.get_meta("cover_random", "1") == "1":
            r = self._cover_random(pid, kind, cols, lo, hi)
            if r:
                return r
        # Ảnh đại diện LUÔN là ảnh cá nhân: ảnh chỉ có đúng một khuôn mặt (người đó), không bao giờ lấy ảnh chụp chung nhiều người.
        solo = "(SELECT COUNT(*) FROM faces z WHERE z.image_id=i.id)=1 AND i.id NOT IN (SELECT image_id FROM dup_hidden)"
        inside = "f.y>=0.04 AND f.y+f.h<=0.97 AND f.x>=0.02 AND f.x+f.w<=0.98"
        r = self.one(f"""SELECT {cols} FROM faces f JOIN images i ON i.id=f.image_id
                         WHERE f.person_id=? AND f.score>=0.9 AND f.h BETWEEN ? AND ? AND i.thumb IS NOT NULL AND {inside} AND {solo}
                         ORDER BY f.locked DESC, f.score*f.px DESC LIMIT 1""", (pid, lo, hi))
        return r or self.one(f"""SELECT {cols} FROM faces f JOIN images i ON i.id=f.image_id WHERE f.person_id=? AND i.thumb IS NOT NULL AND {solo}
                                 ORDER BY ({inside}) DESC, f.locked DESC, f.score*f.px DESC LIMIT 1""", (pid,))

    def person_images(self, pid):
        return self.q("""SELECT DISTINCT i.id,i.path,i.thumb,i.taken,i.w,i.h,i.vid,i.name FROM images i
            WHERE i.id IN (SELECT image_id FROM faces WHERE person_id=?
                           UNION SELECT image_id FROM person_guess WHERE person_id=? AND state=2)
              AND i.id NOT IN (SELECT image_id FROM dup_hidden)        -- bản trùng đã ẩn không hiện lại trong album
            ORDER BY i.taken DESC""", (pid, pid))

    def person_guesses(self, pid):
        """Ảnh chưa thấy mặt nhưng nhiều khả năng cùng người (chưa xác nhận, chưa bị loại)."""
        return self.q("""SELECT i.id,i.path,i.thumb,i.taken,i.w,i.h,i.vid,i.name,g.score FROM person_guess g
            JOIN images i ON i.id=g.image_id WHERE g.person_id=? AND g.state=0
            AND i.id NOT IN (SELECT image_id FROM dup_hidden) ORDER BY g.score DESC""", (pid,))

    # ---- nhãn ----
    def labels(self):
        return self.q("""SELECT l.id,l.name,COUNT(li.image_id) n FROM labels l
            LEFT JOIN label_images li ON li.label_id=l.id GROUP BY l.id ORDER BY l.name""")

    def label_ids(self, lid):
        return [r["image_id"] for r in self.q("SELECT image_id FROM label_images WHERE label_id=?", (lid,))]

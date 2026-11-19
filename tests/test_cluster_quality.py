import io

import numpy as np
from PIL import Image

from pp import cluster, db as dbm, paths
from pp.db import vec_to_blob
from pp.secure import SEC


def _vec(seed, noise=0.0, base=None):
    r = np.random.default_rng(seed)
    v = (base if base is not None else r.normal(size=128)).astype(np.float32)
    if noise:
        v = v + np.random.default_rng(seed + 1000).normal(size=len(v)).astype(np.float32) * noise / np.sqrt(len(v))
    return v / np.linalg.norm(v)


def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "h"))
    return dbm.DB(paths.db_path())


def _img(db, n):
    return db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/p/{n}.jpg", 1, 1, 100, 100, "t")).lastrowid


def _face(db, iid, v, thumb=None, px=90, score=0.95):
    return db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,thumb) VALUES(?,?,?,?,?,?,?,?,?)",
                (iid, 0.3, 0.3, 0.3, 0.3, score, px, vec_to_blob(v), thumb)).lastrowid


def _thumb(tmp_path, name, rgb):
    p = tmp_path / name
    Image.new("RGB", (112, 112), rgb).save(p)
    return str(p)


def test_same_person_grouped_two_people_apart(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a, b = _vec(1), _vec(2)
    fa = [_face(db, _img(db, i), _vec(10 + i, 0.25, a)) for i in range(4)]
    fb = [_face(db, _img(db, 10 + i), _vec(20 + i, 0.25, b)) for i in range(4)]
    cluster.cluster_faces(db)
    pa = {db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] for f in fa}
    pb = {db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] for f in fb}
    assert len(pa) == 1 and len(pb) == 1 and pa != pb and None not in pa | pb


def test_two_faces_in_one_photo_never_merge(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    v = _vec(3)
    i1 = _img(db, 1)
    f1 = _face(db, i1, v)
    f2 = _face(db, i1, _vec(4, 0.05, v))            # gần như y hệt nhưng cùng một ảnh -> hai người khác nhau
    cluster.cluster_faces(db)
    p1 = db.one("SELECT person_id p FROM faces WHERE id=?", (f1,))["p"]
    p2 = db.one("SELECT person_id p FROM faces WHERE id=?", (f2,))["p"]
    assert p1 != p2 and p1 is not None and p2 is not None


def test_borderline_faces_split_by_skin_color(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    base = _vec(5)
    rng = np.random.default_rng(77)
    u1, u2 = rng.normal(size=128), rng.normal(size=128)
    u1 -= (u1 @ base) * base
    u1 /= np.linalg.norm(u1)
    u2 -= (u2 @ base) * base + (u2 @ u1) * u1
    u2 /= np.linalg.norm(u2)
    c = 0.55                                        # độ giống vừa phải với base: nếu chỉ dựa vào khuôn mặt thì sẽ bị gộp
    near = (c * base + np.sqrt(1 - c * c) * u1).astype(np.float32)
    near2 = (c * base + np.sqrt(1 - c * c) * u2).astype(np.float32)
    light = _thumb(tmp_path, "a.png", (232, 190, 160))     # da sáng ấm
    olive = _thumb(tmp_path, "b.png", (150, 160, 120))     # tông da/sắc độ khác hẳn
    same = _thumb(tmp_path, "c.png", (230, 188, 158))
    sim = c
    f1 = _face(db, i1, v)
    f2 = _face(db, i1, _vec(4, 0.05, v))            # gần như y hệt nhưng cùng một ảnh -> hai người khác nhau
    cluster.cluster_faces(db)
    p1 = db.one("SELECT person_id p FROM faces WHERE id=?", (f1,))["p"]
    p2 = db.one("SELECT person_id p FROM faces WHERE id=?", (f2,))["p"]
    assert p1 != p2 and p1 is not None and p2 is not None


def test_borderline_faces_split_by_skin_color(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    base = _vec(5)
    rng = np.random.default_rng(77)
    u1, u2 = rng.normal(size=128), rng.normal(size=128)
    u1 -= (u1 @ base) * base
    u1 /= np.linalg.norm(u1)
    u2 -= (u2 @ base) * base + (u2 @ u1) * u1
    u2 /= np.linalg.norm(u2)
    c = 0.55                                        # độ giống vừa phải với base: nếu chỉ dựa vào khuôn mặt thì sẽ bị gộp
    near = (c * base + np.sqrt(1 - c * c) * u1).astype(np.float32)
    near2 = (c * base + np.sqrt(1 - c * c) * u2).astype(np.float32)
    light = _thumb(tmp_path, "a.png", (232, 190, 160))     # da sáng ấm
    olive = _thumb(tmp_path, "b.png", (150, 160, 120))     # tông da/sắc độ khác hẳn
    same = _thumb(tmp_path, "c.png", (230, 188, 158))
    sim = min(float(base @ near), float(base @ near2))
    assert 0.47 < sim < 0.7, sim
    f1 = _face(db, _img(db, 1), base, light)
    f2 = _face(db, _img(db, 2), near, olive)
    f3 = _face(db, _img(db, 3), near2, same)
    cluster.cluster_faces(db, thr=min(0.45, sim - 0.02))
    p = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert p(f1) == p(f3)                           # cùng tông da: được gộp
    assert p(f2) != p(f1)                           # khác tông da rõ rệt: tách


def test_weak_faces_left_unassigned_when_unsure(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a, b = _vec(7), _vec(8)
    for i in range(3):
        _face(db, _img(db, i), _vec(30 + i, 0.2, a))
        _face(db, _img(db, 20 + i), _vec(40 + i, 0.2, b))
    mid = (a + b) / 2                                # mặt mờ nằm giữa hai người: không chắc là ai
    weak = _face(db, _img(db, 99), mid / np.linalg.norm(mid), px=30, score=0.9)
    cluster.cluster_faces(db)
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (weak,))["p"] is None


def test_named_people_never_merge(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    v = _vec(9)
    f1 = _face(db, _img(db, 1), v)
    f2 = _face(db, _img(db, 2), _vec(11, 0.05, v))          # gần như y hệt, nhưng đã được đặt tên là hai người
    p1 = db.x("INSERT INTO persons(name) VALUES('An')").lastrowid
    p2 = db.x("INSERT INTO persons(name) VALUES('Binh')").lastrowid
    db.x("UPDATE faces SET person_id=?, locked=1 WHERE id=?", (p1, f1))
    db.x("UPDATE faces SET person_id=?, locked=1 WHERE id=?", (p2, f2))
    cluster.cluster_faces(db)
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (f1,))["p"] == p1
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (f2,))["p"] == p2


def test_mixed_dimensions_use_new_model_only(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a = np.random.default_rng(50).normal(size=512).astype(np.float32)
    b = np.random.default_rng(51).normal(size=512).astype(np.float32)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    old = [_face(db, _img(db, i), (lambda v: v / np.linalg.norm(v))(np.random.default_rng(i).normal(size=128)).astype(np.float32)) for i in range(3)]   # SFace cũ
    new_a = [_face(db, _img(db, 10 + i), _vec(60 + i, 0.25, a)) for i in range(3)]
    new_b = [_face(db, _img(db, 20 + i), _vec(70 + i, 0.25, b)) for i in range(3)]
    assert cluster.face_dim(db) == 512 and cluster.default_thr(db) == cluster.FACE_THR_BY_DIM[512]
    cluster.cluster_faces(db)                         # không lỗi dù lẫn mặt cũ (128 chiều) và mới (512 chiều)
    pa = {db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] for f in new_a}
    pb = {db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] for f in new_b}
    assert len(pa) == 1 and len(pb) == 1 and pa != pb and None not in pa | pb
    assert all(db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] is None for f in old)     # mặt cũ chờ quét lại


def test_match_box_updates_named_face_not_duplicate():
    from pp.scan import _match_box
    kept = [{"id": 7, "x": 0.30, "y": 0.30, "w": 0.2, "h": 0.2}, {"id": 8, "x": 0.7, "y": 0.1, "w": 0.2, "h": 0.2}]
    assert _match_box(kept, (0.31, 0.29, 0.2, 0.2)) == 7
    assert _match_box(kept, (0.0, 0.0, 0.1, 0.1)) is None


def test_name_from_archive_rules():
    f = cluster.name_from_archive
    assert f("zip:///x/Nguyen Van A.zip") == "Nguyen Van A"
    assert f("C:\\Down\\tran_thi_b_hd.rar") == "Tran Thi B"
    assert f("Lê Văn C.7z") == "Lê Văn C"
    assert f("/x/_High Quality No Watermark.rar") is None          # từ chung, không phải tên người
    assert f("/x/167350.zip") is None and f("/x/176207_hd.zip") is None
    assert f("D:/x/191777_hd Christen Autumn.rar") == "Christen Autumn" and f("x/176207_hd.zip") is None
    assert f("/x/Nguyen.zip") is None                               # một từ: không chắc
    assert cluster.fold("Đặng Thị Bé") == "dang thi be"


def _arch_img(db, arch, n):
    return db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"zip://{arch}!/{n}.jpg", 1, 1, 100, 100, "t")).lastrowid


def test_archive_named_after_person_assigns_faces(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a = np.random.default_rng(81).normal(size=512).astype(np.float32)
    a /= np.linalg.norm(a)
    fs = []
    for i in range(4):                                              # 4 ảnh một mặt trong file 'Nguyen Van A.zip' (không cần giống nhau)
        iid = _arch_img(db, "/d/Nguyen Van A.zip", i)
        fs.append(_face(db, iid, _vec(300 + i, 3.0, a)))
    iid = _arch_img(db, "/d/Nguyen Van A.zip", 9)                   # ảnh 2 mặt: chọn mặt giống người đó nhất
    near = _face(db, iid, _vec(400, 0.2, a))
    far = _face(db, iid, _vec(401, 0.0, np.random.default_rng(82).normal(size=512).astype(np.float32)))
    other = _face(db, _arch_img(db, "/d/167350.zip", 1), _vec(500, 0.0, np.random.default_rng(83).normal(size=512).astype(np.float32)))
    cluster.cluster_faces(db)
    p = db.one("SELECT id FROM persons WHERE name='Nguyen Van A'")
    assert p is not None
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert all(pid(f) == p["id"] for f in fs) and pid(near) == p["id"] and pid(far) != p["id"]
    assert pid(other) != p["id"]                                    # file nén không có tên người: không gán
    assert db.one("SELECT locked FROM faces WHERE id=?", (fs[0],))["locked"] == 1


def test_archive_multi_person_images_pick_most_frequent_person(tmp_path, monkeypatch):
    """Ảnh có nhiều người: người xuất hiện ở nhiều ảnh nhất trong file nén là người mang tên file (dù mặt họ nhỏ hơn)."""
    db = _db(tmp_path, monkeypatch)
    rng = np.random.default_rng(55)
    A = rng.normal(size=512).astype(np.float32)
    A /= np.linalg.norm(A)
    B = rng.normal(size=512).astype(np.float32)
    B /= np.linalg.norm(B)
    a_faces, b_faces, one_off = [], [], []
    for i in range(5):                                              # A có mặt ở cả 5 ảnh, B chỉ ở 3 ảnh và mặt B luôn LỚN hơn
        iid = _arch_img(db, "/d/Tran Van Hung.zip", i)
        a_faces.append(_face(db, iid, _vec(1000 + i, 0.25, A)))
        db.x("UPDATE faces SET w=0.15,h=0.15 WHERE id=?", (a_faces[-1],))
        if i < 3:
            b_faces.append(_face(db, iid, _vec(1100 + i, 0.25, B)))
            db.x("UPDATE faces SET w=0.4,h=0.4 WHERE id=?", (b_faces[-1],))
        else:                                                       # ảnh 4 và 5: thêm một người lạ khác nhau, mặt cũng lớn
            one_off.append(_face(db, iid, _vec(1200 + i, 0.0, np.random.default_rng(1300 + i).normal(size=512).astype(np.float32))))
            db.x("UPDATE faces SET w=0.4,h=0.4 WHERE id=?", (one_off[-1],))
    cluster.cluster_faces(db)
    p = db.one("SELECT id FROM persons WHERE name='Tran Van Hung'")["id"]
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert all(pid(f) == p for f in a_faces)                         # chọn A (xuất hiện nhiều nhất), không chọn mặt lớn nhất
    assert all(pid(f) != p for f in b_faces + one_off)


def test_archive_name_matches_existing_person_ignoring_accents(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pid = db.x("INSERT INTO persons(name) VALUES('Đặng Thị Bé')").lastrowid
    f = _face(db, _arch_img(db, "/d/dang_thi_be_2024_photos.zip", 1), _vec(600))
    cluster.cluster_faces(db)
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] == pid
    assert db.one("SELECT COUNT(*) c FROM persons")["c"] == 1       # không tạo thêm người mới


def test_person_profile_survives_deleting_all_photos(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a, b = (np.random.default_rng(s).normal(size=512).astype(np.float32) for s in (91, 92))
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    fa = [_face(db, _img(db, i), _vec(700 + i, 0.3, a)) for i in range(4)]
    fb = [_face(db, _img(db, 20 + i), _vec(800 + i, 0.3, b)) for i in range(4)]
    cluster.cluster_faces(db)
    pa = db.one("SELECT person_id p FROM faces WHERE id=?", (fa[0],))["p"]
    cluster.rename_person(db, pa, "Nguoi A")                         # đặt tên: lưu hồ sơ khuôn mặt
    assert db.one("SELECT COUNT(*) c FROM person_profile WHERE person_id=?", (pa,))["c"] >= 1
    for f in fa:                                                     # xóa toàn bộ ảnh của người A khỏi thư viện
        r = db.one("SELECT image_id FROM faces WHERE id=?", (f,))
        db.x("DELETE FROM faces WHERE id=?", (f,))
        db.x("DELETE FROM images WHERE id=?", (r["image_id"],))
    cluster.cluster_faces(db)
    assert db.one("SELECT name FROM persons WHERE id=?", (pa,)) is not None      # người và hồ sơ vẫn còn
    assert db.one("SELECT COUNT(*) c FROM person_profile WHERE person_id=?", (pa,))["c"] >= 1
    new = _face(db, _img(db, 99), _vec(900, 0.3, a))                 # thêm lại ảnh của người A sau này
    stranger = _face(db, _img(db, 98), _vec(901, 0.0, np.random.default_rng(93).normal(size=512).astype(np.float32)))
    cluster.cluster_faces(db)
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (new,))["p"] == pa                 # nhận ra đúng người A (đã có tên)
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (stranger,))["p"] != pa
    assert db.one("SELECT name FROM persons WHERE id=?", (pa,))["name"] == "Nguoi A"


def _mk_person(db, base, noise, seed, n, img_start, name=None):
    pid = db.x("INSERT INTO persons(name) VALUES(?)", (name,)).lastrowid
    fs = []
    for i in range(n):
        f = _face(db, _img(db, img_start + i), _vec(seed + i, noise, base))
        db.x("UPDATE faces SET person_id=?, locked=? WHERE id=?", (pid, 1 if name else 0, f))
        fs.append(f)
    return pid, fs


def test_suggest_and_merge_split_person(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    rng = np.random.default_rng(31)
    A = rng.normal(size=512).astype(np.float32)
    A /= np.linalg.norm(A)
    shift = rng.normal(size=512).astype(np.float32)
    shift -= (shift @ A) * A
    shift /= np.linalg.norm(shift)
    A2 = (0.80 * A + 0.60 * shift).astype(np.float32)               # cùng người nhưng khác góc/tuổi: giống A khoảng 0.8
    B = rng.normal(size=512).astype(np.float32)
    B /= np.linalg.norm(B)
    p_small, _ = _mk_person(db, A2, 0.15, 2000, 7, 0)               # nhóm 7 ảnh
    p_big, _ = _mk_person(db, A, 0.15, 2100, 40, 100)               # nhóm 40 ảnh
    p_other, _ = _mk_person(db, B, 0.15, 2200, 20, 300)             # người khác hẳn
    s = cluster.suggest_merges(db)
    pairs = {frozenset((d["a"], d["b"])) for d in s}
    assert frozenset((p_small, p_big)) in pairs                      # gợi ý gộp đúng cặp bị tách
    assert not any(p_other in k for k in pairs)                      # không gợi ý người khác
    cluster.reject_merge(db, p_small, p_big)
    assert not cluster.suggest_merges(db)                            # đã bấm 'khác người': không đề xuất lại
    db.x("DELETE FROM person_nomerge")
    dst = cluster.merge_pair(db, p_small, p_big)
    assert dst == p_big                                              # giữ nhóm nhiều ảnh hơn
    assert db.one("SELECT COUNT(*) c FROM faces WHERE person_id=?", (p_big,))["c"] == 47


def test_no_merge_when_sharing_a_photo_or_both_named(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    A = np.random.default_rng(41).normal(size=512).astype(np.float32)
    A /= np.linalg.norm(A)
    p1, f1 = _mk_person(db, A, 0.1, 3000, 5, 0)
    p2, f2 = _mk_person(db, A, 0.1, 3100, 5, 100)
    assert cluster.suggest_merges(db)                                # nhìn giống nhau: có gợi ý
    # hai nhóm cùng xuất hiện trong một ảnh => hai người khác nhau
    shared = db.one("SELECT image_id i FROM faces WHERE id=?", (f1[0],))["i"]
    extra = _face(db, shared, _vec(3200, 0.1, A))
    db.x("UPDATE faces SET person_id=? WHERE id=?", (p2, extra))
    assert not cluster.suggest_merges(db)
    # hai nhóm đều đã đặt tên: không đề xuất
    db.x("DELETE FROM faces WHERE id=?", (extra,))
    assert cluster.suggest_merges(db)
    db.x("UPDATE persons SET name='A' WHERE id=?", (p1,))
    db.x("UPDATE persons SET name='B' WHERE id=?", (p2,))
    assert not cluster.suggest_merges(db)
    # nhóm có tên được giữ khi gộp với nhóm chưa tên
    db.x("UPDATE persons SET name=NULL WHERE id=?", (p2,))
    assert cluster.merge_pair(db, p1, p2) == p1


def test_auto_merge_only_strong_pairs(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    rng = np.random.default_rng(51)
    A = rng.normal(size=512).astype(np.float32)
    A /= np.linalg.norm(A)
    p1, _ = _mk_person(db, A, 0.1, 4000, 6, 0)
    p2, _ = _mk_person(db, A, 0.1, 4100, 6, 100)                    # gần như y hệt: rất chắc
    B = rng.normal(size=512).astype(np.float32)
    B /= np.linalg.norm(B)
    p3, _ = _mk_person(db, B, 0.1, 4200, 6, 200)
    assert cluster.auto_merge(db) == 1
    left = {r["id"] for r in db.q("SELECT id FROM persons")}
    assert p3 in left and len(left & {p1, p2}) == 1


def test_named_person_attracts_old_and_new_faces(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    rng = np.random.default_rng(61)

    def unit(v):
        return (v / np.linalg.norm(v)).astype(np.float32)
    A = unit(rng.normal(size=512))
    B = unit(rng.normal(size=512))
    side = rng.normal(size=512)
    side = unit(side - (side @ A) * A)
    a_side = unit(0.75 * A + 0.66 * side)                            # cùng người A nhưng nghiêng/khác tuổi (giống A khoảng 0.75)
    # người A đã đặt tên với vài ảnh chính diện + vài ảnh nghiêng
    pa, fa = _mk_person(db, A, 0.1, 5000, 4, 0, name="Nguoi A")
    pa2, fa2 = _mk_person(db, a_side, 0.1, 5100, 4, 100)
    pb, fb = _mk_person(db, B, 0.1, 5200, 5, 200, name="Nguoi B")
    old_a = _face(db, _img(db, 400), _vec(5300, 0.1, A))             # ảnh cũ chưa xếp nhóm
    old_a_side = _face(db, _img(db, 401), _vec(5301, 0.1, a_side))   # ảnh cũ nghiêng chưa xếp nhóm
    stranger = _face(db, _img(db, 402), _vec(5302, 0.0, rng.normal(size=512).astype(np.float32)))
    db.x("UPDATE faces SET locked=1 WHERE person_id IN (?,?)", (pa, pb))
    cluster.save_profiles(db)
    cluster.cluster_faces(db)
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert pid(old_a) == pa and pid(old_a_side) == pa                # tự gom vào người A (cả ảnh nghiêng)
    assert pid(stranger) not in (pa, pb)                             # người lạ không bị gán nhầm
    assert all(pid(f) == pb for f in fb)
    # ảnh mới thêm sau: tự nhận ra
    new_a = _face(db, _img(db, 500), _vec(5400, 0.1, A))
    cluster.cluster_faces(db)
    assert pid(new_a) == pa
    # đặt tên cho nhóm nghiêng cũ -> cùng người? (tên khác) không bị ép gộp; nhưng mặt mới chưa xếp nhóm được gán ngay khi đặt tên
    late = _face(db, _img(db, 600), _vec(5500, 0.1, B))
    cluster.rename_person(db, pb, "Nguoi B")
    assert pid(late) == pb


def _unit_vec(seed):
    v = np.random.default_rng(seed).normal(size=512).astype(np.float32)
    return v / np.linalg.norm(v)


def test_name_in_many_archives_uses_cross_archive_identity(tmp_path, monkeypatch):
    """Mỗi file có người A và một người khác, mặt người khác LUÔN lớn hơn và xuất hiện nhiều như A trong file đó (hòa nếu chỉ xét từng file).
    Nhưng A có mặt ở cả 3 file còn mỗi người khác chỉ ở một file -> A là người mang tên."""
    db = _db(tmp_path, monkeypatch)
    A = _unit_vec(70)
    a_faces, other_faces = [], []
    for ai, arch in enumerate(["/d/Tran Van Hung 1.zip", "/d/tran van hung - 2.zip", "/d/Tran_Van_Hung_3.zip"]):
        friend = _unit_vec(80 + ai)
        for i in range(3):
            iid = _arch_img(db, arch, i)
            fa = _face(db, iid, _vec(2000 + ai * 10 + i, 0.25, A))
            db.x("UPDATE faces SET w=0.15,h=0.15 WHERE id=?", (fa,))
            fo = _face(db, iid, _vec(3000 + ai * 10 + i, 0.25, friend))
            db.x("UPDATE faces SET w=0.4,h=0.4 WHERE id=?", (fo,))
            a_faces.append(fa)
            other_faces.append(fo)
    cluster.cluster_faces(db)
    p = db.one("SELECT id FROM persons WHERE name='Tran Van Hung'")["id"]
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert all(pid(f) == p for f in a_faces)
    assert all(pid(f) != p for f in other_faces)
    assert db.one("SELECT COUNT(*) c FROM persons WHERE name='Tran Van Hung'")["c"] == 1


def test_archive_with_two_known_names_assigns_each_face(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    A, B = _unit_vec(90), _unit_vec(91)
    pa, _ = _mk_person(db, A, 0.2, 4000, 3, 0, name="Anna Nguyen")
    pb, _ = _mk_person(db, B, 0.2, 4100, 3, 100, name="Bella Tran")
    cluster.save_profiles(db)
    fa, fb, other = [], [], []
    for i in range(3):
        iid = _arch_img(db, "/d/Anna Nguyen & Bella Tran photos.zip", i)
        fb.append(_face(db, iid, _vec(4200 + i, 0.25, B)))                # thứ tự ngược để tránh phụ thuộc vị trí
        fa.append(_face(db, iid, _vec(4300 + i, 0.25, A)))
    iid = _arch_img(db, "/d/Anna Nguyen & Bella Tran photos.zip", 9)
    other.append(_face(db, iid, _unit_vec(95)))                           # ảnh chỉ có người lạ: không gán bừa
    cluster.cluster_faces(db)
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert all(pid(f) == pa for f in fa) and all(pid(f) == pb for f in fb)
    assert pid(other[0]) not in (pa, pb)
    assert cluster._names_in_base("Anna Nguyen & Bella Tran") == ["Anna Nguyen", "Bella Tran"]


def test_hair_classes_and_letters():
    hc = cluster.hair_class
    assert hc(15, 2, 3) == "black"
    assert hc(30, 6, 12) == "brunette"
    assert hc(45, 10, 18) == "brown"
    assert hc(70, 4, 24) == "blonde"
    assert hc(45, 22, 20) == "red"
    assert hc(75, 1, 2) == "gray"
    assert cluster.letter_key("Nguyễn Văn Đức") == "N" and cluster.letter_key("Nguyễn Văn Đức", given=True) == "D"
    assert cluster.letter_key("Đặng Thị Bé", given=True) == "B" and cluster.letter_key("") == "#" and cluster.letter_key("123") == "#"


def test_person_hair_from_face_attr(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pa, fa = _mk_person(db, _unit_vec(1), 0.1, 100, 3, 0)
    pb, fb = _mk_person(db, _unit_vec(2), 0.1, 200, 3, 100)
    for f in fa:
        db.x("INSERT INTO face_attr(face_id,sk_l,sk_a,sk_b,hr_l,hr_a,hr_b,sharp) VALUES(?,?,?,?,?,?,?,?)", (f, 70, 12, 20, 12, 1, 2, 3))      # tóc đen
    for f in fb:
        db.x("INSERT INTO face_attr(face_id,sk_l,sk_a,sk_b,hr_l,hr_a,hr_b,sharp) VALUES(?,?,?,?,?,?,?,?)", (f, 70, 12, 20, 72, 3, 26, 3))     # tóc vàng
    h = cluster.person_hair(db)
    assert h[pa] == "black" and h[pb] == "blonde"


def test_sequence_assign_in_multi_name_archive(tmp_path, monkeypatch):
    """Tệp nén nhiều tên: ảnh không thấy mặt nằm giữa các ảnh của một người thì thuộc người đó; ảnh lạ và ảnh ở ranh giới không bị gán nhầm."""
    import numpy as np
    from pp import cluster, db as dbm, paths
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    db = dbm.DB(paths.db_path())
    rng = np.random.default_rng(3)

    def clipv(axis, noise=0.01):
        v = np.zeros(512, np.float32)
        v[axis] = 1.0
        v += rng.normal(0, noise, 512).astype(np.float32)
        return (v / np.linalg.norm(v)).astype(np.float32)
    a = db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    b = db.x("INSERT INTO persons(name) VALUES('Bella Tran')").lastrowid
    arch = "zip://D:/x/Anna Nguyen & Bella Tran.zip!/"
    plan = [("01", "A"), ("02", "A"), ("03", "A"), ("04", "-A"), ("05", "-S"), ("06", "A"), ("07", "B"), ("08", "B"), ("09", "-B"), ("10", "B")]
    ids = {}
    for name, kind in plan:
        axis = {"A": 0, "-A": 0, "B": 1, "-B": 1, "-S": 5}[kind]
        iid = db.x("INSERT INTO images(path,mtime,size,clip) VALUES(?,?,?,?)", (arch + name + ".jpg", 1, 1, dbm.vec_to_blob(clipv(axis)))).lastrowid
        ids[name] = iid
        if not kind.startswith("-"):
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)",
                 (iid, dbm.vec_to_blob(np.ones(512, np.float32)), a if kind == "A" else b))
    cluster.assign_by_sequence(db)
    got = {r["image_id"]: (r["person_id"], r["state"]) for r in db.q("SELECT * FROM person_guess")}
    assert got[ids["04"]][0] == a and got[ids["04"]][1] == 2          # giữa các ảnh của Anna, giống Anna: tự xác nhận
    assert got[ids["09"]][0] == b                                     # giữa các ảnh của Bella
    assert ids["05"] not in got                                       # ảnh lạ (không giống ai) không bị gán
    assert ids["04"] in {i["id"] for i in db.person_images(a)}


def test_comma_separated_names_create_missing_persons(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    A = _unit_vec(90)
    pa, _ = _mk_person(db, A, 0.2, 4000, 3, 0, name="Anna Nguyen")
    cluster.save_profiles(db)
    for i in range(3):
        iid = _arch_img(db, "/d/191777_hd Anna Nguyen, Bella Tran.zip", i)
        _face(db, iid, _vec(4300 + i, 0.25, A))
        _face(db, iid, _vec(4400 + i, 0.25, _unit_vec(91)))
    cluster.cluster_faces(db)
    names = {r["name"] for r in db.q("SELECT name FROM persons WHERE name IS NOT NULL")}
    assert names == {"Anna Nguyen", "Bella Tran"}
    assert cluster._names_in_base("191777_hd Anna Nguyen, Bella Tran") == ["Anna Nguyen", "Bella Tran"]


def test_ellipsis_and_coverage_report(tmp_path, monkeypatch):
    f = cluster._names_in_base
    assert f("175748 Carlotta Champagne, Renée Reece, Destiny Moody, ...") == ["Carlotta Champagne", "Renée Reece", "Destiny Moody"]
    assert cluster._has_more("A B, C D, ...") and not cluster._has_more("A B, C D")
    db = _db(tmp_path, monkeypatch)
    A = _unit_vec(90)
    _mk_person(db, A, 0.2, 4000, 3, 0, name="Anna Nguyen")
    cluster.save_profiles(db)
    arch = "/d/175748 Anna Nguyen, Bella Tran, ....zip"
    for i in range(3):
        iid = _arch_img(db, arch, i)
        _face(db, iid, _vec(4300 + i, 0.25, A))
        _face(db, iid, _vec(4500 + i, 0.25, _unit_vec(77)))             # người thứ ba chưa có tên, xuất hiện nhiều lần
    cluster.cluster_faces(db)
    rep = cluster.archive_coverage(db)
    assert len(rep) == 1 and rep[0]["names"] == ["Anna Nguyen", "Bella Tran"] and rep[0]["more"]
    assert rep[0]["counts"]["Anna Nguyen"] >= 3 and "Bella Tran" in rep[0]["missing"] and rep[0]["unnamed"] >= 1


def test_connectors_between_names():
    f, n = cluster._names_in_base, cluster.name_from_archive
    for single in ["Cassie Keller", "Angel Constance", "Mia Valentine", "Kit Rysha", "Karoline CC"]:
        assert n(single + ".zip") == single and f(single) == []
    assert n("Mary-Jane Smith.zip") == "Mary Jane Smith" and f("Mary-Jane Smith") == []
    assert f("Cassie Keller and Angel Constance") == ["Cassie Keller", "Angel Constance"]
    assert f("Cassie Keller - Angel Constance") == ["Cassie Keller", "Angel Constance"]
    assert f("Mia Valentine with Kit Rysha") == ["Mia Valentine", "Kit Rysha"]
    assert f("Kit Rysha x Karoline CC") == ["Kit Rysha", "Karoline CC"]
    assert f("Kit Rysha feat. Karoline CC") == ["Kit Rysha", "Karoline CC"]
    assert f("Cassie_Keller_&_Angel_Constance") == ["Cassie Keller", "Angel Constance"]
    assert f("Cassie Keller, Angel Constance & Mia Valentine - Kit Rysha") == ["Cassie Keller", "Angel Constance", "Mia Valentine", "Kit Rysha"]
    assert n("Kit Rysha x Karoline CC.zip") is None and n("Cassie Keller - Angel Constance.rar") is None


def test_short_names():
    f = cluster._names_in_base
    assert f("Mia, Eva Li, Kit") == ["Mia", "Eva Li", "Kit"]
    assert f("175748 Ann, Bo Li & Zoe") == ["Ann", "Bo Li", "Zoe"]
    assert f("Photos, Anna Nguyen") == []                       # từ chung không thành tên
    assert cluster.name_from_archive("Bo Li.zip") == "Bo Li"


def test_artwork_faces_excluded_from_people(tmp_path, monkeypatch):
    import numpy as np
    from pp import art, cluster
    from pp.db import vec_to_blob
    db = _db(tmp_path, monkeypatch)
    pa, fa = _mk_person(db, _unit_vec(5), 0.1, 100, 3, 0)               # người thật
    painting = _arch_img(db, "/d/x.zip", 50)
    f = _face(db, painting, _unit_vec(5))
    e0, e1 = np.zeros(512, np.float32), np.zeros(512, np.float32)
    e0[0], e1[1] = 1, 1
    db.x("UPDATE images SET clip=? WHERE id=?", (vec_to_blob(e0), painting))
    real = db.one("SELECT image_id i FROM faces WHERE person_id=?", (pa,))["i"]
    db.x("UPDATE images SET clip=? WHERE id=?", (vec_to_blob(e1), real))
    txt = lambda p: e0 if p in art.ART else e1
    assert art.detect(db, txt) == 1
    assert db.one("SELECT art FROM image_art WHERE image_id=?", (painting,))["art"] == 1
    cluster.cluster_faces(db)
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] is None
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (fa[0],))["p"] == pa


def test_infer_name_from_common_archives(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pa, _ = _mk_person(db, _unit_vec(1), 0.1, 100, 3, 0, name="Anna Nguyen")
    pu = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    for k, arch in enumerate(["/d/Anna Nguyen, Bella Tran.zip", "/d/Bella Tran, Cara Lee.zip"]):
        for i in range(2):
            iid = _arch_img(db, arch, i)
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,0,80,0.9)", (iid, vec_to_blob(_unit_vec(50)), pu))
            if k == 0:                                                           # Anna đã có người riêng trong tệp đầu: tên còn lại chỉ là Bella
                db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, vec_to_blob(_unit_vec(1)), pa))
    assert cluster.infer_names(db) == 1
    r = db.one("SELECT name,n_arch FROM person_suggest WHERE person_id=?", (pu,))
    assert r["name"] == "Bella Tran" and r["n_arch"] == 2                       # tên chung của cả hai tệp


def test_infer_name_is_cautious_when_several_people(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    # hai tệp cùng chứa HAI tên chung (Bella, Cara) và hai nhóm mặt lạ: không đủ cơ sở để biết nhóm nào là ai
    pu1 = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    pu2 = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    for arch in ["/d/Bella Tran, Cara Lee, Dana Fox.zip", "/d/Bella Tran, Cara Lee, Eve Ray.zip"]:
        for i in range(3):
            iid = _arch_img(db, arch, i)
            for pu, seed in ((pu1, 50), (pu2, 60)):
                db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,0,80,0.9)", (iid, vec_to_blob(_unit_vec(seed)), pu))
    assert cluster.infer_names(db) == 0
    # một nhóm, hai tệp chỉ chung một tên nhưng tệp còn nhiều tên lạ và có '...': không rõ ràng nên không đoán
    pu3 = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    for arch in ["/d/Fay One, Gus Two, ....zip", "/d/Fay One, Hal Six, ....zip"]:
        for i in range(2):
            iid = _arch_img(db, arch, i)
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,0,80,0.9)", (iid, vec_to_blob(_unit_vec(70)), pu3))
    assert cluster.infer_names(db) == 0


def test_infer_by_elimination_in_single_archive(tmp_path, monkeypatch):
    """Tệp có tên người đã nhận diện + một tên còn lại: sau khi loại người đã biết, nhóm mặt chiếm phần lớn tệp là người còn lại."""
    db = _db(tmp_path, monkeypatch)
    pa, _ = _mk_person(db, _unit_vec(1), 0.1, 100, 3, 0, name="Anna Nguyen")
    pu = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    for i in range(5):
        iid = _arch_img(db, "/d/Anna Nguyen, Bella Tran.zip", i)
        db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, vec_to_blob(_unit_vec(1)), pa))
        db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,0,80,0.9)", (iid, vec_to_blob(_unit_vec(50)), pu))
    assert cluster.infer_names(db) == 1
    assert db.one("SELECT name FROM person_suggest WHERE person_id=?", (pu,))["name"] == "Bella Tran"


def test_wrongly_locked_face_returns_to_right_person(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    A, B = _unit_vec(11), _unit_vec(12)
    pa, fa = _mk_person(db, A, 0.2, 100, 6, 0, name="Anna Nguyen")
    pb, fb = _mk_person(db, B, 0.2, 200, 6, 100, name="Bella Tran")
    cluster.save_profiles(db)
    wrong = _face(db, _img(db, 300), _vec(900, 0.2, A))                  # mặt của Anna nhưng bị khóa nhầm vào Bella
    db.x("UPDATE faces SET person_id=?, locked=1 WHERE id=?", (pb, wrong))
    mine = _face(db, _img(db, 301), _vec(901, 0.2, A))                   # người dùng TỰ ĐẶT vào Bella: giữ nguyên
    db.x("UPDATE faces SET person_id=?, locked=1, lsrc='user' WHERE id=?", (pb, mine))
    assert cluster.reconcile_named(db) == 1
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert pid(wrong) == pa and pid(mine) == pb
    assert all(pid(f) == pa for f in fa) and all(pid(f) == pb for f in fb)


def test_infer_auto_names_when_evidence_is_strong(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pu = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    for arch in ["/d/Bella Tran, Cara Lee.zip", "/d/Bella Tran, Dana Fox.zip", "/d/Bella Tran, Eve Ray.zip"]:
        for i in range(3):
            iid = _arch_img(db, arch, i)
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,0,80,0.9)", (iid, vec_to_blob(_unit_vec(50)), pu))
    assert cluster.infer_names(db) == 1 and db.one("SELECT name FROM persons WHERE id=?", (pu,))["name"] is None    # mặc định chỉ gợi ý
    assert cluster.infer_names(db, auto=True) == 1
    assert db.one("SELECT name FROM persons WHERE id=?", (pu,))["name"] == "Bella Tran"


def test_boundary_photo_can_belong_to_both_people(tmp_path, monkeypatch):
    import numpy as np
    from pp import cluster, db as dbm, paths
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home2"))
    db = dbm.DB(paths.db_path())
    a = db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    b = db.x("INSERT INTO persons(name) VALUES('Bella Tran')").lastrowid
    both = np.zeros(512, np.float32)
    both[0] = both[1] = 1.0
    both /= np.linalg.norm(both)
    ax, bx = np.zeros(512, np.float32), np.zeros(512, np.float32)
    ax[0], bx[1] = 1.0, 1.0
    arch = "zip://D:/x/Anna Nguyen & Bella Tran.zip!/"
    ids = {}
    for name, who in [("01", a), ("02", a), ("03", None), ("04", b), ("05", b)]:
        v = both if who is None else (ax if who == a else bx)
        iid = db.x("INSERT INTO images(path,mtime,size,clip) VALUES(?,?,?,?)", (arch + name + ".jpg", 1, 1, dbm.vec_to_blob(v))).lastrowid
        ids[name] = iid
        if who:
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, dbm.vec_to_blob(np.ones(512, np.float32)), who))
    cluster.assign_by_sequence(db)
    got = {r["person_id"] for r in db.q("SELECT person_id FROM person_guess WHERE image_id=?", (ids["03"],))}
    assert got == {a, b}                                             # xuất hiện ở cả hai nhóm tên, dạng gợi ý để duyệt


def test_removed_photo_moves_to_other_person_and_never_returns(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    A, B = _unit_vec(21), _unit_vec(22)
    pa, fa = _mk_person(db, A, 0.2, 100, 6, 0, name="Anna Nguyen")
    pb, fb = _mk_person(db, B, 0.2, 200, 6, 100, name="Bella Tran")
    cluster.save_profiles(db)
    stray = _face(db, _img(db, 300), _vec(900, 0.2, B))                 # mặt của Bella đang nằm nhầm trong nhóm Anna
    db.x("UPDATE faces SET person_id=?, locked=0 WHERE id=?", (pa, stray))
    img = db.one("SELECT image_id i FROM faces WHERE id=?", (stray,))["i"]
    cluster.remove_from_person(db, pa, [img])
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert pid(stray) == pb                                              # tự chuyển sang đúng người
    cluster.cluster_faces(db)
    assert pid(stray) == pb and pid(stray) != pa


def test_clothing_options_add_up_to_total():
    from pp import clothing
    o = clothing.options({"cloth": 125, "nude": 137}, 278)
    assert [c for c, _ in o] == ["cloth", "nude", "unclear"] and "16" in o[-1][1]      # 125 + 137 + 16 = 278
    assert clothing.options({}, 10) == []


def test_manual_clothing_classification_not_overwritten(tmp_path, monkeypatch):
    import numpy as np
    from pp import clothing
    from pp.db import vec_to_blob
    db = _db(tmp_path, monkeypatch)
    iid = _img(db, 1)
    db.x("UPDATE images SET clip=? WHERE id=?", (vec_to_blob(np.ones(512, np.float32)), iid))
    clothing.set_manual(db, [iid], "nude")
    assert db.one("SELECT grp FROM cloth_group WHERE image_id=?", (iid,))["grp"] == "nude"
    prompts = [p for _, _, ps in clothing.CATS for p in ps]
    clothing.analyze(db, lambda s: np.ones(512, np.float32), redo=True)                # phân tích tự động chạy lại
    assert db.one("SELECT grp FROM cloth_group WHERE image_id=?", (iid,))["grp"] == "nude"
    clothing.clear_manual(db, [iid])
    assert db.one("SELECT grp FROM cloth_group WHERE image_id=?", (iid,)) is None


def test_clothing_is_not_a_label_and_old_labels_are_removed(tmp_path, monkeypatch):
    from pp import clothing
    db = _db(tmp_path, monkeypatch)
    a = _img(db, 1)
    clothing.set_manual(db, [a], "cloth")
    assert not db.labels()                                                   # phân loại không tạo nhãn
    lid = db.x("INSERT INTO labels(name) VALUES('Mặc đồ')").lastrowid       # nhãn do bản cũ tạo ra
    db.x("INSERT INTO label_images VALUES(?,?)", (lid, a))
    other = db.x("INSERT INTO labels(name) VALUES('Yêu thích')").lastrowid
    clothing.remove_clothing_labels(db)
    assert [l["name"] for l in db.labels()] == ["Yêu thích"] and other
    assert db.one("SELECT grp FROM cloth_group WHERE image_id=?", (a,))["grp"] == "cloth"     # phân loại vẫn còn



def test_single_name_archive_assigns_faceless_photos(tmp_path, monkeypatch):
    import numpy as np
    from pp import cluster, db as dbm, paths
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home3"))
    db = dbm.DB(paths.db_path())
    a = db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    ax, other = np.zeros(512, np.float32), np.zeros(512, np.float32)
    ax[0] = 1.0
    other[7] = 1.0
    arch = "zip://D:/x/Anna Nguyen.zip!/"
    ids = {}
    for name, kind in [("01", "F"), ("02", "F"), ("03", "-"), ("04", "F"), ("05", "F"), ("06", "X")]:
        v = other if kind == "X" else ax
        iid = db.x("INSERT INTO images(path,mtime,size,clip) VALUES(?,?,?,?)", (arch + name + ".jpg", 1, 1, dbm.vec_to_blob(v))).lastrowid
        ids[name] = iid
        if kind == "F":
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, dbm.vec_to_blob(np.ones(512, np.float32)), a))
    cluster.assign_by_sequence(db)
    got = {r["image_id"]: r["state"] for r in db.q("SELECT image_id,state FROM person_guess WHERE person_id=?", (a,))}
    assert got.get(ids["03"]) == 2                                    # nằm giữa ảnh của Anna và giống Anna: thuộc Anna
    assert ids["06"] not in got                                       # ảnh lạ cuối tệp không giống ai: không gán


def test_single_name_archive_claims_every_photo(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pa, _ = _mk_person(db, _unit_vec(31), 0.1, 100, 3, 0, name="Anna Nguyen")
    imgs = [_arch_img(db, "/d/Anna Nguyen.zip", i) for i in range(5)]
    db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (imgs[0], vec_to_blob(_unit_vec(31)), pa))
    multi = _arch_img(db, "/d/Anna Nguyen, Bella Tran.zip", 1)                      # tệp nhiều tên: không coi toàn bộ là của Anna
    assert cluster.claim_single_name_archives(db) == 4                               # 4 ảnh chưa có mặt của Anna, thêm vào hết
    ids = {i["id"] for i in db.person_images(pa)}
    assert set(imgs) <= ids and multi not in ids
    cluster.remove_from_person(db, pa, [imgs[2]])                                    # người dùng loại một ảnh
    cluster.claim_single_name_archives(db)
    assert imgs[2] not in {i["id"] for i in db.person_images(pa)}                    # không bị thêm lại


def test_duplicates_without_clip_vectors_and_order(tmp_path, monkeypatch):
    """Hai bản sao y hệt (cùng kích thước, dung lượng, hình) bị gom dù chưa có vectơ nội dung."""
    import io
    from PIL import Image
    from pp import dup
    from pp.secure import SEC
    db = _db(tmp_path, monkeypatch)
    ids = []
    for i, shade in enumerate([100, 100, 200]):
        im = Image.new("RGB", (64, 64), (shade, 80, 60))
        for x in range(0, 64, 8):
            im.putpixel((x, x), (255, 255, 255))
        buf = io.BytesIO()
        im.save(buf, "JPEG")
        t = tmp_path / f"t{i}.jpg"
        t.write_bytes(buf.getvalue())
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/d/{i}.jpg", i, 5000 if shade == 100 else 7000, 640, 480, str(t))).lastrowid
        ids.append(iid)
    g = dup.find_groups(db)
    assert len(g) == 1 and sorted(g[0]["members"]) == sorted(ids[:2])


def test_clothing_menu_hides_current_group(tmp_path, monkeypatch):
    from pp import clothing
    db = _db(tmp_path, monkeypatch)
    a, b, c = _img(db, 1), _img(db, 2), _img(db, 3)
    clothing.set_manual(db, [a], "cloth")
    clothing.set_manual(db, [b], "nude")
    names = lambda ids: [n for _, n in clothing.menu_options(db, ids)]
    assert names([a]) == ["Naked", "Chưa rõ"]                 # đang Dressed: không hiện Dressed
    assert names([b]) == ["Dressed", "Chưa rõ"]
    assert names([c]) == ["Dressed", "Naked"]                  # chưa phân loại: không hiện Chưa rõ
    assert names([a, b]) == ["Dressed", "Naked", "Chưa rõ"]    # lẫn nhiều nhóm: hiện đủ


def test_photo_combos_include_unnamed_people_but_not_solo_photos(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a = db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    b = db.x("INSERT INTO persons(name) VALUES('Bella Tran')").lastrowid
    un = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    loner = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid

    def photo(i, ppl):
        iid = _img(db, 1000 + i)
        for pid in ppl:
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, vec_to_blob(_unit_vec(pid + i)), pid))
        return iid
    ab = [photo(i, (a, b)) for i in range(3)]               # Anna + Bella
    au = [photo(10 + i, (a, un)) for i in range(3)]         # Anna + người CHƯA đặt tên: vẫn vào Mashup
    solo = [photo(20 + i, (a,)) for i in range(5)]          # ảnh riêng: không vào
    photo(30, (a, loner))                                   # người chỉ có 1 ảnh: bỏ (nhiễu)
    got = cluster.photo_combos(db)
    labels = [g["names"] for g in got]
    assert ["Anna Nguyen", "Bella Tran"] in labels and any(n[0] == "Anna Nguyen" and n[1].startswith("Chưa đặt tên") for n in labels)
    assert all(set(g["ids"]).isdisjoint(solo) for g in got)
    assert sum(g["n"] for g in got) == 6 and ab and au


def test_infer_name_from_group_photos_with_named_person(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a = db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    un = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    for i in range(4):                                       # tệp 3 tên: Anna, Bella, Cara; ảnh chung của Anna và nhóm lạ
        iid = _arch_img(db, "/d/Anna Nguyen, Bella Tran, Cara Lee.zip", i)
        db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, vec_to_blob(_unit_vec(1)), a))
        db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,0,80,0.9)", (iid, vec_to_blob(_unit_vec(5)), un))
    # ảnh có cả Bella (đã nhận) thì loại Bella khỏi ứng viên của nhóm lạ trong ảnh đó
    bella = db.x("INSERT INTO persons(name) VALUES('Bella Tran')").lastrowid
    for i in range(4, 9):
        iid = _arch_img(db, "/d/Anna Nguyen, Bella Tran, Cara Lee.zip", i)
        db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, vec_to_blob(_unit_vec(1)), a))
        db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, vec_to_blob(_unit_vec(2)), bella))
        db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,0,80,0.9)", (iid, vec_to_blob(_unit_vec(5)), un))
    assert cluster.infer_names_by_photo(db) == 1
    assert db.one("SELECT name FROM person_suggest WHERE person_id=?", (un,))["name"] in ("Cara Lee", "Bella Tran")


def test_people_refresh_does_not_recluster_rejected_faces(tmp_path, monkeypatch):
    """Mặt người dùng đã loại khỏi một người (chưa có chỗ khác) không được coi là 'chờ gom': nếu không mỗi lần làm mới lại gom lại toàn bộ."""
    from PySide6.QtWidgets import QApplication
    from pp.ui.ctx import AppContext
    from pp.ui.pages import PeoplePage
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("PP_HOME", str(tmp_path / "rf"))
    ctx = AppContext()
    pa, fa = _mk_person(ctx.db, _unit_vec(51), 0.1, 100, 4, 0, name="Anna Nguyen")
    img = ctx.db.one("SELECT image_id i FROM faces WHERE id=?", (fa[0],))["i"]
    ctx.db.x("UPDATE faces SET vec=? WHERE id=?", (vec_to_blob(_unit_vec(999)), fa[0]))       # mặt này chẳng giống ai
    cluster.remove_from_person(ctx.db, pa, [img])
    calls = []
    monkeypatch.setattr(cluster, "cluster_faces", lambda *a, **k: calls.append(1))
    page = PeoplePage(ctx)
    page.refresh()
    page.refresh()
    assert not calls


def test_exact_duplicates_auto_trash_only_identical_bytes(tmp_path, monkeypatch):
    from pp import dup
    db = _db(tmp_path, monkeypatch)
    base = tmp_path / "d"
    base.mkdir()
    (base / "a.jpg").write_bytes(b"A" * 1000)
    (base / "a_copy.jpg").write_bytes(b"A" * 1000)            # y hệt
    (base / "b.jpg").write_bytes(b"B" * 1000)                 # cùng dung lượng nhưng khác nội dung
    ids = {}
    for n in ("a", "a_copy", "b"):
        ids[n] = db.x("INSERT INTO images(path,mtime,size,w,h) VALUES(?,?,?,?,?)", (str(base / f"{n}.jpg"), 1, 1000, 640, 480)).lastrowid
    groups = [{"keep": ids["a"], "members": [ids["a"], ids["a_copy"], ids["b"]]}]
    items = dup.exact_items(db, groups)
    assert [i for i, _, _ in items] == [ids["a_copy"]]                          # chỉ bản y hệt từng byte
    trashed = []
    monkeypatch.setattr(dup, "_trash", lambda p: (trashed.append(p), __import__("os").remove(p)))
    n, errs = dup.trash_images(db, items)
    assert n == 1 and not errs and not (base / "a_copy.jpg").exists() and (base / "a.jpg").exists() and (base / "b.jpg").exists()
    assert db.one("SELECT 1 FROM images WHERE id=?", (ids["a_copy"],)) is None


def test_incremental_cluster_does_not_regroup_whole_library(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pa, fa = _mk_person(db, _unit_vec(61), 0.1, 100, 4, 0, name="Anna Nguyen")
    cluster.save_profiles(db)
    new_known = _face(db, _img(db, 500), _vec(950, 0.15, _unit_vec(61)))        # mặt mới của người đã biết
    stranger = _face(db, _img(db, 501), _unit_vec(777))                          # mặt lạ hoàn toàn
    called = []
    monkeypatch.setattr(cluster, "cluster_faces", lambda *a, **k: called.append(1))
    left = cluster.cluster_incremental(db)
    pid = lambda f: db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"]
    assert not called                                                            # không gom lại toàn bộ
    assert pid(new_known) == pa                                                  # mặt người đã biết được gán nhanh
    assert pid(stranger) is None and left >= 1                                   # mặt lạ chờ lần gom đầy đủ


def test_bust_crop_is_wider_and_three_by_four():
    from pp import cover
    l, t, r, b = cover.bust_box(300, 400, (0.4, 0.2, 0.2, 0.15))                 # mặt nhỏ ở giữa ảnh
    assert 0 <= l < r <= 300 and 0 <= t < b <= 400
    assert abs((r - l) / (b - t) - 0.75) < 0.02                                   # 3 : 4
    assert (r - l) >= 0.2 * 300 * 2.5                                             # rộng hơn mặt nhiều lần (lấy cả vai)
    l2, t2, r2, b2 = cover.bust_box(100, 100, (0.1, 0.1, 0.5, 0.5))              # mặt lớn trong ảnh nhỏ: không vượt ảnh
    assert 0 <= l2 < r2 <= 100 and 0 <= t2 < b2 <= 100


def test_persons_report_cover_mode(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pa, fa = _mk_person(db, _unit_vec(71), 0.1, 100, 2, 0, name="Anna Nguyen")
    db.x("UPDATE persons SET cover_mode='bust' WHERE id=?", (pa,))
    row = next(p for p in db.persons() if p["id"] == pa)
    assert row["cover_mode"] == "bust" and "cover_img" in row.keys() and "cover_box" in row.keys()


def test_stage_names_with_numbers_and_single_word_names(tmp_path, monkeypatch):
    f, n = cluster._names_in_base, cluster.name_from_archive
    known = {"la sirena 69", "reed"}
    assert n("La Sirena 69.zip") == "La Sirena"                                  # chưa biết: số cuối coi là số thứ tự
    assert n("La Sirena 69.zip", known) == "La Sirena 69"                       # đã có người tên 'La Sirena 69': giữ số
    assert n("175748 La Sirena 69 hd.rar", known) == "La Sirena 69"
    assert n("Anna Nguyen 02.rar", known) == "Anna Nguyen"                      # số thứ tự tệp vẫn bị bỏ
    assert f("La Sirena 69, Elsa Jean & Reed") == ["La Sirena 69", "Elsa Jean", "Reed"]    # trong danh sách: số thuộc về nghệ danh
    assert f("Noelle Monique, La Sirena 69", known) == ["Noelle Monique", "La Sirena 69"]
    assert cluster.letter_key("La Sirena 69") == "L"
    # tệp đặt tên theo nghệ danh có số khớp đúng người đã có (không tạo thêm 'La Sirena')
    db = _db(tmp_path, monkeypatch)
    pid, fs = _mk_person(db, _unit_vec(88), 0.1, 100, 3, 0, name="La Sirena 69")
    cluster.save_profiles(db)
    for i in range(2):
        iid = _arch_img(db, "/d/La Sirena 69 hd.zip", i)
        _face(db, iid, _vec(900 + i, 0.2, _unit_vec(88)))
    cluster.cluster_faces(db)
    names = [r["name"] for r in db.q("SELECT name FROM persons WHERE name IS NOT NULL")]
    assert names == ["La Sirena 69"]


def test_same_name_persons_are_merged(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pa, fa = _mk_person(db, _unit_vec(81), 0.1, 100, 5, 0, name="Ashley Doris")
    pb, fb = _mk_person(db, _unit_vec(82), 0.1, 200, 3, 100, name="ashley  doris")       # cùng tên (khác hoa thường): cùng một người
    pc, fc = _mk_person(db, _unit_vec(83), 0.1, 300, 2, 200, name="Bella Tran")
    assert cluster.merge_same_name(db) == 1
    names = sorted(r["name"] for r in db.q("SELECT name FROM persons"))
    assert len(names) == 2 and "Bella Tran" in names
    owners = {db.one("SELECT person_id p FROM faces WHERE id=?", (f,))["p"] for f in fa + fb}
    assert owners == {pa}                                                                    # mọi mặt về nhóm lớn hơn
    assert cluster.merge_same_name(db) == 0


def test_session_suggests_dominant_person_for_unknown_photos(tmp_path, monkeypatch):
    import numpy as np
    db = _db(tmp_path, monkeypatch)
    a = db.x("INSERT INTO persons(name) VALUES('Anna Nguyen')").lastrowid
    ax, other = np.zeros(512, np.float32), np.zeros(512, np.float32)
    ax[0] = 1.0
    other[9] = 1.0

    def photo(name, when, vec, person=None):
        iid = db.x("INSERT INTO images(path,mtime,size,taken,thumb,clip) VALUES(?,?,?,?,?,?)",
                   (f"/shoot/{name}.jpg", 1, 1, when, "t", vec_to_blob(vec))).lastrowid
        if person:
            db.x("INSERT INTO faces(image_id,vec,person_id,locked,px,score) VALUES(?,?,?,1,80,0.9)", (iid, vec_to_blob(np.ones(512, np.float32)), person))
        return iid
    for i in range(4):
        photo(f"k{i}", f"2024-05-01 10:{i:02d}:00", ax, a)                     # buổi 1: 4 ảnh đã nhận ra Anna
    u1 = photo("u1", "2024-05-01 10:20:00", ax)                                # ảnh chưa rõ, giống Anna, trong cùng buổi
    u2 = photo("u2", "2024-05-01 10:25:00", other)                             # ảnh lạ (không giống): không gán
    far = photo("far", "2024-05-01 18:00:00", ax)                              # cách xa hàng giờ: buổi khác, không có căn cứ
    assert cluster.assign_by_session(db) == 1
    got = {r["image_id"]: r["person_id"] for r in db.q("SELECT image_id,person_id FROM person_guess")}
    assert got == {u1: a} and u2 not in got and far not in got


def test_full_body_crop_is_largest_three_by_four_with_face_inside():
    from pp import cover
    l, t, r, b = cover.full_box(300, 400, (0.4, 0.1, 0.2, 0.15))
    assert (l, t, r, b) == (0, 0, 300, 400)                                  # ảnh đã đúng 3:4: lấy cả ảnh
    l, t, r, b = cover.full_box(800, 400, (0.8, 0.2, 0.1, 0.2))             # ảnh ngang, mặt lệch phải
    assert abs((r - l) / (b - t) - 0.75) < 0.02 and (b - t) == 400
    assert l <= 0.85 * 800 <= r and r <= 800                                 # khung chứa khuôn mặt, không vượt ảnh


def test_thigh_crop_and_favorite_toggle(tmp_path, monkeypatch):
    from pp import cover
    l, t, r, b = cover.thigh_box(600, 1200, (0.4, 0.1, 0.2, 0.08))               # mặt nhỏ trong ảnh cao: thấy từ đầu đến giữa đùi
    assert abs((r - l) / (b - t) - 0.75) < 0.02 and (b - t) >= 0.4 * 1200 and r <= 600 and b <= 1200
    assert t <= 0.1 * 1200                                                          # khung bắt đầu từ trên đầu
    l2, t2, r2, b2 = cover.thigh_box(300, 300, (0.3, 0.1, 0.4, 0.4))               # ảnh cận mặt: khung không vượt ảnh
    assert 0 <= l2 < r2 <= 300 and 0 <= t2 < b2 <= 300
    db = _db(tmp_path, monkeypatch)
    pa, fa = _mk_person(db, _unit_vec(91), 0.1, 100, 2, 0, name="Anna Nguyen")
    assert db.toggle_favorite(pa) is True and [p["favorite"] for p in db.persons() if p["id"] == pa] == [1]
    assert db.toggle_favorite(pa) is False


def test_navel_crop_is_shorter_than_thigh_crop():
    from pp import cover
    box = (0.4, 0.08, 0.2, 0.06)
    tl, tt, tr, tb = cover.thigh_box(600, 1200, box)
    nl, nt, nr, nb = cover.navel_box(600, 1200, box)
    assert (nb - nt) < (tb - tt) and abs((nr - nl) / (nb - nt) - 0.75) < 0.02 and nt <= 0.08 * 1200        # từ rốn lên: ngắn hơn từ giữa đùi lên


def test_mashup_ignores_mirror_reflection_of_same_person(tmp_path):
    """Ảnh chỉ có một người nhưng thấy thêm bóng trong gương (mặt giống hệt, bị tách thành hai nhóm) không được tính là ảnh Mashup."""
    from pp.db import DB, vec_to_blob
    db = DB(str(tmp_path / "m.db"))
    a = db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    b = db.x("INSERT INTO persons(name) VALUES('B')").lastrowid
    c = db.x("INSERT INTO persons(name) VALUES('C')").lastrowid
    rng = np.random.default_rng(1)
    va, vc = rng.normal(size=128).astype("float32"), rng.normal(size=128).astype("float32")
    mirrored = va + rng.normal(size=128).astype("float32") * 0.1          # bóng gương của A: gần như cùng vector
    def face(iid, pid, v, h=0.2):
        db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,thumb) VALUES(?,?,?,?,?,?,?,?,?,?)", (iid, .2, .2, .1, h, .95, 80, vec_to_blob(v), pid, "f"))
    for j in range(3):
        i1 = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/m/g{j}.jpg", 1, 1, 100, 100, "t")).lastrowid
        face(i1, a, va)
        face(i1, b, mirrored)                                              # cùng người, nằm nhầm nhóm B
        i2 = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/m/r{j}.jpg", 1, 1, 100, 100, "t")).lastrowid
        face(i2, a, va)
        face(i2, c, vc)                                                    # hai người thật khác nhau
    out = cluster.photo_combos(db)
    assert len(out) == 1 and set(out[0]["persons"]) == {a, c} and out[0]["n"] == 3


def test_pixel_identical_same_size_files_are_deletable(tmp_path, monkeypatch):
    """Cùng dung lượng, từng điểm ảnh giống hệt nhưng khác byte (chỉ khác siêu dữ liệu): được tự xóa; nếu khác dù một điểm ảnh thì giữ."""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    from pp import dup
    db = _db(tmp_path, monkeypatch)
    base = tmp_path / "p"
    base.mkdir()
    img = Image.new("RGB", (40, 30), (10, 20, 30))
    for name, tag in (("k.png", "aaaa"), ("same.png", "bbbb")):
        meta = PngInfo()
        meta.add_text("c", tag)
        img.save(base / name, pnginfo=meta)
    other = img.copy()
    other.putpixel((3, 3), (11, 20, 30))
    meta = PngInfo()
    meta.add_text("c", "cccc")
    other.save(base / "diff.png", pnginfo=meta)
    assert (base / "k.png").stat().st_size == (base / "same.png").stat().st_size
    ids = {}
    for n in ("k", "same", "diff"):
        p = base / f"{n}.png"
        ids[n] = db.x("INSERT INTO images(path,mtime,size,w,h) VALUES(?,?,?,?,?)", (str(p), 1, p.stat().st_size, 40, 30)).lastrowid
    out = dup.exact_items(db, [{"keep": ids["k"], "members": list(ids.values())}])
    assert [i for i, _, _ in out] == [ids["same"]]


def test_pixel_identical_different_size_deletes_lower_quality_copy(tmp_path, monkeypatch):
    """Từng điểm ảnh giống hệt nhưng dung lượng khác: xóa bản thấp (nhỏ) hơn, giữ bản tốt nhất; khác điểm ảnh thì giữ cả hai."""
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    from pp import dup
    db = _db(tmp_path, monkeypatch)
    base = tmp_path / "q"
    base.mkdir()
    img = Image.new("RGB", (40, 30), (10, 20, 30))
    big = PngInfo()
    big.add_text("note", "x" * 500)                                         # bản giữ lại: có thêm dữ liệu nên lớn hơn
    img.save(base / "big.png", pnginfo=big)
    img.save(base / "small.png")
    other = img.copy()
    other.putpixel((1, 1), (200, 20, 30))
    other.save(base / "diff.png")
    ids = {}
    for n in ("big", "small", "diff"):
        p = base / f"{n}.png"
        ids[n] = db.x("INSERT INTO images(path,mtime,size,w,h) VALUES(?,?,?,?,?)", (str(p), 1, p.stat().st_size, 40, 30)).lastrowid
    out = dup.exact_items(db, [{"keep": ids["big"], "members": list(ids.values())}])
    assert [i for i, _, _ in out] == [ids["small"]]


def test_infer_candidates_lists_up_to_three_likely_names(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    pid = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    for j in range(4):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)",
                   (f"zip://C:/x/100_hd Anna Nguyen, Bella Hoang, Cleo Pham, Dana Vu and Eve Lam.zip!/img{j}.jpg", 1, 1, 9, 9, "t")).lastrowid
        db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(_unit_vec(5)), pid))
    assert cluster.infer_candidates(db) == 1
    rows = db.q("SELECT name,score FROM person_candidates WHERE person_id=? ORDER BY score DESC", (pid,))
    assert len(rows) == 3 and all(0 < r["score"] <= 1 for r in rows)                    # 5 tên trong tệp: chỉ giữ 3 tên đứng đầu


def test_assign_images_to_person_moves_faces_or_records_membership(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a = db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    b = db.x("INSERT INTO persons(name) VALUES('B')").lastrowid
    def img(n):
        return db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/z/{n}.jpg", 1, 1, 9, 9, "t")).lastrowid
    def face(iid, pid):
        return db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(_unit_vec(1)), pid)).lastrowid
    one, two, none = img(1), img(2), img(3)
    f1 = face(one, a)
    fa, fb = face(two, a), face(two, b)
    assert cluster.assign_images_to_person(db, [one, two, none], b, from_pid=a) == 3
    assert db.one("SELECT person_id p, locked l FROM faces WHERE id=?", (f1,))["p"] == b          # mặt của người đang xem chuyển sang người đích
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (fa,))["p"] == b and db.one("SELECT person_id p FROM faces WHERE id=?", (fb,))["p"] == b
    assert db.one("SELECT state FROM person_guess WHERE image_id=? AND person_id=?", (none, b))["state"] == 2     # ảnh không thấy mặt: ghi thuộc người đích


def test_removed_by_mistake_can_be_undone_or_readded(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    a = db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", ("/u/1.jpg", 1, 1, 9, 9, "t")).lastrowid
    fid = db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(_unit_vec(2)), a)).lastrowid
    cluster.remove_from_person(db, a, [iid])
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (fid,))["p"] != a                  # đã bị loại
    cluster.restore_to_person(db, [iid], a)                                                       # hoàn tác
    assert db.one("SELECT person_id p, locked l FROM faces WHERE id=?", (fid,)) == {"p": a, "l": 1} or tuple(db.one("SELECT person_id p, locked l FROM faces WHERE id=?", (fid,))) == (a, 1)
    assert not db.one("SELECT 1 FROM face_reject WHERE face_id=?", (fid,))
    cluster.remove_from_person(db, a, [iid])                                                      # loại nhầm lần nữa rồi thêm lại bằng "Thêm vào người…"
    cluster.assign_images_to_person(db, [iid], a)
    assert db.one("SELECT person_id p FROM faces WHERE id=?", (fid,))["p"] == a and not db.one("SELECT 1 FROM face_reject WHERE face_id=?", (fid,))


def test_mashup_counts_real_people_by_faces(tmp_path, monkeypatch):
    """Số người = số khuôn mặt rõ KHÁC NHAU trong ảnh: không phụ thuộc đã vào nhóm người nào, bỏ bóng gương và mặt quá nhỏ."""
    db = _db(tmp_path, monkeypatch)
    rng = np.random.default_rng(9)
    v = [rng.normal(size=128).astype("float32") for _ in range(4)]
    def photo(n, faces):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/m/{n}.jpg", 1, 1, 100, 100, "t")).lastrowid
        for vec, h in faces:
            db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,NULL)", (iid, .1, .1, h, h, .95, 80, vec_to_blob(vec)))
        return iid
    three = photo("three", [(v[0], .2), (v[1], .2), (v[2], .2)])               # 3 người, chưa nhóm vào ai
    mirror = photo("mirror", [(v[0], .2), (v[0] + rng.normal(size=128).astype("float32") * 0.05, .2)])   # 1 người + bóng gương
    poster = photo("poster", [(v[0], .3), (v[1], .05)])                         # mặt thứ hai quá nhỏ: áp phích phía sau
    two = photo("two", [(v[2], .2), (v[3], .2)])
    out = cluster.mashup_by_count(db)
    assert set(out) == {2, 3} and out[3] == [three] and out[2] == [two]
    assert mirror not in sum(out.values(), []) and poster not in sum(out.values(), [])


def test_mashup_fuses_bodies_with_faces(tmp_path, monkeypatch):
    import json
    db = _db(tmp_path, monkeypatch)
    rng = np.random.default_rng(3)
    v = [rng.normal(size=128).astype("float32") for _ in range(3)]
    def photo(n, faces, bodies):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/b/{n}.jpg", 1, 1, 100, 100, "t")).lastrowid
        for vec, x, sc in faces:
            db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,NULL)", (iid, x, .1, .1, .1, sc, 80, vec_to_blob(vec)))
        db.x("INSERT INTO image_body(image_id,n,boxes) VALUES(?,?,?)", (iid, len(bodies), json.dumps(bodies)))
        return iid
    B = lambda x: [x, .05, .3, .8, .9]                                          # người cao 80% ảnh
    back = photo("back", [(v[0], .1, .95)], [B(0.0), B(.5)])                    # 1 mặt + 1 người quay lưng = 2
    mirror = photo("mirror", [(v[0], .1, .95), (v[0], .6, .95)], [B(0.0)])      # bóng gương: mặt thứ hai trùng, chỉ 1 người
    solo = photo("solo", [(v[0], .1, .95)], [B(0.0)])
    far = photo("far", [(v[0], .1, .95), (v[1], .6, .95)], [[0, .05, .05, .1, .9]])   # người quá nhỏ bị bỏ; hai mặt rõ = 2
    out = {i: n for n, ids in cluster.mashup_by_count(db).items() for i in ids}
    assert out == {back: 2, far: 2}
    assert mirror not in out and solo not in out


def test_calibrate_mashup_needs_enough_data(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    assert cluster.calibrate_mashup(db) is None


def test_single_person_photo_keeps_one_name_extra_is_fallback(tmp_path):
    from pp.db import DB
    db = DB(str(tmp_path / "n.db"))
    a = db.x("INSERT INTO persons(name) VALUES('A')").lastrowid
    b = db.x("INSERT INTO persons(name) VALUES('B')").lastrowid
    one = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES('/x/1.jpg',1,1,300,400,'t')").lastrowid
    two = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES('/x/2.jpg',1,1,300,400,'t')").lastrowid
    db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (one, .4, .1, .1, .1, .99, 90, b"", a))
    db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (two, .2, .1, .1, .1, .99, 90, b"", a))
    db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (two, .6, .1, .1, .1, .99, 90, b"", b))
    db.x("INSERT INTO person_guess(image_id,person_id,score,state) VALUES(?,?,1.0,2)", (one, b))      # tên thừa do tệp nén gán
    db.x("INSERT INTO person_guess(image_id,person_id,score,state) VALUES(?,?,1.0,2)", (two, b))      # ảnh hai người: giữ
    assert cluster.demote_extra_names(db) == 1
    assert db.one("SELECT state FROM person_guess WHERE image_id=? AND person_id=?", (one, b))["state"] == 0
    assert db.one("SELECT state FROM person_guess WHERE image_id=? AND person_id=?", (two, b))["state"] == 2
    assert [r["id"] for r in db.person_images(b)] == [two]
    cluster.accept_guesses(db, b, [one])                                                           # người dùng xác nhận tên B: mặt sang B, A thành dự phòng
    assert db.one("SELECT person_id FROM faces WHERE image_id=?", (one,))["person_id"] == b
    assert db.one("SELECT state FROM person_guess WHERE image_id=? AND person_id=?", (one, a))["state"] == 0


def test_reference_images_flag_wrong_name_and_suggest_name(tmp_path):
    import numpy as np
    from pp import refimg
    from pp.db import DB, vec_to_blob
    rng = np.random.default_rng(3)
    db = DB(str(tmp_path / "r.db"))
    def vec(base, noise=0.012):
        v = base + rng.normal(0, noise, 512).astype(np.float32)
        return v / np.linalg.norm(v)
    a_id, b_id = rng.normal(size=512).astype(np.float32), rng.normal(size=512).astype(np.float32)
    a_id /= np.linalg.norm(a_id); b_id /= np.linalg.norm(b_id)
    A = db.x("INSERT INTO persons(name) VALUES('Anna Test')").lastrowid
    B = db.x("INSERT INTO persons(name) VALUES('Bella Test')").lastrowid
    U = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid
    def face(pid, base):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/x/{rng.integers(1e9)}.jpg", 1, 1, 9, 9, "t")).lastrowid
        db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .1, .1, .2, .2, .9, 80, vec_to_blob(vec(base)), pid))
    for _ in range(6):
        face(A, a_id)                  # nhóm tên Anna đúng là mặt Anna
        face(B, a_id)                  # nhóm tên Bella lại là mặt Anna: gán nhầm tên
        face(U, b_id)                  # nhóm chưa tên giống Bella (theo ảnh tham chiếu)
    for pid, base in ((A, a_id), (B, b_id)):
        for _ in range(4):
            db.x("INSERT INTO person_ref(person_id,dim,vec,src) VALUES(?,?,?,?)", (pid, 512, vec_to_blob(vec(base)), "commons"))
    flags, sug = cluster.apply_refs(db)
    assert [r["person_id"] for r in db.q("SELECT person_id FROM ref_flag")] == [B]                 # Bella nghi nhầm tên
    assert db.one("SELECT name FROM person_candidates WHERE person_id=?", (U,))["name"] == "Bella Test"
    assert refimg.consistent([vec(a_id), vec(a_id), vec(b_id)]) == []                                 # chỉ 2/3 khớp nhau: chưa đủ đồng thuận
    assert len(refimg.consistent([vec(a_id) for _ in range(4)] + [vec(b_id)])) == 4                  # bỏ mặt lạc lõng


def test_cover_pool_rounds_star_first(tmp_path, monkeypatch):
    """Ảnh profile làm sẵn theo vòng (mỗi người 1 ảnh trước), ảnh đánh dấu sao được làm trước, chỉ lấy ảnh Naked một người nhìn thẳng."""
    from PIL import Image
    from pp import cover
    db = _db(tmp_path, monkeypatch)
    monkeypatch.setattr(cover, "_pool_dir", lambda: tmp_path)
    jpg = str(tmp_path / "p.jpg")
    Image.new("RGB", (400, 800), (120, 90, 70)).save(jpg)
    lab = db.x("INSERT INTO labels(name) VALUES('Yêu thích')").lastrowid

    def person(name):
        return db.x("INSERT INTO persons(name) VALUES(?)", (name,)).lastrowid

    def photo(pid, nude=True, star=False, faces=1):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (jpg + str(db.one("SELECT COUNT(*) c FROM images")["c"]), 1, 1, 400, 800, jpg)).lastrowid
        fid = db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,?)", (iid, .35, .08, .18, .09, .97, 90, b"", pid)).lastrowid
        for _ in range(faces - 1):
            db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id) VALUES(?,?,?,?,?,?,?,?,NULL)", (iid, .1, .1, .1, .05, .9, 60, b""))
        if nude:
            db.x("INSERT INTO cloth_group(image_id,grp) VALUES(?,?)", (iid, "nude"))
        if star:
            db.x("INSERT INTO label_images(label_id,image_id) VALUES(?,?)", (lab, iid))
        return iid, fid
    a, b = person("A"), person("B")
    _, a_plain = photo(a)
    _, a_star = photo(a, star=True)
    photo(a, nude=False)                      # không phải Naked: bỏ
    photo(a, faces=2)                         # ảnh nhiều người: bỏ
    _, b1 = photo(b)
    cands = db.cover_candidates(a)
    assert [c["fid"] for c in cands] == [a_star, a_plain]
    seen = []
    orig = cover.render_pool_item

    def spy(db_, row, fetch=None):
        seen.append(row["fid"])
        return orig(db_, row, fetch)
    monkeypatch.setattr(cover, "render_pool_item", spy)
    assert cover.ensure_pool(db) == 3
    assert seen[:2] == [a_star, b1] and seen[2] == a_plain                     # vòng 1: mỗi người một ảnh (sao trước); vòng 2: ảnh thứ hai
    assert cover.pooled_bytes(db, a_star)[:2] == b"\xff\xd8"
    assert cover.ensure_pool(db) == 0                                          # đã đủ: không làm lại


def test_confirm_to_person_and_undo(tmp_path, monkeypatch):
    from pp import cluster
    db = _db(tmp_path, monkeypatch)
    a = db.x("INSERT INTO persons(name) VALUES(NULL)").lastrowid          # nhóm chưa đặt tên
    b = db.x("INSERT INTO persons(name) VALUES('Cleo')").lastrowid
    ims, fids = [], []
    for i in range(3):
        iid = db.x("INSERT INTO images(path,mtime,size,w,h,thumb) VALUES(?,?,?,?,?,?)", (f"/c/{i}.jpg", 1, 1, 9, 9, "t")).lastrowid
        fids.append(db.x("INSERT INTO faces(image_id,x,y,w,h,score,px,vec,person_id,locked) VALUES(?,?,?,?,?,?,?,?,?,0)", (iid, .1, .1, .2, .2, .95, 80, b"", a)).lastrowid)
        ims.append(iid)
    rec = cluster.confirm_to_person(db, ims[:2], b, a)
    assert len(rec) == 2
    rows = {r["id"]: (r["person_id"], r["locked"], r["lsrc"]) for r in db.q("SELECT id,person_id,locked,lsrc FROM faces")}
    assert rows[fids[0]] == (b, 1, "user") and rows[fids[2]][0] == a
    cluster.undo_confirm(db, rec)
    rows = {r["id"]: (r["person_id"], r["locked"], r["lsrc"]) for r in db.q("SELECT id,person_id,locked,lsrc FROM faces")}
    assert all(rows[f][0] == a and rows[f][1] == 0 for f in fids)
    cluster.confirm_to_person(db, ims[:1], b, a)
    assert cluster.unconfirm_images(db, ims[:1], b, a) == 1                 # hoàn tác theo ảnh (thao tác từ điện thoại)
    assert db.one("SELECT person_id FROM faces WHERE id=?", (fids[0],))["person_id"] == a

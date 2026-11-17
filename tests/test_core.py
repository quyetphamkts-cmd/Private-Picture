import os
import numpy as np
import pytest
from PIL import Image

from pp import cluster, db as dbm, scan, vault, vi


class FakeFaces:
    def process(self, rgb):
        a = np.asarray(rgb, np.float32).reshape(-1, 3).mean(axis=0)
        v = np.concatenate([a / 255.0, np.ones(125, np.float32) * 0.01])
        v /= np.linalg.norm(v)
        return [{"box": (0.3, 0.3, 0.3, 0.3), "score": 0.95, "px": 80.0, "vec": v.astype(np.float32)}]


class FakeClip:
    def images(self, pils):
        out = []
        for p in pils:
            a = np.asarray(p.convert("RGB"), np.float32).reshape(-1, 3).mean(axis=0) / 255.0
            out.append(np.concatenate([a, np.ones(509) * 0.001]))
        o = np.array(out, np.float32)
        return o / np.linalg.norm(o, axis=1, keepdims=True)


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_HOME", str(tmp_path / "home"))
    pics = tmp_path / "pics"
    pics.mkdir()
    rng = np.random.default_rng(1)
    for i, base in enumerate([(220, 30, 30)] * 3 + [(30, 30, 220)] * 3):
        arr = np.clip(np.array(base) + rng.integers(-8, 8, (240, 320, 3)), 0, 255).astype(np.uint8)
        Image.fromarray(arr).save(pics / f"a{i}.jpg")
    (pics / "bad.jpg").write_bytes(b"not an image")
    from pp import paths
    return pics, dbm.DB(paths.db_path())


def test_scan_and_cluster(lib):
    pics, db = lib
    sc = scan.Scanner(db, FakeFaces(), FakeClip())
    r = sc.run([str(pics)])
    assert r["total"] == 7
    assert db.one("SELECT COUNT(*) c FROM images WHERE err IS NULL")["c"] == 6
    n = cluster.cluster_faces(db)
    assert n == 2
    ps = db.persons()
    assert sorted(p["n"] for p in ps) == [3, 3]
    # đặt tên rồi quét lại: tên được giữ
    cluster.rename_person(db, ps[0]["id"], "An")
    cluster.cluster_faces(db)
    assert db.one("SELECT COUNT(*) c FROM persons WHERE name='An'")["c"] == 1
    assert len(db.persons()) == 2
    # quét lần hai không xử lý lại
    assert sc.run([str(pics)])["total"] == 0


def test_similar_and_rank(lib):
    pics, db = lib
    scan.Scanner(db, FakeFaces(), FakeClip()).run([str(pics)])
    ids, mat = db.clip_matrix()
    g = cluster.group_similar(ids, mat, 0.95)
    assert sorted(len(x) for x in g) == [3, 3]
    q = cluster.prototype(mat[:1])
    top = cluster.rank(ids, mat, q, top=3)
    assert len({i for i, _ in top} & set(g[0]) | {i for i, _ in top} & set(g[1])) == 3


def test_scan_without_models_then_upgrade(lib):
    pics, db = lib
    scan.Scanner(db).run([str(pics)])
    assert db.one("SELECT COUNT(*) c FROM images WHERE ml=0")["c"] == 6
    r = scan.Scanner(db, FakeFaces(), FakeClip()).run([str(pics)])
    assert r["total"] == 6
    assert db.one("SELECT COUNT(*) c FROM images WHERE ml=1 AND clip IS NOT NULL")["c"] == 6


def test_vault_roundtrip(tmp_path):
    src = tmp_path / "x.jpg"
    Image.new("RGB", (100, 60), (1, 2, 3)).save(src)
    v = vault.Vault(tmp_path / "v")
    v.create("secret1")
    iid = v.add(str(src), delete_original=True)
    assert not src.exists()
    raw = open(tmp_path / "v" / (iid + ".enc"), "rb").read()
    assert b"JFIF" not in raw and b"Exif" not in raw
    v.lock()
    v2 = vault.Vault(tmp_path / "v")
    with pytest.raises(vault.WrongPassword):
        v2.unlock("wrong-pass")
    v2.unlock("secret1")
    assert v2.index[0]["name"] == "x.jpg"
    assert Image.open(__import__("io").BytesIO(v2.read(iid))).size == (100, 60)
    assert len(v2.thumb(iid)) > 100
    v2.change_password("secret1", "newpass2")
    v3 = vault.Vault(tmp_path / "v")
    v3.unlock("newpass2")
    assert len(v3.read(iid)) > 100
    v3.remove(iid)
    assert v3.index == []


def test_vi():
    assert "back view" in vi.to_english("ảnh phía sau")
    assert vi.to_english("a red car") == "a red car"

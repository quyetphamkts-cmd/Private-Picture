"""Kiểm thử CLIP thật (cần mạng tải mô hình). Chạy trên CI."""
import numpy as np
import pytest
from PIL import Image


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    import os
    os.environ["PP_HOME"] = str(tmp_path_factory.mktemp("home"))
    from pp import models
    try:
        models.download(models.CLIP_FILES)
    except Exception as e:
        pytest.skip(f"không tải được mô hình CLIP: {e}")
    return models.ClipEngine()


def test_retrieval(clip):
    from skimage import data
    imgs = [Image.fromarray(data.astronaut()), Image.fromarray(data.chelsea()), Image.fromarray(data.coffee())]
    v = clip.images(imgs)
    assert v.shape == (3, 512)
    assert np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-3)
    txt = {k: clip.text(k) for k in ["a photo of an astronaut", "a photo of a cat", "a cup of coffee"]}
    assert np.argmax([v[i] @ txt["a photo of an astronaut"] for i in range(3)]) == 0
    assert np.argmax([v[i] @ txt["a photo of a cat"] for i in range(3)]) == 1
    assert np.argmax([v[i] @ txt["a cup of coffee"] for i in range(3)]) == 2


def test_clothing_zero_shot_sanity(clip):
    """Kiểm tra mức cơ bản với CLIP thật: ảnh không có người phải ra 'không có người', ảnh người mặc kín không bị xếp vào nhóm hở."""
    from skimage import data
    from pp import clothing
    imgs = [Image.fromarray(data.chelsea()), Image.fromarray(data.coffee()), Image.fromarray(data.astronaut())]
    v = clip.images(imgs)
    tv = [clip.text(p) for _, _, ps in clothing.CATS for p in ps]
    best, prob = clothing.classify(v, tv)
    cats = [clothing.CATS[int(b)][0] for b in best]
    msg = str([(c, round(float(p), 2)) for c, p in zip(cats, prob)])
    assert cats[0] == "none" and cats[1] == "none", msg
    assert cats[2] not in ("none", "nude", "swim", "topless"), msg

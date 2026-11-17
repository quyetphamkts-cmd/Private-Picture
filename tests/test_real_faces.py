"""Kiểm thử với mô hình thật (cần mạng để tải mô hình lần đầu)."""
import numpy as np
import pytest
from PIL import Image


@pytest.fixture(scope="module")
def faces(tmp_path_factory):
    import os
    os.environ["PP_HOME"] = str(tmp_path_factory.mktemp("home"))
    from pp import models
    try:
        models.download(models.FACE_FILES)
    except Exception as e:
        pytest.skip(f"không tải được mô hình: {e}")
    eng = models.FaceEngine()
    yield eng
    eng.close()
    import gc
    del eng
    gc.collect()


def test_astronaut(faces):
    from skimage import data
    a = data.astronaut()
    f = faces.process(a)
    assert len(f) == 1 and f[0]["score"] > 0.8
    b = np.asarray(Image.fromarray(a).resize((380, 380)))
    f2 = faces.process(b)
    assert len(f2) == 1
    assert float(f[0]["vec"] @ f2[0]["vec"]) > 0.8
    cat = data.chelsea()
    assert faces.process(cat) == []

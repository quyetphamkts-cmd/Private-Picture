import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def selftest(out, image):
    """Kiểm tra bản đã đóng gói: tải mô hình, nhận diện mặt, CLIP. Ghi kết quả ra tệp."""
    lines = []
    try:
        import numpy as np
        from PIL import Image
        from pp import models
        models.download(models.FACE_FILES + models.CLIP_FILES)
        im = Image.open(image).convert("RGB")
        f = models.FaceEngine().process(np.asarray(im))
        lines.append(f"faces={len(f)}")
        c = models.ClipEngine()
        v = c.images([im])[0]
        t1, t2 = c.text("a photo of an astronaut"), c.text("a photo of a cat")
        lines.append(f"clip_astronaut={float(v @ t1):.3f} clip_cat={float(v @ t2):.3f}")
        import tempfile
        d = tempfile.mkdtemp()
        import subprocess
        from pp import zipimg
        a7 = os.path.join(d, "a.7z")
        subprocess.run([zipimg._exe(), "a", a7, image], check=True, stdout=subprocess.DEVNULL)
        ents = zipimg.entries(a7)
        z7 = len(zipimg.read(zipimg.make(a7, ents[0][0]))) > 1000
        lines.append(f"7zip={z7}")
        ok = len(f) == 1 and float(v @ t1) > float(v @ t2) and z7
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        from pp.ui.main import MainWindow
        MainWindow()
        lines.append("gui=ok")
        lines.append("OK" if ok else "FAIL")
    except Exception as e:  # noqa
        import traceback
        lines.append("ERROR " + traceback.format_exc())
    open(out, "w", encoding="utf-8").write("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3])
    else:
        from pp.ui.main import run
        run()

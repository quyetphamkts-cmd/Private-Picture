"""Tải mô hình (lần đầu) và các bộ nhận diện mặt, hiểu nội dung ảnh (CLIP). Chạy hoàn toàn trên máy."""
import os
import urllib.request
import numpy as np
from PIL import Image

from . import paths

ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"  # Git LFS
HF = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/"
FILES = {
    "yunet.onnx": ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx",
    "clip_vision.onnx": [HF + "onnx/vision_model_quantized.onnx", HF + "onnx/vision_model.onnx"],
    "clip_text.onnx": [HF + "onnx/text_model_quantized.onnx", HF + "onnx/text_model.onnx"],
    "clip_tokenizer.json": HF + "tokenizer.json",
}
GH_BUFFALO = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
FILES["arcface.onnx"] = ["https://huggingface.co/immich-app/buffalo_l/resolve/main/recognition/model.onnx",
                         {"zip": GH_BUFFALO, "member": "w600k_r50.onnx"}]       # ArcFace ResNet50 (WebFace600K), 512 chiều
FACE_FILES = ["yunet.onnx", "arcface.onnx"]
LEGACY_FACE_FILES = ["yunet.onnx", "sface.onnx"]
CLIP_FILES = ["clip_vision.onnx", "clip_text.onnx", "clip_tokenizer.json"]


def model_path(name):
    return paths.models_dir() / name


def have(names):
    return all(model_path(n).exists() and model_path(n).stat().st_size > 1000 for n in names)


def face_model():
    """Mô hình nhận dạng mặt đang dùng: ArcFace (chính xác hơn) nếu đã tải, không thì SFace cũ, không có thì None."""
    if have(["yunet.onnx", "arcface.onnx"]):
        return "arcface"
    if have(["yunet.onnx", "sface.onnx"]):
        return "sface"
    return None


def ready():
    return face_model() is not None and have(CLIP_FILES)


def _fetch(url, tmp, name, progress, cancel):
    req = urllib.request.Request(url, headers={"User-Agent": "PrivatePicture/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel():
                raise RuntimeError("Đã hủy tải")
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(name, done, total)


def download(names, progress=None, cancel=lambda: False):
    """progress(tên_file, đã_tải, tổng). Ném lỗi nếu mạng hỏng."""
    for n in names:
        dst = model_path(n)
        if dst.exists() and dst.stat().st_size > 1000:
            continue
        tmp = dst.with_suffix(dst.suffix + ".part")
        urls = FILES[n] if isinstance(FILES[n], list) else [FILES[n]]
        last = None
        for u in urls:
            try:
                if isinstance(u, dict):                       # tải gói zip rồi lấy đúng một tệp bên trong
                    import zipfile
                    zp = tmp.with_suffix(".zip.part")
                    try:
                        _fetch(u["zip"], zp, n, progress, cancel)
                        with zipfile.ZipFile(zp) as z, open(tmp, "wb") as f:
                            f.write(z.read(u["member"]))
                    finally:
                        if zp.exists():
                            zp.unlink()
                else:
                    _fetch(u, tmp, n, progress, cancel)
                if tmp.stat().st_size < 10000 and n.endswith(".onnx"):
                    raise RuntimeError(f"Tệp {n} tải về không hợp lệ")
                os.replace(tmp, dst)
                last = None
                break
            except Exception as e:
                last = e
                if tmp.exists():
                    tmp.unlink()
        if last is not None:
            raise last


ARC_TEMPLATE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]], np.float32)


class FaceEngine:
    """Phát hiện mặt (YuNet, kèm 5 điểm mốc) và tạo vectơ đặc trưng: ArcFace ResNet50 (512 chiều, chính xác cao) nếu đã tải,
    không thì SFace (128 chiều). Không dùng chung giữa nhiều luồng."""

    def __init__(self, threads=None):
        import cv2
        self.cv2 = cv2
        self.threads = threads or max(1, (os.cpu_count() or 2) // 2)
        self.det = cv2.FaceDetectorYN.create(str(model_path("yunet.onnx")), "", (320, 320), 0.8, 0.3, 5000)
        self.name = face_model() or "sface"
        if self.name == "arcface":
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = self.threads
            self.arc = ort.InferenceSession(str(model_path("arcface.onnx")), so, providers=["CPUExecutionProvider"])
            self.arc_in = self.arc.get_inputs()[0].name
            self.rec = None
        else:
            self.rec = cv2.FaceRecognizerSF.create(str(model_path("sface.onnx")), "")
        self.dim = 512 if self.name == "arcface" else 128

    def close(self):
        """Giải phóng phiên ONNX trước khi thoát (tránh lỗi khi dọn dẹp lúc kết thúc tiến trình)."""
        self.arc = None
        self.rec = None
        self.det = None

    def _arc_feature(self, rgb, f):
        cv2 = self.cv2
        pts = np.asarray(f[4:14], np.float32).reshape(5, 2)
        m, _ = cv2.estimateAffinePartial2D(pts, ARC_TEMPLATE, method=cv2.LMEDS)
        if m is None:
            raise ValueError("không căn chỉnh được khuôn mặt")
        crop = cv2.warpAffine(rgb, m, (112, 112), borderValue=0)
        vs = []
        for img in (crop, crop[:, ::-1]):                                      # ảnh và bản lật ngang: lấy trung bình cho ổn định
            blob = ((np.ascontiguousarray(img).astype(np.float32) - 127.5) / 127.5).transpose(2, 0, 1)[None]
            o = self.arc.run(None, {self.arc_in: blob})[0][0]
            vs.append(o / max(float(np.linalg.norm(o)), 1e-9))
        return np.mean(vs, axis=0).astype(np.float32)

    def process(self, rgb: np.ndarray):
        cv2 = self.cv2
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        self.det.setInputSize((w, h))
        _, faces = self.det.detect(bgr)
        out = []
        if faces is None:
            return out
        for f in faces:
            try:
                if self.name == "arcface":
                    v = self._arc_feature(rgb, f)
                else:
                    aligned = self.rec.alignCrop(bgr, f)
                    v = self.rec.feature(aligned).flatten().astype(np.float32)
            except Exception:
                continue
            n = float(np.linalg.norm(v))
            if n > 0:
                v /= n
            x, y, fw, fh = [float(t) for t in f[:4]]
            out.append({"box": (x / w, y / h, fw / w, fh / h), "score": float(f[14]),
                        "px": min(fw, fh), "vec": v})
        return out


class ClipEngine:
    """Hiểu nội dung ảnh và chữ (tiếng Anh) bằng CLIP ViT-B/32 chạy qua ONNX Runtime."""
    MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
    STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)

    def __init__(self, threads=None):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads or max(1, (os.cpu_count() or 2) // 2)
        prov = ["CPUExecutionProvider"]
        self.v = ort.InferenceSession(str(model_path("clip_vision.onnx")), so, providers=prov)
        self.t = ort.InferenceSession(str(model_path("clip_text.onnx")), so, providers=prov)
        self.tok = Tokenizer.from_file(str(model_path("clip_tokenizer.json")))
        self.tok.enable_truncation(max_length=77)
        self.tok.enable_padding(length=77, pad_id=49407, pad_token="<|endoftext|>")
        self.v_in = self.v.get_inputs()[0].name

    @staticmethod
    def _pick(outs, names):
        for n, o in zip(names, outs):
            if "embeds" in n and o.ndim == 2:
                return o
        for o in outs:
            if o.ndim == 2:
                return o
        raise RuntimeError("Không tìm thấy vector đặc trưng trong mô hình")

    def prep(self, im: Image.Image) -> np.ndarray:
        im = im.convert("RGB")
        w, h = im.size
        s = 224 / min(w, h)
        im = im.resize((max(224, round(w * s)), max(224, round(h * s))), Image.BICUBIC)
        w, h = im.size
        l, t = (w - 224) // 2, (h - 224) // 2
        a = np.asarray(im.crop((l, t, l + 224, t + 224)), np.float32) / 255.0
        return ((a - self.MEAN) / self.STD).transpose(2, 0, 1)

    @staticmethod
    def _norm(x):
        x = x.astype(np.float32)
        return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)

    def images(self, pils):
        x = np.stack([self.prep(p) for p in pils]).astype(np.float32)
        names = [o.name for o in self.v.get_outputs()]
        return self._norm(self._pick(self.v.run(None, {self.v_in: x}), names))

    def text(self, s: str):
        e = self.tok.encode(s)
        ids = np.array([e.ids], np.int64)
        feed = {}
        for i in self.t.get_inputs():
            feed[i.name] = ids if "input_ids" in i.name else np.array([e.attention_mask], np.int64)
        names = [o.name for o in self.t.get_outputs()]
        return self._norm(self._pick(self.t.run(None, feed), names))[0]

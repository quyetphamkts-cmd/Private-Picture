"""Từ điển nhỏ Việt -> Anh để tìm ảnh bằng tiếng Việt (CLIP chỉ hiểu tiếng Anh)."""
import unicodedata


def _n(s):
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


WORDS = {
    "phia truoc": "front view", "mat truoc": "front view", "chinh dien": "front view",
    "phia sau": "back view, seen from behind", "mat sau": "back view", "ben hong": "side view",
    "ben canh": "side view", "nghieng": "side view", "tren cao": "view from above",
    "dau": "head", "mat": "face", "co": "neck", "vai": "shoulder", "nguc": "chest", "bung": "belly",
    "than": "torso, body", "lung": "back", "tay": "arm and hand", "ban tay": "hand", "chan": "legs and feet",
    "ban chan": "foot", "toc": "hair", "mat nguoi": "face portrait",
    "toan than": "full body", "can canh": "close-up", "toan canh": "wide shot", "chan dung": "portrait",
    "nguoi": "person", "dan ong": "man", "phu nu": "woman", "tre em": "child", "em be": "baby",
    "gia dinh": "family", "dong vat": "animal", "con cho": "dog", "con meo": "cat", "chim": "bird",
    "bien": "beach, sea", "nui": "mountain", "cay": "tree", "hoa": "flower", "thanh pho": "city",
    "nha": "house", "noi that": "interior of a room", "phong khach": "living room", "bep": "kitchen",
    "phong ngu": "bedroom", "xe": "car", "do an": "food", "ban an": "dining table", "hoang hon": "sunset",
    "dem": "night", "ngoai troi": "outdoors", "tuong": "statue", "dieu khac": "sculpture", "gom": "ceramic pottery",
    "chai": "bottle", "binh": "vase", "phu dieu": "relief carving", "ban ve": "drawing, blueprint",
}


# Từ khóa xoay quanh CON NGƯỜI để bấm chọn khi tìm: nhóm -> [(chữ hiện trên nút, mô tả tiếng Anh cho bộ nhận dạng ảnh)]
CATALOG = {
    "Tư thế": [("đứng", "standing"), ("ngồi", "sitting"), ("nằm", "lying down"), ("quỳ", "kneeling"), ("ngồi xổm", "squatting"),
               ("cúi người", "bending over"), ("nghiêng người", "leaning to the side"), ("tựa tường", "leaning against a wall"),
               ("nằm sấp", "lying on stomach"), ("nằm ngửa", "lying on back"), ("giơ tay", "arms raised"), ("khoanh tay", "arms crossed"),
               ("chống nạnh", "hands on hips"), ("bắt chéo chân", "legs crossed"), ("đi bộ", "walking"), ("chạy", "running"),
               ("nhảy", "jumping"), ("vươn vai", "stretching"), ("quay lưng", "back turned to the camera"), ("nhìn thẳng", "looking at the camera")],
    "Dáng người": [("mảnh mai", "slim slender body"), ("cao", "tall"), ("nhỏ nhắn", "petite"), ("đầy đặn", "curvy full figure"),
                   ("săn chắc", "toned fit body"), ("thể thao", "athletic body"), ("đường cong", "curvy silhouette")],
    "Bộ phận": [("khuôn mặt", "face close-up"), ("mắt", "eyes"), ("môi", "lips"), ("tóc", "hair"), ("cổ", "neck"), ("vai", "shoulders"),
                ("xương quai xanh", "collarbone"), ("ngực", "chest"), ("lưng", "back"), ("eo", "waist"), ("bụng", "belly abdomen"),
                ("hông", "hips"), ("mông", "buttocks"), ("đùi", "thighs"), ("chân", "legs"), ("bàn chân", "feet"), ("bàn tay", "hands"), ("cánh tay", "arms")],
    "Trang phục": [("váy", "wearing a skirt or dress"), ("đầm dạ hội", "evening gown"), ("áo dài", "ao dai traditional dress"),
                   ("áo thun", "t-shirt"), ("quần jeans", "jeans"), ("áo khoác", "jacket coat"), ("vest", "suit blazer"),
                   ("đồ thể thao", "sportswear activewear"), ("bikini", "bikini swimsuit"), ("đồ bơi", "swimwear"),
                   ("đồ ngủ", "pajamas sleepwear"), ("đồ lót", "lingerie underwear"), ("áo tắm", "bathrobe towel"),
                   ("giày cao gót", "high heels"), ("tất", "stockings socks"), ("kính", "glasses sunglasses"), ("mũ", "hat cap"), ("không mặc gì", "nude")],
    "Góc chụp": [("toàn thân", "full body shot"), ("nửa người", "upper body shot, waist up"), ("cận mặt", "face close-up portrait"),
                 ("từ phía sau", "view from behind"), ("nhìn nghiêng", "side profile"), ("từ trên cao", "high angle shot from above"),
                 ("từ dưới lên", "low angle shot from below"), ("soi gương", "mirror selfie"), ("selfie", "selfie")],
    "Bối cảnh": [("studio", "photo studio"), ("ngoài trời", "outdoors"), ("bãi biển", "beach"), ("hồ bơi", "swimming pool"),
                 ("phòng ngủ", "bedroom"), ("bồn tắm", "bathtub"), ("trên giường", "on a bed"), ("ghế sofa", "on a sofa"), ("cửa sổ", "by a window")],
}
_CAT_MAP = {_n(vi): en for items in CATALOG.values() for vi, en in items}


def phrases(text: str):
    """Tách ô tìm thành các từ khóa (ngăn bằng dấu phẩy, chấm phẩy hoặc dấu +) rồi đổi mỗi từ khóa sang mô tả tiếng Anh:
    từ khóa có trong bảng người thì dùng mô tả của bảng, còn lại dịch theo từ điển hoặc giữ nguyên (gõ thẳng tiếng Anh được)."""
    import re
    out = []
    for chunk in re.split(r"[,;+]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        out.append(_CAT_MAP.get(_n(chunk)) or to_english(chunk))
    return out


def prompts_for(text: str):
    """Các câu mô tả đưa cho bộ nhận dạng ảnh (lấy trung bình vector để kết quả ổn định hơn): ưu tiên ảnh CHỤP NGƯỜI có các đặc điểm đã gõ."""
    ph = phrases(text)
    if not ph:
        return []
    body = ", ".join(ph)
    return [f"a photo of a person, {body}", f"a photograph of a woman, {body}", body]


def to_english(text: str) -> str:
    """Dịch các cụm đã biết, giữ nguyên phần còn lại (người dùng có thể gõ thẳng tiếng Anh)."""
    t = _n(text).strip()
    out = t
    for k in sorted(WORDS, key=len, reverse=True):
        if k in out:
            out = out.replace(k, WORDS[k])
    return out if out != t else text

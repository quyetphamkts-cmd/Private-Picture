# Định dạng đồng bộ Private Picture (v1)

Thư mục `PrivatePicture-Sync/` trong Google Drive. Mọi tệp `.pe` (trừ `sync.json`) là dữ liệu mã hóa.

## Mã hóa
- Khóa: `scrypt(mật_khẩu_đồng_bộ UTF-8, salt, N=32768, r=8, p=1, dklen=32)`; `salt` (16 byte) nằm trong `sync.json`.
- Mỗi tệp `.pe`: `b"PPE1" + nonce(12 byte) + AES-256-GCM(ciphertext + tag 16 byte)`, không có dữ liệu xác thực bổ sung (AAD rỗng).

## Tệp
- `sync.json` (không mã hóa): `{"v":1,"kdf":"scrypt","n":32768,"r":8,"p":1,"salt":"<base64>","check":"<base64 của seal(key, b'PPSYNC1')>"}`.
  Điện thoại giải mã `check`; ra `PPSYNC1` là mật khẩu đúng.
- `index.pe`: JSON UTF-8 (sau giải mã):
  - `images`: `[{uid, name, taken, w, h, size, orig}]` (`orig` là true nếu có ảnh gốc trong `orig/`)
  - `persons`: `[{id, name, n}]`, `image_person`: `[[uid, person_id]]`
  - `labels`: `[{id, name}]`, `label_images`: `[[uid, label_id]]`
  - `combos`: `[{names:[tên], uids:[uid]}]` (ảnh chụp chung từ 2 người đã đặt tên trở lên, gom theo tổ hợp người)
  - `covers`: `{person_id: chữ ký}`; ảnh profile đã cắt sẵn (JPEG mã hóa) nằm ở `covers/<person_id>-<chữ ký>.pe`, PC chọn tự động (không chọn tay), điện thoại chỉ tải về dùng
- `thumbs/<uid>.pe`: ảnh nhỏ (JPEG/WebP) đã mã hóa. `orig/<uid>.pe`: ảnh gốc đã mã hóa.
- `inbox/<thiết_bị>-<thời_gian>-<mã>.pe`: thay đổi từ điện thoại gửi lên, JSON `{"device":"...","ops":[...]}`:
  - `{"op":"rename_person","person_id":3,"name":"Tên"}`
  - `{"op":"label_add","image_uid":"...","name":"Yêu thích"}` và `label_remove` tương tự.
  PC áp dụng rồi xóa tệp.

PC là nguồn chính: thư viện luôn được PC ghi lại; điện thoại chỉ đọc và gửi thay đổi qua `inbox/`.

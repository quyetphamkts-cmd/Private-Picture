# Private Picture

Phần mềm xem ảnh cá nhân trên Windows. Chạy hoàn toàn trên máy bạn, **không gửi ảnh đi đâu**.

## Tính năng
- **Lưới ảnh giữ đúng tỉ lệ gốc** (xếp hàng đều, không cắt, không méo); rê chuột hiện ngày và tên tệp; bộ lọc dạng viên thuốc theo Năm, Người, Nhãn. Hỗ trợ JPG, PNG, WEBP, HEIC (ảnh iPhone)…
- **Xem ảnh dạng lớp phủ** nền nâu đen mờ: ảnh giữ kích thước gốc, **thu phóng** bằng cuộn chuột hoặc **nhấn giữ chuột trái rồi kéo lên/xuống** (điểm đang bấm giữ nguyên tại chỗ; kéo lên phóng to, kéo xuống thu nhỏ), nút +/−, phím `+` `-`; `0` vừa khung, `1` kích thước 100%; nhấp đúp để chuyển vừa khung/100%; **di chuyển ảnh** bằng kéo chuột phải, chuột giữa hoặc giữ `Space` rồi kéo (hoặc bấm nút *Kéo: thu phóng* để đổi chuột trái thành di chuyển); `←` `→` chuyển ảnh, dải ảnh nhỏ phía dưới; `Esc` hoặc bấm ra ngoài để đóng.
- **Người:** tự nhận diện khuôn mặt và gom thành từng nhóm; bạn đặt tên, gộp, sửa nhóm nhầm.
- **Ảnh tương tự:** gom ảnh cùng cảnh, cùng góc nhìn, ảnh chụp liên tiếp.
- **Tìm kiếm theo nội dung:** gõ “phía sau”, “bàn chân”, “biển”… (tiếng Việt hoặc tiếng Anh).
- **Nhãn:** tự tạo nhãn như “phía trước”, “phía sau”, “tay”, “chân”; chọn vài ảnh mẫu rồi để ứng dụng gợi ý các ảnh giống.
- **Mã hóa theo từng thư mục** (xem bên dưới).

## Bảo mật: bật/tắt tùy bạn
Lần đầu mở, bạn chọn hai công tắc độc lập (đổi lại được sau trong *Cài đặt → Tài khoản và dữ liệu* → **Thay đổi bảo mật…**):

| Mã hóa dữ liệu | Mật khẩu | Kết quả |
|---|---|---|
| Bật | Bật | Dữ liệu mã hóa AES-256, nhập mật khẩu mỗi lần mở (khuyên dùng khi dùng chung máy). |
| Bật | Tắt | Mở thẳng, không hỏi gì. Khóa mã hóa gắn với **tài khoản Windows** của bạn: người dùng tài khoản khác hoặc lấy ổ cứng đi không đọc được. |
| Tắt | Bật | Chỉ khóa ứng dụng bằng mật khẩu; dữ liệu không mã hóa. |
| Tắt | Tắt | Mở thẳng, không bảo vệ gì. |

- **Dữ liệu được mã hóa** gồm: danh mục ảnh, tên người, nhãn, ảnh thu nhỏ, khuôn mặt và Kho mã hóa.
- **Mức theo từng thư mục** (chỉ khi bật mã hóa): *Giữ ảnh gốc tại chỗ* (mở được bằng mọi phần mềm khác) hoặc *Mã hóa cả ảnh gốc* (nhập vào kho, có thể xóa ảnh gốc sau khi nhập). Nâng thư mục từ mức 1 lên mức 2 bất cứ lúc nào; chiều ngược lại thì xuất ảnh ra (chuột phải ảnh đã mã hóa → *Xuất ảnh giải mã ra thư mục…*).
- Chuột phải một ảnh bất kỳ → *Mã hóa và chuyển vào kho…* để mã hóa riêng từng ảnh.
- **Tự khóa** sau 10 phút không thao tác và nút *Khóa ứng dụng* (khi bật mật khẩu).
- **Tắt mã hóa** cần Kho mã hóa trống (xuất ảnh ra trước); các thư mục mức “mã hóa cả ảnh gốc” sẽ chuyển về “giữ ảnh gốc tại chỗ”.

## Cài đặt (không cần biết lập trình)
1. Vào trang **Releases** của repo này, mục **Bản mới nhất**, tải file `PrivatePicture-Windows.zip`.
2. Giải nén ra một thư mục bất kỳ (ví dụ `D:\PrivatePicture`).
3. Mở `PrivatePicture.exe`. Nếu Windows hiện cảnh báo “Windows protected your PC”, chọn **More info** rồi **Run anyway** (ứng dụng chưa được ký số).
4. Lần đầu mở, đặt mật khẩu chính.
5. Vào **Cài đặt → Thư mục và quét** → **Thêm thư mục…**, chọn thư mục ảnh và mức mã hóa → bấm **Quét ảnh**. Lần quét đầu tiên ứng dụng tự tải mô hình nhận diện (một lần, cần mạng); sau đó chạy offline.
   Lần đầu cần mạng để tải mô hình (khoảng 150 MB). Sau đó chạy offline.

## Tự cập nhật
Repo này riêng tư nên ứng dụng cần một **mã truy cập chỉ-đọc** để tải bản mới. Tạo một lần:
1. GitHub → ảnh đại diện → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Token name: `PrivatePicture`. Expiration: 1 năm.
3. Repository access: **Only select repositories** → chọn `Private-Picture`.
4. Permissions → Repository permissions → **Contents: Read-only** (các quyền khác để *No access*).
5. **Generate token**, sao chép mã (bắt đầu bằng `github_pat_`).
6. Trong ứng dụng: *Cài đặt → Tài khoản và dữ liệu* → **Mã truy cập cập nhật…** → dán mã.

Từ đó ứng dụng tự kiểm tra khi mở (có thể tắt) hoặc bấm **Kiểm tra cập nhật**. Khi có bản mới, ứng dụng hỏi, tải, tự đóng, chép đè rồi mở lại; mật khẩu và dữ liệu giữ nguyên. Hãy đặt ứng dụng ở thư mục bạn có quyền ghi (ví dụ `D:\PrivatePicture`, không đặt trong `Program Files`). Mã chỉ lưu mã hóa trong ứng dụng và chỉ có quyền đọc.

## Lưu ý quyền riêng tư
- **Khóa khôi phục:** khi bật mã hóa hoặc mật khẩu, ứng dụng hiện một khóa khôi phục (chỉ hiện một lần). Hãy chép ra giấy hoặc lưu ở nơi an toàn. Quên mật khẩu (hoặc mất tài khoản Windows khi dùng chế độ không mật khẩu) thì nhập khóa này (“Quên mật khẩu?”) để mở lại. Mất cả hai thì không thể lấy lại dữ liệu và ảnh đã mã hóa.
- Thẻ *Tài khoản và dữ liệu* trong Cài đặt có: đổi mật khẩu, tạo khóa khôi phục mới (khóa cũ hết hiệu lực), sao lưu dữ liệu ra tệp zip.
- Ảnh ở thư mục mức “giữ ảnh gốc” **không được mã hóa** (đó là tệp thường của Windows); chỉ dữ liệu phân tích của ứng dụng được mã hóa.
- “Xóa ảnh gốc sau khi mã hóa” là xóa vĩnh viễn, không qua Thùng rác. Trên ổ SSD, việc xóa không đảm bảo xóa sạch hoàn toàn dấu vết. Hãy xuất thử vài ảnh ra để chắc chắn mọi thứ hoạt động trước khi bật xóa ảnh gốc cho thư mục lớn.
- Khi ứng dụng đang mở, dữ liệu được giải mã trong bộ nhớ. Ứng dụng không bảo vệ trước phần mềm độc hại đang chạy trên máy bạn.
- Nhận diện khuôn mặt không phải lúc nào cũng đúng (mặt nhỏ, ngược sáng, che khuất). Hãy sửa tay các nhóm nhầm.
- Dữ liệu nằm trong `%LOCALAPPDATA%\PrivatePicture`. Sao lưu thư mục này (cùng mật khẩu) nếu bạn dùng mức “mã hóa cả ảnh gốc” và đã xóa ảnh gốc.

## Dành cho người phát triển
```
pip install -r requirements.txt pytest scikit-image
python -m pytest tests
python main.py
```
Mỗi lần đẩy code lên nhánh `main`, GitHub Actions tự kiểm thử, dựng `.exe` và đăng lên Releases.

## Tự cập nhật, sao lưu, file nén (bản mới)

- **Tự cập nhật theo thư mục**: ứng dụng theo dõi các thư mục đã thêm; khi bạn thêm, xóa, đổi ảnh trong Windows, thư viện tự quét lại sau vài giây (không tải mô hình, không xóa ảnh gốc). Thư mục mức "Mã hóa tất cả + xóa ảnh gốc" không tự quét, chỉ báo để bạn bấm quét.
- **Sao lưu**: Cài đặt > Sao lưu. Chọn một thư mục (ví dụ thư mục Google Drive for Desktop) để lưu file zip sao lưu, tự xoay vòng giữ các bản mới nhất. Khóa API và token cập nhật không nằm trong bản sao lưu. Chưa tải trực tiếp lên Drive bằng API.
- **Ảnh trong file .zip**: được quét như ảnh thường, kể cả zip đặt mật khẩu (ZipCrypto/AES). Zip có mật khẩu sẽ báo, bấm "Nhập mật khẩu file nén…". Chưa hỗ trợ RAR/7z.
- **Người**: mặt giống nhau tự gom nhóm sau mỗi lần quét và khi mở trang Người; nhóm chỉ 1 ảnh được ẩn mặc định.
- **Giao diện sổ danh bạ**: thanh bên chỉ có hai mục là Người và Tất cả; các chức năng khác (Nhãn, Ảnh tương tự, Ảnh trùng lặp, Tìm kiếm, Kho mã hóa, Cài đặt, Tài khoản) nằm trong nút Công cụ.
- Mục lọc "Tất cả (N)" ở Tất cả hiện tổng số ảnh.
- **Xem ảnh kiểu Google Ảnh**: bấm chuột trái một lần vào ảnh để mở toàn màn hình (Ctrl/Shift + bấm để chọn nhiều ảnh); dải ảnh nhỏ đã ẩn; thanh công cụ tự ẩn khi không di chuột; ảnh kế bên được nạp trước nên chuyển ảnh tức thì; thư viện tự cuộn tới ảnh đang xem. Hai nút hình chuột: chuột trái kéo để thu phóng, chuột phải kéo để di chuyển (bấm nút chuột phải để chuột trái cũng di chuyển được, dành cho bàn di chuột); nút khung là "vừa khung", 1:1 là kích thước gốc.
- Cuộn thư viện mượt hơn: cuộn có hiệu ứng, ảnh nhỏ nạp nền, vẽ nhanh khi đang cuộn.
- **Xem ảnh**: dải ảnh nhỏ phía dưới như cũ; nút toàn màn hình (hoặc F11) ẩn dải ảnh và thanh công cụ tự ẩn; Esc thoát toàn màn hình trước, bấm lần nữa mới đóng.
- **Ảnh chụp người nhưng không thấy mặt**: sau khi gom mặt, ứng dụng so sánh ảnh không có mặt với ảnh đã biết của từng người theo bối cảnh, ánh sáng, trang phục (CLIP), màu, độ sáng, độ nét và ngày giờ chụp, rồi gợi ý trong trang của người đó. Bạn xác nhận hoặc loại từng ảnh (chuột phải) hoặc "Thêm tất cả"; ảnh đã xác nhận được tính vào nhóm, ảnh đã loại không gợi ý lại. Đây là gợi ý theo suy đoán, không tự gom bừa.
- **Xem ảnh giống Google Ảnh**: cuộn chuột giữa để thu phóng tại vị trí con trỏ; nhấn giữ chuột trái và kéo để di chuyển; khi đang phóng to có bản đồ nhỏ góc trên bên phải (bấm để nhảy tới vùng khác); nút thông tin (I) hiện tên, ngày chụp, kích thước, thư mục, người, nhãn; nút ngôi sao thêm vào nhãn "Yêu thích"; nút trình chiếu tự chuyển ảnh mỗi 4 giây.
- **Đặt tên người**: bấm chuột phải vào nhóm trong trang Người, chọn "Đặt tên…".

## Đồng bộ với điện thoại Android (qua Google Drive)

- PC: **Thư mục và quét → Đồng bộ điện thoại…** chọn thư mục trong ổ Google Drive (Drive for Desktop), đặt mật khẩu đồng bộ, bấm Đồng bộ. Mọi thứ (ảnh nhỏ, ảnh gốc, danh mục) được mã hóa AES-256-GCM trước khi lên Drive. Định dạng: `docs/SYNC_FORMAT.md`.
- Android: cài APK ở mục Releases (`android-latest`), đăng nhập Google và nhập mật khẩu đồng bộ. Xem ảnh, nhóm người, nhãn, tìm kiếm; đặt tên người và đánh dấu yêu thích được gửi về PC qua thư mục `inbox`.
- Cần tạo OAuth client Android một lần trong Google Cloud Console (tên gói `vn.pp.photos`, SHA-1 của khóa ký trong `android/app/pp.keystore`).
- **File nén**: quét ảnh trong ZIP (kể cả mã hóa AES), RAR, 7z, TAR/TGZ/TBZ2/TXZ, CAB, ISO và các định dạng 7-Zip đọc được, kể cả file có mật khẩu (cả loại mã hóa tên tệp). RAR nhiều tập (`.part1.rar`...) chỉ cần để đủ các tập cạnh nhau. Bản Windows kèm sẵn 7-Zip (giấy phép LGPL) để đọc các định dạng này. RAR nén "solid" đọc từng ảnh sẽ chậm hơn.
- **Chọn ảnh như Google Ảnh**: rê chuột vào ảnh sẽ hiện vòng tròn ở góc trên trái; bấm vòng tròn để chọn, khi đã chọn thì bấm vào ảnh nào cũng là chọn/bỏ chọn (không mở). Có thanh "Chọn tất cả / Bỏ chọn". Ở trang Nhãn, sau khi bấm "Gợi ý ảnh giống", chọn các ảnh đúng rồi bấm "Thêm N ảnh đã chọn vào nhãn"; danh sách gợi ý tự cập nhật.
- **Người và Ảnh tương tự**: bấm một lần vào nhóm là mở. Ảnh trong cùng một file nén được coi là gợi ý mạnh cho cùng một người hoặc nhóm người khi đoán ảnh không thấy mặt.
- **Ảnh trùng lặp**: mục "Ảnh trùng lặp" tự tìm ảnh giống nhau (so nội dung bằng CLIP, dấu vân tay hình và màu trung bình), giữ bản độ phân giải cao nhất và ẩn các bản thừa khỏi thư viện (tick "Hiện cả ảnh trùng" để xem lại, "Bỏ ẩn" để khôi phục). Mặc định tự ẩn sau mỗi lần quét. Nút **Xóa bản độ phân giải thấp…** chuyển vào Thùng rác của Windows các bản trùng chắc chắn (mức giống chặt hơn khi chỉ ẩn), có hộp thoại xác nhận; không bao giờ xóa bản có độ phân giải cao hơn, ảnh trong file nén hay Kho mã hóa.
- **Ảnh trùng lặp (danh sách đối chiếu)**: mỗi cụm trùng là một khung với ảnh xem trước lớn; ảnh có độ phân giải cao nhất viền xanh (giữ lại), các bản còn lại viền đỏ (sẽ xóa). "Không trùng, loại khỏi cụm" loại ảnh sai khỏi danh sách (không bị gom lại lần sau); kiểm tra xong bấm "Xác nhận xóa bản thừa" để chuyển các tệp thừa trong thư mục gốc vào Thùng rác. Ảnh trong file nén hoặc Kho mã hóa không xóa được từ đây.
- **Gom người chính xác hơn**: liên kết trung bình (không "bắc cầu" nối hai người), kết hợp màu da và màu tóc, hai mặt trong cùng một ảnh luôn là hai người khác nhau, mặt mờ chỉ được gán khi rất chắc, người đã đặt tên không bao giờ bị gộp. Mắt và dáng người chưa dùng vì ảnh thường quá nhỏ và chưa có mô hình phù hợp.
- **Trang riêng**: "Tài khoản và cài đặt" (bảo mật, sao lưu, đồng bộ điện thoại, cập nhật, khóa API) tách khỏi "Thư mục và quét".
- **Đồng bộ chỉnh sửa hai chiều (bên nào sửa sau cùng thì thắng)**: nhãn (thêm, bỏ, đổi, đổi tên, xóa nhãn, yêu thích) và người (đặt tên, gộp, ẩn, "không phải người này") sửa trên điện thoại hoặc PC đều đồng bộ qua Drive. PC ghi lại thời điểm sửa của từng mục; thao tác từ điện thoại chỉ được chấp nhận nếu mới hơn lần sửa gần nhất trên PC của đúng mục đó. Điện thoại giữ lại các thay đổi chưa được PC xử lý và hiển thị chúng cho tới khi PC nhận. Điện thoại có nút "Tải lại" để lấy thay đổi mới từ PC (PC phải đồng bộ trước). Hai máy nên để đồng hồ đúng giờ.
- **Android khóa lại khi rời app**: tắt màn hình, chuyển ứng dụng hoặc vuốt ra khỏi app thì khi quay lại phải mở khóa bằng vân tay hoặc khóa màn hình của điện thoại (hoặc nhập lại mật khẩu đồng bộ nếu máy không hỗ trợ). Cửa sổ app bị chặn chụp màn hình và hiện trống trong danh sách ứng dụng gần đây.
- **Android xem ảnh**: chạm một lần vào ảnh để ẩn/hiện công cụ, thanh trạng thái và thông tin (tên, ngày, kích thước, người, nhãn); nhấp đúp để phóng to.
- **Chọn ảnh tương tự (PC)**: khi đã chọn vài ảnh, bấm "Chọn ảnh tương tự" (hoặc chuột phải → Chọn ảnh tương tự) để chọn thêm các ảnh giống trong danh sách đang hiện (mức: Rất giống 90%, Giống 85%, Khá giống 80%), rồi thêm vào nhãn. Ở trang Nhãn, sau khi "Gợi ý ảnh giống" có thêm ô chọn nhanh theo độ giống và nút "Chọn ảnh tương tự".
- **Dòng thời gian (Android)**: tab Ảnh xếp từ mới nhất đến cũ nhất, có tiêu đề theo ngày ("CN, 18 Th5, 2025"), nhãn ngày nổi khi cuộn, thanh kéo nhanh bên phải có mốc năm và bong bóng "Th5 2025" khi kéo. PC cũng hiện nhãn tháng/năm khi cuộn thư viện.
- **Tự động phân loại thông minh**: dựa trên các ảnh bạn đã gắn vào từng nhãn (từ 3 ảnh mẫu), app đề xuất nhãn cho các ảnh chưa có nhãn (trung bình 3 ảnh mẫu gần nhất của mỗi nhãn nên nhãn gồm nhiều kiểu ảnh vẫn đúng; chỉ gợi ý khi nhãn tốt nhất hơn hẳn nhãn thứ hai). Trang Nhãn → "Tự động phân loại…": xem theo từng nhãn, bỏ chọn ảnh sai rồi thêm; "Không phải nhãn này" để không gợi ý lại. Tùy chọn tự gán khi rất chắc (từ 92%) sau mỗi lần quét, có nút "Hoàn tác các nhãn đã tự gán". Ảnh bạn đã gỡ khỏi một nhãn sẽ không bị tự gán lại.
- **Điện thoại: chọn ảnh tương tự và gợi ý nhãn**: PC đồng bộ vectơ nội dung ảnh (mã hóa) lên Drive (khoảng 1 KB mỗi ảnh). Trên điện thoại chọn vài ảnh → "Chọn ảnh tương tự" (90/85/80%); trong một nhãn → "Gợi ý ảnh giống" rồi chọn ảnh đúng và "Thêm vào nhãn".
- **Nhận diện mặt chính xác hơn (ArcFace)**: thay SFace bằng ArcFace ResNet50 (huấn luyện trên WebFace600K, vectơ 512 chiều), căn chỉnh khuôn mặt theo 5 điểm mốc và lấy trung bình ảnh gốc với ảnh lật để ổn định. Lần quét đầu sau khi cập nhật, app tải mô hình (khoảng 166 MB, một lần) và quét lại ảnh để tính lại khuôn mặt; các nhóm đã đặt tên được giữ nguyên (khuôn mặt được cập nhật tại chỗ, không nhân đôi). Nếu chưa tải được ArcFace thì tạm dùng SFace. Ngưỡng gom người tự chỉnh theo mô hình.
- **Cửa sổ co giãn**: kích thước ban đầu theo màn hình đang dùng (không tràn), thu nhỏ được xuống 640×420; nội dung từng trang cuộn được khi cửa sổ nhỏ.
- **Giữ vị trí danh sách**: sau khi thêm, bỏ, đổi nhãn (hoặc làm mới), danh sách giữ đúng chỗ đang xem thay vì quay về đầu. Thanh chọn ảnh có thêm nút **Nhãn ▾** (thêm, bỏ, đổi nhãn) cạnh "Chọn ảnh tương tự".
- **Cập nhật tự động bền hơn**: dùng tập lệnh PowerShell chạy ẩn (không còn hộp thoại đen): chờ app thoát tối đa 20 giây rồi buộc tắt, tắt mọi tiến trình PrivatePicture.exe còn giữ tệp, chép đè (thử lại nếu tệp đang bị khóa), mở lại app và ghi nhật ký vào `update.log` trong thư mục dữ liệu.
- **Lọc Dressed / Nude**: PC phân loại ảnh bằng CLIP (so ảnh với các câu mô tả: đồ dài, đồ ngắn, bikini hoặc đồ bơi, cởi trần, không mặc gì, chân dung, không có người) rồi gộp thành hai nhóm: **Mặc đồ** (đồ dài, đồ ngắn, bikini hoặc đồ bơi) và **Không mặc đồ** (cởi trần, không mặc gì); ảnh không có người hoặc chỉ có mặt không thuộc nhóm nào. Có hai nút lọc ở mục Tất cả (hàng "Đồ") và trong trang ảnh của từng người, trên cả PC và điện thoại (kết quả đồng bộ sang điện thoại). Chỉ là gợi ý, có thể sai.
- **Android xem ảnh**: gõ hai lần phóng to đúng điểm gõ (hiệu ứng mượt), gõ hai lần nữa để thu về vừa khung; nút ▶ tự phát ảnh trong danh sách mỗi ảnh 3 giây (giữ màn hình sáng, dừng ở ảnh cuối, tạm chờ khi đang phóng to).
- **Thống kê dung lượng đồng bộ**: hộp "Đồng bộ điện thoại" hiện dung lượng đang chiếm trên Drive (ảnh gốc mã hóa, ảnh nhỏ, danh mục, app Android) so với ảnh gốc trên PC. Ảnh gốc mã hóa chỉ nặng hơn ảnh gốc khoảng 32 byte mỗi ảnh và giải mã ra **đúng từng byte** (chất lượng không đổi; AES-GCM còn kiểm tra toàn vẹn). Điện thoại có nút "Lưu ảnh gốc vào máy" (trong ⓘ) lưu nguyên bản vào Pictures/PrivatePicture.
- **Giải phóng dung lượng PC**: nút "Giải phóng dung lượng PC…" chuyển vào Thùng rác các ảnh gốc đã có bản mã hóa trên Drive, sau khi giải mã bản Drive và so sánh từng byte với tệp trên PC (lệch thì giữ lại). Thư viện vẫn xem, đồng bộ và quét bình thường (ảnh được ghi nhận "archived", không bị coi là đã xóa); chuột phải "Khôi phục ảnh gốc từ Drive…" để lấy lại về vị trí cũ hoặc thư mục khác. Rủi ro: sau đó bản Drive là bản duy nhất ngoài Thùng rác, mất mật khẩu đồng bộ hoặc tệp Drive là mất ảnh.
- **Tên file nén là tên người**: ảnh trong file nén có tên người (vd. `Nguyen Van A.zip`, `dang_thi_be_2024_photos.zip`) mặc định là của người đó. Tên được khớp với người đã có (không phân biệt dấu, hoa thường, cho phép kèm số hoặc chữ khác) hoặc, nếu tên file trông giống tên người (2 đến 5 từ chữ, không có số, không phải từ chung như "High Quality", "Photos"), app tạo người mới với tên đó. Ảnh có nhiều người: app gom các khuôn mặt trong cùng file nén và chọn **người xuất hiện ở nhiều ảnh nhất** (ưu tiên nhóm khớp với người đã có mốc) làm người mang tên file, gán đúng khuôn mặt đó trong từng ảnh (không chọn theo mặt lớn nhất); ảnh chỉ có một mặt thì mặc định là người đó. Mặt được gán là mốc cố định nên ảnh của người đó ở nơi khác cũng được nhận ra. Gỡ "không phải người này" thì không bị gán lại.
- **Nhớ người đã đặt tên kể cả khi xóa hết ảnh**: khi đặt tên (và sau mỗi lần gom), app lưu hồ sơ gồm tối đa 24 khuôn mặt tiêu biểu của người đó. Xóa toàn bộ ảnh của họ khỏi thư viện thì hồ sơ vẫn còn; khi ảnh của họ được thêm lại, khuôn mặt mới tự được nhận ra đúng là người đó với đúng tên.
- **Gộp người bị tách làm đôi**: trang Người có nút "Gợi ý gộp người…" liệt kê các cặp nhóm có thể là cùng một người, xếp cạnh nhau (ảnh đại diện, số ảnh, độ giống) để bấm "Gộp" hoặc "Khác người" (không đề xuất lại). Chuột phải vào một nhóm → "Gộp với nhóm giống nhóm này…". Bỏ qua cặp có chung một ảnh (hai mặt cùng ảnh là hai người) và cặp đã đặt tên cả hai; khi gộp giữ nhóm đã có tên hoặc nhóm nhiều ảnh hơn. "Gom lại khuôn mặt" còn tự gộp các cặp rất chắc.
- **Người đã đặt tên tự nhận ảnh mới và ảnh cũ**: mỗi khi đặt tên và sau mỗi lần quét, từng khuôn mặt chưa khóa được so với hồ sơ của mọi người có tên (trung bình 5 mặt mẫu giống nhất, nên người có nhiều góc mặt vẫn nhận ra), đủ giống và hơn hẳn người thứ hai thì tự vào nhóm người đó; mặt đã chỉnh tay thì không bị đổi.
- **Thanh phân loại gọn**: mục Tất cả thay bốn hàng nút xếp chồng (Năm, Người, Nhãn, Trang phục) bằng một dòng có hai ô chọn: chọn kiểu phân loại, rồi chọn giá trị (kèm số ảnh). Mỗi lần dùng một kiểu; nút "Bỏ lọc" để xem tất cả. Chỉ hiện các kiểu đang có dữ liệu.
- **Giao diện hiện đại hơn**: phẳng và bo góc mềm (nút, ô nhập, danh sách, thanh cuộn mảnh), nút chính màu đồng, ô tick có dấu ✓ rõ ràng, thanh bên có biểu tượng đường nét và tên ứng dụng, ảnh trong lưới bo góc.
- **Tên người trong nhiều file nén**: nếu một người có tên ở nhiều file nén, danh tính của họ được xác định **xuyên mọi file** (khuôn mặt xuất hiện ở nhiều file nén nhất), nên người lạ chụp chung chỉ ở một file không bị nhầm là người đó; ảnh nào giống danh tính đó nhất trong từng file được gán đúng. Một file có thể mang **nhiều tên người** (vd. `Anna Nguyen & Bella Tran.zip`): mỗi khuôn mặt được gán cho người giống nhất (cần người đã có mốc nhận diện). Đuôi như số, năm, `hd` trong tên file được bỏ qua khi suy ra tên.
- **Trang Người với danh sách rất dài**: có ô tìm tên (không phân biệt dấu), nút **A – Z** mở bảng chữ cái (chữ nào không có người thì mờ), lọc **màu tóc** (đen, nâu, nâu sẫm, vàng hoe, đỏ/hung đỏ, bạc/trắng; ước lượng gần đúng từ vùng tóc quanh khuôn mặt, kèm số người) và **xếp theo** (nhiều ảnh nhất, tên A–Z theo họ tên, hoặc theo tên gọi tức từ cuối như cách gọi tiếng Việt). Đ tính là D; người chưa đặt tên không nằm trong bảng chữ cái.

## Khóa khôi phục và khôi phục thư viện từ Drive
- **Đồng bộ với điện thoại → Khóa khôi phục…**: hiện một chuỗi dạng `ABCD-EFGH-…` mở được toàn bộ dữ liệu trên Drive khi quên mật khẩu đồng bộ. Cất ở nơi an toàn (giấy, trình quản lý mật khẩu), không để trên Drive.
- **Khôi phục thư viện từ Drive…** (máy mới hoặc cài lại): chọn thư mục Drive, nhập mật khẩu hoặc khóa khôi phục, chọn thư mục lưu. Ảnh gốc được giải mã đúng từng byte về thư mục đó, thêm vào thư viện, sau khi quét app tự áp lại nhãn và tên người. Ảnh chưa từng được đồng bộ ảnh gốc thì không khôi phục được.

## Tệp nén có nhiều người
Với tệp nén có nhiều tên (ví dụ `Anna Nguyen & Bella Tran.zip`), ảnh được chia cho từng người bằng khuôn mặt đối chiếu với ảnh đã biết của họ ở các tệp khác. Mặt giống hai người ngang nhau thì để chưa gán. Ảnh không thấy mặt (chụp từ phía sau…) được xếp theo **vị trí liền kề** (ảnh của một người thường nằm liền nhau), có kiểm tra thêm độ giống nội dung, trang phục, giờ chụp với ảnh đã biết của người đó. Chắc chắn thì tự xác nhận, chưa chắc thì thành gợi ý để bạn duyệt; ảnh lạ không giống ai thì không bị gán.
- Tên file kết thúc bằng “…” (ví dụ `175748 Anna Nguyen, Bella Tran, ....rar`) nghĩa là còn người chưa ghi tên. **Cài đặt → Thư mục và quét → Kiểm tra tệp nhiều tên** cho biết mỗi tệp: có bao nhiêu tên, bao nhiêu người đã có ảnh, tên nào chưa thấy ảnh, và còn bao nhiêu nhóm mặt chưa có tên để bạn đặt tên nốt.
- **Trang Người có 3 khu vực:** *Đã có tên*; *App suy đoán từ các tệp nén* (nhóm mặt chưa có tên nhưng xuất hiện trong nhiều tệp nén chung đúng một tên, đã loại các tên có người riêng trong tệp; hiện “Có thể là …”, chuột phải để xác nhận); *Chưa đặt tên*. Suy đoán thận trọng: tên chung của mọi tệp phải còn đúng một, có ít nhất một tệp “rõ ràng” (1 tên chưa ai nhận, 1 nhóm mặt chưa tên, không có “…”) hoặc xuất hiện ở từ 3 tệp, và hai nhóm không cùng nhận một tên.
- **Khi đang xem ảnh:** bấm chuột phải (không kéo) để Phân loại (Dressed / Nude), gỡ ảnh khỏi một người, chuyển sang người khác hoặc nhảy tới vị trí ảnh trong Tất cả.
- **Xem ảnh to ngay trong danh sách:** Space = xem nhanh ảnh đang trỏ chuột (← → chuyển ảnh, cuộn chuột thu phóng, Enter hoặc X chọn / bỏ chọn mà không rời khung); thanh “Cỡ ảnh”, Ctrl + cuộn chuột hoặc phím + − để phóng to / thu nhỏ ảnh trong lưới. Ở trang một người, kéo thanh chia để mở rộng khung “ảnh có thể là người này”.

## Dọn tệp nén sau khi đồng bộ (tùy chọn, mặc định tắt)
Trong *Đồng bộ với điện thoại*, ô **“Tự dọn tệp nén sau khi đồng bộ”**: với tệp `.zip` và `.7z` mà mọi ảnh bên trong đã có bản mã hóa trên Drive (từ ít nhất 30 phút, giống hệt từng byte), app xóa ảnh khỏi tệp nén và **giữ lại tệp nén rỗng cùng tên** để bạn không tải trùng. Ảnh vẫn nằm trong thư viện, vẫn xem được (đọc từ Drive) và khôi phục lại nguyên bản được. Tệp `.rar` không xóa bớt được nên bị bỏ qua. Khôi phục ảnh của tệp nén: ảnh được lưu thành tệp ảnh trong thư mục cạnh tệp nén (hoặc thư mục bạn chọn).

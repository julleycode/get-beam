# Nhận danh tính khách từ Leadpipe — bàn giao cho team

Cập nhật 06-08-26. Đọc 5 phút. Ai cần chi tiết kỹ thuật thì xem
[visitor-identity-flow-architecture.md §6.2b](./visitor-identity-flow-architecture.md).

---

## Một câu

Trước đây Beam **đi hỏi** Leadpipe mỗi giờ "có nhận ra ai không". Giờ Leadpipe **tự báo** ngay lúc
nó nhận ra. Cách cũ vẫn chạy song song, chưa tắt.

---

## Trước vs sau

**Trước:**

```
Khách vào web  →  pixel Leadpipe nhận diện  →  ghi vào kho của Leadpipe
                                                        ↓ (Beam chờ tới lượt quét, tối đa 1 giờ)
                                     Beam tải về 50 bản ghi mới nhất
                                                        ↓
                                     Beam TỰ ĐOÁN: ai trùng IP + cách nhau dưới 30 phút?
```

Ba chỗ đau:

- chờ tới 1 tiếng
- Beam phải tự đoán người nào là khách nào
- mỗi lần chỉ lấy được 50 bản ghi mới nhất, site ít khách bị chìm mất

**Sau:**

```
Khách vào web  →  pixel Leadpipe nhận diện  →  Leadpipe gọi thẳng vào Beam (ngay lập tức)
                                                        ↓
                                     Beam biết ngay: site nào, người nào
```

---

## Beam ghép người thế nào

Leadpipe nói "tôi nhận ra người này". Beam phải biết đó là khách nào trên web mình. Thử 3 cách,
chắc chắn trước, đoán sau:

| Thứ tự | Cách | Độ chắc |
|---|---|---|
| 1 | Beam gắn sẵn mã khách vào pixel, Leadpipe trả lại đúng mã đó | Chắc — **nhưng chưa chạy**, xem mục "Chưa xong" |
| 2 | Khớp email — khách này từng tự gõ email vào form trên site | Chắc |
| 3 | Trùng IP + cách nhau dưới 30 phút | Đoán — nên bị **giới hạn điểm tin cậy**, không cho lên cao |

Cách 1 chưa có dữ liệu thì tự tụt xuống cách 2, rồi cách 3. Đây là thiết kế, không phải lỗi.

Nếu cả 3 cách đều không ra ai, Beam **bỏ qua**, không gán bừa.

---

## Ảnh hưởng

**Không đổi gì với việc gửi mail.** Danh tính từ Leadpipe vẫn là **"ứng viên"**, không phải "đã xác
minh", và vẫn **không được phép gửi outreach**. Đây là ràng buộc cũ, không nới lỏng chút nào.

| Thứ | Có đổi không |
|---|---|
| Danh sách được phép gửi mail | Không đổi |
| Cách cũ (Beam đi hỏi mỗi giờ) | Vẫn chạy — tắt được bằng 1 biến môi trường, không cần deploy |
| Số lượng danh tính | Có thể tăng, sau khi bật webhook trên dashboard |
| Dữ liệu trùng | Không thể trùng — database có ràng buộc "một khách một dòng danh tính" |
| Site khách đang chạy | Không đổi. File pixel phục vụ cho khách chưa được build lại |

**Một chỗ đo lường đổi cách đọc:** trước đây báo cáo chia tiền cho số danh tính lấy được. Con số đó
tự lừa mình — danh tính sai vẫn được tính là thắng. Giờ có thêm cột chia cho số danh tính **chưa bị
chứng minh là sai** (email không bị trả về) và số **có người thật mở mail**. Trên dữ liệu mẫu:
`$1.33` theo cách cũ, `$4.00` theo cách mới. Cùng một khoản tiền, đọc theo cách cũ đẹp gấp 3 lần.

---

## Ai cần làm gì

Phần code xong rồi. Còn 2 việc **thao tác tay**, không code được:

1. **Đăng ký webhook trên dashboard Leadpipe**, chọn chế độ First Match.
   ⚠️ Phải làm **sau khi** code đã lên môi trường có địa chỉ công khai. Leadpipe **tự tắt** webhook
   nếu nó gọi mà lỗi vài lần liên tiếp — đăng ký sớm quá là webhook bị tắt sẵn, rồi ngồi tìm lỗi ở
   chỗ không có lỗi.

2. **Đặt biến `LEADPIPE_WEBHOOK_SECRET`** — chuỗi bí mật, dán cùng vào đường dẫn webhook trên
   dashboard. Để trống thì cửa đóng hoàn toàn (đây là chủ ý, không phải bug).

Kiểm đã chạy chưa: xem log server có nhận được cú gọi thật từ Leadpipe. **Đừng** tin trạng thái
hiển thị trên dashboard.

---

## Chưa xong

- **Cách ghép số 1 chưa chạy.** File pixel bản nén mà server đang phục vụ đang cũ hơn mã nguồn 11
  ngày. Build lại sẽ đẩy kèm một thay đổi pixel khác chưa rõ đã kiểm chưa, nên để lại quyết định
  riêng. Trong lúc chờ, cách 2 và 3 vẫn chạy bình thường.
- **Chưa xác minh Leadpipe có trả lại mã khách của Beam hay không.** Chỉ biết sau khi có cú gọi thật
  đầu tiên.
- **Chưa đo được danh tính có ĐÚNG người không.** Cần người thật xác minh tay (khoảng 30 mẫu), chưa
  có nguồn. Giai đoạn này chỉ chứng minh **đường ống chạy**, không chứng minh **kết quả đúng** —
  đừng suy từ "số danh tính tăng" ra "chất lượng tốt".

---

## Nếu có sự cố

| Triệu chứng | Nhiều khả năng là |
|---|---|
| Không nhận được cú gọi nào | Webhook chưa đăng ký, hoặc bị Leadpipe tự tắt do lỗi liên tiếp |
| Nhận cú gọi nhưng không ra danh tính nào | Không ghép được khách — site chưa có pixel, hoặc khách chưa từng để lại email và IP không khớp |
| Muốn tắt gấp | Đặt `LEADPIPE_WEBHOOK_SECRET` rỗng ⇒ cửa đóng ngay, cách cũ vẫn chạy |
| Nghi ngờ tốn tiền gấp đôi do chạy song song | Không tốn thêm tiền lưu trữ; chỉ thừa một lượt gọi API. Tắt cách cũ bằng `LEADPIPE_PULL_ENABLED=false` |

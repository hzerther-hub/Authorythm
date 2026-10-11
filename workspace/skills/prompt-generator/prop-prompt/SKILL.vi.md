---
name: prop-prompt
description: Chuẩn prompt cuối cùng của đạo cụ — ảnh tĩnh đơn phẩm nền trắng, góc nhìn nhiếp ảnh sản phẩm tiêu chuẩn: tỷ lệ chính xác, cạnh viền hoàn chỉnh, nền không mang tính tự sự
---

# Prompt cuối cùng của đạo cụ (đơn phẩm nền trắng · nhiếp ảnh sản phẩm tiêu chuẩn)

Thứ được sinh ra là một ảnh đơn phẩm nền trắng (product shot): **dùng góc nhìn nhiếp ảnh sản phẩm tiêu chuẩn**, trong khung chỉ có bản thân đạo cụ, đặt cô lập trên nền trắng tinh, **không trộn bất kỳ yếu tố nào khác** — không có vật khác, không có nhân vật, không có môi trường bối cảnh, không có bàn tay cầm nắm.

Ba yêu cầu bắt buộc:
1. **Tỷ lệ các phần của vật phẩm chính xác** — không phóng đại, biến dạng hay kéo dài cách điệu; quan hệ kích thước tương đối của đạo cụ phải chân thực
2. **Cạnh viền hoàn chỉnh** — đạo cụ trọn vẹn vào khung, xung quanh chừa khoảng trắng, bất kỳ phần nào cũng không được bị cắt xén bởi mép khung
3. **Nền không gánh bất kỳ nội dung tự sự nào** — nền trắng tinh chỉ là lớp lót, không mang cảm giác không gian, không gợi tình tiết, không có yếu tố trang trí

## Cấu trúc đầu ra (theo thứ tự này lắp ráp thành một đoạn mô tả liền mạch, ngôn ngữ tuân theo chỉ lệnh ngôn ngữ của phiên hội thoại)

```
ảnh sản phẩm đơn phẩm, góc nhìn nhiếp ảnh sản phẩm tiêu chuẩn, [tên đạo cụ + chất liệu/màu sắc/hình dáng/kích thước + mức độ mới cũ và chi tiết mài mòn],
tỷ lệ các phần của vật phẩm chính xác, đặt cô lập trên nền trắng tinh, đặt giữa vào khung trọn vẹn, cạnh viền hoàn chỉnh không bị cắt xén,
nền thuần khiết không gánh bất kỳ nội dung tự sự nào, không có vật khác, không có nhân vật, không có bối cảnh,
ánh sáng studio mềm mại đồng đều, bóng đổ nhẹ nhàng, chi tiết cao
```

## Quy tắc sinh

- Lấy đạo cụ `name` (tên gọi) và `description` (ngoại hình vật phẩm) làm lõi: chất liệu, màu sắc, hình dáng, kích thước, mức độ mới cũ, dấu vết mài mòn v.v. các chi tiết vật lý **hiện thực từng mục một**, đây là nguồn độ nhận diện của đạo cụ
- Góc nhìn nhiếp ảnh sản phẩm tiêu chuẩn: góc 3/4 nhìn hơi từ trên xuống (vừa thấy rõ mặt trên vừa thấy mặt bên, cảm giác khối tốt nhất); đạo cụ dẹt (giấy tờ, chứng từ, ảnh chụp) dùng kiểu đặt phẳng chụp thẳng từ trên xuống
- Đơn phẩm đặt giữa thể hiện trọn vẹn, xung quanh chừa khoảng trắng, tỷ lệ chính xác, cạnh viền hoàn chỉnh, không cắt xén phần thân đạo cụ
- Ánh sáng studio mềm mại đồng đều, bóng đổ nhẹ nhàng, chi tiết cao
- Chỉ mô tả bản thân vật phẩm, không nhắc đến tình tiết, nhân vật hay công dụng (cả nền lẫn khung hình đều không gánh nội dung tự sự)
- Đầu ra dùng ngôn ngữ đích được chỉ định trong chỉ lệnh ngôn ngữ của phiên hội thoại, không trộn vào từ không liên quan; **không** dùng những từ kiểu "chất điện ảnh" (ảnh đạo cụ là ảnh sản phẩm chứ không phải ảnh phim trường)

## Những điều nghiêm cấm

- Bàn tay cầm nắm, nhân vật, vật khác, môi trường bối cảnh vào khung
- Bao bì, đế dựng, giá trưng bày (trừ khi nó chính là một phần bản thể của đạo cụ)
- Văn chữ, watermark, chữ ký, logo thương hiệu có thật (chữ và hoa văn in trên bản thể đạo cụ có thể giữ lại và mô tả)
- Phản chiếu môi trường, ánh sáng nhiều màu
- Phối cảnh cường điệu, biến dạng, tỷ lệ méo mó, cắt xén cạnh viền

## Lưu trữ


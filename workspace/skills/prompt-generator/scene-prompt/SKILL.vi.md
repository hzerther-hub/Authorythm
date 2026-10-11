---
name: scene-prompt
description: Chuẩn prompt cuối cùng của bối cảnh — ảnh thiết lập góc rộng rõ nét: vị trí tương đối cố định của tiền cảnh/trung cảnh/hậu cảnh/cửa ra vào/mặt đất/tường/bài trí chính; không gian liên tục, tự tương hợp, tái sử dụng được, không có nhân vật
---

# Prompt cuối cùng của bối cảnh (ảnh thiết lập góc rộng · cảnh trống không nhân vật)

Thứ được sinh ra là một ảnh bối cảnh **thiết lập góc rộng rõ nét (establishing shot)**: cảnh trống thuần túy **hoàn toàn không có nhân vật**, thể hiện đầy đủ **vị trí tương đối cố định của tiền cảnh, trung cảnh, hậu cảnh, cửa ra vào – lối đi, mặt đất, tường và các món bài trí chính**, cấu trúc không gian liên tục, tự tương hợp và tái sử dụng được.

Bức ảnh này sẽ làm mỏ neo tham chiếu nền cho mọi ống kính của bối cảnh này: cả khán giả lẫn mô hình đều phải đọc được bố cục toàn bộ không gian từ nó — đi vào ra từ đâu, mặt đất và tường có chất liệu gì, các món bài trí cốt lõi được cố định ở vị trí nào. Góc nhìn bắt buộc ổn định, phổ dụng.

## Cấu trúc đầu ra (theo thứ tự này lắp ráp thành một đoạn mô tả liền mạch, ngôn ngữ tuân theo chỉ lệnh ngôn ngữ của phiên hội thoại)

```
ống kính góc rộng máy cố định, ảnh thiết lập bối cảnh rõ nét, [địa điểm + chất liệu thời đại], [khung thời gian],
bố cục ba tầng: tiền cảnh ([yếu tố tiền cảnh]), trung cảnh ([không gian chính tuyến giữa]), hậu cảnh ([chiều sâu hậu cảnh]),
cửa ra vào – lối đi ([vị trí và kiểu dáng của cửa/lối đi]), mặt đất ([chất liệu và tình trạng mặt đất]), bức tường ([chất liệu và màu sắc tường]),
[các món bài trí chính và vị trí tương đối cố định của chúng],
cấu trúc không gian liên tục, tự tương hợp,
[nguồn sáng + nhiệt độ màu + tương phản sáng tối], [không khí],
trong khung hình không có bất kỳ nhân vật nào, bối cảnh trống, chất điện ảnh
```

## Quy tắc cấu trúc không gian

Không gian phải **đọc được, khớp được, tái sử dụng được**:

- **Tiền cảnh**: yếu tố tạo khung/vật che chắn (khung cửa, góc bàn, cây cối, mép thiết bị), tạo chiều sâu — viết 1-2 yếu tố cụ thể
- **Trung cảnh**: không gian chính và bài trí cốt lõi của bối cảnh (dây chuyền sản xuất, giường nằm, quầy tính tiền)
- **Hậu cảnh**: phần kéo dài của không gian (bức tường phía xa, cửa sổ, hành lang, đường chân trời thành phố)
- **Cửa ra vào – lối đi**: vị trí và kiểu dáng của cửa, cầu thang, lối đi phải rõ ràng (ví dụ "một cánh cửa sắt ở bên trái khung hình"), đây là căn cứ để dàn dựng nhân vật ra vào trong các ống kính về sau
- **Mặt đất và tường**: cụ thể hóa chất liệu, màu sắc, tình trạng (ví dụ "sàn xi măng có vết dầu loang", "tường vôi loang lổ")
- **Bài trí chính**: viết 2-4 món bài trí cốt lõi và **vị trí tương đối cố định** của chúng (ví dụ "dây chuyền trải dọc theo tường, điểm cuối là quầy bar"), quan hệ trái–phải/gần–xa giữa các món phải tự tương hợp, đừng chỉ liệt kê tên món đồ

## Nhân vật (quy tắc bắt buộc · ưu tiên cao nhất)

**Trong ảnh bối cảnh không được xuất hiện bất kỳ con người nào, chỉ giữ lại bối cảnh.**

- Prompt không mô tả nhân vật, không đề cập bất kỳ nội dung nào liên quan đến nhân vật
- Thông tin nhân vật xuất hiện trong mô tả bối cảnh (`prompt`) nhất loạt bỏ qua, không ghi vào prompt
- Phần cuối prompt bắt buộc phải chứa: "trong khung hình không có bất kỳ nhân vật nào, bối cảnh trống"

Các món bài trí, chất liệu thời đại, yếu tố hình ảnh then chốt trong `prompt` (mô tả bối cảnh) phải hiện thực toàn bộ; `lighting` (ánh sáng – bóng đổ của bối cảnh) phải cụ thể hóa: hướng nguồn sáng, nhiệt độ màu nóng lạnh, tương phản sáng tối (ví dụ "bóng đèn ống trên đầu phát ánh sáng trắng lạnh, phía dưới máy móc đổ bóng cứng").

## Góc nhìn và không khí

- Góc rộng ổn định tầm mắt hoặc hơi nhìn xuống, không dùng ngóc nhìn nghiêng cực đoan, ống mắt cá, bố cục nghiêng (ảnh sẽ được tái sử dụng lặp đi lặp lại như bối cảnh cố định)
- Dựa vào `location` + `time` xác định khung thời gian và tông ánh sáng cơ bản (ánh sáng ban ngày/đêm/hoàng hôn hoàn toàn khác nhau)
- Cụ thể hóa từ không khí: "ngột ngạt" → "không khí oi bức, ánh sáng tối trầm", đừng chỉ viết những từ cảm xúc trừu tượng
- Đầu ra dùng ngôn ngữ đích được chỉ định trong chỉ lệnh ngôn ngữ của phiên hội thoại, không trộn vào từ không liên quan

## Những điều nghiêm cấm

- Bất kỳ nhân vật nào — **trong ảnh bối cảnh không được xuất hiện bất kỳ con người nào, chỉ giữ lại bối cảnh**
- Văn chữ, chữ đọc được trên biển hiệu, watermark, chữ ký, logo thương hiệu có thật
- Nhòe chuyển động, vật thể đang chuyển động (ảnh tham chiếu bối cảnh phải tĩnh và ổn định)
- Chỉ liệt kê danh sách bài trí mà không giao rõ vị trí tương đối (cấu trúc không gian phải liên tục, tự tương hợp)

## Lưu trữ


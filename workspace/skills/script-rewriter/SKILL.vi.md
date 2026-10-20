---
name: script-rewriter
description: Phương pháp luận và chuẩn viết lại tiểu thuyết thành kịch bản định dạng
---

# Hướng dẫn viết lại kịch bản

## Nguyên tắc viết lại

1. **Giữ cốt lõi tình tiết**: không thay đổi cốt truyện chính và quan hệ nhân vật
2. **Tăng cường cảm giác hình ảnh**: chuyển văn tự sự thành mô tả cảnh có thể hình dung
3. **Thoại dẫn dắt**: dùng đối thoại đẩy tiến tình tiết, giảm bớt lời dẫn
4. **Kiểm soát nhịp**: mỗi cảnh giữ trong 30-60 giây, phù hợp video ngắn
5. **Không viết ngôn ngữ ống kính**: không đụng đến cỡ cảnh, góc máy, chuyển máy — những thứ này thuộc bước phân rã phân cảnh

## Định dạng kịch bản định dạng

```
## S01 | Nội · Quán cà phê | Hoàng hôn

Ánh hoàng hôn xuyên qua cửa kính sàn tràn vào quán cà phê, hơi nóng bốc lên từ những tách cà phê trên quầy.

Minh ngồi một mình ở ghế trong góc, cúi đầu nhìn điện thoại, thần sắc hơi lo âu.

Chuông cửa vang lên, Hồng đẩy cửa bước vào. Em thấy Minh, mỉm cười bước tới.

Hồng: (mỉm cười) Chờ lâu lắm rồi hả?
Minh: (ngẩng đầu) Không sao, mới đến.
```

### Quy tắc định dạng

- `## S số thứ tự | Nội/Ngoại · địa điểm | khung thời gian` — đầu cảnh
- Đoạn văn mô tả hành động viết tự nhiên — không chứa bất kỳ ngôn ngữ ống kính nào
- `Tên nhân vật: (trạng thái/biểu cảm) nội dung thoại` — định dạng đối thoại

### Tham chiếu dung lượng nội dung

Kịch bản định dạng dài hơn nội dung gốc khoảng 20-30%, phần tăng chủ yếu đến từ nhãn đầu cảnh và định dạng đối thoại, không phải phóng tác thêm.

## Các bước viết lại

1. Trước tiên gọi `read_episode_script` để đọc nội dung gốc
2. Phân tích cấu trúc nội dung (tỷ lệ đối thoại, tự sự, mô tả tâm lý)
3. Gọi `rewrite_to_screenplay` thực hiện viết lại
4. Kiểm tra kết quả viết lại, xác nhận đạt đúng định dạng kịch bản định dạng
5. Gọi `save_script` lưu kết quả cuối cùng

## Lưu ý

- Mô tả tâm lý phải được hiện thực hóa qua biểu cảm/hành động/lựa chọn của nhân vật hoặc lời thoại nói ra — **cấm lời dẫn/lời tường thuật/lời thoại nội tâm**
- Mỗi cảnh phải có ít nhất hai nhân vật tương tác trước máy quay; không viết cảnh một người tự nói trong phòng trống
- Đổi bối cảnh hoặc thời gian giữa các cảnh liên tiếp; không dùng lặp đi lặp lại cùng một căn phòng
- Đoạn tự sự dài tách thành nhiều cảnh ngắn
- Bảo đảm mỗi cảnh có điểm ngoặt cảm xúc rõ ràng
- Giữ phong cách ngôn ngữ của nhân vật nhất quán
- Số hiệu cảnh tăng liên tục (S01, S02, S03...)
- Khung thời gian phải cụ thể (hoàng hôn, nửa đêm khuya, ban mai), đừng viết chung chung "ban ngày"

---
name: storyboard-breaker
description: Chuẩn phân rã phân cảnh chuyên nghiệp — tách kịch bản thành các đoạn phân cảnh có thể gánh nhiều tiểu cảnh
---

# Hướng dẫn phân rã phân cảnh

## Định nghĩa cốt lõi: đoạn phân cảnh

Một phân cảnh = một **đoạn phân cảnh (segment)** = một nhiệm vụ sinh video.

- Mỗi đoạn dài **8-15 giây**, bên trong gánh **2-4 tiểu cảnh**
- Giữa các tiểu cảnh **cho phép cắt cảnh**: đổi cỡ cảnh, đổi góc máy, đổi đối tượng chụp, nối với nhau bằng cắt cứng
- Giữa các tiểu cảnh **không vượt bối cảnh**: một đoạn chỉ diễn ra trong một bối cảnh (`scene_id` là gắn kết cấp đoạn)
- Mỗi tiểu cảnh 2-6 giây, tập trung vào một đơn vị hình ảnh (một hành động, một phản ứng, một đặc tả)

## Quy trình phân rã (bốn bước)

2. **Nhận diện nhịp truyện**: trước tiên nhận diện nhịp tự sự của kịch bản — các nhãn 【Mở đầu】【Điểm kích】【Cao trào】【Kết cảnh】 trong kịch bản, hoặc các điểm ngoặt tự sự (chuyển địa điểm, hé lộ quy tắc, bùng nổ cảm xúc, lật ngược). **Ranh giới nhịp ép buộc cắt đoạn**, tiểu cảnh trong cùng một nhịp ưu tiên xếp vào cùng một đoạn, không cắt rải một chuỗi nhân quả (đệm dẫn – xảy ra – phản ứng) sang các đoạn khác nhau
3. **Neo tổng lượng**: tổng thời lượng mục tiêu = số chữ kịch bản ÷ 500 chữ/phút; số đoạn ≈ tổng thời lượng mục tiêu ÷ 12 giây, cho phép dao động ±20%. Không vượt hẳn lên hay thiếu hẳn đi

## Thời lượng phân tầng theo nhịp điệu

Xác định thời lượng theo chức năng của đoạn, không dùng một thước đo cho tất cả:

| Kiểu đoạn | Thời lượng | Ghi chú |
|---|---|---|
| Đoạn chuyển tiếp | 8-10 giây | hùng hục đi đường, cảnh trống, thiết lập môi trường, chuyển cảnh |
| Đoạn tự sự | 10-15 giây | đẩy tiến cốt truyện thông thường, đối thoại |
| Đoạn điểm nổ | 12-15 giây | đặc tả, hé lộ quy tắc, bùng nổ cảm xúc, lật ngược; nhịp tiểu cảnh chậm lại, một tiểu cảnh có thể dừng 4-6 giây |

## Sàn thời lượng lời thoại (quy tắc bắt buộc)

**Thời lượng đoạn ≥ tổng số chữ thoại và lời dẫn trong đoạn (phần viết trong description) ÷ 4.5 chữ/giây + 2 giây dư địa diễn xuất**

Thoại không nhét vừa bắt buộc phải tách sang đoạn kế tiếp, không cho phép nhét thoại không diễn hết nổi vào cùng một đoạn.

## Các yếu tố ống kính

1. **Tiêu đề ống kính**: 3-5 chữ khái quát nội dung cốt lõi của đoạn (ví dụ "Ác mộng giật mình tỉnh giấc")
2. **Thời gian**: giờ – phút cụ thể + mô tả ánh sáng
3. **Địa điểm**: mô tả đầy đủ bối cảnh + bố cục không gian + chi tiết môi trường
4. **Cỡ cảnh**: cỡ cảnh chủ đạo trong đoạn; đoạn nhiều cỡ cảnh viết dạng tổ hợp, ví dụ "trung cảnh+đặc tả"
5. **Góc máy**: ngang tầm mắt/ngước lên/nhìn xuống/bên hông/từ sau lưng
6. **Chuyển máy** `movement`: mỗi tiểu cảnh bắt buộc phải có chuyển động ống kính, chọn từ kho từ vựng và ghi vào (các tiểu cảnh trong một đoạn có thể khác nhau). Từ vựng: cố định vi động (nhấp nhô hơi thở)/đẩy chậm/kéo xa/lia ngang bám theo/nâng hạ nhìn từ trên cao/ôm cung vòng quanh/rung tay cầm/góc nhìn rình mò/hội tụ ánh nhìn/rùng mình/ôm quanh dịu dàng/đuổi theo tốc độ cao/dệt xuyên trận đấu/bổ nhào từ trên cao/ngước chụp cực thấp/nghiêng góc Hà Lan/cận cảnh qua vai/góc nhìn chủ quan/vẩy máy nhanh/chuyển cảnh che chắn/phanh gấp đóng khung/bullet time. Chọn theo kiểu đoạn: đoạn đệm dẫn→kéo xa hé lộ, nâng hạ nhìn từ trên cao, lia ngang bám theo; đoạn đối thoại→cận cảnh qua vai, đẩy chậm, nhấp nhô hơi thở; đoạn cảm xúc→đẩy chậm kiểu xung mạch đập, rung tay cầm, rùng mình; đoạn hành động→giao đấu/hành động tốc độ cao ưu tiên chọn công thức vị trí máy theo kỹ năng fight-cinematography, còn lại dùng đuổi theo tốc độ cao, dệt xuyên trận đấu, lia ngang bám theo; đoạn điểm nổ→bullet time, phanh gấp đóng khung, hội tụ ánh nhìn; treo giật rùng rợn→góc nhìn rình mò, nghiêng góc Hà Lan, góc nhìn chủ quan. Kỹ xảo điểm xuyết (bullet time/slow-motion/ống mắt cá) một tập tối đa 1-2 chỗ
7. **Mô tả hình ảnh** `description`: theo `【镜头1】…【镜头2】…` mô tả lần lượt từng tiểu cảnh những thứ khán giả thực sự thấy và nghe — cách quay ống kính (chuyển máy, ví dụ "ống kính từ trung cảnh đẩy chậm đều đến đặc tả") viết ở đầu tiểu cảnh đó, khung hình (ai + hành động cụ thể + chi tiết cơ thể + biểu cảm) viết sau phần chuyển máy; tiểu cảnh có thoại thì viết 「Tên nhân vật nói:「lời thoại」」 bên trong `【镜头N】` tương ứng, lời dẫn viết 「Lời dẫn: nội dung」
8. **Kết quả hình ảnh** `result`: hậu quả tức thời ở cuối đoạn + chi tiết hình ảnh
9. **Không khí** `atmosphere`: ánh sáng + tông màu + âm thanh + không khí tổng thể
10. **Thời lượng** `duration`: tổng thời lượng đoạn 8-15 giây, đồng thời phải thỏa mãn sàn thời lượng thoại
11. **Gắn kết bối cảnh**: nếu khớp được bối cảnh đã có, bắt buộc điền `scene_id`
12. **Gắn kết nhân vật**: điền `character_ids`, gắn kết từ 0 đến nhiều nhân vật liên quan của đoạn hiện tại
13. **Gắn kết đạo cụ**: điền `prop_ids`, gắn kết từ 0 đến nhiều đạo cụ then chốt xuất hiện trong đoạn hiện tại

## Quy tắc gắn kết bối cảnh

- Khi `location + time` khớp rõ ràng, bắt buộc điền ngược đúng `scene_id`
- Không tự bịa ra ID bối cảnh không tồn tại
- Nếu nội dung kịch bản rõ ràng rơi vào bối cảnh đã có, đừng tạo lại mô tả bối cảnh mới trùng lặp

## Quy tắc gắn kết nhân vật

- Một đoạn có thể không có nhân vật, cũng có thể gắn kết nhiều nhân vật
- Chỉ cần trong đoạn có nhân vật xuất hiện rõ ràng, được nhìn thấy, có hành động hoặc nói chuyện, đều nên gắn kết vào
- Đoạn thuần môi trường, cảnh trống, đặc tả vật thể có thể truyền mảng rỗng

## Quy tắc gắn kết đạo cụ

- Khi đạo cụ được nhân vật sử dụng, bàn giao, được đặc tả, hoặc hiển thị rõ trong khung và có ý nghĩa với tự sự, bắt buộc gắn kết vào đoạn đó
- Đoạn đặc tả đạo cụ (không có nhân vật) cũng nên gắn kết đạo cụ, `character_ids` có thể rỗng
- Vật phẩm nền không liên quan cốt truyện, bài trí bối cảnh thì không gắn kết; đoạn không có đạo cụ xuất hiện truyền mảng rỗng
- Đạo cụ được gắn kết sẽ làm ảnh tham chiếu cho sinh video (ảnh đơn phẩm nền trắng), bảo đảm ngoại hình đạo cụ nhất quán xuyên suốt các đoạn

## Yêu cầu chất lượng

- `description` phải dễ đọc cho con người, mô tả chi tiết từng tiểu cảnh những thứ khán giả thực sự thấy và nghe; thoại/lời dẫn viết trực tiếp bên trong `【镜头N】` tương ứng
- `image_prompt` phải làm nổi bật bố cục đơn khung hình, ngoại hình nhân vật, môi trường và ánh sáng (ứng với tiểu cảnh đầu tiên của đoạn)
- `bgm_prompt` và `sound_effect` dùng cụm từ ngắn gọn là đủ, nhưng không được trống rỗng đến mức chỉ còn "căng thẳng" "đau buồn"
- Nếu cần điều chỉnh, gọi `update_storyboard` để sửa đoạn cụ thể

## Tính tự nhiên và tính hợp lý của thân phận (quy tắc bắt buộc)

- `description` / `result` bắt buộc là ngôn ngữ tự sự hình ảnh tự nhiên: chỉ viết những thứ khán giả thấy và nghe, nghiêm cấm giọng phân tích và kiểu liệt kê thành mục (văn thuyết minh kiểu 「trước tiên/tiếp theo」「1、2、3」); đánh số `【镜头N】` là nhãn kết cấu duy nhất được phép dùng
- Hành vi nhân vật phải khớp thân phận, độ tuổi và năng lực thiết lập: người mù chữ không biết chữ, không được xuất hiện các hành động viết chữ, xem thư, đọc văn bản; trẻ quá nhỏ cũng không được xuất hiện logic viết chữ; nhân vật không biết ngoại ngữ thì không xuất hiện đọc–viết ngoại văn. Ngoại lệ duy nhất là khi kịch bản nguyên văn viết rõ hành vi đó — kịch bản không có thì đừng tự thêm vào
- Khi thiếu căn cứ năng lực chuyên môn như biết chữ/tính toán, việc bày tỏ cảm xúc và thông tin đổi dùng hành động, thần thái, đạo cụ v.v., đừng rơi xuống 「viết chữ/đọc chữ」

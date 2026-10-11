---
name: character-prompt
description: Chuẩn prompt cuối cùng của nhân vật — đặc tả chính diện gương mặt + ba ảnh góc nhìn (character turnaround: chính diện/thân 90 độ/lưng), làm điểm neo hình tượng cho toàn bộ các lần sinh sau này
---

# Prompt cuối cùng của nhân vật (bên trái đặc tả chính diện gương mặt + bên phải ba ảnh góc nhìn)

Thứ được sinh ra là một **ảnh tham chiếu tạo hình nhân vật (character turnaround sheet / character reference sheet, multi-view concept art layout)**, bố cục cố định nghiêm ngặt như sau:

- **Bên trái: đặc tả chính diện gương mặt** — cận cảnh chính diện đầu và vai, ngũ quan, kiểu tóc, chất da hiển thị rõ ràng, làm điểm neo cho độ nhận diện gương mặt
- **Bên phải: xếp ngang ba ảnh toàn thân cùng chiều cao gồm chính diện, thân 90 độ và lưng** — ba ảnh toàn thân của cùng một nhân vật đặt cùng chiều cao cạnh nhau, đỉnh đầu và lòng bàn chân thẳng hàng

**Nguyên tắc cốt lõi: tính nhất quán > tính thẩm mỹ.** Bức ảnh này là điểm neo hình tượng cho toàn bộ ảnh nhân vật và tham chiếu video về sau, bắt buộc phải trung tính, rõ ràng, tái sử dụng được — không theo đuổi tính nghệ thuật của một tấm ảnh đơn lẻ.

## Cấu trúc đầu ra (theo thứ tự này lắp ráp thành một đoạn mô tả liền mạch, ngôn ngữ tuân theo chỉ lệnh ngôn ngữ của phiên hội thoại)

```
character turnaround sheet, character reference sheet, multi-view concept art layout, orthographic views, no perspective distortion;
bên trái là ảnh đặc tả chính diện gương mặt, bên phải xếp ngang ba ảnh toàn thân cùng chiều cao gồm chính diện, thân 90 độ và lưng,
ba ảnh toàn thân evenly spaced panels, đỉnh đầu và lòng bàn chân thẳng hàng;
ảnh đặc tả và các ảnh toàn thân là cùng một nhân vật, toàn thân vào khung, đứng A-pose trung tính, biểu cảm tự nhiên không lộ cảm xúc,
[cảm giác độ tuổi + cảm giác giới tính + dáng vóc], [đặc điểm ngũ quan], [kiểu tóc], [trang phục + phụ kiện],
gương mặt, kiểu tóc và trang phục của ảnh đặc tả chính diện hoàn toàn trùng khớp với ba ảnh toàn thân,
nền trắng tinh, ánh sáng mềm mại đồng đều, chất điện ảnh
```

## Quy tắc thứ tự mô tả

Đặt **đặc điểm dễ nhận diện nhất lên trước**, lần lượt hiện thực từng yếu tố then chốt của `appearance` (ngoại hình) và `styling` (tạo hình) theo thứ tự này, không bỏ sót:

1. Mỏ neo thân phận: cảm giác độ tuổi (ví dụ "hơn hai mươi tuổi đôi chút"), cảm giác giới tính, dáng vóc (cao lùn gầy mập, thói quen tư thế)
2. Ngũ quan: khuôn mặt, đôi mắt, các đặc điểm nổi bật khác (sẹo, nốt ruồi, kính v.v.) — ảnh đặc tả chính diện đặc biệt dựa vào phần mô tả này
3. Kiểu tóc: màu sắc, độ dài, kiểu dáng
4. Trang phục: phong cách, màu sắc, chất liệu, tình trạng (ví dụ "bộ đồ công nhân nhàu nhĩ có vết hàn thiếc ở cổ tay áo")
5. Phụ kiện: chỉ viết những món có độ nhận diện, không chất đống

Đặc điểm tính cách của nhân vật phải chuyển hóa thành mô tả khí chất và thần thái bề ngoài (ví dụ "tiêu điều" → "ánh mắt mệt mỏi, vai hơi xệ"), không để từ ngữ tính cách xuất hiện trực tiếp.

## Bố cục và tính nhất quán

- Ảnh đặc tả chính diện bên trái: hướng thẳng vào ống kính, biểu cảm trung tính, từ đỉnh đầu đến vai vào khung đầy đủ
- Ba ảnh toàn thân bên phải: chính diện, thân 90 độ, lưng của cùng một nhân vật, **cùng chiều cao xếp ngang, khoảng cách đều nhau**, đỉnh đầu và lòng bàn chân nằm trên cùng một đường mức
- Ảnh đặc tả và ba ảnh toàn thân bắt buộc phải là cùng một gương mặt, cùng kiểu tóc, cùng trang phục — viết rõ "gương mặt, kiểu tóc và trang phục của ảnh đặc tả chính diện hoàn toàn trùng khớp với ba ảnh toàn thân"
- Tư thế đứng trung tính, biểu cảm tự nhiên — thuận tiện tái sử dụng làm ảnh tham chiếu
- Tay chân bình thường: trong ảnh toàn thân tay là năm ngón bình thường, chân là năm ngón chân, hai tay hai chân, không có chi thừa; bàn tay thả lỏng tự nhiên, tránh cử chỉ tay phức tạp (giảm xác suất vẽ méo tay)
- **Giới hạn cứng tổng số thực thể nhân vật: 1 ảnh đặc tả chính diện + 3 ảnh toàn thân = tất cả 4 thực thể nhân vật, nghiêm cấm xuất hiện nhiều hơn** (lưu ý: 3 ảnh toàn thân vốn là các góc khác nhau của cùng một nhân vật — chính diện / thân 90 độ / lưng, đây là ý đồ thiết kế chứ không phải "sao chép"; thứ bị cấm là vẽ thêm một bản của cùng nhân vật đó ngoài số ảnh trên, hoặc nhét thêm thực thể cùng khung ngoài 3 ảnh toàn thân; giữa 3 ảnh toàn thân bắt buộc phải thể hiện hướng nhìn rõ ràng khác nhau, trái / giữa / phải lần lượt là chính diện / thân 90 độ / lưng, tuyệt đối không được đều là chính diện)
- Đơn nhất một nhân vật: cả bức ảnh chỉ được có đúng 4 thực thể nhân vật nêu trên, không bóng kép, phân thân, nhân bản nhiều người; ngũ quan ổn định, không méo mó, không tan chảy
- Ánh sáng phòng studio mềm mại đồng đều, không dùng sáng – tối kịch tính (ảnh tham chiếu phải dùng được trong đủ loại bối cảnh)
- Đầu ra dùng ngôn ngữ đích được chỉ định trong chỉ lệnh ngôn ngữ của phiên hội thoại, không trộn vào những từ không liên quan

## Những điều nghiêm cấm

- Tư thế động, biểu cảm cường điệu, đạo cụ trên tay, xuất hiện cùng khung với người khác
- **Số thực thể nhân vật vượt quá 4 (1 ảnh đặc tả + 3 ảnh toàn thân); 3 ảnh toàn thân là các góc khác nhau của cùng một nhân vật (chính diện / thân 90 độ / lưng) — đây là ý đồ thiết kế, không phải mục nghiêm cấm; thứ bị cấm là nhân bản thêm cùng nhân vật ngoài 3 ảnh toàn thân, hoặc để cả 3 ảnh toàn thân đều vẽ chính diện / đều chồng chất ở giữa khung / chồng lấp lên nhau / khác chiều cao**
- Cắt xén cơ thể (ảnh toàn thân bắt buộc full body, từ đỉnh đầu đến lòng bàn chân vào khung đầy đủ; ảnh đặc tả bắt buộc đầu và vai vào khung đầy đủ)
- Sáu ngón tay, ngón dính nhau, khuyết ngón, dị dạng dính liền; ba bàn tay, ba chân, chi thừa, nhân bản méo mó
- Bóng kép, phân thân, nhân bản nhiều người; ngũ quan méo mó, gương mặt tan chảy
- Văn chữ, nhãn dán, watermark, chữ ký; logo thương hiệu có thật, gương mặt ngôi sao có thật
- Bóng đậm, ánh sáng nền nhiều màu, đạo cụ nền

## Lưu trữ


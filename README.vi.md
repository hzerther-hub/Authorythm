<!-- 此 README 的语言: vi。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | **Tiếng Việt** | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# Yihao Shorts · Phiên bản PySide6

> Studio AI tất cả trong một cho phim ngắn, tiểu thuyết và truyện tranh — tương đương 100% với phiên bản Web mã nguồn mở, tích hợp đọc to giọng thần kinh 16 ngôn ngữ.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ Tính năng cốt lõi

🎬 **5 mục tiêu sáng tạo**: tiểu thuyết · phim ngắn · truyện tranh · quảng bá (6 nền tảng × 6 định dạng) · nhân bản video viral
🔧 **Quy trình 6 giai đoạn**: văn bản thô → AI viết lại → câu chuyện hình ảnh → phân cảnh → truyện tranh → ghép & xuất
🤖 **10 tác nhân AI**: viết lại kịch bản, trích xuất nhân vật/bối cảnh, phân chia cảnh quay, prompt, viết tiểu thuyết, lập kế hoạch, đánh giá 6 chiều, biên tập, phân chia truyện tranh, văn bản quảng bá — System Prompt mở hoàn toàn để chỉnh sửa
🎙️ **Đọc to Edge TTS miễn phí**: 16 ngôn ngữ × 2 giới tính = 32 giọng thần kinh Microsoft, không cần API Key, không cần gói ngôn ngữ, chỉ cần internet. Cài đặt giọng cấp dự án để giữ chương nhất quán
🎨 **Nhất quán giữa các khung**: tạo truyện tranh hàng loạt dùng chuỗi keyframe (hình ảnh khung trước nuôi khung sau) + tham chiếu đa góc `character_variants`, nhân vật và bối cảnh ổn định giữa các khung

## 🚀 Bắt đầu nhanh

- **Yêu cầu**: Python 3.10+ (phát triển xác nhận trên 3.13)
- **Chạy**: `py -3.13 -m app.main` hoặc nhấp đúp `start.bat`
- **Tài liệu đầy đủ**: xem [README chính](README.md)

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。

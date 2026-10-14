<!-- 此 README 的语言: th。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | **ภาษาไทย**

# Yihao Shorts · รุ่น PySide6

> สตูดิโอ AI ครบวงจรสำหรับหนังสั้น นิยาย และการ์ตูน — เทียบเท่าคุณสมบัติ 100% กับเวอร์ชัน Web แบบโอเพนซอร์ส พร้อมเสียงอ่านประสาท 16 ภาษา.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ คุณสมบัติหลัก

🎬 **5 เป้าหมายเชิงสร้างสรรค์**: นิยาย · หนังสั้น · การ์ตูน · โปรโมชัน (6 แพลตฟอร์ม × 6 รูปแบบ) · โคลนวิดีโอไวรัล
🔧 **ไปป์ไลน์ 6 ขั้นตอน**: ข้อความดิบ → เขียนใหม่ด้วย AI → เรื่องด้วยภาพ → สตอรี่บอร์ด → การ์ตูน → รวมและส่งออก
🤖 **10 เอเจนต์ AI**: เขียนสคริปต์ใหม่, สกัดตัวละคร/ฉาก, แบ่งช็อต, พรอมต์, เขียนนิยาย, วางแผน, รีวิว 6 มิติ, แก้ไข, แบ่งการ์ตูน, ข้อความโปรโมชัน — System Prompts แก้ไขได้ทั้งหมด
🎙️ **อ่าน Edge TTS ฟรี**: 16 ภาษา × 2 เพศ = 32 เสียงประสาทของ Microsoft, ไม่ต้องใช้ API Key, ไม่ต้องดาวน์โหลดชุดภาษา, แค่มีอินเทอร์เน็ต การตั้งค่าเสียงระดับโปรเจกต์ทำให้บทสอดคล้องกัน
🎨 **ความสอดคล้องข้ามแผง**: การสร้างคอมิกเป็นชุดใช้การป้อน keyframe แบบลูกโซ่ (ภาพแผงที่เสร็จแล้วป้อนแผงถัดไป) + การอ้างอิงหลายมุม `character_variants` ตัวละครและฉากยังคงที่ข้ามแผง

## 🚀 เริ่มต้นอย่างรวดเร็ว

- **ข้อกำหนด**: Python 3.10+ (พัฒนาและทดสอบบน 3.13)
- **รัน**: `py -3.13 -m app.main` หรือดับเบิลคลิก `start.bat`
- **เอกสารฉบับเต็ม**: ดู [README หลัก](README.md)

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。

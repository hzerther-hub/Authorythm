<!-- 此 README 的语言: tr。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | **Türkçe** | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# Yihao Shorts · PySide6 Sürümü

> Kısa filmler, romanlar ve çizgi romanlar için hepsi bir arada yapay zekâ stüdyosu — açık kaynak Web sürümüyle %100 özellik eşliği, 16 dilde sinirsel sesli okuma özelliğiyle.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ Temel özellikler

🎬 **5 yaratıcı hedef**: roman · kısa film · çizgi roman · tanıtım (6 platform × 6 format) · viral-video klonu
🔧 **6 aşamalı iş akışı**: ham metin → AI yeniden yazma → görsel hikâye → storyboard → çizgi roman → birleştirme & dışa aktarma
🤖 **10 AI ajanı**: senaryo yeniden yazma, karakter/sahne çıkarımı, çekim bölme, istemler, roman yazma, planlama, 6 boyutlu inceleme, düzenleme, çizgi roman bölme, tanıtım metni — System Prompt'lar tamamen düzenlenebilir
🎙️ **Ücretsiz Edge TTS okuma**: 16 dil × 2 cinsiyet = 32 Microsoft sinir sesi, API anahtarı yok, dil paketi yok, sadece internet gerekir. Proje düzeyinde ses ayarı bölüm tutarlılığını korur
🎨 **Panel arası tutarlılık**: toplu çizgi roman üretimi zincirleme keyframe beslemesi (tamamlanan her panelin görüntüsü bir sonrakini besler) + `character_variants` çok açılı referansları kullanır, karakterler ve sahneler paneller arası sabit kalır

## 🚀 Hızlı başlangıç

- **Gereksinimler**: Python 3.10+ (3.13 ile geliştirildi)
- **Çalıştır**: `py -3.13 -m app.main` veya `start.bat` çift tıklayın
- **Tam belgeler**: [ana README](README.md) bölümüne bakın

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。

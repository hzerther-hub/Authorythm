<!-- 此 README 的语言: en。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | **English** | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# Yihao Shorts · PySide6 Edition

> An all-in-one AI studio for short dramas, novels and comics — 100% feature-parity with the open-source Web build, now with 16-language neural TTS read-aloud.

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ Core features

🎬 **5 creative goals**: novel · short drama · comic · promotion (6 platforms × 6 formats) · viral-video clone
🔧 **Six-stage pipeline**: raw text → AI rewrite → visual-story → storyboard → comic → merge & export
🤖 **10 AI agents**: script rewriting, character/scene extraction, shot splitting, prompts, novel writing, planning, 6-dimension review, editing, comic split, promo copy — System Prompts fully editable
🎙️ **Microsoft TTS read-aloud (free)**: 16 languages × 2 genders = 32 Edge neural voices, no API key, no language packs, only needs internet. Project-level voice setting keeps the whole chapter consistent. Configurable in Settings → Narration.
💬 **Chat-edit image editing**: type Chinese commands like "改亮 30" / "改成黑白" → instant edit via PhotoCraft, plus PNG/text watermark with 9-position grid, opacity & stroke presets.
📷 **PhotoCraft integration**: when installed (Settings → PhotoCraft), opens images in the desktop editor and auto-syncs edits back — chat panel and external editor stay in lockstep.
🎨 **Cross-panel consistency**: batched comic generation uses chained keyframe feeding (each completed panel image feeds the next) plus `character_variants` multi-angle references, so characters and scenes stay stable across panels.

## 🚀 Quick start

- **Requirements**: Python 3.10+ (tested on 3.13)
- **Run**: `py -3.13 -m app.main` or double-click `start.bat`
- **Full documentation**: see the [main README](README.md)

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。

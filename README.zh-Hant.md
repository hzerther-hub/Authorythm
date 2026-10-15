<!-- 此 README 的语言: zh-Hant。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | **繁體中文** | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 易好短劇 · PySide6 版

> AI 短劇/小說/漫畫一站式製作工具 · 100% 對齊開源 Web 版,整合 16 種語言神經語音朗讀。

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ 核心特性

🎬 **5 種創作目標**: 寫小說 · 生成短劇 · 生成漫畫 · 宣傳行銷(6 平臺 × 6 格式) · 同款復刻
🔧 **六階段流水線**: 原始內容 → AI 改寫 → 視漫製作 → 分鏡 → 漫畫 → 拼接匯出
🤖 **10 類 AI Agent**: 劇本改寫、角色場景提取、分鏡拆解、提示詞、小說生成、策劃、六維審校、改稿、漫畫分鏡、宣傳文案;System Prompt 全開放可編輯
🎙️ **Microsoft TTS 免費朗讀**: 16 種語言 × 男女 32 個微軟神經 voice,無需 API Key / 任何語言包,只要上網就有聲;項目級「朗讀音色」統一整集聲音;在 設定 → 配音 裡調
💬 **聊天改圖**:輸入「改亮 30」「改成黑白」等中文 → 即時通過 PhotoCraft 改圖;另支援 PNG/文字水印(9 宮格位置、透明度、描邊預設)
📷 **PhotoCraft 整合**:安裝 PhotoCraft 後(設定 → PhotoCraft 聊天修圖)可一鍵在桌面端打開圖片,改完自動同步回會話 —— 聊天面板與外部編輯器雙向同步
🎨 **跨格一致性**: 漫畫批出圖採用鏈式 keyframe 饋送(上一張 panel 圖餵給下一張)+ character_variants 多角度參考圖,跨格角色/場景/光影保持一致

## 🚀 快速開始

- **要求**: Python 3.10+ (開發驗證於 3.13)
- **執行**: `py -3.13 -m app.main` 或雙擊 `start.bat`
- **完整文件**: 請看[主 README](README.md)

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。

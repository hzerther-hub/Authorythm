<!-- 此 README 的语言: ja。所有 16 语言 README 互链,见顶部跳转栏。 -->
[简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | **日本語** | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 易好短劇 (イーハオ ショートドラマ) · PySide6 版

> AI 短編ドラマ / 小説 / 漫画をワンストップで制作するツール。オープンソースの Web 版と 100% 機能互換、16 言語のニューラル音声読み上げも統合。

> 黑盒分析: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)
> 上游项目: [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版) · 集成组件: [golanse/easymerger](https://github.com/golanse/easymerger) · [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)

## ✨ 主な特徴

🎬 **5 つの制作目的**: 小説 · 短編ドラマ · 漫画 · 宣伝(6 プラットフォーム × 6 フォーマット) · 同款再現
🔧 **6 段階パイプライン**: 生コンテンツ → AI 改稿 → ビジュアル制作 → 絵コンテ → 漫画 → 結合書き出し
🤖 **10 種の AI Agent**: 台本改稿、キャラクター/シーン抽出、絵コンテ分割、プロンプト、小説生成、企画、6 軸レビュー、修正、漫画分割、宣伝文。System Prompt はすべて編集可能
🎙️ **無料 Edge TTS 読み上げ**: 16 言語 × 男女 = 32 の Microsoft ニューラル voice。API キー不要、言語パック不要、ネットがあればすぐ声が出る。プロジェクト単位で読み上げ音声を統一可能
🎨 **コマ跨ぎの一貫性**: 漫画一括生成は「キーフレーム連鎖フィード」(前のコマ画像を次のコマへ)+ `character_variants` 複数角度リファレンスで、キャラクターとシーンがコマを跨いでも安定

## 🚀 クイックスタート

- **動作環境**: Python 3.10+ (3.13 で開発検証)
- **実行**: `py -3.13 -m app.main` または `start.bat` をダブルクリック
- **完全ドキュメント**: [メイン README](README.md) を参照

---

📘 **完整文档 / Full docs / Dokümentlar / 文档全貌**: [主 README](README.md) (简中) — 包含「功能对照表」「项目结构」「许可」等全部章节。

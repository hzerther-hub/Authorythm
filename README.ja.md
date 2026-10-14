<!-- 此注释表明此 README 的语言。其它语言的 README 见同目录下的兄弟文件。 -->
> **语言 / Language / 言語 / 언어**: [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | **日本語** | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 易好短剧 · PySide6 版 / Yihao Shorts (PySide6 Edition)

AI 短剧/小说/漫画一站式制作工具。功能 100% 对齐开源项目 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版),并集成了两个社区工具的核心能力:
- **[golanse/easymerger](https://github.com/golanse/easymerger)** — 无损视频合并(参数检测/智能直通/一键对齐异类)
- **[liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)** — 同款复刻(爆款视频结构迁移到你的产品)

> 黑盒分析报告: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)

---
<a name="日本語"></a>
# 🎬 易好短劇 PySide6 版(日本語)

**AI によるショートドラマ・小説・漫画のワンストップ制作ツール**(Python 3.10+ / PySide6)。オープンソース [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) の全機能を再実装し、[golanse/easymerger](https://github.com/golanse/easymerger)(ロスレス結合)と [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)(動画複製)の核心ロジックを統合しました。

## 🌐 対応言語 — 15 言語

**UI 言語と AI 出力言語は同じスイッチで**、15 言語に対応:

中国語 / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

切り替えると、画面表示と AI が生成するすべてのコンテンツ(脚本・アセット・絵コンテ・プロンプト・小説・宣伝文)が同じ言語で出力されます。

## 主な機能

- **5 つの創作目標**:小説 / ショートドラマ / 漫画 / プロモーション / 動画複製
- **6 段階ワークベンチ**:原文 → AI リライト → アセット → 絵コンテ → 漫画 → 結合・書き出し
- **10 種類の AI Agent**(System Prompt は全て編集可能)
- **マルチプロバイダ AI**(OpenAI 互換 / Gemini / 火山 Seedance / MiniMax / 阿里 Wan / Agnes / ローカル顔交換)
- **ロスレス結合ツール**:ffprobe によるパラメータ一致判定(解像度/コーデック/FPS/Profile)→ `-c copy` / スマートパススルー / 外れ値整列の 3 チャネル + 失敗時フォールバック
- **小説制作**:企画 → 逐章生成 → 6 観点レビュー → 加筆 → 全編書き出し

## 📊 機能対応表（原版 Web ↔ 本デスクトップ版）

### 原版のモジュール — すべて対応

| 原版モジュール | 原版ファイル | 本版 | |
|---|---|---|---|
| プロジェクト起動台 | `pages/index.vue` | `ProjectsPage` | ✅ |
| 新規プロジェクト（5 目標） | 同上 | `NewProjectDialog` | ✅ |
| プロジェクト詳細 / 話数一覧 | `views/drama/detail.vue` | `ProjectPage` | ✅ |
| プロジェクト設定 | detail.vue ダイアログ | `ProjectSettingsDialog` | ✅ |
| アセットライブラリ | detail.vue | `AssetDetailDialog` | ✅ |
| エピソードスタジオ（6 段階） | `episode.vue`（11.6k 行） | `EpisodePage` | ✅ |
| 原文 / AI リライト | scriptStep | `raw` / `rewrite` パネル | ✅ |
| アセット | prodTab assets | `assets` パネル（通常/コミック） | ✅ |
| 絵コンテ / 動画 | prodTab videos | `storyboard` パネル | ✅ |
| コミック | prodTab comic | `comic` パネル | ✅ |
| 結合・書き出し | prodTab export | `export` パネル | ✅ |
| 設定（6 セクション） | `pages/settings.vue` | `SettingsDialog` | ✅ |
| Agent 設定 | settings.vue | System Prompt / Skills タブ | ✅ |
| スタイルプリセット | settings.vue | 20 シード + 編集 | ✅ |
| AI サービス（5 種） | settings.vue | `ServiceDialog` | ✅ |
| 顔入れ替え | `tools/face-swap.vue` | アセットのキャラカード内 | ✅ |
| タスクパネル | `useTaskDrawer` | `TaskPanel` | ✅ |

### 多言語の深み — 原版を超えた点

| 機能 | 原版 Web | 本版 |
|---|---|---|
| UI 言語 | 15 | 15 |
| AI コンテンツ言語 | 15 | 15（全体 + **プロジェクト個別**） |
| Agent プロンプト変種 | 4 言語固定 | **15 言語**（150 ファイル） |
| Skill 変種 | 4 | **15**（165 ファイル） |

### 信頼性の強化

| 機能 | 目的 |
|---|---|
| LLM ハングタイムアウト | `AI_LLM_TIMEOUT_MS`（既定 300 秒）— 応答しないプロバイダ対策 |
| タスク段階の可視化 | `writing → reviewing → repairing → splitting` を記録 |
| 書き込み後の検証 | 成功は DB 判定、`content < 200` は失敗扱い |
| 絵コンテのバックグラウンド分割 | 再入防止 + ゴミ行掃除 + 6 秒ポーリング |
| 上書き防止 | 本文がある章は batch 拒否、明示操作時のみ許可 |
| 中断タスクの整理 | 再起動時、出力の実着地で completed/failed を判定 |
| 参考画像インデックス | 単一真実源、`@画像N ≡ reference_image_urls[N-1]` |

### 本版のみの追加機能

| 機能 | 備考 |
|---|---|
| 話数の一括作成 | 1〜999 話を一度に挿入 |
| 伏線台帳 | LCS≥5 の重複排除、上限 40、対話的トグル |
| レビュー詳細 / 全書レビュー一覧 | 項目チェック、章へのジャンプ |
| 章全体の読み上げ | 600 字分割、逐次 TTS を MP3 結合 |
| 三区画プログレスバー | 成功 / 失敗 / 実行中 + 章ごとの段階 |
| 制作段階バー | 生成物から 5 状態を判定 |
| 文字数プログレス | `X / Y 字`、80% 未満は琥珀色 |
| カバー体系 | プロジェクト / 章カバー、ともに 3:4 |
| 速度適応 TTS | デュアルエンジン + 実測で長ければ再合成 |
| AI 未設定ガード | 設定不足時はボタン押下で即座に明示 |
| 自動更新 | Releases 確認 → バックアップ → 再起動確認 |
| ロスレス結合 | パラメータ検査 + 3 チャネル + フォールバック |
| 同款复刻 | ヒット動画の構造を製品へ移行 |

## クイックスタート

```bash
pip install -r requirements.txt   # Python 3.10+
python app/main.py
```

ライセンス:CC BY-NC-SA 4.0(原プロジェクトより継承)。

---

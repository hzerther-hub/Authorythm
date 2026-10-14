<!-- 此注释表明此 README 的语言。其它语言的 README 见同目录下的兄弟文件。 -->
> **语言 / Language / 言語 / 언어**: [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | **English** | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 易好短剧 · PySide6 版 / Yihao Shorts (PySide6 Edition)

AI 短剧/小说/漫画一站式制作工具。功能 100% 对齐开源项目 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版),并集成了两个社区工具的核心能力:
- **[golanse/easymerger](https://github.com/golanse/easymerger)** — 无损视频合并(参数检测/智能直通/一键对齐异类)
- **[liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)** — 同款复刻(爆款视频结构迁移到你的产品)

> 黑盒分析报告: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)

---
<a name="english"></a>
# 🎬 Yihao Shorts (PySide6 Edition)

**A one-stop AI studio for short dramas, novels and comics**, rebuilt in PySide6 (Python 3.10+). Feature-complete rewrite of [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git), plus core logic from [golanse/easymerger](https://github.com/golanse/easymerger) (lossless merging) and [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite) (viral-video cloning).

## 🌐 Languages — 15 supported

**UI language and AI-content language share one switch**, available in 15 languages:

Chinese / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

Switching updates both the interface and all AI output (scripts, asset extraction, storyboards, prompts, novels, marketing copy). Languages outside zh/en/ja/ko are enforced via an explicit output-language directive appended to each agent's system prompt.

**Beyond the original**: agent prompts and skills ship in **all 15 languages** here (150 prompt + 165 skill files), and each project can fix its own content language independently of the global setting.

## Features

- **5 creative goals**: novel / short drama / comic / promotion (6 platforms × 6 formats) / video clone
- **6-stage studio**: raw text → AI rewrite → assets → storyboard → comic → merge & export
- **10 AI agents** with fully editable system prompts (`workspace/prompts/*.md`)
- **Multi-provider AI services**: text/image/video/TTS (OpenAI-compatible, Gemini, Volcengine Seedance/Seedream, MiniMax, Aliyun Wan, Agnes, qwen-image, local InsightFace face-swap)
- **Lossless merger tool**: ffprobe parameter consistency check (resolution/codec/fps/profile/sample-rate) → lossless concat (`-c copy`), smart passthrough (video copy + audio aligned), or align-outliers-then-merge; with fallback chain
- **Video clone**: analyze reference video → AI storyboard → your product/presenter → shot-by-shot re-generation → lossless merge
- **Novel pipeline**: planning → chapter writing → 6-dimension review → editing → full book export
- **20 style presets** faithful to the original (cinematic quality anchors), SQLite storage (23 tables)

## 📊 Feature mapping (original Web ↔ this desktop build)

### Original modules — all covered

| Original module | Original file | Here | |
|---|---|---|---|
| Project launcher | `pages/index.vue` | `ProjectsPage` | ✅ |
| New project (5 goals) | same | `NewProjectDialog` | ✅ |
| Project detail / episode list | `views/drama/detail.vue` | `ProjectPage` | ✅ |
| Project settings | detail.vue dialog | `ProjectSettingsDialog` | ✅ |
| Asset library (chars/scenes/props) | detail.vue | `AssetDetailDialog` | ✅ |
| Episode studio (6 stages) | `views/drama/episode.vue` (11.6k lines) | `EpisodePage` | ✅ |
| Raw text / AI rewrite | scriptStep | `raw` / `rewrite` panels | ✅ |
| Assets | prodTab assets | `assets` panel (normal + comic tabs) | ✅ |
| Storyboard / video | prodTab videos | `storyboard` panel | ✅ |
| Comic | prodTab comic | `comic` panel | ✅ |
| Merge & export | prodTab export | `export` panel | ✅ |
| Settings (6 sections) | `pages/settings.vue` | `SettingsDialog` | ✅ |
| Agent config | settings.vue | System Prompt / Skills dual tabs | ✅ |
| Style presets | settings.vue | 20 seeds + editor | ✅ |
| AI services (5 types) | settings.vue | `ServiceDialog` | ✅ |
| Face swap | `tools/face-swap.vue` | in-dialog on asset character card | ✅ |
| Task panel | `useTaskDrawer` | `TaskPanel` | ✅ |

### Multilingual depth — beyond the original

| Capability | Original Web | Here |
|---|---|---|
| UI languages | 15 | 15 |
| AI content languages | 15 (per project) | 15 (global **+ independent per project**) |
| Agent prompt variants | 4 hardcoded | **15** (150 files) |
| Skill variants | 4 | **15** (165 files, incl. fight-cinematography) |

### Reliability hardening

| Capability | Why |
|---|---|
| LLM hang timeout | `AI_LLM_TIMEOUT_MS` (300s default) — providers that accept the connection but never answer |
| Task stage visibility | `writing → reviewing → repairing → splitting` stored in `sys_task.params.stage` |
| Write-after verify | success judged from the DB; `content < 200` = failure (no "completed but empty chapter") |
| Background storyboard split | re-entrancy guard + junk-row cleanup + 6s polling (the original synchronous HTTP gets cut off) |
| Overwrite protection | chapters with existing text are rejected unless you explicitly hit "rewrite" |
| Interrupted task settling | on restart, completed/failed decided by whether output actually landed |
| Reference-image indexing | single source of truth; `@图片N ≡ reference_image_urls[N-1]` |

### Additions not in the original

| Capability | Notes |
|---|---|
| Bulk episode creation | 1–999 episodes inserted in one go |
| Foreshadowing ledger | LCS≥5 dedup, 40-item cap, chapter backfill, interactive toggle |
| Review detail / book-wide review list | per-item checkbox, jump to chapter |
| Full-chapter read-aloud | sentence-split at 600 chars, per-chunk TTS concatenated to MP3 |
| Three-segment progress bar | ok / fail / running + legend + per-chapter stage |
| Production stage bar | derived from actual artifacts, 5 states |
| Word-count progress | `X / Y 字`, amber below 80% |
| Cover system | project cover (with asset reference) + per-chapter cover, both 3:4 |
| Speed-adaptive TTS | dual engine + ffprobe-measured re-synthesis when too long |
| AI readiness guard | missing config/Key blocks the button with a clear message |
| Auto update | GitHub Releases check → backup & overwrite → ask to restart |
| Lossless merger | ffprobe param check + three-channel merge + fallback chain |
| Video clone | migrate a viral video's structure onto your product |

## Quick start

```bash
pip install -r requirements.txt   # Python 3.10+
python app/main.py
```

Data lives in `data/`; configure AI providers in Settings → AI Services (or paste a Yihao API Key for one-click setup).

License: CC BY-NC-SA 4.0 (inherited from the original project).

---

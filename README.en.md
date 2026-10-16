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
## 📖 Novel Generation Logic & How "Novel Plan & Settings" Drives It

### Overview

pydrama novel-mode (`work_type=novel`) generation lives in `app/pipeline/novel.py` and is a **two-phase AI call chain**:
1. **Plan & Settings** — `NovelPlanDialog` (`app/ui/novel_dialogs.py`) lets the user author 4 setting blocks → `AI drafts each block → saves to dramas table`
2. **Chapter generation** — `generate_chapters_batched` → `write_chapter_with_review` → **LangGraph review loop**

### title / intro / genre — the three input anchors

| Field | Source | Used for |
|---|---|---|
| **title** | `dramas.title` (user typed) | Filename / launchpad card / every prompt anchor |
| **intro** | `novel_meta.intro`, user-typed then **AI-autofills** | Injected as prompt context for every chapter — model gets "what this project is" |
| **genre** | `novel_meta.genre`, user-picked from the style preset list | Injected as `style:` prefix in chapter prompts — controls writing voice |

### How `NovelPlanDialog` & its 4 setting blocks drive novel generation

`NovelPlanDialog` lets the user fill **4 setting blocks**; each block has its own AI-draft task, but they have a **PREREQ dependency chain**:

```
PREREQ dependencies:
  outline  (总纲 / synopsis) — the foundation; nothing else writes without it
       ↓
  world    (世界观 / world)   — expands within outline's setting envelope
       ↓
  contract (故事合约 / narrative contract) — POV / voice / hard constraints
       ↓
  volume   (分卷战略 / volume plan) — splits outline into volumes
```

#### What each block stores & how it feeds chapter generation

| Block | Storage location | Injected as prompt context for chapter generation |
|---|---|---|
| **outline (总纲)** | `dramas.novel_outline` | Project direction · main characters · core conflict |
| **world (世界观)** | `dramas.novel_world` | Time · geography · rules · customs; characters cannot break these |
| **contract (合约)** | `dramas.novel_contract` | POV · register · style · hard constraints (e.g. "no magic") |
| **volume (分卷)** | `dramas.novel_volume` | Where the current chapter sits within its volume + volume-level arc |

Combined with the user's `plan_novel(drama_id, idea, ...)` input (stored as `novel_meta.intro`, used as the seed for `AI draft outline`), **these 5 contexts together compose every chapter-generation prompt**. Skip any one and chapters drift — the model loses track of POV / setting / voice.

### Chapter generation + review flow (Phase C.1 + C.2)

`write_chapter_with_review` (`app/pipeline/novel.py:918`) now internally calls `run_novel_review_loop`.
`run_novel_review_loop` (`app/agents/novel_review_flow.py`) has 5 nodes:

```
   ┌──────────┐    ┌─────────┐
   │  WRITER  │───▶│ CRITIC  │
   └──────────┘    └────┬────┘
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
  ┌─ REPAIR ─┐   ┌─ COMPRESSOR  ┐  ┌─ END ┐
  │   ▲      │   │   (terminal) │  │      │
  └─JEV──────┘   └───────────────┘  └──────┘
```

- **WRITER** — calls `write_chapter(episode_id, ...)`; sets `sys_task.stage='writing'`
- **CRITIC** — calls `review_chapter(episode_id, ...)`, runs the six-axis critique (continuity / pacing / prose / character / setting / tone)
  - `overall=pass`  → **OK** → COMPRESSOR
  - `overall=fix` + 1-4 issues → **revise** → REPAIR
  - `overall=fix` + ≥5 issues  → **rewrite** → WRITER (faster to redraft than patch)
  - cycle ≥ `max_cycles` (default 3) → **giveup** (forced termination)
- **REPAIR** — calls `run_agent("novel_editor", ...)` for a revised draft; saves to DB
- **JEV GATE** — calls `jev_gate().client.decide(...)` for **continuity check**:
  - score < 0.5  → **rewrite** → back to WRITER
  - score ≥ 0.5  → **pass** → one more CRITIC pass
  - unconfigured / error → fallback (continue to CRITIC)
- **COMPRESSOR** — terminal node; pushes the passing draft into `final[]` for caller to commit.

### LangGraph vs Fallback — two tracks, same logic

| Mode | Trigger | Value |
|---|---|---|
| **Fallback** (default) | LangGraph not installed | Same node functions run inline in a cycle loop — behavior identical |
| **LangGraph real graph** | `pip install langgraph` | Auto-switches to StateGraph; supports LangSmith traces + `interrupt_before=["jev_gate"]` mid-flow pausing |

Zero-code switch: just `pip install langgraph`. The 13 other-language READMEs in this repo link to this section for the full description.


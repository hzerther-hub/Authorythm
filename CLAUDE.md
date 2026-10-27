# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**深坑目录见 [AGENTS.md](AGENTS.md)**(线程模型 / Jev 能力边界 / 三视图提示词管线 / i18n / Qt 布局坑 / 测试段 id 冲突等,全部带实测依据)。本文件只写命令与大局,不重复它。

## 项目是什么

「易好短剧」PySide6 桌面版 —— AI 短剧/小说/漫画一站式制作工具,**功能对齐开源 Web 版** `ooooinfo/yihao_drama`。上游参照仓库在本机 `E:\xiaoshuo`(Node backend + Vue frontend);另有三个社区工具的逻辑已融入:easymerger(无损合并)、video-clone-lite(同款复刻)、director-desk(导演台预演,内嵌其 web 构建)。

**核心工作模式 = 对齐 E:\xiaoshuo**:改动某个功能前,先读原版对应实现(`backend/src/routes/*.ts` / `services/adapters/*.ts`),逐项比对找偏差再修;发现「桌面版更有利」的差异(如出图规格、语言继承)可以保留,但要在代码注释与 `PROGRESS.md` 里写明是有意不对齐。原版用 `git log` 确认功能对应提交(对齐时以提交为基准,别对 HEAD 拍脑袋)。

## 常用命令

```bash
pip install -r requirements.txt        # 运行依赖(PySide6/requests/Pillow/edge-tts/cryptography…)
pip install -r requirements-dev.txt    # 开发(ruff/mypy/pytest)

python -m app.main                     # 启动 GUI(Windows 桌面;start.bat 同)
python -m pytest tests/ -q             # 全量回归(约 30s,800+ 用例)
python -m pytest tests/test_book_import.py -q        # 单文件
python -m pytest tests/test_book_import.py::test_short_book_splits_by_chapter_headings -q   # 单用例
ruff check .                           # lint(CI 会跑)
mypy                                   # 类型检查(core/ai/agents/pipeline;ui/ 与 tests/ 未纳入)
python scripts/i18n_audit.py           # 16 语言 i18n 缺口体检(改 UI 文案/翻译后跑)
python scripts/readme_factcheck.py     # README 里的数字与仓库实际状态对账
```

- Git Bash 启动用 `start.ps1`,**不要** `cmd //c start.bat`(路径编码炸)。**启动/验收应用前先读 [STARTUP.md](STARTUP.md)**(「怎么跑起来」的唯一真相源:启动判据、失败对照表、环境事实)。
- **PySide6 版本敏感,分环境两种事实**(2026-10-27 双会话实测):CI/干净机器走 requirements.txt 的 `>=6.6.0,<6.10`(6.9.x 三平台 CI 全绿);**本机(Anaconda)必须 pip 完整发行版 6.11.3 + `PySide6/icuuc.dll` 副本,勿动** —— 装回 6.9.2 在本机 CPython 3.13.9 上多模块连导必炸,且单模块 `import QtCore` 测试会骗过你。换版本前必读 STARTUP.md 与 AGENTS.md「PySide6 版本」。
- CI(GitHub Actions,三平台 × py3.13)跑 ruff + mypy + pytest,测试环境 `QT_QPA_PLATFORM=offscreen`、`PYDRAMA_OFFLINE=1`(测试不许联网、不许真调 LLM)、`PYDRAMA_TEST_MODE=1`,pytest 带 `--timeout=60 -x`(单用例 60s 超时即红、首个失败即停 —— 新测试跑超过 60s 就是写法错了)。

## 大局架构

**分层单向依赖**:`app/ui → app/pipeline → app/ai → app/core`,`core` 不 import 上层(实测全仓扫描确认)。已知例外(函数内懒导入,为绕循环依赖,别当 bug 修):`pipeline/comic.py:_style_for` 被 storyboard/prompts_gen 反向复用;`ai/photocraft_bridge.py` 懒导入 `pipeline/inpaint.py` 的 `inpaint_masked`。

- `app/core/` 基建:`db.py`(SQLite 29 张表;源码里有 30 处 `CREATE TABLE`,因 `storyboard_scenes` 在迁移列表重复定义一次给老库补表 —— 数表数别按 CREATE TABLE 计数。`q/q1/ex/exmany`,连接 **thread-local** —— 后台线程各自建连,这点支撑了 pipeline 里的多线程并发)、`config.py`(路径/ffmpeg 探测)、`i18n.py + ui_strings.py`(16 语言)、`taskmgr.py`(QThreadPool 上限 6)、`secrets.py`(API Key Fernet 加密)、`logging_setup.py` / `metrics.py`、`encoding.py`(乱码防护:GBK 误读不可逆,必须抛 `MojibakeError` 中止,绝不静默落库)、`preflight.py`(AI 未就绪拦截,按钮点击即校验)。
- `app/ai/` 供应商客户端:`registry.py`(配置 CRUD + `check_ready` 就绪判定 + `PROVIDER_PRESETS` 模板)、`text/image/video/tts_client.py`、`face_swap.py`,另有 `jev_client/ask/gate`(辅助判定服务,只作线索不进决策,能力边界见 AGENTS.md)、`prompt_guards.py`(人数/画风守卫)、`photocraft_bridge.py` / `text_replace_skill.py`(PhotoCraft 桥接 / 多模态改图)。多供应商统一走 OpenAI 兼容 + 各家原生协议;TTS 是**四通道**(火山豆包收费 / Edge 免费 / 本机 Windows 离线 / 降级链,显式选免费通道不降级)。
- `app/agents/`:`runner.run_agent(type, prompt)` 单次调 LLM(无工具),System Prompt 从 `workspace/prompts/<type>.<lang>.md` 加载(用户可改,150+ 文件);`runner.extract_json()` 是**唯一** JSON 解析入口 —— 必须先剥 `<think>` 再剥围栏(推理型模型必坑)。繁体(zh-Hant)产出在 runner 出口统一 OpenCC 转换,不走 AI。
- `app/pipeline/` 业务编排:`novel.py`(小说线,规划/正文双模型分设 + LangGraph 审校循环)、`book_import.py`(TXT 整书导入→Map-Reduce 分析→仿写新书三段式)、`storyboard.py` / `comic.py` / `comic_pipeline.py`、`video_clone.py`(同款复刻)、`previz*.py`(导演台)、`overseas.py`(海外改写)、`merge.py`(无损合并)、`state_ledger.py`(人物状态台账 —— 长篇跨章的「世界状态事实层」,提取→合并→Jev 门控,全链路软失败)、`storyboard_repair.py`(拆分中途失败留下的残缺分镜自动补全,成败以落库为准)。
- `app/ui/`:页面 + 对话框;`main_window.py` 持有 QStackedWidget 与 `_open_drama(drama_id)` 导航;`episode_page.py` 最大(六阶段工作台,≈8k 行)。
- 数据全部落 `data/`(SQLite + 媒体文件,gitignore);`data/vendor/directordesk/` 是导演台渲染内核(fetch 脚本下载,不入库)。

**新增页面的三处同步**(`_PAGE_KINDS` / `_make_page` / `_goto` 映射)、worker 线程禁碰 Qt 控件等坑,详见 AGENTS.md「Qt / UI 约定」与「线程模型」。

## 必须遵守的项目规则(违反会被测试或用户数据咬)

1. **测试绝不碰真实库** `data/yihao.sqlite3`。落库路径一律 `tmp_path` + `monkeypatch.setattr(db.config, "DB_PATH", ...)` + 重置 `db._local.conn`(见 `tests/test_overseas_pipeline.py` 的 `tmp_db` fixture);LLM/PowerShell/网络调用一律 monkeypatch 打桩。测试段的 `ai_service_configs` id 冲突坑见 AGENTS.md。
2. **新增 UI 文案**:`tr()` 的字面量中文 key 必须同步补 `i18n.py` 主表(中文基准)+ `ui_strings.py` 的 **15 语言 list**(列序 `zh en ja ko ar hi id th tr vi fr de es pt it`),`tests/test_i18n_coverage.py` 会抓漏。带参数用 `{0}` 位置占位。
3. **Python 3.10+ 兼容**:`tests/test_py310_compat.py` 守着 —— 嵌套 f-string 里同引号复用/反斜杠转义是 3.12+ 语法,禁止。
4. **密钥不进代码**:Key 一律 `registry` 加密落库或环境变量/设置表;提交前 `git grep -nIE "[\"'](sk-[A-Za-z0-9]{16,}|[0-9a-f]{40,})[\"']" -- '*.py'` 自查。本仓库 public,历史里泄露过的 key 必须服务端作废。
5. **注释写「为什么」并记实测坑**(带数据),不写「这做了什么」—— 这是本仓库注释文化的核心,大量修 bug 的依据就在注释里。
6. **过程记录**:`PROGRESS.md` 按轮次追加(文件头写「倒序」但实际是**尾部追加**,最新在最后),每轮记改动/依据/测试数;计划在 `PLAN.md`,黑盒分析在 `docs/易好短剧-工具分析.md`。
7. ffmpeg 走外部二进制(`config.find_ffmpeg()`),不要假设 PATH 里有;ffmpeg 子进程**失败不抛异常**,必须查 returncode / 产物存在性。

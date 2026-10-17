# max_tokens 与上下文配置说明(给 AI 的修改任务书)

> 交付给 AI 的目标:排查/修复「章节计划生成失败」,重点核查 **最大输出 token
> (max_tokens)** 与上下文配置。本文档给出全部事实位置、取值链、当前值与
> 验证方法。修改代码后必须 `git commit` + `git push`,另一台机器 `git pull` 后
> 重启应用生效。

## 1. 症状

- 操作:「小说策划与设定 → 章节计划 → AI 生成章节计划」(重工众生,全书 500
  章,第 1 卷 [1-80],每章 2500 字,规划模型 deepseek-v4-pro,80 章分 2 批)。
- 报错 toast 只显示 traceback 头部(已在新代码修复:toast 现取末行真实异常)。
- 高度怀疑方向:**输出截断**。单批 40 章 × 每章计划约 150-250 字,加上
  deepseek-v4-pro 的思考段(思考与正文**共用**输出预算),输出轻松超过
  8192 默认值。代码里对截断有显式判定:
  `RuntimeError: 第 X-Y 章生成失败(返回 N 字,疑似被截断)`。

## 2. max_tokens 取值链(权威实现)

`app/ai/text_client.py` → `_build_body()`(chat 与 chat_stream 共用):

```python
mt = max_tokens                      # ① 调用方显式传值,最优先
if mt is None:
    mt = int(cfg.get("max_tokens") or 0) or None   # ② 服务配置手填值
body["max_tokens"] = mt or 8192      # ③ 兜底默认 8192
```

结论:**调用方没传时,由「AI 服务配置」里的 max_tokens 字段决定;留空 = 8192**。

## 3. 配置在哪里改(三种方式,任选)

### 方式 A:应用界面(推荐)

`设置 → AI 服务 → 选中服务 → 编辑`:

- **最大输出 token**:实际发给模型的 `max_tokens`(如 32768)
- **上下文长度**:仅作提示/校验,不进请求体(`settings_dialog.py` 注释原文)
- 已有内置提示:「思考型模型(deepseek-v4-pro / MiniMax-M3 等)思考与正文共用
  输出预算,最大输出填太小会把正文截断,建议 32768 以上」

### 方式 B:直接改 SQLite(`data/yihao.sqlite3`)

```sql
-- 查看当前文本服务配置
SELECT id, provider, model, max_tokens, is_active
  FROM ai_service_configs WHERE service_type='text';

-- 调大最大输出(例:deepseek-v4-pro 调到 65536;上限以服务商文档为准)
UPDATE ai_service_configs SET max_tokens=65534 WHERE id=13 AND service_type='text';
```

字段:`ai_service_configs.max_tokens`(可空,NULL=走 8192 兜底)。

### 方式 C:改代码默认值

`app/ai/text_client.py` `_build_body` 末行 `body["max_tokens"] = mt or 8192`
—— 把 8192 改大(影响所有未显式传值、配置也未填的调用,**慎用**)。

## 4. 当前值参考(一台已配好的机器,2026-10)

| id | provider | model | max_tokens | 用途 |
|----|----------|-------|-----------|------|
| 4  | minimax  | MiniMax-M3     | 32768 | 正文模型(novel.prose_cfg) |
| 10 | GLM      | glm-5.3        | 32768 | 备用 |
| 13 | deepseek | deepseek-v4-pro| 32768 | 规划模型(novel.plan_cfg) |
| 14 | agnes    | agnes-3.0-flash| (空)  | 未启用 |

规划/正文模型选择键:`app_settings` 表 `yihao.novel.plan_cfg` / `yihao.novel.prose_cfg`
(值为 ai_service_configs.id)。**注意每台机器的 id 不同,先查再改。**

## 5. 相关代码位置(要改代码看这里)

| 位置 | 作用 |
|------|------|
| `app/ai/text_client.py` `_build_body` | max_tokens 取值链(§2) |
| `app/ui/settings_dialog.py` | 「上下文长度」「最大输出 token」输入框 + 思考型模型提示文案 |
| `app/ai/registry.py` `add_config` / `update_config` | max_tokens 字段落库 |
| `app/pipeline/novel.py` `CHAPTER_BATCH = 40` | 章节计划每批章数;**调小(如 20)可显著降低单批输出需求** |
| `app/pipeline/novel.py` `_clean_chapter_list` 调用处 | 截断判定报错「疑似被截断」 |
| `app/core/taskmgr.py` `short_error` | 报错 toast 取 traceback 末行(已修) |

## 6. 建议的修改顺序

1. 先把规划模型(deepseek-v4-pro)的「最大输出 token」确认 ≥ 32768;
   若服务商文档允许更大(如 65536),可再调大,**不超过模型官方输出上限**。
2. 重跑「AI 生成章节计划」。若仍报「疑似被截断」:
   - 把 `app/pipeline/novel.py` 的 `CHAPTER_BATCH` 从 40 调到 20(单批输出
     需求减半,代价是批次数翻倍、总时长变长);
   - 或在「AI 服务」里换一个输出上限更大的模型当规划模型。
3. 上下文长度(输入侧)如果模型报 context 超限,再核对模型官方上下文窗口,
   同步填到「上下文长度」字段(仅提示用,不影响请求体)。

## 7. 提交与同步

改完(无论配置方式 B 还是代码方式 C)必须:

```bash
git add -A && git commit -m "调大规划模型 max_tokens/降低章节计划批量" && git push
```

另一台运行应用的机器 `git pull` 后**重启应用**(SQLite 配置方式 B 只存在
于本机 `data/`,不随 git 走 —— 两台机器要各自改一次,或都用方式 C 走代码)。

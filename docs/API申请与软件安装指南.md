# API 申请与软件安装指南

> 本指南给两类读者:① 直接照着做的用户;② **AI 助手** —— 把本文件发给任意 AI
> (或告诉它本文件路径),它可以一步步辅助你完成申请与配置。
> 填 key 的统一入口:**易好短剧 → 设置 → AI 服务 → 对应标签页**。
> 所有配置**只存本机** SQLite(`data/yihao.sqlite3`),不进版本库、不上传。

---

## 〇、最少可用配置(只想先跑起来)

| 想做什么 | 至少需要 |
|---|---|
| 写小说 / 分镜 / 改写(文本) | 任一文本服务 key(MiniMax / DeepSeek / GLM / Agnes 选一) |
| 生成图片(角色/场景/首帧) | Agnes 图片 key(推荐,支持参考图) |
| 生成视频 | Agnes 视频或 火山方舟 Seedance key |
| 配音 | 不配也能用(自动落免费微软 Edge 音色);配豆包语音则音质/时长对齐更好 |
| 聊天改图全部功能 | PhotoCraft CLI(免费软件,见「软件下载」) |
| 意图路由 / 实时网站查询(可选) | Jev key(TypeSafe)+ jev-ultrafast —— 见《Jev与浏览器实时查询指南.md》 |

---

## 一、文本模型(写小说 / 分镜 / 提取 / AI 改写)

| 服务 | 申请入口 | 说明 |
|---|---|---|
| MiniMax | https://platform.minimaxi.com | 注册 → 控制台创建 API Key;本仓默认模型 MiniMax-M3(多模态、带推理) |
| DeepSeek | https://platform.deepseek.com | 创建 API Key;便宜稳定,填表类任务快 |
| 智谱 GLM | https://open.bigmodel.cn | 创建 API Key;glm-5.3 |
| Agnes | https://apihub.agnes-ai.com | 文本/图片/视频一家全包(本项目预设多家都走 Agnes) |

填法:设置 → AI 服务 → 「文本」标签 → 对应卡片编辑 → 粘贴 API Key → 测试。

## 二、图片生成(角色形象 / 场景 / 首帧)

| 服务 | 申请入口 | 说明 |
|---|---|---|
| **Agnes(推荐)** | https://apihub.agnes-ai.com | **支持参考图** —— 角色一致性、换画风、首帧都依赖它;其它家传参考图会被忽略 |
| 火山方舟 · 豆包 Seedream | https://console.volcengine.com/ark | 控制台开通模型 → API Key;注意模型名要与控制台开通的一致(名字错会 404) |

⚠ 换画风 / 角色一致性必须用**支持参考图**的模型:agnes / local / comfyui / sdwebui / fooocus。

## 三、视频生成(分镜出片)

| 服务 | 申请入口 | 说明 |
|---|---|---|
| Agnes 视频 | https://apihub.agnes-ai.com | agnes-video-2.5-flash;支持参考图 |
| 火山方舟 · Seedance | https://console.volcengine.com/ark | doubao-seedance-2-0-mini / fast / 标准版;**模型名必须与控制台开通的一致**(错一名 = 全部 404);时长支持 4–12 秒,3 秒不支持 |

计费提示:视频按秒计费,批量前先用单镜试一条。

## 四、配音(TTS)

| 引擎 | 需要配置吗 | 说明 |
|---|---|---|
| **微软 Edge(默认兜底)** | ❌ 不需要,零配置 | 免费微软神经音色(16 语言 × 男女);不配任何 TTS key 时自动使用 |
| 火山方舟 · 豆包语音 | 需要方舟 API Key | 音色更有情感、支持旁白时长对齐镜头;按字符计费 |

切换方式:设置 → AI 服务 → 「配音」标签 → 启用/停用「豆包语音」开关。停用即全自动免费 Edge。

## 五、图库搜图(找参考图 / 美女图等)

三家免费图库,任配一家即可(也可全配,「全部图库」会聚合):

| 图库 | 申请入口 | 说明 |
|---|---|---|
| Pexels | https://www.pexels.com/api/ | 免费申请,秒发 key |
| Unsplash | https://unsplash.com/developers | 免费申请;Demo 应用限额较低 |
| Pixabay | https://pixabay.com/api/docs/ | 免费申请 |

填法:设置 → AI 服务 → 「图库」标签 → 添加 → 粘贴 Key。

## 六、PhotoCraft(聊天改图 / 局部重绘的引擎,免费软件)

- 下载:https://github.com/storytold/photocraft (Releases 里下 `photocraft-0.7.0-windows-x64-portable` 压缩包)
- 安装:解压到任意目录(如 `E:\photocraft\`)
- 配置:设置 → PhotoCraft → 填解压目录(里面有 `photocraft-cli.exe`)→ 测试
- 没装也能用大部分功能(内置图像编辑器兜底),但「聊天改图」的白名单命令、
  「我手动改」接力需要它。

## 七、浏览器实时查询(可选,实验)

查火车/天气等实时信息时用本机 Chrome 上官网真查(消耗 Jev 决策调用,默认关闭)。
需要:本机装有 Chrome;设置 → AI 服务 → 勾选「浏览器实时查询(实验)」。

## 八、交给 AI 助手安装

把本文件发给任意 AI 助手(或告诉它本文件路径),说:
「按这份指南帮我申请并配置 XXX 服务」—— AI 会逐步引导:
注册 → 建 Key → 打开易好短剧设置页 → 填入 → 点测试。

---

## 附:常见错误对照

| 现象 | 原因 |
|---|---|
| HTTP 404 InvalidEndpointOrModel.NotFound | 模型名与控制台开通的不一致(差一个字母都不行) |
| HTTP 400 InvalidParameter: role must be specified | 请求体图片缺 role 字段(本仓已修,遇到即报 bug) |
| HTTP 429 / Throttling.AllocationQuota | 额度耗尽或限流,等退避或充值 |
| 提取/分镜报「无法解析为 JSON」 | 推理模型偶发写坏 JSON,重试一次通常就好(已自动重试) |
| 配音是英文播报感音色 | 走了免费 Edge 兜底 —— 豆包配置停用中,启用即切回 |

# Jev 与浏览器实时查询(jev-ultrafast)申请配置指南

> 读者同《API申请与软件安装指南》:① 照着做的用户;② **AI 助手**(把本文件
> 发给 AI,它可以逐步辅助)。所有 key **只存本机** SQLite,不进版本库。
> 前置阅读:主指南《API申请与软件安装指南.md》(文本服务 key 是本指南的前置)。

---

## 〇、这两样东西是什么、值不值得配

| 名称 | 本质 | 在本应用里干什么 | 不配会怎样 |
|---|---|---|---|
| **Jev**(TypeSafe 出品) | 决策模型:只输出「选了哪个选项 + 概率」,**不生成文本** | 聊天改图意图路由(聊天/改图/知识/找图/联网查询五选一)、快捷命令近似匹配(「改黑白」→「改成黑白」) | 全部软降级:问句规则兜底,聊天/改图照常用,只是灰色地带判得差些 |
| **jev-ultrafast**(Browser Use × TypeSafe 开源) | 浏览器 Agent:Jev 决策「点哪里」,文本模型填表单 | 实时网站查询:聊「查宁波到淄博的火车」自动上 12306 真查(网页搜索只能给链接) | 联网查询落回「搜索+读结果页正文」,够用但拿不到实时余票 |

**成本提示**:Jev 单次调用极便宜(输出几十 token);但浏览器查一次重站
(12306)要烧 **200+ 次** Jev 决策,所以浏览器查询**默认关闭**(见 §4 开关)。

---

## 一、申请 Jev API Key(TypeSafe 官方)

1. 打开 TypeSafe 文档/控制台:**https://docs.typesafe.ai/introduction**
   → 按站内指引注册账号、创建 API Key。
2. 复制 key(形如 `ts-...` 的长串)。
3. 打开应用:**设置 → AI 服务 → 「Jev」标签页**:
   - 预设已内置「TypeSafe AI · Jev」,base_url 固定 `https://api.typesafe.ai`;
   - 模型填 `jev-latest`(当前唯一型号);
   - 粘贴 key → 点「测试配置」,显示就绪即成。
4. 配置落在本机 `data/yihao.sqlite3` 的 `ai_service_configs`
   (`service_type='jev'`),不进版本库。

> 本应用所有 Jev 调用走 `POST {base_url}/v1/systemone`,任何失败
> (未配/断网/限流)**一律软降级**,绝不打断改图业务。

---

## 二、安装 jev-ultrafast(浏览器 Agent,可选)

只在想要「实时网站查询」时安装。Windows 命令行执行:

```bash
pip install browser-use
pip install git+https://github.com/browser-use/jev-ultrafast
```

- 不在 PyPI 的是主仓快照,官方源就是 GitHub(上文 git+https 直装)。
- 还需要本机装有 **Chrome 或 Edge**(应用会自动用一个独立配置目录拉起
  专用实例,不影响你日常的浏览器窗口)。
- 验证装好:`python -c "import jev_ultrafast"` 不报错。

---

## 三、在应用里启用浏览器实时查询

**默认关闭**(单次查询消耗 200+ 次 Jev 决策,防止悄悄烧配额)。开启:

```sql
-- 对本机 data/yihao.sqlite3 执行(可用 DB Browser for SQLite)
INSERT OR REPLACE INTO app_settings(key, value) VALUES('browser_query_enabled', '1');
```

关闭:把 value 改回 `'0'`。重启应用生效。

**用法**:聊天改图页直接发「查宁波到淄博的火车」「帮我查一下天气」——
应用自动路由:火车→12306、天气→中国天气网、快递→快递100;查完由文本
模型基于页面内容作答并附来源链接。查不到/超时自动落回网页搜索。

**行为细节**(实测):
- 拉起的 Chrome 窗口是查询的**工作窗口,查询期间别关**(关了会自动重拉
  再试一次,两次都挂才落回搜索);
- 每次查询预算 120 步/120 秒;单步决策都可追溯,概率异常低说明页面和
  预期不符。

---

## 四、文本模型(浏览器填表单用)

jev-ultrafast 填输入框时需要一个 OpenAI 兼容文本模型。应用自动取「AI 服务
→ 文本」里的配置,**优先 DeepSeek**(便宜、非推理档、填表快),没有就用
默认文本服务。所以:确保至少配过一个文本 key(见主指南§一)。

---

## 五、已知局限(实测,别踩)

- Jev 只做选择题,**不能生成文本** —— 提取关键词/写文案类需求走文本模型,
  不要指望 Jev。
- Jev 判「图」不可信(实测对参考图能力臆断),应用已用白名单机制兜住,
  别把 Jev 判图接进决策。
- 12306 这类重站(登录弹窗/城市选择器/日期控件)可能走不完步数预算 ——
  这是浏览器查询默认关的第二个原因;轻站(天气/快递)体验好得多。
- 浏览器查询以你的真实 Chrome 打开外部网站,**不要**在 goal 里要求
  提交订单/支付(应用内置提示词已禁止,自己也别绕过)。

---

## 六、排障

| 现象 | 处理 |
|---|---|
| 浏览器查询无反应 | 看日志 `C:\Users\<你>\.config\browser-harness\tmp\bu-default.log`;`DevToolsActivePort not found` = 日常 Chrome 没带调试启动,应用会自动拉独立实例,若仍失败关掉所有 Chrome 再试 |
| 「Jev 未配置」 | 设置 → AI 服务 → Jev 标签填 key 并测试 |
| 查询烧配额太快 | 把 `browser_query_enabled` 改回 `'0'` |
| 意图判错(该改图判成聊天等) | toast/气泡里的路由结果发开发者;问句规则与 Jev criteria 都在 `app/ui/chat_edit_drawer.py`,几行就能扩 |

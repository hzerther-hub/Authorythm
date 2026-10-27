# STARTUP.md — 启动指南(给人,也给所有智能体)

> 「怎么把应用跑起来」的唯一真相源。环境相关的坑全部来自实测
> (2026-10-27,Windows 11 / Anaconda 机器),复发时按这里对照。

## 一行启动

```bash
python -m app.main        # 前台 GUI;智能体后台跑用 run_in_background
```

- **Git Bash 禁止 `cmd //c start.bat`**(路径编码会炸);需要 PowerShell 启动脚本时用 `start.ps1`。
- 智能体启动用后台方式,stdout 会落到会话日志文件里,按下面的判据验收。
- 停止:`taskkill //F //PID <pid>`。

## 启动成功的判据(智能体按这个验收)

1. `tasklist` 里有 python.exe,内存 ≈ 350–450 MB(Qt 完整加载的量级);
2. stdout 只有两类**良性噪音**,不是错误:
   - `WSALookupServiceBegin failed with: 10108`(Qt 网络组件在 Windows 上的常见警告);
   - shiboken 的 `*** Python is at version 3.10 now ***` UserWarning;
3. 没有任何 Traceback;
4. 结构化日志落 `data/logs/pydrama.log`(JSON,10MB × 5 轮转),启动异常先看它。

无界面验证(不起窗口,适合 CI / 智能体自检):

```bash
QT_QPA_PLATFORM=offscreen python -c "
from PySide6.QtWidgets import QApplication
app = QApplication([])
from app.ui.settings_dialog import SettingsDialog
dlg = SettingsDialog()   # 换成要验的任何对话框/页面
print('构造 OK')
"
```

## 这台机器的环境事实(改动前必读)

- Python 3.13.9,在 `C:\tools\Anaconda3`(base env),PATH 里直接 `python` 就是它。
- **PySide6 必须是 pip 官方完整发行版 6.11.3**(2026-10-27 从混装状态修复到位)。
  - ❌ 不要 `conda install pyside6` —— 会把 pip 版叠成混装状态,段错误;
  - ❌ 不要只装 `PySide6-Essentials` —— 缺 Multimedia / WebEngine 组件;
  - ✅ 装法:
    ```bash
    pip install --force-reinstall --ignore-installed --no-deps \
      "PySide6==6.11.3" "PySide6-Essentials==6.11.3" \
      "PySide6-Addons==6.11.3" "shiboken6==6.11.3"
    ```
- `site-packages/PySide6/icuuc.dll` 是从 `C:\Windows\System32` 拷来的副本
  (Qt 6.11 硬依赖带 ucnv 符号的系统 ICU;conda `Library/bin` 的 ICU 73 缺符号
  且抢先被加载)。**删了它 QtCore 都加载不了,别动。**
- ⚠ **本机别按 requirements.txt 重装 PySide6**:requirements.txt 钉的是
  `>=6.6.0,<6.10`(给 CI/干净机器用,6.9.x 三平台全绿),而本机已钉 6.11.3,
  **超出该上限** —— 照它重装会降级成 6.9.x,触发下表 `could not init enum`。
  本机只缺其它依赖时单独装(AGENTS.md 说的 6.11 即此)。

## 启动失败对照表(全部实测过)

| 症状 | 根因 | 处置 |
|---|---|---|
| `No module named 'PySide6.QtMultimedia'` | 阉割版 PySide6(缺 Addons 组件) | 按上面命令装完整发行版;「看原视频」已兜底退回系统播放器 |
| `DLL load failed ... 找不到指定的程序` | 依赖 DLL 被 `Library/bin` 旧版遮蔽(icuuc 等) | 确认 `PySide6/icuuc.dll` 副本还在;用文末依赖扫描法定位 |
| 段错误(exit 139)/ 静默闪退 | site-packages 里两代绑定并存(`*.cp313-win_amd64.pyd` 旧 + pip 新),一个进程两套 shiboken 打架 | 隔离全部 `*.cp313-win_amd64.pyd` |
| `Fatal Python error: could not init enum` | shiboken 6.9 / 6.10 不适配 CPython 3.13.9(多模块连导必炸,单模块正常) | 升到 6.11.3+ |
| `SecretError: API Key 解密失败` 且设置弹窗打不开 | 换机器 / 删了 `data/.secret_salt`(密文与指纹解不开) | 重新输入 key;跨用户历史密文跑 `scripts/migrate_secrets_fingerprint.py`(改库前自动备份) |

## 排查方法论:「DLL load failed / 找不到指定的程序」类问题

按以下顺序做符号级定位(无需第三方工具,PE 导入/导出表用 Python `struct`
就能解析,智能体可按需现写解析脚本):

1. **解析入口 `.pyd` 的导入表** → 列出它依赖哪些 DLL;
2. **逐个确认依赖在 `site-packages/PySide6/` 里是否存在** —— 不在的会被
   `Library/bin` 的旧版遮蔽(典型:icuuc.dll);
3. **对比符号**:解析依赖 DLL 的导出表 vs 入口方的导入符号,精确找出缺哪个;
4. 修法通常是「把正确版本的同名 DLL 放进 `PySide6/`」(该目录在加载顺序上
   最优先)——2026-10-27 用此法确认 Qt 6.11 需要的是 System32 那份 icuuc.dll。

其他实测有效的手法:
- `python -v -c "import 模块名"` 看死前最后在导什么(-u 防 stdout 丢失);
- 逐模块二分:`python -c "import PySide6.QtXxx"` 单独跑,定位哪层崩;
- stdout 在段错误时会整体丢失,验证脚本一律加 `-u`。

## 与 AGENTS.md 的关系

AGENTS.md 是全项目工作规范(线程模型、i18n、数据库纪律等);本文件只管
「把应用跑起来」这一件事。两处都读,冲突时以实测可复现的一方为准。

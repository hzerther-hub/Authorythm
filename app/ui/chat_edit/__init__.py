# -*- coding: utf-8 -*-
"""聊天改图抽屉的子包(从 chat_edit_drawer.py 拆分)。

各子模块:
- `intent`:意图解析 + 帮助文案 + 正典命令清单(纯函数,无 Qt)
- 后续: `message` / `panel` / `drawer`(等下一轮拆)

外部 import 兼容:
    from app.ui.chat_edit_drawer import ChatEditDrawer   # 老路径,继续可用
"""

# -*- coding: utf-8 -*-
"""iconfont 扁平线性图标加载器。

来源:阿里 iconfont(uid=261251),30 枚线性(line)风格图标,源码在
app/assets/icons/*.svg。

为什么用 SVG 而不是字体 / emoji:
  - **字体路线走不通**:Qt 的 QSS 不支持 @font-face,得把 TTF 用
    QFontDatabase 注册后拿私有区码位当文字渲染,多一层依赖;
  - **emoji 会缺字形**:🗑(U+1F5D1)、▶(U+25B6)、⬇(U+2B07)、🩹(U+1FA79) 在
    Windows 应用字体里没有字形,按钮渲染成纯空白(实测颜色数=1)。这轮排查的
    历史视频下载/删除、旁白播放/删除、资产下载、漫画格重画/擦除全是这个问题;
  - **PNG 不能换色**:应用有浅色/深色/slate 三套主题,固定黑图在深色下不可见。
  SVG 里把 fill 留成 __ICON_COLOR__ 占位,由本模块按当前主题替换。

用法:W.icon("delete") 或 W.icon("delete", size=20, color="#dc2626")
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
_PLACEHOLDER = "__ICON_COLOR__"

# 源文件名是 iconfont 的拼音(shanchu/bianji/…),代码里用可读名。
# 别名表是**唯一**的对应关系,改图标名时先看这里。
ALIAS = {
    "save": "baocun",          # 保存
    "edit": "bianji",          # 编辑
    "play": "bofang",          # 播放
    "globe": "ditu_diqiu_o",   # 地球/语言
    "check": "duigoux",        # 对勾
    "chat": "duihuaxinxi",     # 对话
    "close": "guanbi",         # 关闭
    "warning": "jinggao",      # 警告
    "list": "liebiao",         # 列表/批量
    "magic": "moshubang",      # 魔术棒/AI 起草
    "delete": "shanchu",       # 删除
    "bolt": "shandian",        # 闪电
    "upload": "shangchuan",    # 上传
    "settings": "shezhi",      # 设置
    "doc": "shiyongwendang",   # 文档
    "clock": "shizhong",       # 时钟/时长
    "home": "shouye",          # 首页
    "refresh": "shuaxin",      # 刷新
    "search": "sousuo",        # 搜索/审校
    "palette": "tiaoseban",    # 调色板/改图
    "image": "tupian",         # 图片
    "book": "tushuyinxiang",   # 图书/批量
    "folder": "wenjianjia_o",  # 文件夹
    "camera": "xiangji",       # 相机/参考视频
    "check_circle": "xianxingtubiao_xuanzhong",  # 圆圈对勾/完成
    "download": "xiazai",      # 下载
    "star": "xingqiu",         # 星/默认
    "volume": "yinliang",      # 音量/朗读
    "user": "yonghu",          # 用户
    "ledger": "zhangben",      # 账本/台账
}

# (图标名, 颜色, 尺寸) -> QIcon,避免同图标同色同尺寸反复解析 SVG + 重新栅格化。
# **键里必须带 name**:漏了的话第一枚会把后面所有名字都顶掉,30 个图标全变同一个
# (写完渲染预览时一眼看出来的 —— 30 个按钮长得一模一样)。
_cache: dict[tuple[str, str, int], QIcon] = {}
_src_cache: dict[str, str] = {}


def available() -> list[str]:
    """已有图标的**可读名**(缺资源时用来报错)。"""
    if not ICON_DIR.exists():
        return []
    inv = {v: k for k, v in ALIAS.items()}
    return sorted(inv.get(p.stem, p.stem) for p in ICON_DIR.glob("*.svg"))


def _source(name: str) -> str | None:
    stem = ALIAS.get(name, name)
    if stem not in _src_cache:
        p = ICON_DIR / f"{stem}.svg"
        _src_cache[stem] = p.read_text(encoding="utf-8") if p.exists() else ""
    return _src_cache[stem] or None


def icon(name: str, size: int = 16, color: str = "#1f2329") -> QIcon:
    """取一枚图标。

    color 默认跟正文色;深色主题请显式传浅色,或用 theme_color() 让它跟着
    当前调色板走。图标缺失时返回空 QIcon(按钮仍可用,只是没图标)——
    比抛异常好:换图标名不该把整个界面搞崩。
    """
    key = (name, color, int(size))
    if key in _cache:
        return _cache[key]
    src = _source(name)
    if not src:
        _cache[key] = QIcon()
        return _cache[key]

    from PySide6.QtSvg import QSvgRenderer
    # 把**所有** fill 都换成主题色,不只换占位符:iconfont 源文件里有蓝色垃圾桶、
    # 橙色时钟这类硬编码彩色,不覆盖掉就不是「统一风格」了。
    svg = re.sub(r'fill="[^"]*"', f'fill="{color}"', src)
    renderer = QSvgRenderer(bytearray(svg, "utf-8"))
    px = int(size * (2 if renderer.isValid() else 1))
    pm = QPixmap(px, px)                      # 2 倍绘制,高 DPI 下不糊
    pm.fill(Qt.transparent)
    if renderer.isValid():
        p = QPainter(pm)
        renderer.render(p)
        p.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def clear_cache() -> None:
    """主题切换后清缓存 —— 颜色变了要重新栅格化。"""
    _cache.clear()


def theme_color(widget=None) -> str:
    """按当前调色板取图标色(亮色深墨 / 暗色浅墨)。"""
    from PySide6.QtGui import QPalette
    pal = (widget.palette() if widget is not None else QPalette())
    c = pal.color(QPalette.ColorRole.WindowText)
    return c.name()
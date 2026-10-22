# -*- coding: utf-8 -*-
"""抓取**正在运行**的易好短剧窗口(Win32 GDI 截屏),并可把它拉回屏幕可见位置。

为什么不用 scripts/shot_*.py 那一套:
    那些脚本是**离屏**渲染 —— 另起一个 QApplication 实例在 offscreen 平台里
    画一遍,截的是「代码现在长这样」,不是「用户屏幕上那个应用长这样」。
    要证明「入口确实在已发布的构建里」,得抓活的那个窗口。

顺带解决一个实测踩到的坑:
    窗口被 Qt 记在**上次会话的坐标**上,可能整个落在屏幕外
    (实测 x=2192,而屏幕只有 1920 宽)—— 用户会说「我找不到入口」,
    其实入口在,只是窗口在屏幕外。所以默认先把窗口挪进可视区再截。

用法:
    py -3.13 -X utf8 scripts/shot_live_window.py [out.png] [--title=易好短剧] [--no-move]
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
try:
    user32.SetProcessDPIAware()
except Exception:  # noqa: BLE001
    pass

DEFAULT_TITLE = "易好短剧"
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def _find_window(title: str) -> int:
    hits: list[int] = []

    def _enum(h, _l):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, buf, 256)
        if buf.value == title and user32.IsWindowVisible(h):
            hits.append(h)
        return True

    user32.EnumWindows(EnumWindowsProc(_enum), 0)
    return hits[0] if hits else 0


def _move_on_screen(hwnd: int) -> None:
    """把窗口挪进主屏可视区并置前(实测窗口可能整个在屏幕外)。"""
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    user32.ShowWindow(hwnd, 9)                                  # SW_RESTORE
    user32.SetWindowPos(hwnd, -1, 80, 40, 1376, 899, 0x0040)   # HWND_TOPMOST
    user32.SetWindowPos(hwnd, -2, 80, 40, 1376, 899, 0x0040)   # 解除置顶
    user32.SwitchToThisWindow(hwnd, True)
    print(f"屏幕 {sw}x{sh};窗口已移到 (80, 40) 1376x899")


def _capture(hwnd: int, out: Path) -> tuple[int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        raise RuntimeError(f"窗口尺寸非法:{w}x{h}")

    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    # PrintWindow(PW_RENDERFULLCONTENT) 比 BitBlt 可靠:后者抓 DWM 合成窗口
    # 经常拿到黑块/半张图(实测 Qt 窗口就是这样)。
    user32.PrintWindow(hwnd, mem, 2)

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)

    from PIL import Image
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).save(out)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return w, h


def main(argv: list[str]) -> int:
    out = Path("data/logs/live_window.png")
    title = DEFAULT_TITLE
    move = True
    for a in argv:
        if a.startswith("--title="):
            title = a.split("=", 1)[1]
        elif a == "--no-move":
            move = False
        elif not a.startswith("-"):
            out = Path(a)

    hwnd = _find_window(title)
    if not hwnd:
        print(f"没找到标题为「{title}」的可见窗口 —— 应用没在跑?")
        return 1
    if move:
        _move_on_screen(hwnd)
    w, h = _capture(hwnd, out)
    print(f"窗口 {w}x{h} -> saved: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

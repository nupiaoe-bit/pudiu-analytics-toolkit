# -*- coding: utf-8 -*-
"""屏幕工具：取工作区尺寸、把窗口约束在屏幕内。

Windows 下多显示器/缩放比例经常导致 pywebview 或 Chrome 窗口跑到屏幕外，
这里统一用 Win32 API 取"工作区"（排除任务栏），再计算安全的位置和尺寸。
"""
import ctypes
import sys


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


SPI_GETWORKAREA = 0x0030


def make_dpi_aware():
    """尽早调用，避免缩放环境下坐标被系统虚拟放大导致窗口偏移。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # SYSTEM_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def work_area():
    """返回 (x, y, width, height) 主屏工作区，失败时回退到常见分辨率。"""
    if sys.platform != "win32":
        return 0, 0, 1366, 768
    try:
        r = RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
        if ok and r.right > r.left and r.bottom > r.top:
            return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:
        pass
    try:
        return 0, 0, ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        return 0, 0, 1366, 768


def fit_window(width, height, margin=24, anchor="center"):
    """把请求尺寸限制在工作区内，返回 (x, y, w, h)。

    anchor: center / left / right —— 用于让抓包工具与浏览器窗口错开。
    """
    x0, y0, aw, ah = work_area()
    w = max(640, min(int(width), aw - 2 * margin))
    h = max(460, min(int(height), ah - 2 * margin))
    if anchor == "left":
        x = x0 + margin
    elif anchor == "right":
        x = x0 + aw - w - margin
    else:
        x = x0 + (aw - w) // 2
    y = y0 + (ah - h) // 2
    return x, y, w, h


def chrome_window_args(kind="browser"):
    """给 Playwright/Chrome 用的 --window-position / --window-size 参数。

    kind='browser' 靠右，kind='app' 靠左，避免两个窗口完全重叠。
    """
    x0, y0, aw, ah = work_area()
    if kind == "app":
        x, y, w, h = fit_window(1200, 820, 20, anchor="left")
    else:
        w = max(800, min(1180, aw - 40))
        h = max(560, min(820, ah - 40))
        x = x0 + (aw - w) // 2
        y = y0 + (ah - h) // 2
        # 与工具窗口错开一点，两个都能看到
        if aw >= 1500:
            x = x0 + aw - w - 20
    return [f"--window-position={x},{y}", f"--window-size={w},{h}"]


if __name__ == "__main__":
    print("work_area =", work_area())
    print("fit app   =", fit_window(1400, 880, anchor="left"))
    print("fit chrome=", fit_window(1400, 880, anchor="right"))
    print("chrome args=", chrome_window_args())

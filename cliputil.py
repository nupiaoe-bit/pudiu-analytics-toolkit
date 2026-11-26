# -*- coding: utf-8 -*-
"""跨平台剪贴板写入（Windows 用系统 API，pywebview 的 window.clipboard 在 6.x 已不存在）。"""
import sys
import time


def set_clipboard(text):
    """把文本写入系统剪贴板，返回 (是否成功, 说明)。"""
    text = str(text if text is not None else "")
    if sys.platform != "win32":
        return False, "仅支持 Windows"
    try:
        import ctypes
        from ctypes import wintypes

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        opened = False
        for _ in range(8):  # 剪贴板可能被别的程序短暂占用
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.05)
        if not opened:
            return False, "剪贴板被其他程序占用"

        try:
            user32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return False, "内存分配失败"
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                kernel32.GlobalFree(h)
                return False, "内存锁定失败"
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(h)
            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                kernel32.GlobalFree(h)
                return False, "写入剪贴板失败"
            # 成功后句柄所有权归系统，不能在这里释放
            return True, "ok"
        finally:
            user32.CloseClipboard()
    except Exception as e:
        return False, str(e)[:100]


def get_clipboard():
    """读取系统剪贴板文本（用于自检）。"""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        CF_UNICODETEXT = 13
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.argtypes = []
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        for attempt in range(5):
            if not user32.OpenClipboard(None):
                time.sleep(0.05)
                continue
            try:
                h = user32.GetClipboardData(CF_UNICODETEXT)
                if not h:
                    time.sleep(0.05)
                    continue
                ptr = kernel32.GlobalLock(h)
                if not ptr:
                    time.sleep(0.05)
                    continue
                try:
                    text = ctypes.wstring_at(ptr)
                    return text
                finally:
                    kernel32.GlobalUnlock(h)
            finally:
                user32.CloseClipboard()
        return ""
    except Exception:
        return ""

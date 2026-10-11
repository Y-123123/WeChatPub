"""Windows rich-text clipboard, using the documented CF_HTML byte offsets."""
import ctypes
import os
import re
from ctypes import wintypes


def cf_html(fragment):
    prefix = '<html><head><meta charset="utf-8"></head><body><!--StartFragment-->'
    suffix = '<!--EndFragment--></body></html>'
    template = "Version:1.0\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n"
    header_len = len(template.format(0, 0, 0, 0).encode("ascii"))
    body = (prefix + fragment + suffix).encode("utf-8")
    start = header_len + len(prefix.encode("utf-8"))
    end = start + len(fragment.encode("utf-8"))
    header = template.format(header_len, header_len + len(body), start, end).encode("ascii")
    return header + body + b"\0"


def copy_html(fragment):
    if os.name != "nt":
        raise RuntimeError("自动复制按钮目前支持 Windows；其他系统打开 copy.html 选择正文复制。")
    user, kernel = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.OpenClipboard.restype = wintypes.BOOL
    user.EmptyClipboard.restype = wintypes.BOOL
    user.CloseClipboard.restype = wintypes.BOOL
    user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user.RegisterClipboardFormatW.restype = wintypes.UINT
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    html_format = user.RegisterClipboardFormatW("HTML Format")
    if not html_format or not user.OpenClipboard(None):
        raise RuntimeError("剪贴板正被占用，请重试。")
    try:
        if not user.EmptyClipboard():
            raise RuntimeError("无法清空剪贴板。")
        plain = re.sub("<[^>]+>", "", fragment)
        for format_id, payload in [(html_format, cf_html(fragment)), (13, plain.encode("utf-16-le") + b"\0\0")]:
            handle = kernel.GlobalAlloc(0x0002, len(payload))
            if not handle:
                raise RuntimeError("剪贴板内存分配失败。")
            transferred = False
            try:
                ptr = kernel.GlobalLock(handle)
                if not ptr:
                    raise RuntimeError("无法写入剪贴板。")
                ctypes.memmove(ptr, payload, len(payload))
                kernel.GlobalUnlock(handle)
                if not user.SetClipboardData(format_id, handle):
                    raise RuntimeError("剪贴板写入失败。")
                transferred = True
            finally:
                if not transferred:
                    kernel.GlobalFree(handle)
    finally:
        user.CloseClipboard()

"""屏幕截图：枚举显示器，按显示器抓图并压成 JPEG。

抓图走 GDI（PIL 的 ``ImageGrab``），坐标必须是物理像素。wininput 在导入时已经声明了
进程 DPI 感知，而 server.py 会先 import wininput，所以这里的显示器矩形和 SendInput
用的是同一套坐标，多屏 + 高 DPI 下不会错位。

``EnumDisplayMonitors`` 从左到右排序后再编号，编号稳定，手机端的「显示器 N」
和托盘里看到的摆放顺序一致。
"""

from __future__ import annotations

import ctypes
import io
from ctypes import wintypes

from PIL import Image, ImageGrab

__all__ = ["monitors", "capture_jpeg"]

_user32 = ctypes.WinDLL("user32", use_last_error=True)

MONITORINFOF_PRIMARY = 0x1

# 放宽一点上限，防止有人拿 URL 参数把 CPU 和带宽打满
MAX_WIDTH_LIMIT = 3840
MIN_QUALITY, MAX_QUALITY = 30, 95


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)


def _raw_monitors() -> list[_MONITORINFO]:
    """按物理坐标从左到右列出所有显示器。"""
    collected: list[_MONITORINFO] = []

    def _collect(hmonitor, _hdc, _rect, _lparam) -> bool:
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            collected.append(info)
        return True

    callback = _MONITORENUMPROC(_collect)
    if not _user32.EnumDisplayMonitors(None, None, callback, 0):
        raise OSError(f"EnumDisplayMonitors 失败（错误码 {ctypes.get_last_error()}）")

    collected.sort(key=lambda info: (info.rcMonitor.left, info.rcMonitor.top))
    return collected


def monitors() -> list[dict]:
    """所有显示器。主屏未必排在第一块（副屏可能摆在左边）。"""
    result: list[dict] = []
    for index, info in enumerate(_raw_monitors()):
        rect = info.rcMonitor
        result.append(
            {
                "index": index,
                "left": rect.left,
                "top": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            }
        )
    return result


def capture_jpeg(index: int = 0, max_width: int = 1600, quality: int = 70) -> bytes:
    """抓第 index 块显示器，等比缩到 max_width 以内，返回 JPEG 字节。

    max_width 传 0 表示不缩放。
    """
    found = _raw_monitors()
    if not found:
        raise RuntimeError("没有检测到显示器")
    if not 0 <= index < len(found):
        raise ValueError(f"显示器序号越界：{index}")

    rect = found[index].rcMonitor
    box = (rect.left, rect.top, rect.right, rect.bottom)
    # all_screens 不能省：不带它时坐标是相对主屏的，副屏在左边就会抓到空白
    image = ImageGrab.grab(bbox=box, all_screens=True)

    if max_width and image.width > max_width:
        height = max(1, round(image.height * max_width / image.width))
        image = image.resize((max_width, height))

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()

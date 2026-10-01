"""电源与显示器控制：关屏、唤醒、锁屏、睡眠、休眠。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import wininput

__all__ = ["monitor_off", "wake_display", "lock", "sleep", "hibernate", "PowerError"]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_powrprof = ctypes.WinDLL("powrprof", use_last_error=True)

HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
SMTO_ABORTIFHUNG = 0x0002

MONITOR_ON = -1
MONITOR_OFF = 2

_user32.SendMessageTimeoutW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong),
)
_user32.SendMessageTimeoutW.restype = wintypes.LPARAM

_powrprof.SetSuspendState.argtypes = (wintypes.BOOLEAN, wintypes.BOOLEAN, wintypes.BOOLEAN)
_powrprof.SetSuspendState.restype = wintypes.BOOLEAN


class PowerError(RuntimeError):
    pass


def _set_monitor_power(state: int) -> None:
    result = ctypes.c_ulonglong() if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong()
    _user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SYSCOMMAND,
        SC_MONITORPOWER,
        state,
        SMTO_ABORTIFHUNG,
        1000,
        ctypes.byref(result),
    )


def monitor_off() -> None:
    """关闭显示器（系统继续运行，服务保持在线，随时可以唤醒）。"""
    _set_monitor_power(MONITOR_OFF)


def wake_display() -> None:
    """唤醒显示器。

    ``SC_MONITORPOWER`` 会把显示器打开，但部分驱动不响应，所以再轻微抖动一下鼠标
    作为兜底——注入的鼠标输入同样会重置系统的空闲计时器。
    """
    _set_monitor_power(MONITOR_ON)
    try:
        wininput.move_mouse(1, 0)
        wininput.move_mouse(-1, 0)
    except wininput.InputError:
        pass


def lock() -> None:
    """锁定工作站。注意：锁屏后 SendInput 会被系统拦截，鼠标/键盘将不可用。"""
    if not _user32.LockWorkStation():
        raise PowerError("LockWorkStation 调用失败")


def _suspend(hibernate_mode: bool) -> None:
    # bForce=True 强制挂起，忽略其他程序"阻止休眠"的请求（远程操作时必须这样）
    if not _powrprof.SetSuspendState(hibernate_mode, True, False):
        raise PowerError("SetSuspendState 调用失败，可能需要在电源选项里启用休眠")


def sleep() -> None:
    """睡眠（S3）。睡眠期间服务随系统挂起，需要靠开机卡/电源键唤醒。"""
    _suspend(False)


def hibernate() -> None:
    """休眠（S4），把内存写入磁盘后断电。"""
    _suspend(True)

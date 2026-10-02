"""Windows 输入模拟：键盘、鼠标、媒体键、窗口跨屏移动。

全部基于 Win32 ``SendInput``，不依赖 pyautogui 等库。

两个关键细节：

1. 鼠标移动使用 **绝对坐标**（``MOUSEEVENTF_ABSOLUTE`` + ``MOUSEEVENTF_VIRTUALDESK``），
   先用 ``GetCursorPos`` 取当前位置再加上增量。这样能绕开"提高指针精确度"（鼠标加速度），
   手指滑动距离和光标位移是 1:1 的，手感才像真正的触摸板。
2. 进程必须声明 DPI 感知，否则 ``GetCursorPos`` / ``GetSystemMetrics`` 返回的是被缩放的
   逻辑坐标，而 ``SendInput`` 要的是物理坐标，高 DPI 多屏下会整体错位。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

__all__ = [
    "InputError",
    "move_mouse",
    "mouse_button",
    "mouse_wheel",
    "press_key",
    "press_named_key",
    "hotkey",
    "type_text",
    "move_window_to_other_monitor",
    "media_play_pause",
    "media_next",
    "media_prev",
    "media_stop",
    "volume_key_up",
    "volume_key_down",
    "volume_key_mute",
    "screen_size",
    "cursor_pos",
]

_user32 = ctypes.WinDLL("user32", use_last_error=True)


# --------------------------------------------------------------------------- DPI
def _enable_dpi_awareness() -> None:
    """声明进程 DPI 感知，保证坐标系统一为物理像素。"""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == -4
        if _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        return
    except (AttributeError, OSError):
        pass
    try:
        _user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


_enable_dpi_awareness()


# ------------------------------------------------------------------- SendInput 结构
_ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT
_user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.IsWindow.argtypes = (wintypes.HWND,)
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsIconic.argtypes = (wintypes.HWND,)
_user32.IsIconic.restype = wintypes.BOOL
_user32.IsZoomed.argtypes = (wintypes.HWND,)
_user32.IsZoomed.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.PostMessageW.restype = wintypes.BOOL
_user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowLongW.restype = wintypes.LONG
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.EnumWindows.argtypes = (ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM)
_user32.EnumWindows.restype = wintypes.BOOL

# 判断 UWP 应用留下的"挂起来"的窗口要用 dwmapi
_dwmapi = ctypes.WinDLL("dwmapi")
_dwmapi.DwmGetWindowAttribute.argtypes = (
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

WHEEL_DELTA = 120

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

ERROR_ACCESS_DENIED = 5

# 两次鼠标注入之间的最小间隔，详见 move_mouse()
_MIN_INJECT_GAP = 0.002
_last_inject = 0.0


class InputError(RuntimeError):
    """SendInput 被系统拒绝（锁屏、UAC 安全桌面，或前台窗口以管理员权限运行）。"""


# ------------------------------------------------------------------ 虚拟按键码
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21  # PageUp
VK_NEXT = 0x22  # PageDown
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_M = 0x4D
VK_INSERT = 0x2D
VK_DELETE = 0x2E

# 手机端按键面板能按的名字。只认这张表，前端传什么进来都注入不了别的键。
_NAMED_KEYS = {
    "enter": VK_RETURN,
    "backspace": VK_BACK,
    "tab": VK_TAB,
    "space": VK_SPACE,
    "esc": VK_ESCAPE,
    "insert": VK_INSERT,
    "delete": VK_DELETE,
    "home": VK_HOME,
    "end": VK_END,
    "pageup": VK_PRIOR,
    "pagedown": VK_NEXT,
    "left": VK_LEFT,
    "right": VK_RIGHT,
    "up": VK_UP,
    "down": VK_DOWN,
    "win": VK_LWIN,
}

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

# 这些键在键盘协议里带 E0 前缀，注入时必须加 KEYEVENTF_EXTENDEDKEY，
# 否则系统会把它当成小键盘上的同名键。
_EXTENDED_VKS = frozenset(
    {
        0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # PgUp PgDn End Home ← ↑ → ↓
        0x2D, 0x2E,                                       # Insert Delete
        0x5B, 0x5C, 0x5D,                                 # LWin RWin Apps
        0x6F, 0x90,                                       # 小键盘 / NumLock
        0xA3, 0xA5,                                       # RCtrl RAlt
        0xAD, 0xAE, 0xAF,                                 # 音量静音/减/加
        0xB0, 0xB1, 0xB2, 0xB3,                           # 上一曲/下一曲/停止/播放暂停
    }
)


def _key_input(vk: int, flags: int, scan: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = scan
    inp.ki.dwFlags = flags
    return inp


def _mouse_input(dx: int, dy: int, data: int, flags: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = data & 0xFFFFFFFF
    inp.mi.dwFlags = flags
    return inp


def _send(*inputs: INPUT) -> None:
    count = len(inputs)
    if not count:
        return
    array = (INPUT * count)(*inputs)
    sent = _user32.SendInput(count, array, ctypes.sizeof(INPUT))
    if sent != count:
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            raise InputError(
                "系统拒绝了按键注入：当前处于锁屏/UAC 安全桌面，"
                "或前台窗口以管理员权限运行。请先解锁，并以相同权限运行本程序。"
            )
        raise InputError(f"SendInput 失败（已发送 {sent}/{count}，错误码 {err}）")


# ---------------------------------------------------------------------- 鼠标
def _virtual_desktop() -> tuple[int, int, int, int]:
    return (
        _user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        _user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def screen_size() -> tuple[int, int]:
    """整个虚拟桌面（所有显示器拼起来）的尺寸。"""
    _, _, w, h = _virtual_desktop()
    return w, h


_MAX_TITLE = 200

# 窗口列表里每条的标题截断长度。列表是给手机屏看的，太长没意义，还费流量。
_MAX_LISTED_TITLE = 120


def _window_title(hwnd: int, limit: int = _MAX_TITLE) -> str:
    """读一个窗口的标题，读不到就返回空串。"""
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value[:limit]


def foreground_title() -> str:
    """当前前台窗口的标题，读不到就返回空串。

    手机上要靠它知道现在切到了哪个窗口，所以每秒查一次。标题可能很长
    （浏览器会把整篇文章的标题塞进来），这里先截到 200 个字符，免得每秒
    往手机上推一大坨。
    """
    return _window_title(_user32.GetForegroundWindow())


# ---------------------------------------------------------------- 窗口列表

_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_GW_OWNER = 4
_SW_RESTORE = 9
_SW_MINIMIZE = 6
_SW_MAXIMIZE = 3
_WM_CLOSE = 0x0010
_DWMWA_CLOAKED = 14

# EnumWindows 的回调签名，得在外面建好，回调对象被回收的话枚举会直接崩
_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _is_cloaked(hwnd: int) -> bool:
    """窗口是不是 UWP 那种"挂着但没显示"的壳。

    每个 UWP 应用都会额外留一个 visible、有标题、但实际看不见的顶层窗口，
    不滤掉的话列表里会凭空多出一堆重复条目。
    """
    value = ctypes.c_int(0)
    result = _dwmapi.DwmGetWindowAttribute(
        hwnd, _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
    )
    # 老系统上可能查不到这个属性，查不到就当没挂起
    return result == 0 and value.value != 0


def _is_switchable(hwnd: int) -> bool:
    """这个窗口会不会出现在系统的 Alt+Tab 列表里。判据跟系统大致对齐。"""
    if not _user32.IsWindowVisible(hwnd):
        return False
    # 有 owner 的是对话框 / 浮动面板，Alt+Tab 本来就不列它们
    if _user32.GetWindow(hwnd, _GW_OWNER):
        return False
    if _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW:
        return False
    if _is_cloaked(hwnd):
        return False
    return _window_title(hwnd) != ""


def list_windows() -> list[dict]:
    """列出所有能切过去的窗口，按 Z 序（最前面的排第一）。

    id 就是 HWND，current 标的是当前前台那个 —— 手机端要拿它给列表里的
    "自己在哪一行" 加高亮。前端如果拿标题去比是对不上的：标题在这里截到
    120 字符，而每秒推的 focus 截到 200，长标题两边对不齐。
    """
    foreground = _user32.GetForegroundWindow()
    found: list[dict] = []

    def callback(hwnd, _):
        if _is_switchable(hwnd):
            found.append(
                {
                    "id": int(hwnd),
                    "title": _window_title(hwnd, _MAX_LISTED_TITLE),
                    "current": hwnd == foreground,
                }
            )
        return True

    _user32.EnumWindows(_ENUM_PROC(callback), 0)
    return found


def activate_window(hwnd: int) -> None:
    """把指定窗口切到前台；最小化的先还原。

    Windows 不允许后台进程随便抢前台焦点，直接调 SetForegroundWindow 会静默
    失败。标准绕法是先按住 Alt —— 系统会认为这次前台切换是用户敲出来的，
    于是放行。代价是会短暂按一下 Alt，松手就好。
    """
    if not _user32.IsWindow(hwnd):
        return
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)
    _send(_key_input(VK_MENU, 0))
    _user32.SetForegroundWindow(hwnd)
    _send(_key_input(VK_MENU, KEYEVENTF_KEYUP))


def minimize_all_windows() -> None:
    """Win+M：把所有窗口最小化，露出桌面。

    用 Win+M 而不是 Win+D —— Win+D 是切换式的，已经在桌面时按下去会把窗口
    全部还原，跟"点击列表里的桌面"这个动作的语义对不上。
    """
    hotkey(VK_LWIN, VK_M)


# ------------------------------------------------------------ 窗口标题栏按钮

class NoWindowError(RuntimeError):
    """当前没有可操作的应用窗口（已经在桌面上了）。"""


def _focused_window() -> int:
    """前台窗口句柄，但必须是个真正的应用窗口，否则返回 0。

    回到桌面时前台窗口是 Progman（桌面本身），对它发 WM_CLOSE 会把资源管理器
    关掉。所以这里跟窗口列表用同一套判据，不是应用窗口就当没有目标，调用方
    什么也不做。
    """
    hwnd = _user32.GetForegroundWindow()
    if not hwnd or not _is_switchable(hwnd):
        return 0
    return int(hwnd)


def _require_focused_window() -> int:
    hwnd = _focused_window()
    if not hwnd:
        raise NoWindowError("当前没有窗口在前台（已经在桌面上了）")
    return hwnd


def foreground_maximized() -> bool:
    """前台窗口是不是最大化状态 —— 手机端拿它决定中间那个键画哪个图标。"""
    hwnd = _focused_window()
    return bool(hwnd) and bool(_user32.IsZoomed(hwnd))


def minimize_foreground() -> None:
    """最小化当前前台窗口（标题栏那个「—」）。"""
    _user32.ShowWindow(_require_focused_window(), _SW_MINIMIZE)


def toggle_maximize_foreground() -> None:
    """最大化 / 还原当前前台窗口。

    一个键两种状态：没最大化就最大化，已经最大化了就还原成窗口大小。这正是
    Windows 标题栏中间那个键的行为，图标也跟着状态换。
    """
    hwnd = _require_focused_window()
    _user32.ShowWindow(hwnd, _SW_RESTORE if _user32.IsZoomed(hwnd) else _SW_MAXIMIZE)


def close_foreground() -> None:
    """关闭当前前台窗口（标题栏那个「✕」）。

    发的是 WM_CLOSE 而不是强杀进程 —— 跟点标题栏的 ✕ 完全一样，该弹"要不要
    保存"的照样会弹，不会让人白丢工作。
    """
    _user32.PostMessageW(_require_focused_window(), _WM_CLOSE, 0, 0)


def move_mouse(dx: int, dy: int) -> None:
    """把光标相对当前位置移动 (dx, dy) 像素。"""
    global _last_inject
    if not dx and not dy:
        return

    # 系统要花一点时间处理上一次注入，紧接着再读 GetCursorPos 会拿到旧坐标，
    # 那样算出来的目标位置就会丢步（实测背靠背调用会丢约 25% 的位移）。
    # 这里补一个最小间隔，代价是一条指令多等 2ms，用户完全感觉不到。
    gap = _MIN_INJECT_GAP - (time.monotonic() - _last_inject)
    if gap > 0:
        time.sleep(gap)

    x, y = cursor_pos()
    _last_inject = time.monotonic()

    left, top, width, height = _virtual_desktop()
    if width <= 1 or height <= 1:
        return
    target_x = min(max(x + dx, left), left + width - 1)
    target_y = min(max(y + dy, top), top + height - 1)
    # 绝对坐标要归一化到 0..65535，且映射的是整个虚拟桌面而非主屏
    norm_x = round((target_x - left) * 65535 / (width - 1))
    norm_y = round((target_y - top) * 65535 / (height - 1))
    _send(
        _mouse_input(
            norm_x,
            norm_y,
            0,
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        )
    )


_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def mouse_button(button: str = "left", action: str = "click") -> None:
    try:
        down_flag, up_flag = _BUTTON_FLAGS[button]
    except KeyError:
        raise ValueError(f"未知鼠标按键: {button}") from None
    if action == "down":
        _send(_mouse_input(0, 0, 0, down_flag))
    elif action == "up":
        _send(_mouse_input(0, 0, 0, up_flag))
    elif action == "click":
        _send(_mouse_input(0, 0, 0, down_flag), _mouse_input(0, 0, 0, up_flag))
    else:
        raise ValueError(f"未知鼠标动作: {action}")


def mouse_wheel(delta: int, horizontal: bool = False) -> None:
    """滚动滚轮。delta 为正表示向上/向左滚动一格的整数倍（一格 = 120）。"""
    if not delta:
        return
    flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
    _send(_mouse_input(0, 0, delta, flag))


# ---------------------------------------------------------------------- 键盘
def press_key(vk: int, extended: bool | None = None) -> None:
    if extended is None:
        extended = vk in _EXTENDED_VKS
    flags = KEYEVENTF_EXTENDEDKEY if extended else 0
    _send(_key_input(vk, flags), _key_input(vk, flags | KEYEVENTF_KEYUP))


def press_named_key(name: str) -> None:
    """按一下按键面板上的功能键（回车、退格、方向键……）。只认 _NAMED_KEYS 里的名字。"""
    try:
        vk = _NAMED_KEYS[name]
    except KeyError:
        raise ValueError(f"未知按键：{name}") from None
    press_key(vk)


def hotkey(*vks: int, step: float = 0.015) -> None:
    """按顺序按下所有键，再逆序松开。用于 Win+Shift+← 这类组合键。"""
    downs = []
    ups = []
    for vk in vks:
        flags = KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED_VKS else 0
        downs.append(_key_input(vk, flags))
        ups.append(_key_input(vk, flags | KEYEVENTF_KEYUP))
    for i, event in enumerate(downs):
        _send(event)
        # 组合键之间留一点间隔，否则资源管理器来不及识别 Win+Shift+方向键
        if i != len(downs) - 1:
            time.sleep(step)
    for event in reversed(ups):
        _send(event)


def move_window_to_other_monitor(direction: str = "right") -> None:
    """Win+Shift+←/→，把前台窗口移到另一块显示器。"""
    if direction == "left":
        vk = VK_LEFT
    elif direction == "right":
        vk = VK_RIGHT
    else:
        raise ValueError(f"未知方向: {direction}")
    hotkey(VK_LWIN, VK_SHIFT, vk)


def type_text(text: str, char_delay: float = 0.004) -> None:
    """把文本逐字注入到当前焦点窗口。

    普通字符走 ``KEYEVENTF_UNICODE``，直接发 UTF-16 码元，所以中文、emoji 都能输入，
    不受当前输入法影响。换行和制表符转成对应的功能键。
    """
    if not text:
        return
    for ch in text:
        if ch == "\n":
            press_key(VK_RETURN, extended=False)
        elif ch == "\r":
            continue
        elif ch == "\t":
            press_key(VK_TAB, extended=False)
        elif ch == "\b":
            press_key(VK_BACK, extended=False)
        else:
            units = ch.encode("utf-16-le")
            for i in range(0, len(units), 2):
                code = units[i] | (units[i + 1] << 8)
                _send(
                    _key_input(0, KEYEVENTF_UNICODE, code),
                    _key_input(0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, code),
                )
        if char_delay:
            time.sleep(char_delay)


# ---------------------------------------------------------------------- 媒体键
def media_play_pause() -> None:
    press_key(VK_MEDIA_PLAY_PAUSE)


def media_next() -> None:
    press_key(VK_MEDIA_NEXT_TRACK)


def media_prev() -> None:
    press_key(VK_MEDIA_PREV_TRACK)


def media_stop() -> None:
    press_key(VK_MEDIA_STOP)


def volume_key_up() -> None:
    press_key(VK_VOLUME_UP)


def volume_key_down() -> None:
    press_key(VK_VOLUME_DOWN)


def volume_key_mute() -> None:
    press_key(VK_VOLUME_MUTE)

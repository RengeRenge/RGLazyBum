"""开机自启动：读写 HKCU 的 Run 键。

键位于 HKEY_CURRENT_USER，**不需要管理员权限**，也不会污染其它用户。

写入的命令行按运行形态区分：
- 冻结（onedir exe）：`"D:\\...\\dist\\RGLazyBum\\RGLazyBum.exe"`
- 源码：`"D:\\...\\.venv\\Scripts\\pythonw.exe" "D:\\...\\tray.py"`

用 pythonw 而不是 python，否则开机时会看到一个黑窗口一闪而过。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import winreg
from pathlib import Path

logger = logging.getLogger("rglazybum")

VALUE_NAME = "RGLazyBum"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

_PROJECT_DIR = Path(__file__).resolve().parent
_TRAY_SCRIPT = _PROJECT_DIR / "tray.py"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def expected_command() -> str:
    """当前形态下正确的自启动命令行。"""
    if is_frozen():
        return subprocess.list2cmdline([sys.executable])

    interpreter = Path(sys.executable)
    pythonw = interpreter.with_name("pythonw.exe")
    if pythonw.exists():
        interpreter = pythonw
    return subprocess.list2cmdline([str(interpreter), str(_TRAY_SCRIPT)])


def state() -> str:
    """返回 "enabled" / "stale"（值在，但指向已失效的旧路径）/ "disabled"。"""
    current = _read()
    if current is None:
        return "disabled"
    if _normalize(current) == _normalize(expected_command()):
        return "enabled"
    return "stale"


def set_enabled(enabled: bool) -> bool:
    """写入或删除自启动项，返回是否成功。"""
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(
                    key, VALUE_NAME, 0, winreg.REG_SZ, expected_command()
                )
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        logger.exception("写入开机自启动项失败")
        return False
    logger.info("开机自启动已%s：%s", "开启" if enabled else "关闭", expected_command())
    return True


# ------------------------------------------------------------------ 内部


def _read() -> str | None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None
    except OSError:
        logger.exception("读取开机自启动项失败")
        return None
    return str(value)


def _normalize(command: str) -> str:
    """比较用：统一大小写与首尾空白（Windows 路径大小写不敏感）。"""
    return os.path.normcase(command.strip())

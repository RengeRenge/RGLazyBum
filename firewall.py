"""Windows 防火墙放行规则：检测、按需提权添加。

实测事实（本机 Windows，非管理员）：
- `netsh advfirewall firewall show rule name="X"`：存在 → 退出码 0，不存在 → 1。
  只看退出码，不解析文本（输出随系统语言变化）。
- `Get-NetFirewallRule` 在非管理员下会报 Access is denied 却返回空集，不能用。
- venv 的 python.exe 只是启动器，真正持有监听套接字的是 base 解释器，
  所以**源码模式不能写程序型规则**（永远匹配不上），只能用端口型；
  冻结后 sys.executable 就是稳定的 RGLazyBum.exe，程序型规则才成立，
  一次加好以后换端口都不用再管。
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys

logger = logging.getLogger("rglazybum")

_CREATE_NO_WINDOW = 0x08000000
_SW_HIDE = 0
_NETSH = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"), "System32", "netsh.exe"
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def rule_spec(port: int) -> tuple[str, list[str]]:
    """按运行形态给出 (规则名, 添加规则的 netsh 参数)。"""
    if is_frozen():
        # 程序型：绑定 exe 自身，端口任意
        name = "RGLazyBum"
        args = [
            "advfirewall", "firewall", "add", "rule",
            f"name={name}", "dir=in", "action=allow",
            "protocol=TCP", "localport=any",
            f"program={sys.executable}",
            "enable=yes", "profile=any",
        ]
    else:
        # 端口型：源码模式下唯一能命中的写法
        name = f"RGLazyBum {port}"
        args = [
            "advfirewall", "firewall", "add", "rule",
            f"name={name}", "dir=in", "action=allow",
            "protocol=TCP", f"localport={port}",
            "enable=yes", "profile=any",
        ]
    return name, args


def is_rule_present(name: str) -> bool:
    return _run_netsh(["advfirewall", "firewall", "show", "rule", f"name={name}"]) == 0


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def ensure_rule(port: int) -> str:
    """确保放行规则存在。

    返回 "present"（本来就有）/ "added"（新建成功）/ "denied"（用户拒绝提权）
    / "failed"（其它失败）。会阻塞到用户点完 UAC，调用方必须放独立线程。
    """
    name, args = rule_spec(port)

    if is_rule_present(name):
        return "present"

    if is_elevated():
        if _run_netsh(args) == 0 and is_rule_present(name):
            return "added"
        logger.warning("以管理员身份添加防火墙规则失败：%s", name)
        return "failed"

    if _run_elevated(args) is None:
        logger.info("用户拒绝了防火墙提权请求")
        return "denied"

    if is_rule_present(name):
        return "added"
    logger.warning("提权后复查仍未找到规则：%s", name)
    return "failed"


# ------------------------------------------------------------------ 内部


def _run_netsh(args: list[str]) -> int:
    try:
        completed = subprocess.run(
            [_NETSH, *args],
            creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_clean_env(),
            check=False,
        )
    except OSError:
        logger.exception("执行 netsh 失败")
        return -1
    return completed.returncode


def _run_elevated(args: list[str]) -> int | None:
    """用 UAC 提权跑 netsh；用户点"否"或失败返回 None。"""
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int,
    ]
    result = shell32.ShellExecuteW(
        None, "runas", _NETSH, subprocess.list2cmdline(args), None, _SW_HIDE
    )
    # 返回值 <= 32 表示失败（5 = 用户拒绝）
    if not result or int(result) <= 32:
        logger.info("提权调用未成功，ShellExecuteW 返回 %s", result)
        return None
    return int(result)


def _clean_env() -> dict[str, str]:
    """去掉 PyInstaller 注入的 DLL 搜索路径，避免子进程 DLL 冲突。"""
    env = dict(os.environ)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        keep = [
            part
            for part in env.get("PATH", "").split(os.pathsep)
            if part and os.path.normcase(part) != os.path.normcase(meipass)
        ]
        env["PATH"] = os.pathsep.join(keep)
    env.pop("_MEIPASS2", None)
    return env

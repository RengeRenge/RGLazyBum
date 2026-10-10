"""RGLazyBum 托盘后台程序入口。

形态：右下角一个小图标，没有控制台窗口。左键双击（菜单默认项）打开控制页，
右键出菜单。服务跑在独立线程里，托盘图标跑在主线程的 Win32 消息循环里
（pystray 规定必须如此）。

用法：
    pythonw tray.py            端口按 settings.CANDIDATE_PORTS 自动挑
    pythonw tray.py --verbose  日志记 DEBUG
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time

import pystray
from PIL import Image, ImageDraw

import applog
import autostart
import firewall
import netinfo
import qrwin
import server
import settings
import wininput

logger = logging.getLogger("rglazybum")

MUTEX_NAME = "Local\\RGLazyBum.Tray"
ERROR_ALREADY_EXISTS = 183

_MUTEX_HANDLE: int | None = None

# 本进程是不是管理员。菜单里「以管理员身份重启」要不要灰掉就看它。
# 游戏多半以管理员运行，而 Windows 的 UIPI 会把普通权限进程注入的鼠标键盘
# 静默丢掉 —— 提权是让虚拟键盘/触摸板在游戏里生效的唯一办法。
_IS_ADMIN = wininput.is_elevated()

# 图标状态色：一眼看出是不是出问题了
_COLOR_OK = "#1f7ae0"        # 服务在跑，防火墙已放行
_COLOR_BLOCKED = "#e08a20"   # 服务在跑，但手机连不上（防火墙未放行）
_COLOR_STARTING = "#8a94a6"  # 正在启动，端口还没定下来
_COLOR_STOPPED = "#c0392b"   # 服务没起来

# 日志里给颜色配一句人话，省得每次改状态都得同步两处判断。
_STATE_LABELS = {
    _COLOR_OK: "防火墙已放行",
    _COLOR_BLOCKED: "防火墙未放行",
    _COLOR_STARTING: "正在启动",
    _COLOR_STOPPED: "服务未运行",
}

# 防火墙检测的重试次数与间隔。程序挂在开机自启里，启动时常常赶在 Windows
# 防火墙服务（mpssvc/BFE）就绪之前，netsh 会瞬时失败；一次失败就判定"未放行"
# 的话，图标会一直停在黄色，直到用户手动重启服务才恢复。
_FIREWALL_ATTEMPTS = 3
_FIREWALL_RETRY_DELAY = 1.0

# 上面那三次只覆盖启动后 3 秒，开机自启时未必够。判定"未放行"之后再按这两个
# 时间点补查一次，查到了就把图标改回蓝色，免得一直黄着等用户去重启服务。
_FIREWALL_RECHECK_DELAYS = (10.0, 30.0)


# ------------------------------------------------------------------ 单实例


def acquire_single_instance() -> bool:
    """用命名互斥体保证只有一个托盘实例；拿不到就返回 False。"""
    global _MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.GetLastError.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        logger.warning("创建互斥体失败，跳过单实例检查")
        return True
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False

    # 保持引用，进程活着期间不释放
    _MUTEX_HANDLE = handle
    return True


def release_single_instance() -> None:
    """把单实例互斥体让出去。

    提权重启前必须先让 —— 新实例启动时也要抢同一个互斥体，我们不放它就直接
    退出了（"已有实例在运行"）。提权失败的话再 acquire 回来。
    """
    global _MUTEX_HANDLE
    if _MUTEX_HANDLE is None:
        return
    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_MUTEX_HANDLE))
    except OSError:
        logger.debug("释放单实例互斥体失败", exc_info=True)
    _MUTEX_HANDLE = None


def _relaunch_as_admin() -> bool:
    """以管理员身份重新拉起自己（会弹 UAC）。用户点了"否"或失败返回 False。

    提权只能走 ShellExecuteW 的 "runas" 动词 —— CreateProcess 是没法提权的。
    """
    if getattr(sys, "frozen", False):
        # 打包后重新拉自己这个 exe
        exe = sys.executable
        cwd = os.path.dirname(exe)
        rest = list(sys.argv[1:])
    else:
        # 源码模式：python.exe + tray.py
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray.py")
        exe = sys.executable
        cwd = os.path.dirname(script)
        rest = [script, *sys.argv[1:]]

    params = " ".join(f'"{a}"' if " " in a else a for a in rest)
    shell32 = ctypes.windll.shell32
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    try:
        result = shell32.ShellExecuteW(None, "runas", exe, params or None, cwd, 1)
    except OSError:
        logger.exception("提权启动失败")
        return False
    # 返回值 <= 32 一律算失败：5 是"被拒绝"（用户在 UAC 上点了否），32 是找不到文件
    code = int(result) if result else 0
    if code <= 32:
        logger.warning("提权启动未成功（ShellExecuteW 返回 %s）", code)
        return False
    return True


# ------------------------------------------------------------------ 图标


def make_icon_image(color: str = "#1f7ae0", size: int = 64, rounded: bool = True) -> Image.Image:
    """画一个简单的图标：方块 + 一条白色咸鱼。

    底色还是那几种状态色（见 _COLOR_*），蓝=正常、黄=防火墙未放行、
    灰=正在启动、红=服务停止，换成咸鱼之后状态一眼照样分得出来。

    rounded=False 画成满幅方块、不留透明角 —— iOS 的应用图标不接受透明，
    圆角由系统自己裁，所以那边得用这一版。
    """
    # 图形按 64x64 设计，其它尺寸等比放大；安卓 / iOS 启动图标和 exe 的 .ico 都复用这里。
    scale = size / 64.0

    def pt(x: float, y: float) -> tuple[int, int]:
        return (round(x * scale), round(y * scale))

    def rect(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (round(x0 * scale), round(y0 * scale), round(x1 * scale), round(y1 * scale))

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rounded:
        draw.rounded_rectangle(rect(3, 3, 61, 61), radius=round(15 * scale), fill=color)
    else:
        draw.rectangle(rect(0, 0, 64, 64), fill=color)
    draw.polygon([pt(21, 32), pt(7, 19), pt(7, 45)], fill="white")            # 鱼尾
    draw.polygon([pt(25, 22), pt(33, 13), pt(42, 22)], fill="white")          # 背鳍
    draw.ellipse(rect(16, 19, 54, 46), fill="white")                          # 鱼身
    draw.ellipse(rect(41, 27, 47, 33), fill=color)                            # 眼睛挖成底色
    return image


# ------------------------------------------------------------------ 应用


class TrayApp:
    """编排服务线程、托盘菜单与退出时序。"""

    def __init__(self) -> None:
        # 端口由服务线程按候选列表挑，挑定之前是 None。
        # 菜单文案、二维码、防火墙规则都必须等它定下来（见 _on_bound）。
        self.port: int | None = None
        self._server: server.uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._icon: pystray.Icon | None = None
        self._qr = qrwin.QrWindow()
        self._firewall_ok = False
        self._firewall_busy = False
        self._welcome_shown = False
        self._failure: str | None = None

    # ---------------------------------------------------------- 服务线程

    def start_service(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._failure = None
        self._thread = threading.Thread(
            target=self._service_main, name="service", daemon=False
        )
        self._thread.start()

    def _service_main(self) -> None:
        try:
            server.run_server(
                settings.CANDIDATE_PORTS,
                on_ready=self._remember,
                on_bound=self._on_bound,
                ipv6=settings.ipv6_enabled(),
            )
        except OSError:
            # 候选端口全试过了都绑不上，失败原因从 errno 翻译
            self._failure = server.describe_all_failed(settings.CANDIDATE_PORTS)
        except SystemExit:
            # uvicorn 起 lifespan 失败时走 sys.exit(...)，SystemExit 不算 Exception，
            # 不单独接住的话服务线程会静默死掉、菜单只说"服务未运行"。
            self._failure = server.describe_all_failed(settings.CANDIDATE_PORTS)
        except Exception:
            logger.exception("服务线程异常退出")
            self._failure = "服务异常退出，详见日志"
        finally:
            if self._failure:
                logger.error("服务启动失败：%s", self._failure)
                self._notify(f"服务启动失败：{self._failure}")
                self._refresh_menu()
            logger.info("服务线程已结束")

    def _on_bound(self, port: int) -> None:
        """服务线程挑定了端口，回调跑在服务线程里。

        在此之前 self.port 是 None，所以二维码、菜单、防火墙规则一律等这里 ——
        源码模式下防火墙是端口型规则，端口没定下来根本没法生成规则名。
        """
        self.port = port
        self._failure = None
        logger.info("服务实际监听端口 %d", port)
        self._log_endpoints()
        self.refresh_firewall_state()
        self._refresh_menu()

    def _log_endpoints(self) -> None:
        """把手机该访问的地址写进日志，出问题时不用猜端口。"""
        port = self.port
        if port is None:
            return
        for url in netinfo.service_urls(port):
            logger.info("局域网入口：%s", url)
        if not settings.ipv6_enabled():
            logger.info("IPv6 外网访问未开启（可在托盘菜单打开）")
            return
        url = netinfo.external_url(port, server.load_token())
        if url:
            logger.info("外网入口：%s", url)
        else:
            logger.warning("已开启 IPv6 外网访问，但没有可用的外网地址")

    def _remember(self, srv: "server.uvicorn.Server") -> None:
        self._server = srv

    def stop_service(self, timeout: float = 5.0) -> bool:
        """停服务并等待线程收敛；返回 True 表示已干净退出。"""
        srv = self._server
        if srv is not None:
            srv.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None
        self._server = None
        return thread is None or not thread.is_alive()

    # ------------------------------------------------------------ 菜单项

    def _status_text(self, item: pystray.MenuItem) -> str:
        if self._failure:
            return self._failure
        thread = self._thread
        if thread is None or not thread.is_alive():
            return "服务未运行"
        port = self.port
        if port is None:
            return "正在启动…"
        url = netinfo.service_urls(port)
        return url[0] if url else f"http://<本机局域网IP>:{port}"

    def _ready_port(self) -> int | None:
        """给菜单动作用：端口还没定下来就提示一句并返回 None。

        服务线程从启动到挑定端口有几毫秒，期间用户点了二维码/防火墙之类的菜单
        就会走到这里。
        """
        port = self.port
        if port is None:
            logger.info("端口尚未确定，忽略本次菜单操作")
            self._notify("服务正在启动，端口还没定下来，稍等一下")
            return None
        return port

    def on_show_qr(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        port = self._ready_port()
        if port is None:
            return
        urls = netinfo.service_urls(port)
        if not urls:
            logger.warning("没有找到可用的局域网地址")
            urls = [netinfo.local_url(port)]
        logger.info("显示二维码：%s", urls[0])
        self._qr.show(urls)

    def on_open_page(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        port = self._ready_port()
        if port is None:
            return
        url = netinfo.local_url(port)
        logger.info("在电脑浏览器打开 %s", url)
        threading.Thread(target=_open_url, args=(url,), daemon=True).start()

    def on_show_external(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """外网二维码。口令只在链接里出现一次，之后靠 cookie。"""
        port = self._ready_port()
        if port is None:
            return
        url = netinfo.external_url(port, server.load_token())
        if url is None:
            logger.warning("拿不到外网地址，无法显示外网二维码")
            self._notify("拿不到外网地址：没配 DDNS 域名，也没找到公网 IPv6")
            return
        logger.info("显示外网二维码：%s", url)
        self._qr.show([url])

    # ------------------------------------------------------- IPv6 外网访问

    def _external_enabled(self, item: pystray.MenuItem) -> bool:
        return settings.ipv6_enabled()

    def _ipv6_label(self, item: pystray.MenuItem) -> str:
        return "IPv6 外网访问" if settings.ipv6_enabled() else "IPv6 外网访问（已关闭）"

    def _ipv6_checked(self, item: pystray.MenuItem) -> bool:
        return settings.ipv6_enabled()

    def on_toggle_ipv6(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """开/关 IPv6 监听。切换要重新绑套接字，所以顺带重启服务。"""
        want = not settings.ipv6_enabled()
        if not settings.update(ipv6=want):
            self._notify("保存配置失败，详见日志")
            return

        logger.info("IPv6 外网访问已%s", "开启" if want else "关闭")
        if not want:
            self._notify("已关闭 IPv6 外网访问，正在重启服务…")
        elif netinfo.external_host() is None:
            self._notify("已开启，但没有可用的外网地址：请先设置 DDNS 域名")
        else:
            self._notify("已开启 IPv6 外网访问，正在重启服务…")
        threading.Thread(target=self._restart_service, name="restart", daemon=True).start()

    def _ddns_label(self, item: pystray.MenuItem) -> str:
        host = settings.ddns_host()
        return f"设置 DDNS 域名…（{host}）" if host else "设置 DDNS 域名…（未设置）"

    def on_set_ddns(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """弹输入框。菜单回调不能堵，所以丢到线程里去弹。"""
        threading.Thread(target=self._ask_ddns, name="ddnsprompt", daemon=True).start()

    def _ask_ddns(self) -> None:
        current = netinfo.public_ipv6()
        tip = f"当前公网 IPv6：{current}" if current else "当前没检测到公网 IPv6 地址"
        value = self._qr.ask_text(
            "设置 DDNS 域名",
            f"填在 DDNS 上指向本机公网 IPv6 的域名。\n"
            f"留空则自动用本机当前的公网 IPv6 地址。\n\n{tip}",
            settings.ddns_host(),
        )
        if value is None:
            logger.info("取消设置 DDNS 域名")
            return
        if not settings.update(ddns_host=value):
            self._notify("保存 DDNS 域名失败，详见日志")
            return

        # 域名只在生成链接时用到，不用重启服务
        logger.info("DDNS 域名已设为 %s", value or "（空，改用本机公网 IPv6）")
        self._notify(f"DDNS 域名已保存：{value}" if value else "已清空，改用本机公网 IPv6 地址")
        self._refresh_menu()

    def on_reset_token(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """换一个新口令。手机上已经种下的 cookie 立刻失效，得重新扫一次。"""
        server.reset_token()
        logger.info("外网口令已重置，旧链接与旧 cookie 均已失效")
        self._notify("已重置外网口令：旧链接失效了，请重新扫外网二维码")
        self._refresh_menu()

    # ------------------------------------------------------------ 防火墙

    def _firewall_label(self, item: pystray.MenuItem) -> str:
        if self._firewall_ok:
            return "允许手机访问（防火墙）"
        if self._firewall_busy:
            return "允许手机访问（防火墙）— 等待确认…"
        return "允许手机访问（防火墙）— 需要一次管理员确认"

    def _firewall_checked(self, item: pystray.MenuItem) -> bool:
        return self._firewall_ok

    def refresh_firewall_state(self) -> None:
        threading.Thread(
            target=self._refresh_firewall_state, name="fwcheck", daemon=True
        ).start()

    def _refresh_firewall_state(self) -> None:
        port = self.port
        if port is None:
            return
        name, _ = firewall.rule_spec(port)
        ok = False
        for attempt in range(1, _FIREWALL_ATTEMPTS + 1):
            ok = firewall.is_rule_present(name)
            if ok or attempt == _FIREWALL_ATTEMPTS:
                break
            logger.info(
                "防火墙规则「%s」第 %d 次检测未通过，%.0f 秒后重试",
                name, attempt, _FIREWALL_RETRY_DELAY,
            )
            time.sleep(_FIREWALL_RETRY_DELAY)
        self._firewall_ok = ok
        logger.info("防火墙规则「%s」%s", name, "已放行" if ok else "未放行")
        self._refresh_menu()
        if not ok:
            threading.Thread(
                target=self._recheck_firewall, name="fwrecheck", daemon=True
            ).start()

    def _recheck_firewall(self) -> None:
        """判成"未放行"之后再隔一会儿补查。

        开机自启时上面那三次重试可能全赶在防火墙服务就绪之前，此时"未放行"是误判；
        不补查的话图标会一直黄着，直到用户手动重启服务才发现其实早就放行了。
        """
        port = self.port
        if port is None:
            return
        name, _ = firewall.rule_spec(port)
        for delay in _FIREWALL_RECHECK_DELAYS:
            time.sleep(delay)
            if self._firewall_ok:
                return
            if firewall.is_rule_present(name):
                self._firewall_ok = True
                logger.info("防火墙规则「%s」复查已放行", name)
                self._refresh_menu()
                return

    def on_fix_firewall(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self._firewall_ok or self._firewall_busy:
            return
        if self._ready_port() is None:
            return
        self._firewall_busy = True
        logger.info("请求管理员权限以添加防火墙规则，请留意屏幕上的用户账户控制弹窗")
        self._notify("请留意屏幕上的「用户账户控制」弹窗，点“是”即可完成放行")
        self._refresh_menu()
        threading.Thread(target=self._fix_firewall, daemon=True).start()

    def _fix_firewall(self) -> None:
        port = self.port
        if port is None:
            return
        result = firewall.ensure_rule(port)
        name, _ = firewall.rule_spec(port)
        self._firewall_ok = firewall.is_rule_present(name)
        self._firewall_busy = False
        message = {
            "present": "防火墙已放行",
            "added": "已放行，手机现在可以访问了",
            "denied": "已取消：缺少管理员权限，手机暂时连不上",
            "failed": "添加防火墙规则失败，详见日志",
        }.get(result, "防火墙处理结果未知")
        logger.info("防火墙规则处理结果：%s（%s）", result, message)
        self._notify(message)
        self._refresh_menu()

    # ------------------------------------------------------------ 开机自启动

    def _autostart_label(self, item: pystray.MenuItem) -> str:
        if autostart.state() == "stale":
            return "开机自启动 — 路径已变化，点击修复"
        return "开机自启动"

    def _autostart_checked(self, item: pystray.MenuItem) -> bool:
        return autostart.state() == "enabled"

    def on_toggle_autostart(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """勾选/取消开机自启动。只读写注册表，秒回，不用开线程。"""
        want_enabled = autostart.state() != "enabled"
        if not autostart.set_enabled(want_enabled):
            self._notify("设置开机自启动失败，详见日志")
            return
        self._notify("已开启开机自启动" if want_enabled else "已关闭开机自启动")
        self._refresh_menu()

    # ------------------------------------------------------------ 重启 / 日志

    def on_restart_service(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logger.info("收到重启服务请求")
        threading.Thread(
            target=self._restart_service, name="restart", daemon=True
        ).start()

    def _restart_service(self) -> None:
        if not self.stop_service(5.0):
            logger.warning("重启前旧服务线程未能在 5 秒内退出")
        self.start_service()
        self._refresh_menu()
        self._notify("服务已重启")
        logger.info("服务已重启（端口 %d）", self.port)

    def _runas_label(self, item: pystray.MenuItem) -> str:
        """已经是管理员了就把菜单项说清楚，别让人反复点。"""
        return "已是管理员权限" if _IS_ADMIN else "以管理员身份重启"

    def on_restart_as_admin(
        self, icon: pystray.Icon, item: pystray.MenuItem
    ) -> None:
        logger.info("收到「以管理员身份重启」请求")
        threading.Thread(
            target=self._restart_as_admin, name="runas", daemon=True
        ).start()

    def _restart_as_admin(self) -> None:
        """提权重启：让出互斥体和端口 → 拉一个管理员实例 → 自己退出。

        端口必须先让：新实例是按"第一个空闲端口"挑的，我们占着 8765 它就会挑到
        38765，手机那边的地址就对不上了。互斥体同理，不放新实例会直接退出。
        """
        release_single_instance()
        if not self.stop_service(5.0):
            logger.warning("提权重启前，旧服务未能在 5 秒内退出")

        if _relaunch_as_admin():
            logger.info("已拉起管理员实例，本进程退出")
            self.on_quit(self._icon, None)
            return

        # 用户在 UAC 上点了"否"，或者提权失败 —— 东西都恢复回来，别把人晾着
        logger.warning("提权未成功，恢复原服务")
        acquire_single_instance()
        self.start_service()
        self._refresh_menu()
        self._notify("提权没成功，服务仍以普通权限运行")

    def on_open_log(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logger.info("打开日志文件")
        threading.Thread(target=_open_log, daemon=True).start()

    # ------------------------------------------------------------ 图标状态

    def _icon_color(self) -> str:
        if self._failure:
            return _COLOR_STOPPED
        thread = self._thread
        if thread is None or not thread.is_alive():
            return _COLOR_STOPPED
        if self.port is None:
            # 线程活着但端口还没定：服务在起，别画成红的（红只留给"没起来"）
            return _COLOR_STARTING
        if not self._firewall_ok:
            return _COLOR_BLOCKED
        return _COLOR_OK

    def _update_icon_state(self) -> None:
        icon = self._icon
        if icon is None:
            return
        color = self._icon_color()
        try:
            icon.icon = make_icon_image(color)
        except Exception:
            logger.debug("更新托盘图标颜色失败", exc_info=True)
            return
        logger.info("托盘图标颜色 → %s（%s）", color, _STATE_LABELS.get(color, ""))

    def _on_icon_ready(self, icon: pystray.Icon) -> None:
        """图标就绪回调，由 pystray 在消息循环起来之后调用。

        坑：pystray 只在**没传 setup** 时才用默认的 `visible = True`。
        我们传了自定义 setup，就等于接管了这件事，必须自己把 visible 打开，
        否则图标永远不会出现在通知区域（现象：服务一切正常但看不到图标）。
        """
        icon.visible = True
        # 图标显示用的是建图标那一刻画好的图；这里按当前状态重刷一次，
        # 免得端口/防火墙已经就绪了，通知区域却还挂着启动瞬间的那一帧旧颜色。
        self._update_icon_state()
        logger.info("托盘图标已就绪（visible=%s）", icon.visible)
        if self._welcome_shown:
            return
        self._welcome_shown = True
        self._notify("已在后台运行。看不到图标时，点任务栏的「^」展开隐藏的图标。")

    # ------------------------------------------------------------ 通用

    def _notify(self, message: str, title: str = "懒狗") -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.notify(message, title)
        except Exception:
            logger.debug("气泡通知失败", exc_info=True)

    def _refresh_menu(self) -> None:
        self._update_icon_state()
        icon = self._icon
        if icon is None:
            return
        try:
            icon.title = self._title()
        except Exception:
            logger.debug("更新托盘提示文字失败", exc_info=True)
        try:
            icon.update_menu()
        except Exception:
            logger.debug("刷新菜单失败", exc_info=True)

    def on_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logger.info("收到退出请求")
        srv = self._server
        if srv is not None:
            srv.should_exit = True
        if icon is not None:
            icon.stop()

    # ------------------------------------------------------------ 生命周期

    def build_icon(self) -> pystray.Icon:
        menu = pystray.Menu(
            pystray.MenuItem(self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示二维码 / 扫码连接", self.on_show_qr, default=True),
            pystray.MenuItem(
                "显示外网二维码（含 token）",
                self.on_show_external,
                enabled=self._external_enabled,
            ),
            pystray.MenuItem("在电脑浏览器打开", self.on_open_page),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._ipv6_label,
                self.on_toggle_ipv6,
                checked=self._ipv6_checked,
            ),
            pystray.MenuItem(self._ddns_label, self.on_set_ddns),
            pystray.MenuItem(
                "重置外网口令", self.on_reset_token, enabled=self._external_enabled
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._autostart_label,
                self.on_toggle_autostart,
                checked=self._autostart_checked,
            ),
            pystray.MenuItem(
                self._firewall_label,
                self.on_fix_firewall,
                checked=self._firewall_checked,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开日志", self.on_open_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("重启服务", self.on_restart_service),
            pystray.MenuItem(
                self._runas_label,
                self.on_restart_as_admin,
                enabled=not _IS_ADMIN,
            ),
            pystray.MenuItem("退出", self.on_quit),
        )
        self._icon = pystray.Icon(
            "懒狗",
            make_icon_image(self._icon_color()),
            self._title(),
            menu,
        )
        return self._icon

    def _title(self) -> str:
        """鼠标悬停提示。端口定下来之前不显示端口，免得写个 :None 出去。"""
        return f"懒狗 :{self.port}" if self.port else "懒狗"

    def run(self) -> int:
        # 先起服务线程、再建图标：反过来建图标那一刻线程还是 None，会先画一帧红色的
        # "服务没起来"，开机自启时这一帧可能真被用户看到（服务明明是正常的）。
        self.start_service()
        icon = self.build_icon()
        logger.info("托盘已启动，端口会从 %s 里按顺序挑", settings.CANDIDATE_PORTS)

        try:
            icon.run(setup=self._on_icon_ready)
        except Exception:
            logger.exception("托盘消息循环异常")
            return 1

        self._teardown()
        logger.info("已退出")
        return 0

    def _teardown(self) -> None:
        if not self.stop_service(5.0):
            logger.warning("服务线程未能在 5 秒内退出")
        self._qr.shutdown(3.0)
        server.shutdown_executor()

        # 还有非守护线程活着就强杀，避免留下看不见的进程
        leftover = [
            t for t in threading.enumerate() if t is not threading.main_thread() and not t.daemon
        ]
        if leftover:
            logger.warning("仍有线程存活：%s", [t.name for t in leftover])
            logging.shutdown()
            os._exit(0)


def _open_url(url: str) -> None:
    try:
        os.startfile(url)  # type: ignore[attr-defined]
    except OSError:
        logger.exception("打开浏览器失败：%s", url)


def _open_log() -> None:
    try:
        applog.open_log_file()
    except OSError:
        logger.exception("打开日志文件失败")


# ------------------------------------------------------------------ 入口


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    applog.setup("--verbose" in args or "-v" in args)
    applog.install_excepthooks()

    if not acquire_single_instance():
        logger.info("已有实例在运行，本次退出")
        return 0

    return TrayApp().run()


if __name__ == "__main__":
    raise SystemExit(main())

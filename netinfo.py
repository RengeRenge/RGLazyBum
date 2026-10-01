"""局域网地址探测：给二维码和托盘菜单提供手机该访问的 URL。

本机实测（Windows，中文系统）：
    以太网 2                    192.168.3.10   ← 真实网卡
    vEthernet (Default Switch)  172.29.0.1     ← Hyper-V 虚拟网卡
    natpierce                   10.6.22.1      ← 内网穿透虚拟网卡
    以太网 / 本地连接           169.254.x.x    ← 未连接，链路本地地址

虚拟网卡永远不是默认路由，所以"用 UDP connect 问系统默认出口地址"是最可靠的
主地址来源；其余地址按私网段常见程度排序，作为备选展示。
"""

from __future__ import annotations

import ipaddress
import socket

import psutil

import settings

_LOOPBACK_PREFIXES = ("127.", "0.0.0.0")
_LINK_LOCAL_PREFIX = "169.254."


def _usable(ip: str) -> bool:
    if not ip or ip.startswith(_LOOPBACK_PREFIXES) or ip.startswith(_LINK_LOCAL_PREFIX):
        return False
    return True


def _rank(ip: str) -> int:
    """数字越小越可能是手机能访问到的地址。"""
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    parts = ip.split(".")
    if len(parts) == 4 and parts[0] == "172":
        try:
            second = int(parts[1])
        except ValueError:
            return 3
        if 16 <= second <= 31:
            return 2
        return 3
    return 3


def default_route_address() -> str | None:
    """让系统挑出默认出口网卡的地址（UDP connect 不会真的发包）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            ip = probe.getsockname()[0]
    except OSError:
        return None
    return ip if _usable(ip) else None


def candidate_addresses() -> list[str]:
    """所有可用的 IPv4 地址，最可能被手机访问到的排在最前。"""
    found: list[str] = []
    try:
        stats = psutil.net_if_stats()
        interfaces = psutil.net_if_addrs()
    except Exception:
        stats, interfaces = {}, {}

    for name, addrs in interfaces.items():
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        if "loopback" in name.lower():
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET:
                continue
            ip = addr.address
            if _usable(ip) and ip not in found:
                found.append(ip)

    found.sort(key=_rank)

    default_route = default_route_address()
    if default_route:
        if default_route in found:
            found.remove(default_route)
        found.insert(0, default_route)

    return found


def primary_address() -> str | None:
    addresses = candidate_addresses()
    return addresses[0] if addresses else None


def service_urls(port: int) -> list[str]:
    """手机该打开的地址列表，第一个是首选。"""
    return [f"http://{ip}:{port}" for ip in candidate_addresses()]


def local_url(port: int) -> str:
    """电脑本机浏览器用的地址。"""
    return f"http://127.0.0.1:{port}"


def public_ipv6() -> str | None:
    """本机当前的公网 IPv6 字面量（没配 DDNS 时的兜底）。

    只认 is_global：链路本地 fe80::、ULA fc00:: 这些从互联网根本连不上。
    """
    try:
        interfaces = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception:
        return None

    for name, addrs in interfaces.items():
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        if "loopback" in name.lower():
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET6:
                continue
            ip = addr.address.split("%", 1)[0]  # 去掉 %4 这种作用域后缀
            try:
                parsed = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if isinstance(parsed, ipaddress.IPv6Address) and parsed.is_global:
                return ip
    return None


def external_host() -> str | None:
    """外网入口的主机名：优先用户配的 DDNS 域名，没有就用本机公网 IPv6。"""
    configured = settings.ddns_host()
    if configured:
        return configured
    return public_ipv6()


def external_url(port: int, token: str) -> str | None:
    """外网访问用的地址，口令放在查询参数里。

    口令只需要出现这一次：服务端在带 k 的响应上种一个 cookie，
    之后页面里的 app.js / style.css 和 WebSocket 握手都会自动带上。

    拿不到任何可用的外网地址时返回 None（IPv6 没开、或者既没配域名又没公网 IPv6）。
    """
    host = external_host()
    if not host:
        return None
    if ":" in host:
        # IPv6 字面量在 URL 里必须套方括号，不然冒号会被当成端口分隔符
        host = f"[{host}]"
    return f"http://{host}:{port}/?k={token}"

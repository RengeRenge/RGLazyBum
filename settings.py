"""用户可改的配置项，存在 %LOCALAPPDATA%\\RGLazyBum\\config.json。

一共两项：

    ipv6       是否额外监听 IPv6 并把服务暴露到外网（默认关闭）
    ddns_host  DDNS 域名；留空则退回用本机当前的公网 IPv6 字面量

文件不存在、内容读坏了、或者值的类型 / 范围不对，一律退回默认值 ——
配置问题绝不该让程序起不来。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import applog

logger = logging.getLogger("rglazybum")

CONFIG_FILE = applog.LOG_DIR.parent / "config.json"

# 服务监听端口，按顺序试，第一个能绑上的就用。
#
# 不提供手动配置：手机端不知道用户改成了什么端口，改了就连不上。
# 两端共用这一份列表 —— 安卓端在 app/lib/core/endpoint.dart 里有一份同样的常量，
# 改这里必须同步改那边。
#
# 为什么第一个是 8765：老版本固定用它，留着可以让已经扫过码、存过书签的手机
# 继续用。后面几个刻意避开 1024–15000 —— 那是 Windows 的动态端口范围，
# Edge 这类程序会随机占走，正好是当初 8765 偶尔连不上的原因。
CANDIDATE_PORTS: tuple[int, ...] = (8765, 38765, 38766, 38767, 38768)

DEFAULTS: dict[str, Any] = {
    "ipv6": False,
    "ddns_host": "",
}

_cached: dict[str, Any] | None = None


def _coerce(key: str, value: object) -> Any:
    """把读进来的值收敛成默认值那种类型；类型不对就用默认值。"""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, str):
        return value.strip() if isinstance(value, str) else default
    return default


def load() -> dict[str, Any]:
    """读出全部配置（带缓存）。"""
    global _cached
    if _cached is not None:
        return _cached

    raw: object = {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        logger.exception("配置文件读取失败，本次改用默认值：%s", CONFIG_FILE)

    data = raw if isinstance(raw, dict) else {}
    _cached = {key: _coerce(key, data.get(key)) for key in DEFAULTS}
    return _cached


def update(**changes: object) -> bool:
    """改若干项并落盘；写失败返回 False（内存里的值仍然生效）。"""
    global _cached
    data = dict(load())
    data.update({key: value for key, value in changes.items() if key in DEFAULTS})
    _cached = {key: _coerce(key, data[key]) for key in DEFAULTS}

    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(_cached, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError:
        logger.exception("保存配置失败：%s", CONFIG_FILE)
        return False

    logger.info("配置已更新：%s", _cached)
    return True


def ipv6_enabled() -> bool:
    return bool(load()["ipv6"])


def ddns_host() -> str:
    return str(load()["ddns_host"])

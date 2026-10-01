"""系统媒体会话（GSMTC）：读播放状态、播放暂停/切歌、快进/快退。

Windows 会把各个播放器的媒体会话汇总到系统里（Edge、Spotify、网易云、PotPlayer……），
通过 WinRT 的 ``GlobalSystemMediaTransportControlsSessionManager`` 就能拿到
"当前在放什么、是播放还是暂停、放到第几秒"，不用去逐个适配播放器。

两点与别的模块不一样：

* 这里用的是 WinRT 的异步接口，必须 await，所以直接在 asyncio 事件循环里跑，
  不走 server.blocking() 那套单线程执行器——那个是给同步的 SendInput / COM 用的。
* 没有播放器在放东西时 ``get_current_session()`` 返回 None 属于正常情况：
  播放状态汇报成 None（前端把图标退回默认样子），快进/快退则明确报错。
* 媒体键不是每个播放器都支持：网易云音乐只实现了播放/暂停/切歌，位置请求照收不误
  还返回 True，然后什么都不做；Edge 里放单个视频时"上一首/下一首"根本无处可去。
  所以动手前先问能力（``_capability()``），快照里一并下发 ``canSeek`` /
  ``canPrev`` / ``canNext``，前端据此把按不动的键置灰。

播放暂停 / 上一首 / 下一首**必须走这里**，不能按系统媒体键：媒体键由 Windows
自己挑一个会话投递，和 ``snapshot()`` 报告的那条会话经常不是同一个（实测电脑上
Edge 在放视频、网易云在后台，媒体键每次都打到网易云），于是"图标显示的"和
"按下去动的"是两样东西，表现为按钮像坏了一样。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as _SessionManager,
)
from winsdk.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as _Status,
)

__all__ = [
    "MediaError",
    "snapshot",
    "seek",
    "play_pause",
    "next_track",
    "previous_track",
]

logger = logging.getLogger("rglazybum")

# WinRT 的时间单位是 100 纳秒
_TICKS_PER_SECOND = 10_000_000

# 手机端一次最多能跳 10 分钟。手机传什么进来都夹在这个范围里，免得误触跳到天边。
_MAX_SEEK_SECONDS = 600.0

# 播放中进度一直在走，而 GetTimelineProperties() 给的是"最后一次更新时"的位置。
# 播放状态下补上这段漂移才接近真实进度；漂移过大说明数据已经过时，就不补了。
_MAX_DRIFT_SECONDS = 5.0

# 会话的 AppUserModelId 直接显示太丑（msedge.exe、
# Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic），常见播放器给个人话名字。
_APP_NAMES = {
    "msedge.exe": "Edge",
    "chrome.exe": "Chrome",
    "firefox.exe": "Firefox",
    "cloudmusic.exe": "网易云音乐",
    "qqmusic.exe": "QQ音乐",
    "spotify.exe": "Spotify",
    "potplayer.exe": "PotPlayer",
    "potplayermini64.exe": "PotPlayer",
    "vlc.exe": "VLC",
    "wmplayer.exe": "Windows Media Player",
    "bilibili.exe": "哔哩哔哩",
}

_manager: _SessionManager | None = None


class MediaError(RuntimeError):
    pass


async def _session():
    """当前有焦点的那条媒体会话，没有就返回 None。"""
    global _manager
    if _manager is None:
        _manager = await _SessionManager.request_async()
    try:
        return _manager.get_current_session()
    except Exception:
        # 管理器实例可能已经跟着上一个事件循环一起废了，扔掉了下次重建
        _manager = None
        raise


async def _current_session():
    try:
        return await _session()
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(f"读取系统媒体会话失败：{exc}") from exc


async def snapshot() -> dict | None:
    """当前媒体会话的播放状态和控制目标；没有会话时返回 None。

    ``playing`` 给手机端决定播放/暂停图标画哪一个，``app`` 是这条会话属于哪个
    播放器 —— 电脑上同时有好几条会话时手机只控制"当前会话"，把名字显示出来
    才知道按下去会动谁。``canSeek`` / ``canPrev`` / ``canNext`` 是这条会话支不支持
    快退快进、上一首、下一首，前端据此把按不动的那几个键置灰。
    """
    try:
        session = await _current_session()
        if session is None:
            return None
        info = session.get_playback_info()
        status = info.playback_status
        app = _app_name(session.source_app_user_model_id)
        controls = info.controls
    except Exception:
        logger.debug("读取媒体播放状态失败", exc_info=True)
        return None
    return {
        "playing": status == _Status.PLAYING,
        "app": app,
        "canSeek": _capability(controls, "is_playback_position_enabled"),
        "canPrev": _capability(controls, "is_previous_enabled"),
        "canNext": _capability(controls, "is_next_enabled"),
    }


async def seek(delta_seconds: float) -> None:
    """把当前媒体往前（负数=快退）或往后（正数=快进）挪 delta_seconds 秒。"""
    delta = float(delta_seconds)
    delta = max(-_MAX_SEEK_SECONDS, min(_MAX_SEEK_SECONDS, delta))

    session = await _current_session()
    if session is None:
        raise MediaError("电脑上没有正在播放的媒体")
    info = session.get_playback_info()
    if not _capability(info.controls, "is_playback_position_enabled"):
        raise MediaError(
            f"{_app_name(session.source_app_user_model_id)}不支持快进/快退"
        )

    timeline = session.get_timeline_properties()
    position = timeline.position.total_seconds()
    if info.playback_status == _Status.PLAYING:
        drift = (datetime.now(timezone.utc) - timeline.last_updated_time).total_seconds()
        if 0.0 <= drift <= _MAX_DRIFT_SECONDS:
            position += drift

    start = timeline.start_time.total_seconds()
    end = timeline.end_time.total_seconds()
    target = position + delta
    if end > start:
        target = min(target, end)
    target = max(target, start)

    try:
        ok = await session.try_change_playback_position_async(
            int(target * _TICKS_PER_SECOND)
        )
    except Exception as exc:
        raise MediaError(f"跳转失败：{exc}") from exc
    if not ok:
        raise MediaError("当前播放器不支持跳转")


async def play_pause() -> bool:
    """切当前会话的播放/暂停；没有会话时返回 False，由调用方退回系统媒体键。"""
    session = await _current_session()
    if session is None:
        return False
    return await _invoke(session.try_toggle_play_pause_async, "播放/暂停")


async def next_track() -> bool:
    """下一首；没有会话时返回 False。"""
    session = await _current_session()
    if session is None:
        return False
    return await _invoke(session.try_skip_next_async, "切下一首")


async def previous_track() -> bool:
    """上一首；没有会话时返回 False。"""
    session = await _current_session()
    if session is None:
        return False
    return await _invoke(session.try_skip_previous_async, "切上一首")


async def _invoke(method, verb: str) -> bool:
    """跑一个 try_xxx_async，返回它有没有被播放器接受。"""
    try:
        ok = await method()
    except Exception as exc:
        raise MediaError(f"{verb}失败：{exc}") from exc
    if not ok:
        raise MediaError(f"当前播放器不支持{verb}")
    return True


def _capability(controls, name: str) -> bool:
    """这条会话支不支持某个控制项（``controls`` 上的 ``is_xxx_enabled``）。

    不能光看 ``try_xxx_async`` 的返回值：网易云音乐这类播放器只实现了播放/暂停/
    切歌，位置请求照收不误、还返回 True，然后什么都不做（timeline 也一直是全零，
    压根不上报进度）；反过来，Edge 里放单个视频时"上一首/下一首"本来就没地方去。
    所以动手前一律先问能力。
    """
    try:
        return bool(getattr(controls, name))
    except Exception:
        # 拿不到播放信息（控件为空、会话刚失效）时按不支持处理
        return False


def _app_name(aumid: str) -> str:
    """把会话的 AppUserModelId 变成一眼能认出的名字。"""
    if not aumid:
        return "未知播放器"
    known = _APP_NAMES.get(aumid.lower())
    if known:
        return known
    # 没收录的：UWP 的 AUMID 是"包名!应用名"，取感叹号后面那段的最内层名字
    name = aumid.split("!")[-1]
    if name.lower().endswith(".exe"):
        return name[:-4]
    return name.rsplit(".", 1)[-1]

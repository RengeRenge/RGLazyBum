"""系统音量与默认播放设备控制（Windows Core Audio）。

分两类操作：

* 音量读写 —— 通过默认播放设备上的 ``IAudioEndpointVolume``，是绝对音量，不是模拟音量键。
* 切换默认播放设备 —— 通过未公开的 ``IPolicyConfig.SetDefaultEndpoint``，
  这是 SoundSwitch / AudioSwitcher 之类的工具都在用的办法，切换后正在播放的声音会立刻改道。
"""

from __future__ import annotations

import comtypes
from pycaw.api.endpointvolume import IAudioEndpointVolume
from pycaw.api.policyconfig import IPolicyConfig
from pycaw.constants import CLSID_CPolicyConfigClient, DEVICE_STATE, EDataFlow, ERole
from pycaw.utils import AudioUtilities

__all__ = [
    "AudioError",
    "snapshot",
    "output_devices",
    "set_default_device",
    "set_volume",
    "step_volume",
    "toggle_mute",
]

_RENDER = EDataFlow.eRender.value
_MULTIMEDIA = ERole.eMultimedia.value
_ACTIVE = DEVICE_STATE.ACTIVE.value

# 设备名要从属性存储里读，比较慢，所以缓存下来，用设备 id 组成的签名判断是否失效
_device_cache: list[dict] | None = None
_device_signature: str | None = None


class AudioError(RuntimeError):
    pass


def _enumerator():
    enumerator = AudioUtilities.GetDeviceEnumerator()
    if enumerator is None:
        raise AudioError("无法访问 Windows 音频设备枚举器")
    return enumerator


def _default_endpoint():
    try:
        return _enumerator().GetDefaultAudioEndpoint(_RENDER, _MULTIMEDIA)
    except comtypes.COMError as exc:
        raise AudioError("没有找到可用的默认播放设备") from exc


def _endpoint_volume(device=None) -> IAudioEndpointVolume:
    device = device if device is not None else _default_endpoint()
    iface = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
    return iface.QueryInterface(IAudioEndpointVolume)


def _active_ids() -> list[str]:
    """只取设备 id，用来判断设备列表有没有变化——比读设备名便宜得多。"""
    try:
        collection = _enumerator().EnumAudioEndpoints(_RENDER, _ACTIVE)
    except comtypes.COMError:
        return []
    return [collection.Item(i).GetId() for i in range(collection.GetCount())]


def output_devices(force: bool = False) -> list[dict]:
    """当前可用的播放设备列表，形如 ``[{"id": ..., "name": ...}]``。"""
    global _device_cache, _device_signature

    signature = "|".join(_active_ids())
    if not force and _device_cache is not None and signature == _device_signature:
        return _device_cache

    devices = []
    for dev in AudioUtilities.GetAllDevices(_RENDER, _ACTIVE):
        devices.append({"id": dev.id, "name": dev.FriendlyName or dev.id})

    _device_cache = devices
    _device_signature = signature
    return devices


def snapshot() -> dict:
    """默认设备的音量/静音状态 + 设备列表，供服务端每秒轮询对比。"""
    device = _default_endpoint()
    endpoint = _endpoint_volume(device)
    return {
        "volume": round(float(endpoint.GetMasterVolumeLevelScalar()), 4),
        "muted": bool(endpoint.GetMute()),
        "deviceId": device.GetId(),
        "devices": output_devices(),
    }


def set_volume(value: float) -> None:
    """设置主音量，value 取 0.0 ~ 1.0。"""
    level = max(0.0, min(1.0, float(value)))
    _endpoint_volume().SetMasterVolumeLevelScalar(level, None)


def step_volume(delta: float) -> None:
    endpoint = _endpoint_volume()
    current = float(endpoint.GetMasterVolumeLevelScalar())
    level = max(0.0, min(1.0, current + float(delta)))
    endpoint.SetMasterVolumeLevelScalar(level, None)


def toggle_mute() -> None:
    endpoint = _endpoint_volume()
    endpoint.SetMute(0 if endpoint.GetMute() else 1, None)


def set_default_device(device_id: str) -> None:
    """把系统默认播放设备切到指定设备。

    三个角色（控制台 / 多媒体 / 通信）一起切，否则会出现"系统提示音还在旧设备上响"的情况。
    """
    if not device_id:
        raise AudioError("设备 id 不能为空")

    try:
        policy = comtypes.CoCreateInstance(
            CLSID_CPolicyConfigClient, IPolicyConfig, comtypes.CLSCTX_ALL
        )
    except OSError as exc:
        raise AudioError("当前系统不支持用程序切换默认播放设备") from exc

    for role in (ERole.eConsole, ERole.eMultimedia, ERole.eCommunications):
        try:
            result = policy.SetDefaultEndpoint(device_id, role.value)
        except comtypes.COMError as exc:
            raise AudioError(f"切换默认播放设备失败：{exc}") from exc
        # comtypes 在 HRESULT 为 S_OK 时返回 None，其他成功码会原样返回整数
        if result not in (None, 0):
            raise AudioError(f"切换默认播放设备失败（HRESULT={result:#x}）")

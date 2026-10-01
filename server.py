"""RGLazyBum —— 用手机浏览器通过局域网遥控 Windows 的小服务。

启动后在手机浏览器打开 http://<电脑局域网IP>:<端口> 即可，不需要装任何 App。
端口不用配：按 settings.CANDIDATE_PORTS 的顺序试，第一个能绑上的就用，
托盘菜单和二维码显示的永远是实际生效的那个。

IPv6 监听是可选的（见 settings.py 的 ipv6 开关）：打开后配合 DDNS 的 AAAA
记录可以从外网控制，此时外网入口（公网 IPv6 来源）必须带 token，局域网访问一切照旧。

程序正常形态是托盘后台程序（入口 tray.py，打包后是 RGLazyBum.exe）；
本文件的 main() 只是控制台调试形态，Ctrl+C 停。

设计要点：所有 Win32 / COM 调用都丢给一个单线程执行器执行。
一来保证命令严格按顺序生效（鼠标增量必须有序，否则光标会乱跳），
二来让 COM 与 SendInput 都跑在同一个已初始化 COM 的线程里，避免阻塞 asyncio 事件循环。
"""

from __future__ import annotations

import asyncio
import ctypes
import ipaddress
import json
import logging
import secrets
import socket
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response

import applog
import audiocontrol
import mediacontrol
import netinfo
import power
import screenshot
import settings
import wininput


def resource_dir(name: str) -> Path:
    """定位随程序分发的资源目录（web/）。

    打包冻结后 __file__ 指向 bundle 内部，资源实际解包在 sys._MEIPASS 下，
    必须优先用它，否则页面会白屏。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = Path(__file__).resolve().parent
    return Path(base) / name


WEB_DIR = resource_dir("web")
HOST = "0.0.0.0"
IPV6_HOST = "::"

logger = logging.getLogger("rglazybum")

# ------------------------------------------------------------------ 外网准入

# 只有来源是"公网 IPv6"（也就是从互联网进来的）才要 token。
# 局域网 IPv4（192.168.x.x 之类）与链路本地 / ULA 地址全部照旧，不需要带任何东西。
TOKEN_FILE = applog.LOG_DIR.parent / "token.txt"
COOKIE_NAME = "rgk"
_COOKIE_MAX_AGE = 90 * 24 * 3600

_DENIED_HTML = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>需要访问口令</title>
<style>
body{font:16px/1.7 system-ui,-apple-system,"Microsoft YaHei",sans-serif;
     margin:0;padding:9vh 6vw;color:#222;background:#fafafa}
h1{font-size:20px;margin:0 0 12px}
p{margin:0 0 10px;color:#555}
code{background:#eee;padding:2px 5px;border-radius:4px;word-break:break-all}
</style>
<h1>需要访问口令</h1>
<p>这个地址是从外网访问的，链接里必须带上口令。</p>
<p>请在电脑上的托盘菜单点「显示外网二维码（含 token）」，用手机重新扫一次。</p>
<p>局域网内直接访问 <code>192.168.x.x</code> 不需要口令。</p>
"""

_TOKEN: str | None = None


def _persist_token(token: str) -> None:
    """把口令落盘。写不进去也只影响下次启动（会另生成一个），不影响本次运行。"""
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token, encoding="ascii")
        logger.info("外网访问口令已写入 %s", TOKEN_FILE)
    except OSError:
        logger.exception("保存外网口令失败，重启后需要重新扫码")


def load_token() -> str:
    """读取外网口令，没有就生成一个并落盘（保证二维码链接长期有效）。"""
    global _TOKEN
    if _TOKEN:
        return _TOKEN

    try:
        saved = TOKEN_FILE.read_text(encoding="ascii").strip()
        if saved:
            _TOKEN = saved
            return _TOKEN
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("读取外网口令失败，本次改用临时口令")
        _TOKEN = secrets.token_urlsafe(24)
        return _TOKEN

    _TOKEN = secrets.token_urlsafe(24)
    _persist_token(_TOKEN)
    return _TOKEN


def reset_token() -> str:
    """换一个新口令并落盘，旧口令立刻作废。

    手机上已经种下的 cookie 里存的就是旧口令，下一次请求就比对不上了，
    所以要重新扫一次外网二维码。token.txt 也是同一份数据。
    """
    global _TOKEN
    _TOKEN = secrets.token_urlsafe(24)
    _persist_token(_TOKEN)
    logger.info("外网口令已重置")
    return _TOKEN


def is_public_ipv6(host: str | None) -> bool:
    """来源地址是不是公网 IPv6 —— 也就是"从互联网进来的"。"""
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return isinstance(addr, ipaddress.IPv6Address) and addr.is_global


def _gate_open(host: str | None) -> bool:
    """局域网一律放行；只有公网 IPv6 才需要口令。"""
    return not is_public_ipv6(host)


def _token_ok(supplied: str | None) -> bool:
    if not supplied:
        return False
    try:
        return secrets.compare_digest(supplied.encode("utf-8"), load_token().encode("ascii"))
    except (TypeError, UnicodeError, AttributeError):
        return False


# 音频接口要用 COM，而 COM 必须在使用它的线程里显式初始化。
# 用 MTA（多线程单元）而不是 STA，因为这个线程不会跑消息循环。
_COINIT_MULTITHREADED = 0x0


def _init_worker() -> None:
    try:
        ctypes.windll.ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    except (OSError, AttributeError):
        pass


_executor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="winctl", initializer=_init_worker
)


async def blocking(func, *args, **kwargs):
    """把同步的 Win32/COM 调用放到工作线程里执行，并保持全局串行。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, partial(func, *args, **kwargs))


# --------------------------------------------------------------------- 指令分发


async def _state_snapshot() -> dict:
    """手机端要的全部实时状态：音频（音量/静音/设备）+ 媒体播放状态。

    音频那部分是要跑在单线程执行器里的 COM 调用；媒体会话是 WinRT 的异步接口，
    直接在事件循环里 await 就行。
    """
    state = await blocking(audiocontrol.snapshot)
    state["media"] = await mediacontrol.snapshot()
    return state


async def dispatch(action: str, params: dict):
    """执行一条指令，返回需要回给前端的附加数据（通常为 None）。"""
    if action == "media.playpause":
        # 优先按 GSMTC 控制 snapshot() 报告的那条会话；没有会话时才退回系统媒体键
        if not await mediacontrol.play_pause():
            await blocking(wininput.media_play_pause)
    elif action == "media.next":
        if not await mediacontrol.next_track():
            await blocking(wininput.media_next)
    elif action == "media.prev":
        if not await mediacontrol.previous_track():
            await blocking(wininput.media_prev)
    elif action == "media.stop":
        await blocking(wininput.media_stop)
    elif action == "media.seek":
        # delta 单位是秒：负数是快退，正数是快进
        await mediacontrol.seek(float(params.get("delta", 0.0)))

    elif action == "vol.set":
        await blocking(audiocontrol.set_volume, float(params.get("value", 0.0)))
    elif action == "vol.step":
        await blocking(audiocontrol.step_volume, float(params.get("delta", 0.0)))
    elif action == "vol.toggle":
        await blocking(audiocontrol.toggle_mute)

    elif action == "audio.refresh":
        return await _state_snapshot()
    elif action == "audio.set":
        device_id = str(params.get("id") or "")
        if not device_id:
            raise ValueError("缺少音频设备 id")
        await blocking(audiocontrol.set_default_device, device_id)

    elif action == "mouse.move":
        await blocking(
            wininput.move_mouse,
            int(params.get("dx", 0)),
            int(params.get("dy", 0)),
        )
    elif action == "mouse.button":
        await blocking(
            wininput.mouse_button,
            str(params.get("button", "left")),
            str(params.get("action", "click")),
        )
    elif action == "mouse.wheel":
        await blocking(wininput.mouse_wheel, int(params.get("delta", 0)))

    elif action == "window.move":
        await blocking(
            wininput.move_window_to_other_monitor, str(params.get("direction", "right"))
        )
    elif action == "text.send":
        text = str(params.get("text") or "")
        if text:
            await blocking(wininput.type_text, text)
    elif action == "key.press":
        await blocking(wininput.press_named_key, str(params.get("key") or ""))

    elif action == "power.monitor_off":
        await blocking(power.monitor_off)
    elif action == "power.wake":
        await blocking(power.wake_display)
    elif action == "power.lock":
        await blocking(power.lock)
    elif action == "power.sleep":
        return {"_notice": "电脑即将进入睡眠，需要用开机卡或电源键唤醒", "_then": power.sleep}
    elif action == "power.hibernate":
        return {"_notice": "电脑即将休眠，需要用开机卡或电源键唤醒", "_then": power.hibernate}

    else:
        raise ValueError(f"未知指令：{action}")

    return None


def _describe(exc: BaseException) -> str:
    if isinstance(
        exc,
        (
            wininput.InputError,
            power.PowerError,
            audiocontrol.AudioError,
            mediacontrol.MediaError,
        ),
    ):
        return str(exc)
    if isinstance(exc, (ValueError, TypeError)):
        return str(exc)
    logger.exception("指令执行失败")
    return f"{type(exc).__name__}: {exc}"


# ----------------------------------------------------------------- 连接与广播

_clients: set[WebSocket] = set()
_last_payload: dict = {}


async def _send(websocket: WebSocket, message: dict) -> None:
    try:
        await websocket.send_text(json.dumps(message, ensure_ascii=False))
    except Exception:
        _clients.discard(websocket)


async def broadcast(message: dict) -> None:
    if not _clients:
        return
    data = json.dumps(message, ensure_ascii=False)
    listeners = list(_clients)
    results = await asyncio.gather(
        *(ws.send_text(data) for ws in listeners), return_exceptions=True
    )
    for ws, result in zip(listeners, results):
        if isinstance(result, Exception):
            _clients.discard(ws)


async def watch_state() -> None:
    """每秒对一次系统状态，有变化就推给所有手机端。

    这样在电脑上按键盘改音量、切换设备、插拔耳机，或者在电脑上手动播放/暂停，
    手机界面都会跟着变。
    """
    global _last_payload
    while True:
        await asyncio.sleep(1.0)
        if not _clients:
            continue
        try:
            state = await _state_snapshot()
        except Exception:
            logger.debug("读取系统状态失败", exc_info=True)
            continue

        if state != _last_payload:
            _last_payload = state
            await broadcast({"t": "state", "d": state})


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(watch_state())
    try:
        yield
    finally:
        task.cancel()
        # 重启服务时旧连接已经随着上一个事件循环一起死掉，
        # 不清空的话首轮广播会打到死 socket 上。
        _clients.clear()


# ------------------------------------------------------------------- Web 服务

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def external_gate(request: Request, call_next):
    """外网准入。

    只有来源是公网 IPv6 时才拦；局域网（含手机连的 192.168.x.x）完全不受影响。
    带一次的 k 参数访问过之后就种 cookie，页面里的 app.js / style.css
    以及后面的 WebSocket 握手都会自动带上，不用改前端一行代码。
    """
    host = request.client.host if request.client else None
    if _gate_open(host):
        return await call_next(request)

    supplied = request.query_params.get("k") or request.cookies.get(COOKIE_NAME)
    if not _token_ok(supplied):
        logger.warning("拒绝未携带口令的外网访问：%s %s 来自 %s", request.method, request.url.path, host)
        return HTMLResponse(_DENIED_HTML, status_code=403)

    response = await call_next(request)
    if request.query_params.get("k"):
        response.set_cookie(
            COOKIE_NAME,
            supplied,
            max_age=_COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="lax",
        )
    return response


# 页面三件套每次都让浏览器回服务器问一句。
# 不带 Cache-Control 的话浏览器会按启发式规则自己缓存，换了新版 exe 之后
# 手机还拿着旧的 app.js 跑，界面看着就是"改了没生效"。
# no-cache 不是不缓存，是每次都校验，没变就回 304，照样省流量。
_NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html", media_type="text/html; charset=utf-8", headers=_NO_CACHE
    )


@app.get("/style.css")
async def stylesheet() -> FileResponse:
    return FileResponse(
        WEB_DIR / "style.css", media_type="text/css; charset=utf-8", headers=_NO_CACHE
    )


@app.get("/app.js")
async def script() -> FileResponse:
    return FileResponse(
        WEB_DIR / "app.js", media_type="text/javascript; charset=utf-8", headers=_NO_CACHE
    )


@app.get("/api/screens")
async def screens() -> list[dict]:
    """显示器列表，手机端一块屏一个模块。"""
    try:
        return await asyncio.to_thread(screenshot.monitors)
    except Exception as exc:
        logger.exception("枚举显示器失败")
        raise HTTPException(status_code=500, detail=f"枚举显示器失败：{exc}") from exc


@app.get("/api/shot")
async def shot(m: int = 0, w: int = 1600, q: int = 70) -> Response:
    """某块显示器的截图（JPEG）。m 是 /api/screens 里的序号。

    抓图要几十到几百毫秒，扔到线程里做：占着事件循环的话，这期间鼠标指令就卡住了。
    """
    width = max(320, min(w, screenshot.MAX_WIDTH_LIMIT))
    quality = max(screenshot.MIN_QUALITY, min(q, screenshot.MAX_QUALITY))
    try:
        data = await asyncio.to_thread(screenshot.capture_jpeg, m, width, quality)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("截图失败")
        raise HTTPException(status_code=500, detail=f"截图失败：{exc}") from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.websocket("/ws")
async def control_channel(websocket: WebSocket) -> None:
    # HTTP 中间件管不到 WebSocket，这里必须单独守一道。
    # 浏览器在握手时会自动带上 cookie，所以外网扫码一次之后就是通的。
    host = websocket.client.host if websocket.client else None
    if not _gate_open(host) and not _token_ok(
        websocket.query_params.get("k") or websocket.cookies.get(COOKIE_NAME)
    ):
        logger.warning("拒绝未携带口令的外网 WebSocket：%s", host)
        await websocket.close(code=1008)
        return

    await websocket.accept()
    _clients.add(websocket)
    logger.info("手机已接入：%s", websocket.client)

    try:
        try:
            await _send(websocket, {"t": "state", "d": await _state_snapshot()})
        except Exception:
            logger.debug("初始状态推送失败", exc_info=True)

        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
                action = str(message.get("a", ""))
                params = message.get("p")
                if not isinstance(params, dict):
                    params = {}
            except (ValueError, AttributeError):
                continue

            try:
                result = await dispatch(action, params)
            except Exception as exc:
                await _send(websocket, {"t": "err", "a": action, "msg": _describe(exc)})
                continue

            # 睡眠/休眠会挂起整个系统，先把提示发出去，再执行
            if isinstance(result, dict) and "_then" in result:
                await broadcast({"t": "notice", "msg": result["_notice"]})
                try:
                    await blocking(result["_then"])
                except Exception as exc:
                    await _send(websocket, {"t": "err", "a": action, "msg": _describe(exc)})
                continue

            if result:
                await _send(websocket, {"t": "state", "d": result})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("控制通道异常")
    finally:
        _clients.discard(websocket)
        logger.info("手机已断开：%s", websocket.client)


# --------------------------------------------------------------------- 启动


def lan_addresses() -> list[str]:
    """尽量猜出本机在局域网里的 IPv4 地址，方便直接在手机上打开。"""
    addresses: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass

    if not addresses:
        # 兜底：UDP connect 不会真的发包，只是让系统选出默认出口网卡的地址
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("8.8.8.8", 80))
                addresses.append(probe.getsockname()[0])
        except OSError:
            pass

    return addresses


def print_banner(port: int) -> None:
    addresses = lan_addresses()
    lines = [
        "",
        "=" * 56,
        "  懒狗 手机遥控已启动",
        "",
        "  手机浏览器打开下面任意一个地址（需和电脑在同一局域网）：",
    ]
    if addresses:
        lines += [f"      http://{ip}:{port}" for ip in addresses]
    else:
        lines.append(f"      http://<本机局域网IP>:{port}")
    lines += [
        "",
        "  停止服务：在本窗口按 Ctrl+C",
        f"  端口：按 {settings.CANDIDATE_PORTS} 的顺序自动挑，不用手动配。",
        "  安全提示：局域网内没有口令，别在不可信的网络上开着；",
        "            从外网（IPv6/DDNS）进来必须带 token。",
        "=" * 56,
        "",
    ]
    print("\n".join(lines), flush=True)


def _bind(family: int, address: tuple) -> socket.socket:
    """绑定一个监听套接字。

    刻意不设 SO_REUSEADDR —— Windows 上它的语义跟 Unix 恰好相反（本机实测）：
    - 不设：端口被别人占着就老老实实报 10048，而"能发现占用并往下一个候选端口
      退让"正是自动选端口的前提；
    - 设了：反而会抢到占位者的端口上。对方也设了 SO_REUSEADDR 时连错误都不报，
      直接绑成功，于是两个进程抢同一批连接（包里的 exe 自己就是这么绑的，
      所以第二个实例能"看起来启动成功"却把第一个实例的连接抢走）。
    Unix 上设它是为了免掉 TIME_WAIT 的纠缠；这里实测 TIME_WAIT（服务端先关连接）
    不设也能正常绑上，所以没有任何理由保留它。
    """
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if family == socket.AF_INET6:
            # 显式独占：两个套接字分工明确，IPv6 这个不收 IPv4 映射连接，
            # 否则会跟下面的 0.0.0.0 抢同一批 IPv4 流量。
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, True)
        sock.bind(address)
        sock.set_inheritable(True)
    except OSError:
        sock.close()
        raise
    return sock


def listen_sockets(port: int, *, ipv6: bool = True) -> list[socket.socket]:
    """建好监听套接字，交给 uvicorn 一个事件循环跑。

    为什么不直接把 HOST 改成 "::"：CPython 的 asyncio 对 AF_INET6 套接字会强制
    IPV6_V6ONLY=1，那样监听会变成纯 IPv6，局域网 IPv4（手机在家连的那个）会直接废掉。
    所以老老实实开两个，显式各管一族。

    IPv4 是必须的，绑不上就抛异常交给调用方翻译；IPv6 失败只降级（比如系统禁了 IPv6），
    不该连累局域网。ipv6=False 时压根不开第二个套接字，外网入口随之消失。
    """
    opened = [_bind(socket.AF_INET, (HOST, port))]
    if not ipv6:
        return opened
    try:
        opened.append(_bind(socket.AF_INET6, (IPV6_HOST, port)))
    except OSError as exc:
        logger.warning("IPv6 监听失败，外网访问不可用（局域网不受影响）：%s", exc)
    return opened


def bind_first(
    ports: Sequence[int], *, ipv6: bool = True
) -> tuple[int, list[socket.socket]]:
    """按顺序试候选端口，返回第一个绑得上的 (端口, 监听套接字)。

    端口顺序由 settings.CANDIDATE_PORTS 决定。全部绑不上就把最后一个 OSError
    抛出去（errno 精确），调用方用 describe_all_failed() 翻译成人话。
    """
    failure: OSError | None = None
    for port in ports:
        try:
            return port, listen_sockets(port, ipv6=ipv6)
        except OSError as exc:
            failure = exc
            logger.warning("端口 %d 绑不上，试下一个：%s", port, exc)
    assert failure is not None, "候选端口列表不能为空"
    raise failure


def create_server(port: int) -> uvicorn.Server:
    """按托盘模式的口径构造 uvicorn.Server（不启动）。

    log_config=None：别让 uvicorn 的 dictConfig 覆盖我们自己的日志 handler。
    timeout_graceful_shutdown=3：默认值是无限等待存活连接，
    手机上开着控制页时点"退出"会永久卡死。
    """
    config = uvicorn.Config(
        app,
        host=HOST,
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
        timeout_graceful_shutdown=3,
    )
    return uvicorn.Server(config)


def run_server(
    ports: Sequence[int], on_ready=None, on_bound=None, *, ipv6: bool = True
) -> None:
    """在当前线程运行服务，阻塞到 server.should_exit 生效为止。

    端口从 ports 里按顺序试，第一个绑得上的生效。on_ready 会在真正 run() 之前
    拿到 Server 实例，方便调用方持有它以便停止；on_bound 在端口定下来之后立刻
    收到实际端口 —— 二维码、托盘菜单、防火墙规则都得用这个值，不能靠猜。

    所有候选端口都绑不上会抛 OSError（精确到 errno），调用方可以用
    describe_all_failed() 翻译成人话。
    """
    port, sockets = bind_first(ports, ipv6=ipv6)
    logger.info("候选端口里 %d 可用，服务将监听它", port)
    if on_bound is not None:
        on_bound(port)

    server = create_server(port)
    if on_ready is not None:
        on_ready(server)
    try:
        server.run(sockets=sockets)
    finally:
        for sock in sockets:
            sock.close()


def describe_all_failed(ports: Sequence[int]) -> str:
    """候选端口全军覆没时给一句人话。

    逐个端口解释太长，气球提示放不下；报第一个端口的原因就够定位了 ——
    通常几个端口失败原因是同一个（比如被安全软件拦了 TCP 入站）。
    """
    listed = " / ".join(str(port) for port in ports)
    return f"候选端口 {listed} 全都无法监听。{describe_port_problem(ports[0])}"


def describe_port_problem(port: int) -> str:
    """端口起不来时给一句人话。只在失败之后调用，用一次探测判断原因。

    两种 errno 的处置完全不同，必须分开说：
    - 10048 WSAEADDRINUSE：被别的程序占着（动态端口范围里的号容易被临时占走）
    - 10013 WSAEACCES：落在系统保留的端口段里（Hyper-V/WSL 或管理员保留），只能换端口
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # 故意不设 SO_REUSEADDR：Windows 下它会绕过占用检查，探测就失去意义
        probe.bind((HOST, port))
    except OSError as exc:
        code = getattr(exc, "winerror", None) or exc.errno
        if code == 10013 or exc.errno == 13:
            return f"端口 {port} 落在系统保留的端口段里，请换一个端口"
        if code == 10048:
            return f"端口 {port} 已被其它程序占用，请换一个端口"
        return f"端口 {port} 无法监听：{exc}"
    finally:
        probe.close()
    return f"端口 {port} 现在看着是空闲的，启动失败的具体原因见日志"


def shutdown_executor() -> None:
    """显式关闭 Win32/COM 单线程执行器。

    它不是事件循环的默认执行器，工作线程也不是守护线程，
    不关的话会拖住解释器退出。
    """
    _executor.shutdown(wait=False, cancel_futures=True)


def main() -> None:
    # 控制台调试模式：端口规则跟托盘一致，都按候选列表自动挑。
    ipv6 = settings.ipv6_enabled()
    try:
        port, sockets = bind_first(settings.CANDIDATE_PORTS, ipv6=ipv6)
    except OSError as exc:
        print(describe_all_failed(settings.CANDIDATE_PORTS), file=sys.stderr)
        raise SystemExit(1) from exc

    print_banner(port)

    if ipv6:
        url = netinfo.external_url(port, load_token())
        if url:
            print(f"外网入口（要口令）：{url}", flush=True)
        else:
            print("已开启 IPv6 外网访问，但没找到公网 IPv6 地址，也没配 DDNS 域名", flush=True)
            print("在 %LOCALAPPDATA%\\RGLazyBum\\config.json 里设置 ddns_host", flush=True)

    # 刻意不用 create_server()：要保留 uvicorn 默认那套控制台日志
    # （log_config=None 是托盘模式才需要的）。
    uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False)
    ).run(sockets=sockets)


if __name__ == "__main__":
    main()

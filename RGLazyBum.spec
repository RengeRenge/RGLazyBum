# -*- mode: python ; coding: utf-8 -*-
"""RGLazyBum 打包规格：onedir + 无控制台窗口。

必须用 onedir，不能用 onefile：
    onefile 的引导程序会把自身解压到随机临时目录再拉起子进程，进程镜像路径
    每次都不同且退出即删，Windows 防火墙的"程序型"规则永远匹配不上。
    onedir 在 Windows 上只有一个进程，镜像路径就是稳定的 dist\\RGLazyBum\\RGLazyBum.exe，
    firewall.py 也因此能一次加好规则、以后换端口不用再管。

构建：build.bat（或 pyinstaller --noconfirm --clean RGLazyBum.spec）
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    # uvicorn 的 loop / http / ws / lifespan 默认是 "auto"，走运行时动态导入，
    # PyInstaller 静态分析看不到，必须显式声明，否则打包后起服务报 ImportError。
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # comtypes 运行时会动态生成/导入子模块，漏收会报
    # ModuleNotFoundError: No module named 'comtypes.stream'
    *collect_submodules("comtypes"),
    # 媒体会话（mediacontrol.py）走 winsdk 的 WinRT 投影。winsdk 是命名空间包，
    # 每个命名空间就是一个 __init__.py，真正的类型信息由 _winrt 扩展在运行时
    # 从系统元数据里读出来。这里只列用得上的几个命名空间：全量 collect_submodules
    # 会把 300 多个命名空间都扫一遍，白白拖慢打包。
    "winsdk._winrt",
    "winsdk.system",
    "winsdk.windows.media.control",
    "winsdk.windows.foundation",
    "winsdk.windows.foundation.collections",
    "winsdk.windows.media",
    "winsdk.windows.storage.streams",
]

a = Analysis(
    ["tray.py"],
    pathex=[],
    binaries=[],
    datas=[("web", "web")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RGLazyBum",
    icon="fish.ico",        # 咸鱼：和托盘图标、安卓启动图标、网页 favicon 同一套图形
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无控制台窗口；applog 会把 None 标准流换成日志代理
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RGLazyBum",
)

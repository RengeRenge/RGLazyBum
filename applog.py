"""RGLazyBum 日志与未捕获异常处理。

后台模式（pythonw / --noconsole）下没有控制台：sys.stdout 与 sys.stderr 都是 None，
任何 print 都会抛 AttributeError。setup() 会把它们换成写进日志文件的代理，
并安装全局异常钩子，保证后台运行时异常不会静默消失。
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "RGLazyBum" / "logs"
LOG_FILE = LOG_DIR / "rglazybum.log"

LOGGER_NAME = "rglazybum"
_MAX_BYTES = 1 << 20
_BACKUP_COUNT = 3


class _StreamToLogger:
    """把 write/flush 转发给 logging 的伪文件对象，用来替代被置空的标准流。"""

    def __init__(self, logger: logging.Logger, level: int) -> None:
        self._logger = logger
        self._level = level
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line.rstrip())
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._logger.log(self._level, self._buffer.rstrip())
        self._buffer = ""

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError("日志代理没有真实的文件描述符")


def setup(verbose: bool = False) -> logging.Logger:
    """配置项目 logger，日志写到 %LOCALAPPDATA%\\RGLazyBum\\logs\\rglazybum.log。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
            )
        )
        logger.addHandler(handler)

    # 没有控制台时标准流是 None，换成写日志的代理，print 就不会炸
    if sys.stdout is None:
        sys.stdout = _StreamToLogger(logger, logging.INFO)
    if sys.stderr is None:
        sys.stderr = _StreamToLogger(logger, logging.ERROR)

    return logger


def install_excepthooks() -> None:
    """安装全局异常钩子，把未捕获异常写进日志。"""
    logger = logging.getLogger(LOGGER_NAME)

    def _hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logger.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread else "?"
        logger.critical(
            "线程 %s 未捕获异常",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def open_log_file() -> None:
    """用系统默认程序打开日志文件（不存在时先建一个空文件）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    os.startfile(LOG_FILE)  # type: ignore[attr-defined]

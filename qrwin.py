"""二维码窗口：跑在独立的 Tk 线程里。

托盘侧只往队列里投命令（show / hide / ask / shutdown），绝不在别的线程碰 tkinter。
窗口常驻不销毁，只 withdraw / deiconify —— 反复 destroy 会踩
`Tcl_AsyncDelete: async handler deleted by the wrong thread`。

同一个 Tk 线程还负责弹单行输入框（托盘菜单里的设置 DDNS 域名 / 端口用）。tkinter 只允许
一个 Tk 实例，另起一个根窗口很容易踩线程问题，所以统一放这里。

可单独运行做探针：
    python qrwin.py http://192.168.3.10:8765
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk

import qrcode
from PIL import Image, ImageTk

_CMD_SHOW = "show"
_CMD_HIDE = "hide"
_CMD_ASK = "ask"
_CMD_QUIT = "quit"

_BG = "#11161d"
_FG = "#eef2f7"
_ACCENT = "#5aa9ff"

_HEADING_TEXT = "手机扫一扫，打开控制页"
_FONT_HEADING = ("Microsoft YaHei UI", 12, "bold")
_FONT_URL = ("Consolas", 12)
_FONT_ALT = ("Consolas", 9)
_FONT_PROMPT = ("Microsoft YaHei UI", 10)
_FONT_INPUT = ("Consolas", 11)

# 窗口宽度写死。宽度跟着内容走的话，局域网地址和外网链接换着看时窗口会忽宽忽窄。
# 600px 够标题和局域网地址各占一行，带 token 的外网链接则折成两行。
_WINDOW_WIDTH = 600
_PADX = 18  # 控件左右留白，pack 的 padx
_CONTENT_WIDTH = _WINDOW_WIDTH - 2 * _PADX  # 文字折行宽度（wraplength）


class _Prompt:
    """一次输入框请求的结果槽：调用方等 event，用户操作后填 value。"""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: str | None = None


def make_qr_image(url: str, box: int = 260) -> Image.Image:
    """把 URL 编成一张 box×box 的黑白二维码位图。"""
    qr = qrcode.QRCode(border=2, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return image.resize((box, box), Image.NEAREST)


class QrWindow:
    """二维码窗口的门面：所有 tkinter 调用都发生在自己的线程里。"""

    def __init__(self, box: int = 260) -> None:
        self._box = box
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._root: tk.Tk | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._qr_label: tk.Label | None = None
        self._url_label: tk.Label | None = None
        self._alt_label: tk.Label | None = None
        self._positioned = False
        self._drag_origin = (0, 0)

    # ------------------------------------------------------------ 外部接口

    def start(self) -> None:
        """懒启动 Tk 线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._main, name="qrwin", daemon=True)
        self._thread.start()
        self._ready.wait(5.0)

    def show(self, urls: list[str]) -> None:
        self.start()
        self._queue.put((_CMD_SHOW, list(urls)))

    def hide(self) -> None:
        if self._thread is None:
            return
        self._queue.put((_CMD_HIDE, None))

    def ask_text(
        self, title: str, prompt: str, initial: str = "", timeout: float = 180.0
    ) -> str | None:
        """弹一个单行输入框并等结果；取消、关窗或超时都返回 None。

        这是阻塞调用，必须在非 Tk、非菜单回调的线程里用 ——
        Tk 线程要空出来跑 mainloop，pystray 的菜单线程也不能堵。
        """
        self.start()
        if self._root is None:
            return None

        slot = _Prompt()
        self._queue.put((_CMD_ASK, (title, prompt, initial, slot)))
        if not slot.event.wait(timeout):
            return None
        return slot.value

    def shutdown(self, timeout: float = 3.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._queue.put((_CMD_QUIT, None))
        thread.join(timeout)
        if thread.is_alive():
            # Tk 线程卡住也不该拖住退出：它是守护线程，直接放弃
            self._root = None
        self._thread = None

    # --------------------------------------------------------- Tk 线程内部

    def _main(self) -> None:
        try:
            self._build()
        except Exception:
            self._ready.set()
            raise
        self._ready.set()
        if self._root is None:
            return
        self._root.after(120, self._poll)
        try:
            self._root.mainloop()
        finally:
            # Tk/Tcl 对象必须在创建它们的线程里释放。留着引用的话，
            # 解释器退出时会由主线程 GC，触发
            # "Tcl_AsyncDelete: async handler deleted by the wrong thread"。
            self._photo = None
            self._qr_label = None
            self._url_label = None
            self._alt_label = None
            self._root = None

    def _build(self) -> None:
        root = tk.Tk()
        self._root = root
        root.title("懒狗 扫码连接")
        root.configure(bg=_BG)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self._do_hide)

        heading = tk.Label(
            root, text=_HEADING_TEXT, bg=_BG, fg=_FG, font=_FONT_HEADING,
        )
        heading.pack(padx=_PADX, pady=(16, 10))

        self._qr_label = tk.Label(root, bg="white", bd=0)
        self._qr_label.pack(padx=_PADX)

        self._url_label = tk.Label(
            root, text="", bg=_BG, fg=_ACCENT, wraplength=_CONTENT_WIDTH,
            font=_FONT_URL, justify="center",
        )
        self._url_label.pack(padx=_PADX, pady=(12, 4))

        self._alt_label = tk.Label(
            root, text="", bg=_BG, fg="#8b98a8", wraplength=_CONTENT_WIDTH,
            font=_FONT_ALT, justify="center",
        )
        self._alt_label.pack(padx=_PADX, pady=(0, 14))

        for widget in (root, heading, self._qr_label, self._url_label, self._alt_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        root.withdraw()

    def _poll(self) -> None:
        root = self._root
        if root is None:
            return
        try:
            while True:
                command, payload = self._queue.get_nowait()
                if command == _CMD_QUIT:
                    root.destroy()
                    return
                if command == _CMD_SHOW:
                    self._apply_show([str(u) for u in payload])
                elif command == _CMD_HIDE:
                    self._do_hide()
                elif command == _CMD_ASK:
                    self._apply_ask(payload)
        except queue.Empty:
            pass
        root.after(120, self._poll)

    # ------------------------------------------------------------ 窗口动作

    def _apply_show(self, urls: list[str]) -> None:
        root = self._root
        if root is None or not urls:
            return
        primary = urls[0]
        others = list(urls[1:])
        alt_text = "其它可用地址：\n" + "\n".join(others) if others else ""

        if self._url_label is not None:
            self._url_label.configure(text=primary)
        if self._alt_label is not None:
            self._alt_label.configure(text=alt_text)

        self._photo = ImageTk.PhotoImage(make_qr_image(primary, self._box))
        if self._qr_label is not None:
            self._qr_label.configure(image=self._photo)

        # 宽度钉死在 _WINDOW_WIDTH，只有高度跟着内容走。
        # 位置只在第一次显示时定，之后由用户自己拖，别每弹一次就跳一下。
        root.update_idletasks()
        height = root.winfo_reqheight()
        if self._positioned:
            root.geometry(f"{_WINDOW_WIDTH}x{height}")
        else:
            self._place_window(height)
            self._positioned = True

        root.deiconify()
        root.lift()
        root.attributes("-topmost", True)
        try:
            root.focus_force()
        except tk.TclError:
            pass

    def _do_hide(self) -> None:
        if self._root is not None:
            self._root.withdraw()

    def _apply_ask(self, payload: object) -> None:
        """弹单行输入框。不做模态等待，免得堵住 _poll 与 mainloop。"""
        root = self._root
        if root is None:
            return
        title, prompt, initial, slot = payload  # type: ignore[misc]

        top = tk.Toplevel(root)
        top.title(title)
        top.configure(bg=_BG)
        top.resizable(False, False)
        top.attributes("-topmost", True)

        tk.Label(
            top, text=prompt, bg=_BG, fg=_FG, justify="left", wraplength=380,
            font=_FONT_PROMPT,
        ).pack(padx=18, pady=(16, 8), anchor="w")

        entry = tk.Entry(
            top, width=34, font=_FONT_INPUT, bg="#1b2430", fg=_FG,
            insertbackground=_FG, relief="flat",
        )
        entry.insert(0, initial)
        entry.pack(padx=18, ipady=5)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def finish(value: str | None) -> None:
            slot.value = value
            slot.event.set()  # 先放行调用方再销毁窗口
            top.destroy()

        buttons = tk.Frame(top, bg=_BG)
        buttons.pack(padx=18, pady=(14, 16), anchor="e")
        tk.Button(buttons, text="取消", width=8, command=lambda: finish(None)).pack(side="right")
        tk.Button(
            buttons, text="保存", width=8, command=lambda: finish(entry.get().strip())
        ).pack(side="right", padx=(0, 8))

        top.bind("<Return>", lambda _event: finish(entry.get().strip()))
        top.bind("<Escape>", lambda _event: finish(None))
        top.protocol("WM_DELETE_WINDOW", lambda: finish(None))

        # 刻意不用 transient()：根窗口平时是 withdraw 状态，transient 会跟着一起藏起来
        top.update_idletasks()
        x = (top.winfo_screenwidth() - top.winfo_reqwidth()) // 2
        y = (top.winfo_screenheight() - top.winfo_reqheight()) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        top.lift()
        try:
            top.focus_force()
        except tk.TclError:
            pass

    def _place_window(self, height: int) -> None:
        root = self._root
        if root is None:
            return
        x = (root.winfo_screenwidth() - _WINDOW_WIDTH) // 2
        y = (root.winfo_screenheight() - height) // 3
        root.geometry(f"{_WINDOW_WIDTH}x{height}+{max(x, 0)}+{max(y, 0)}")

    def _drag_start(self, event: tk.Event) -> None:
        root = self._root
        if root is None:
            return
        self._drag_origin = (event.x_root - root.winfo_x(), event.y_root - root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        root = self._root
        if root is None:
            return
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        root.geometry(f"+{x}+{y}")


if __name__ == "__main__":
    import sys

    probe = QrWindow()
    probe.start()
    probe.show(sys.argv[1:] or ["http://127.0.0.1:8765"])
    threading.Event().wait()

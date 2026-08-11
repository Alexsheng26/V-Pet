"""未捕获异常的落地点。和 state.py / config.py 一样**不 import Qt**。

`console=False` 的窗口程序没有可看的 stderr：抛一个未捕获异常的表现就是
**"宠物突然不见了"** —— 托盘图标没了、窗口没了、什么都不留下。
用户没法反馈"它崩了，是这么崩的"，开发者也无从排查。
这是这类程序最难受的失败方式，比崩溃本身更麻烦。

所以装一个兜底，把 traceback 连同版本、平台、时间写进
`%APPDATA%\\v-pet\\crash.log`，再由调用方弹一条通知告诉用户日志在哪。

**去重是必需的，不是优化。** 实测 PySide6 6.11 在槽函数里抛异常之后
`sys.excepthook` 会被调用，但**事件循环照常跑下去**（不会 abort）——
而宠物的主循环是 60fps，同一个 bug 会每秒往日志里写 60 条，
几分钟就能把磁盘写满。所以同一个 traceback 只记第一次。
"""

from __future__ import annotations

import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import __version__
from .config import config_path

LOG_NAME = "crash.log"
# 超过就从头写。保留最近的比保留最早的有用 —— 最早那条多半早就修掉了。
MAX_BYTES = 256 * 1024

_seen: set[str] = set()
_lock = threading.Lock()


def log_path() -> Path:
    """和 config.json 同目录 —— 用户找一个地方就够了。"""
    return config_path().with_name(LOG_NAME)


def reset() -> None:
    """清掉去重记录。只有测试会用。"""
    with _lock:
        _seen.clear()


def _environment() -> str:
    frozen = getattr(sys, "frozen", False)
    return (
        f"v-pet {__version__} | Python {platform.python_version()} | "
        f"{platform.system()} {platform.release()} | frozen={frozen}"
    )


def record(exc_type, value, tb, path: Path | None = None) -> Path | None:
    """记一条崩溃。返回写入的文件路径；重复的或写不进去的返回 None。

    整个函数**绝不抛异常** —— 一个会崩的崩溃处理器比没有还糟。
    """
    try:
        text = "".join(traceback.format_exception(exc_type, value, tb))
    except Exception:
        text = f"{exc_type}: {value}\n（traceback 格式化失败）\n"

    with _lock:
        if text in _seen:
            return None                 # 60fps 的主循环会把同一个异常刷爆
        _seen.add(text)

    target = path or log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > MAX_BYTES:
            target.write_text(
                f"（日志超过 {MAX_BYTES // 1024} KB，已从头开始）\n", encoding="utf-8"
            )
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with target.open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp} =====\n{_environment()}\n{text}")
        return target
    except Exception:
        return None                     # 磁盘满了、没权限之类，认了


def install(
    path: Path | None = None,
    notify: Callable[[Path | None], None] | None = None,
    echo: bool = True,
) -> None:
    """接管未捕获异常。

    notify 是给窗口层留的回调（弹托盘通知），参数是日志路径。
    这里刻意不直接调 Qt —— 这个模块要保持 Qt-free，才能进 CI 的架构守卫。
    """

    def handle(exc_type, value, tb) -> None:
        written = record(exc_type, value, tb, path)
        # 仍然按原样打一份到 stderr：开发时是从控制台跑的，那里看得见。
        # 打包后 stderr 没人看，但也无害。echo=False 是给测试用的 —— 否则
        # 每个用例都会往测试输出里吐一段 traceback，真失败时反而找不着。
        if echo:
            try:
                traceback.print_exception(exc_type, value, tb)
            except Exception:
                pass
        if notify is not None:
            try:
                notify(written)
            except Exception:
                pass

    sys.excepthook = handle

    def handle_thread(args) -> None:
        handle(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = handle_thread

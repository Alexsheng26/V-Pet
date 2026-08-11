"""单实例保护。和 autostart.py 一类：只用 Win32，**不 import Qt**。

双击两次 exe 就会有两只宠物，而它们**写的是同一个 `config.json`** ——
位置、大小、跟随开关互相覆盖，最后谁退出得晚谁说了算。
开机自启之后再手动打开一次也会撞上，而这恰恰是最容易发生的情况。

**用命名互斥量而不是锁文件。** 锁文件在进程被任务管理器杀掉、崩溃、
或者断电之后会留在磁盘上，程序从此再也起不来 —— 那比没有保护更糟。
互斥量由系统持有，进程无论怎么死，句柄一关系统就释放。

名字用 `Local\\` 前缀（会话内唯一）而不是 `Global\\`：配置存在 %APPDATA%，
本来就是每个用户各一份，两个用户各养一只宠物是对的。`Global\\` 还需要额外权限。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

MUTEX_NAME = r"Local\v-pet.single-instance"
WAKE_MESSAGE_NAME = "v-pet.wake"

_ERROR_ALREADY_EXISTS = 183
_HWND_BROADCAST = 0xFFFF

_IS_WINDOWS = sys.platform == "win32"

# 句柄必须一直拿着。被垃圾回收掉的话互斥量就释放了，第二个实例又能进来。
_handle: int | None = None

if _IS_WINDOWS:
    _kernel32 = ctypes.windll.kernel32
    _user32 = ctypes.windll.user32
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]


def acquire(name: str = MUTEX_NAME) -> bool:
    """抢占单实例标记。True = 我是第一个，可以继续跑。

    非 Windows 平台一律返回 True —— 没有保护，但也不该拦着人跑。
    """
    global _handle
    if not _IS_WINDOWS:
        return True

    handle = _kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True                       # 建不出来就别拦着，宁可放行

    if _kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)     # 已经有一个了，把自己这份还回去
        return False

    _handle = handle
    return True


def release() -> None:
    """主动释放。正常退出时系统也会回收，这个只是让意图明确。"""
    global _handle
    if _handle and _IS_WINDOWS:
        _kernel32.CloseHandle(_handle)
    _handle = None


def wake_message() -> int:
    """一个全系统唯一的消息号。同一个字符串在任何进程里注册到的值都相同，
    这正是拿它做跨进程招呼的原因。"""
    if not _IS_WINDOWS:
        return 0
    return _user32.RegisterWindowMessageW(WAKE_MESSAGE_NAME)


def broadcast_wake() -> bool:
    """告诉已经在跑的那只"有人又双击了一次，露个面吧"。

    第二个实例直接闷声退出的话，用户看到的是"双击了没反应" ——
    尤其是宠物正被"藏起来"的时候，他会以为程序坏了。
    """
    if not _IS_WINDOWS:
        return False
    return bool(_user32.PostMessageW(_HWND_BROADCAST, wake_message(), 0, 0))

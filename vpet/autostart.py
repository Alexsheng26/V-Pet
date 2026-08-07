"""开机自启：写 HKCU 的 Run 键。

只碰 HKEY_CURRENT_USER，不碰 HKLM —— 后者要管理员权限，而且是改**整台机器**
的行为。一个桌宠没有任何理由需要那个。

默认是关的，只有用户自己在菜单里勾选才会写注册表。

所有函数都吃掉 OSError 返回布尔值：注册表被组策略锁了、键被杀毒软件删了之类的
情况都可能发生，不该让宠物崩在这上面。
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "v-pet"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

_IS_WINDOWS = sys.platform == "win32"
if _IS_WINDOWS:
    import winreg


def launch_command() -> str:
    """开机要执行的命令行。

    刻意用 pythonw.exe 而不是 python.exe：后者每次开机会弹一个黑色控制台窗口
    并且一直挂在任务栏上，很难看。
    """
    if getattr(sys, "frozen", False):          # 以后打包成 exe 时走这条
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    windowless = exe.with_name("pythonw.exe")
    if windowless.exists():
        exe = windowless
    script = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{exe}" "{script}"'


def is_enabled(key_path: str = RUN_KEY, name: str = APP_NAME) -> bool:
    if not _IS_WINDOWS:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, name)
        return True
    except OSError:
        return False


def set_enabled(enable: bool, key_path: str = RUN_KEY, name: str = APP_NAME) -> bool:
    """返回操作后的实际状态，而不是请求的状态 —— 写失败时调用方能据此回退勾选框。"""
    if not _IS_WINDOWS:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            if enable:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass                       # 本来就没有，当作已经关掉
    except OSError:
        return is_enabled(key_path, name)
    return enable

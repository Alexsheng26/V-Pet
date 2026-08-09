"""从 Windows 桌面上读出"宠物能踩的窗口上沿"和"桌面图标的位置"。

这是整个项目里最贴着系统的一层，几个不查文档就会踩的点都写在下面了。
非 Windows 平台上所有函数都返回空，调用方不用特判。

**坐标是物理像素。** Qt6 默认 per-monitor DPI aware，Win32 给的是设备像素，
而窗口层用的是逻辑像素 —— 换算放在 window.py 做，因为只有那边知道屏幕的缩放比例。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from .ledges import Ledge

_IS_WINDOWS = sys.platform == "win32"

# 窗口能当台面的最低要求：太矮的多半是提示条之类，站上去很怪
MIN_LEDGE_HEIGHT = 80


if _IS_WINDOWS:
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    kernel32 = ctypes.windll.kernel32

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    DWMWA_CLOAKED = 14
    DWMWA_EXTENDED_FRAME_BOUNDS = 9

    LVM_GETITEMCOUNT = 0x1004
    LVM_GETITEMRECT = 0x100E
    LVIR_ICON = 1
    PROCESS_VM_OPERATION = 0x0008
    PROCESS_VM_READ = 0x0010
    PROCESS_VM_WRITE = 0x0020
    MEM_COMMIT = 0x1000
    MEM_RELEASE = 0x8000
    PAGE_READWRITE = 0x04

    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _rect_of(hwnd: int) -> tuple[int, int, int, int] | None:
    """窗口的**视觉**边界。

    刻意用 DwmGetWindowAttribute(EXTENDED_FRAME_BOUNDS) 而不是 GetWindowRect：
    后者含 Aero 的不可见投影边框，左右各多出七八个像素，宠物会站在离窗口
    可见边缘一段距离的空气上。这个差别肉眼一眼就能看出来。
    """
    rect = wintypes.RECT()
    ok = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect), ctypes.sizeof(rect),
    )
    if ok != 0:                                   # 老系统或异常窗口，退回旧 API
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
    return rect.left, rect.top, rect.right, rect.bottom


def _is_cloaked(hwnd: int) -> bool:
    """UWP 应用会留下一堆"可见但被隐藏"的幽灵窗口。

    IsWindowVisible 对它们返回真，只有 DWM 的 CLOAKED 属性能识别出来。
    不查这个的话，桌面上会凭空出现一排踩不到实物的台面。
    """
    cloaked = wintypes.DWORD()
    if dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_CLOAKED,
        ctypes.byref(cloaked), ctypes.sizeof(cloaked),
    ) != 0:
        return False
    return bool(cloaked.value)


def window_ledges(skip: int = 0) -> list[Ledge]:
    """所有可见顶层窗口的上沿，物理像素。skip 传自己的窗口句柄。"""
    if not _IS_WINDOWS:
        return []

    found: list[Ledge] = []

    def visit(hwnd: int, _lparam: int) -> bool:
        if hwnd == skip or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
        if style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
            return True                            # 工具窗、输入法候选框之类
        if user32.GetWindowTextLengthW(wintypes.HWND(hwnd)) == 0:
            return True                            # 没标题的多半不是真窗口
        if _is_cloaked(hwnd):
            return True
        rect = _rect_of(hwnd)
        if rect is None:
            return True
        left, top, right, bottom = rect
        if bottom - top < MIN_LEDGE_HEIGHT:
            return True
        found.append(Ledge(left, right, top, key=hwnd))
        return True

    user32.EnumWindows(_ENUM_PROC(visit), 0)
    # EnumWindows 是按 Z 序从上到下给的，保持这个顺序 —— 靠前的压在靠后的上面
    return found


def _desktop_listview() -> int:
    """桌面图标所在的那个 ListView。

    正常在 Progman → SHELLDLL_DefView → SysListView32 下面。但只要用过
    "壁纸幻灯片"，explorer 就会把 DefView 挪到某个 WorkerW 底下，
    只找 Progman 会得到 0 —— 所以要兜一圈 WorkerW。
    """
    def dig(parent: int) -> int:
        defview = user32.FindWindowExW(wintypes.HWND(parent), None, "SHELLDLL_DefView", None)
        if not defview:
            return 0
        return user32.FindWindowExW(wintypes.HWND(defview), None, "SysListView32", None) or 0

    listview = dig(user32.FindWindowW("Progman", None))
    if listview:
        return listview

    found = 0

    def visit(hwnd: int, _lparam: int) -> bool:
        nonlocal found
        candidate = dig(hwnd)
        if candidate:
            found = candidate
            return False
        return True

    user32.EnumWindows(_ENUM_PROC(visit), 0)
    return found


def desktop_icons() -> list[tuple[int, int, int, int]]:
    """桌面图标的矩形，物理像素、屏幕坐标。

    图标属于 explorer.exe 的 ListView，LVM_GETITEMRECT 要求把结果写进
    **对方进程**的地址空间 —— 直接传本进程的指针只会拿到一堆零。
    所以得在 explorer 里分配一块内存、发消息、再读回来。
    拿不到就返回空列表：这只是个锦上添花的功能，不值得让宠物崩掉。
    """
    if not _IS_WINDOWS:
        return []
    listview = _desktop_listview()
    if not listview:
        return []

    count = user32.SendMessageW(wintypes.HWND(listview), LVM_GETITEMCOUNT, 0, 0)
    if count <= 0:
        return []

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(listview), ctypes.byref(pid))
    handle = kernel32.OpenProcess(
        PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE, False, pid
    )
    if not handle:
        return []

    size = ctypes.sizeof(wintypes.RECT)
    remote = kernel32.VirtualAllocEx(handle, None, size, MEM_COMMIT, PAGE_READWRITE)
    if not remote:
        kernel32.CloseHandle(handle)
        return []

    icons: list[tuple[int, int, int, int]] = []
    try:
        for index in range(min(count, 512)):       # 图标多到离谱时别把自己卡住
            rect = wintypes.RECT(LVIR_ICON, 0, 0, 0)   # left 位要先填成 LVIR_*
            if not kernel32.WriteProcessMemory(handle, remote, ctypes.byref(rect), size, None):
                break
            if not user32.SendMessageW(wintypes.HWND(listview), LVM_GETITEMRECT, index, remote):
                continue
            if not kernel32.ReadProcessMemory(handle, remote, ctypes.byref(rect), size, None):
                break
            # LVM_GETITEMRECT 给的是客户区坐标，得换成屏幕坐标
            origin = wintypes.POINT(rect.left, rect.top)
            user32.ClientToScreen(wintypes.HWND(listview), ctypes.byref(origin))
            width, height = rect.right - rect.left, rect.bottom - rect.top
            icons.append((origin.x, origin.y, origin.x + width, origin.y + height))
    finally:
        kernel32.VirtualFreeEx(handle, remote, 0, MEM_RELEASE)
        kernel32.CloseHandle(handle)
    return icons

"""桌面宠物窗口: 无边框 + 置顶 + 逐像素透明 + 可拖拽 + 点击穿透。

整个项目最难的部分在这个文件里，不在宠物逻辑里。三个坑按顺序:

1. 逐像素透明
   FramelessWindowHint 去边框, WA_TranslucentBackground 开真 alpha 通道。
   加 Qt.Tool 是为了不在任务栏和 Alt+Tab 里占位置。

2. 点击穿透(_sync_pointer)
   窗口是个方的，但宠物是圆的 —— 四角那些透明像素如果照样吃鼠标事件，
   宠物就成了一块挡住桌面图标的隐形玻璃。
   Qt 只能整个窗口开关 WA_TransparentForMouseEvents，做不到按像素判断，
   所以要下到 Win32 动态开关 WS_EX_TRANSPARENT。
   注意: 一旦设上 WS_EX_TRANSPARENT，窗口就再也收不到鼠标事件了，
   自然也没法靠 enterEvent 判断鼠标什么时候移回来 —— 只能用全局光标位置轮询。

3. 退出路径
   无边框窗口没有关闭按钮。托盘菜单和 Esc 是在写第一行渲染代码之前接上的，
   否则很容易做出一个只能靠任务管理器杀掉的窗口。

摸头(搓)的判定也挂在第 2 条的光标轮询上: 那个循环每帧已经算出"光标在不在
宠物身上"了，再累加一下光标位移就够了，不用额外装事件过滤器。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QElapsedTimer, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .state import PetBrain, State

FRAME_MS = 16            # ~60fps
MAX_DT = 0.05            # 卡顿后别让宠物瞬移
ALPHA_HIT = 24           # alpha 低于这个值就算"不是宠物身体"
RUB_TRIGGER = 300.0      # 在宠物身上累计搓够这么多像素算摸头
RUB_DECAY = 0.92         # 每帧衰减: 慢慢划过去不算，得来回搓才攒得起来

_IS_WINDOWS = sys.platform == "win32"
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020


class PetWindow(QWidget):
    def __init__(self, provider) -> None:
        super().__init__()
        self.provider = provider
        size = provider.size

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(size, size)
        self.setWindowTitle("v-pet")

        self.brain = PetBrain(size, self._screen_bounds())
        self._frame = provider.render(State.IDLE, 0.0, 1, self.devicePixelRatioF())
        self._t = 0.0
        self._grab_offset = QPoint()
        self._dragging = False
        self._click_through = False
        self._hwnd = 0
        self._rub = 0.0
        self._last_cursor = QCursor.pos()

        self._build_actions()
        self._build_tray()

        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_MS)

    # --- 主循环 -----------------------------------------------------------
    def _tick(self) -> None:
        dt = min(self._clock.restart() / 1000.0, MAX_DT)
        self._t += dt
        cursor = QCursor.pos()

        self.brain.set_bounds(self._screen_bounds())
        self.brain.set_pointer(float(cursor.x()), float(cursor.y()))
        self.brain.update(dt)
        self.move(round(self.brain.x), round(self.brain.y))

        self._frame = self.provider.render(
            self.brain.state, self._t, self.brain.facing, self.devicePixelRatioF()
        )
        self.update()
        self._sync_pointer(cursor)

    def paintEvent(self, event) -> None:
        if self._frame.isNull():
            return
        painter = QPainter(self)
        painter.drawImage(0, 0, self._frame)

    # --- 光标: 点击穿透 + 摸头 --------------------------------------------
    def _sync_pointer(self, cursor: QPoint) -> None:
        moved = (cursor - self._last_cursor).manhattanLength()
        self._last_cursor = cursor

        if self._dragging:
            self._set_click_through(False)
            return

        local = self.mapFromGlobal(cursor)
        on_body = self.rect().contains(local) and self._alpha_at(local) >= ALPHA_HIT
        self._set_click_through(not on_body)

        # 光标在身上来回搓就是摸头。衰减系数决定了"必须来回搓"——
        # 匀速划过去的话，攒的速度赶不上衰减，触发不了。
        self._rub = self._rub * RUB_DECAY + (moved if on_body else 0.0)
        if self._rub >= RUB_TRIGGER:
            self._rub = 0.0
            self.brain.head_pat()

    def _alpha_at(self, pos: QPoint) -> int:
        img = self._frame
        if img.isNull():
            return 0
        dpr = img.devicePixelRatio()
        px, py = int(pos.x() * dpr), int(pos.y() * dpr)
        if not (0 <= px < img.width() and 0 <= py < img.height()):
            return 0
        return img.pixelColor(px, py).alpha()

    def _set_click_through(self, enable: bool) -> None:
        # 非 Windows 平台直接跳过: 宁可不穿透，也不要炸掉
        if not _IS_WINDOWS or enable == self._click_through:
            return
        if not self._hwnd:
            self._hwnd = int(self.winId())
        ex = _get_window_long(self._hwnd, _GWL_EXSTYLE)
        ex = ex | _WS_EX_TRANSPARENT if enable else ex & ~_WS_EX_TRANSPARENT
        _set_window_long(self._hwnd, _GWL_EXSTYLE, ex)
        self._click_through = enable

    # --- 鼠标 -------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self.brain.wake()
        self._dragging = True
        self._grab_offset = event.position().toPoint()
        self.brain.grab()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        target = event.globalPosition().toPoint() - self._grab_offset
        self.brain.drag_to(float(target.x()), float(target.y()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        self.brain.release()

    def mouseDoubleClickEvent(self, event) -> None:
        # Qt 的事件顺序是 press → release → doubleclick，所以上面那次
        # grab/release 已经跑完了，这里直接覆盖成摸头即可。
        if event.button() == Qt.LeftButton:
            self.brain.head_pat()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction(self._follow_action)
        menu.addAction("打个盹", self.brain.doze_off)
        menu.addAction("藏起来", self.hide)
        menu.addSeparator()
        menu.addAction("退出", QApplication.quit)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            QApplication.quit()

    # --- 菜单与托盘 -------------------------------------------------------
    def _build_actions(self) -> None:
        # 同一个 QAction 挂在右键菜单和托盘菜单上，勾选状态天然同步
        self._follow_action = QAction("跟着鼠标", self)
        self._follow_action.setCheckable(True)
        self._follow_action.toggled.connect(self._set_follow)

        self._toggle_action = QAction("藏起来", self)
        self._toggle_action.triggered.connect(self._toggle_visible)

    def _set_follow(self, on: bool) -> None:
        self.brain.follow = on
        if on:
            self.brain.wake()

    def _build_tray(self) -> None:
        icon = QIcon(QPixmap.fromImage(self.provider.render(State.IDLE, 0.0, 1, 1.0)))
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("v-pet")

        menu = QMenu()
        menu.addAction(self._follow_action)
        menu.addAction(self._toggle_action)
        menu.addSeparator()
        menu.addAction("退出", QApplication.quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._toggle_visible()
            if reason == QSystemTrayIcon.DoubleClick else None
        )
        self.tray.show()

    def _toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
            self._toggle_action.setText("叫出来")
        else:
            self.show()
            self._toggle_action.setText("藏起来")

    # --- 屏幕 -------------------------------------------------------------
    def _screen_bounds(self) -> tuple[int, int, int, int]:
        """可用区域已排除任务栏，所以宠物会正好站在任务栏上沿。

        用 self.screen() 而不是 primaryScreen()，多显示器下把宠物拖到副屏才不会
        被硬拽回主屏。Qt6 默认 per-monitor DPI aware，这里一律用逻辑坐标。
        """
        screen = self.screen() or QApplication.primaryScreen()
        g = screen.availableGeometry()
        return g.left(), g.top(), g.right() + 1, g.bottom() + 1


# --- Win32 --------------------------------------------------------------
# 64 位下必须走 ...LongPtrW 并显式声明 argtypes/restype，
# 否则 ctypes 会按 32 位 int 截断句柄和 style，行为随机出错。
if _IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _get = getattr(_user32, "GetWindowLongPtrW", _user32.GetWindowLongW)
    _set = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
    _get.restype = ctypes.c_ssize_t
    _get.argtypes = [wintypes.HWND, ctypes.c_int]
    _set.restype = ctypes.c_ssize_t
    _set.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]

    def _get_window_long(hwnd: int, index: int) -> int:
        return _get(wintypes.HWND(hwnd), index)

    def _set_window_long(hwnd: int, index: int, value: int) -> int:
        return _set(wintypes.HWND(hwnd), index, value)
else:
    def _get_window_long(hwnd: int, index: int) -> int:
        return 0

    def _set_window_long(hwnd: int, index: int, value: int) -> int:
        return 0

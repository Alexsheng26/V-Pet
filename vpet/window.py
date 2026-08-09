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

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from . import autostart, desktop
from .config import SIZE_CHOICES, Config
from .ledges import Ledge, LedgeSet
from .screens import Screen, ScreenLayout
from .state import PetBrain, State

FRAME_MS = 16            # ~60fps
MAX_DT = 0.05            # 卡顿后别让宠物瞬移
ALPHA_HIT = 24           # alpha 低于这个值就算"不是宠物身体"
RUB_TRIGGER = 300.0      # 在宠物身上累计搓够这么多像素算摸头
RUB_DECAY = 0.92         # 每帧衰减: 慢慢划过去不算，得来回搓才攒得起来
# 窗口台面的刷新间隔。实测枚举一次 0.2ms，每帧做也不至于卡，但没必要；
# 100ms 已经足够让宠物跟上被拖动的窗口，肉眼看不出延迟。
LEDGE_REFRESH_MS = 100

_IS_WINDOWS = sys.platform == "win32"
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020


class PetWindow(QWidget):
    def __init__(
        self,
        provider,
        config: Config | None = None,
        config_path=None,
        autostart_key: str = autostart.RUN_KEY,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.config = config or Config()
        self.config_path = config_path      # None = 走 config.py 里的默认位置
        # 注册表键做成可注入的，测试才能在自建的临时键上跑。
        # 不然任何碰到自启开关的测试都会往用户**真实的** Run 键里写东西。
        self.autostart_key = autostart_key
        size = provider.size

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(size, size)
        self.setWindowTitle("v-pet")

        self._layout_sig: tuple | None = None
        self.brain = PetBrain(size, self._read_layout())
        self._layout_sig = self.brain.layout.signature()
        self._frame = provider.render(State.IDLE, 0.0, 1, self.devicePixelRatioF())
        self._t = 0.0
        self._grab_offset = QPoint()
        self._dragging = False
        self._click_through = False
        self._hwnd_cache = 0
        self._rub = 0.0
        self._last_cursor = QCursor.pos()
        self._ledge_sig: tuple | None = None
        self._ledge_clock = QElapsedTimer()
        self._ledge_clock.start()

        self._build_actions()
        self._build_tray()
        self._restore_position()
        self._follow_action.setChecked(self.config.follow)

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

        self._sync_layout()
        if self._ledge_clock.elapsed() >= LEDGE_REFRESH_MS:
            self._ledge_clock.restart()
            self._sync_ledges()
        self.brain.set_pointer(float(cursor.x()), float(cursor.y()))
        self.brain.update(dt)
        self.move(round(self.brain.x), round(self.brain.y))

        self._frame = self.provider.render(
            self.brain.state, self._t, self.brain.facing, self.devicePixelRatioF(),
            self.brain.posture,
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
        ex = _get_window_long(self._hwnd(), _GWL_EXSTYLE)
        ex = ex | _WS_EX_TRANSPARENT if enable else ex & ~_WS_EX_TRANSPARENT
        _set_window_long(self._hwnd(), _GWL_EXSTYLE, ex)
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
        # 图标只在松手这一刻查一次(1.6ms)，不进每帧循环
        if self._dropped_on_icon():
            self.brain.notice_on_landing()
        self.brain.release()

    def mouseDoubleClickEvent(self, event) -> None:
        # Qt 的事件顺序是 press → release → doubleclick，所以上面那次
        # grab/release 已经跑完了，这里直接覆盖成摸头即可。
        if event.button() == Qt.LeftButton:
            self.brain.head_pat()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction(self._follow_action)
        menu.addMenu(self._size_menu)
        menu.addAction(self._autostart_action)
        menu.addSeparator()
        menu.addAction("打个盹", self.brain.doze_off)
        menu.addAction("藏起来", self.hide)
        menu.addSeparator()
        menu.addAction("退出", QApplication.quit)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            QApplication.quit()

    # --- 配置 -------------------------------------------------------------
    def _restore_position(self) -> None:
        """恢复上次的位置，但**必须校验它还在某块屏幕上**。

        存的坐标可能来自一块已经拔掉的显示器，或者分辨率被改小了。
        直接 move 过去的话，宠物会待在屏幕外 —— 进程在跑、托盘图标也在，
        就是死活看不见，这种问题很难被想到。
        """
        cfg = self.config
        if cfg.x is None or cfg.y is None:
            return
        rect = QRect(cfg.x, cfg.y, self.width(), self.height())
        if not any(s.availableGeometry().intersects(rect) for s in QApplication.screens()):
            return
        self.brain.x, self.brain.y = float(cfg.x), float(cfg.y)
        self.move(cfg.x, cfg.y)

    def save_config(self) -> bool:
        self.config.x = int(round(self.brain.x))
        self.config.y = int(round(self.brain.y))
        self.config.follow = self.brain.follow
        if getattr(self.provider, "resizable", False):
            self.config.size = self.provider.size
        return self.config.save(self.config_path)

    # --- 菜单与托盘 -------------------------------------------------------
    def _build_actions(self) -> None:
        # 同一个 QAction 挂在右键菜单和托盘菜单上，勾选状态天然同步
        self._follow_action = QAction("跟着鼠标", self)
        self._follow_action.setCheckable(True)
        self._follow_action.toggled.connect(self._set_follow)

        self._toggle_action = QAction("藏起来", self)
        self._toggle_action.triggered.connect(self._toggle_visible)

        # 初始勾选状态以**注册表为准**而不是配置文件: 用户可能在任务管理器的
        # 启动项里手动关掉了，那边才是真相。
        self._autostart_action = QAction("开机自启", self)
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(autostart.is_enabled(self.autostart_key))
        self._autostart_action.toggled.connect(self._set_autostart)

        self._size_menu = QMenu("大小", self)
        group = QActionGroup(self)
        group.setExclusive(True)
        for n in SIZE_CHOICES:
            act = QAction(f"{n}px", self, checkable=True)
            act.setChecked(n == self.provider.size)
            act.triggered.connect(lambda _checked, v=n: self._set_size(v))
            group.addAction(act)
            self._size_menu.addAction(act)
        self._size_menu.setEnabled(getattr(self.provider, "resizable", False))

    def _set_follow(self, on: bool) -> None:
        self.brain.follow = on
        if on:
            self.brain.wake()
        self.save_config()

    def _set_autostart(self, on: bool) -> None:
        actual = autostart.set_enabled(on, self.autostart_key)
        self.config.autostart = actual
        if actual != on:
            # 写注册表失败(组策略锁了之类)，把勾选框拨回真实状态，
            # 别让菜单显示一个根本没生效的设置
            self._autostart_action.blockSignals(True)
            self._autostart_action.setChecked(actual)
            self._autostart_action.blockSignals(False)
        self.save_config()

    def _set_size(self, n: int) -> None:
        if not getattr(self.provider, "resizable", False):
            return
        self.provider.size = n
        self.config.size = n
        self.setFixedSize(n, n)
        self.brain.size = n
        self.brain.set_layout(self._read_layout())   # 顺带把变大后陷进地面的位置提回来
        self._frame = self.provider.render(
            self.brain.state, self._t, self.brain.facing, self.devicePixelRatioF(),
            self.brain.posture,
        )
        self.tray.setIcon(QIcon(QPixmap.fromImage(self.provider.render(State.IDLE, 0.0, 1, 1.0))))
        self.save_config()

    def _build_tray(self) -> None:
        icon = QIcon(QPixmap.fromImage(self.provider.render(State.IDLE, 0.0, 1, 1.0)))
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("v-pet")

        menu = QMenu()
        menu.addAction(self._follow_action)
        menu.addMenu(self._size_menu)
        menu.addAction(self._autostart_action)
        menu.addSeparator()
        menu.addAction(self._toggle_action)
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

    # --- 桌面 -------------------------------------------------------------
    def _hwnd(self) -> int:
        if not self._hwnd_cache:
            self._hwnd_cache = int(self.winId())
        return self._hwnd_cache

    def _to_logical(self, value: float) -> int:
        """物理像素 -> Qt 逻辑像素。

        Win32 给的是设备像素，窗口层用的是逻辑像素。这里用**当前屏幕**的缩放比例，
        在混合 DPI 的多屏环境下，另一块屏上的台面位置会有偏差 ——
        真要做对得逐显示器换算原点，代价远大于收益，先记在这儿。
        """
        return round(value / self.devicePixelRatioF())

    def _sync_ledges(self) -> None:
        """把可见窗口的上沿变成宠物能站的台面。"""
        ledges = LedgeSet(
            Ledge(self._to_logical(l.left), self._to_logical(l.right),
                  self._to_logical(l.y), l.key)
            for l in desktop.window_ledges(skip=self._hwnd())
        )
        signature = ledges.signature()
        if signature == self._ledge_sig:
            return
        self._ledge_sig = signature
        self.brain.set_ledges(ledges)

    def _dropped_on_icon(self) -> bool:
        """松手时脚底是不是正落在某个桌面图标上。

        用脚底一个点判定，不是整个窗口矩形 —— 宠物有 144px 宽，
        用矩形相交的话在图标区附近几乎总是命中，反应就不值钱了。

        没有检查图标是不是被别的窗口挡住了：真做要 WindowFromPoint 再排除
        自己这个置顶窗口，判断链条比这个功能本身还长，不划算。
        """
        dpr = self.devicePixelRatioF()
        feet_x = self.brain.x + self.width() / 2
        feet_y = self.brain.y + self.height() - 6
        for left, top, right, bottom in desktop.desktop_icons():
            if (left / dpr <= feet_x < right / dpr) and (top / dpr <= feet_y < bottom / dpr):
                return True
        return False

    # --- 屏幕 -------------------------------------------------------------
    def _read_layout(self) -> ScreenLayout:
        """把 Qt 的屏幕列表翻译成 Qt-free 的 ScreenLayout。

        用 availableGeometry 而不是 geometry：它排除了任务栏，
        所以宠物会正好站在任务栏上沿而不是被任务栏盖住。
        Qt6 默认 per-monitor DPI aware，这里一律用逻辑坐标。
        """
        screens = QApplication.screens()
        primary = QApplication.primaryScreen()
        rects = []
        for s in screens:
            g = s.availableGeometry()
            rects.append(Screen(g.left(), g.top(), g.right() + 1, g.bottom() + 1))
        index = screens.index(primary) if primary in screens else 0
        return ScreenLayout(rects, primary=index)

    def _sync_layout(self) -> None:
        """屏幕配置变了就重建布局。

        用指纹比对而不是接 screenAdded / availableGeometryChanged 那一堆信号：
        新插上来的屏还得记得给它也接一遍，漏一个就是一个静默的错误状态。
        每帧比几个整数元组的开销可以忽略。
        """
        layout = self._read_layout()
        signature = layout.signature()
        if signature == self._layout_sig:
            return
        self._layout_sig = signature
        self.brain.set_layout(layout)


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

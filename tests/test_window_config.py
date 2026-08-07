"""窗口层和配置的接线测试：恢复位置、改大小、改动即时落盘。

这些只有真造一个窗口才验得到（屏幕列表、QAction 信号都在窗口里），
但用 offscreen 平台跑，不需要显示器。

安全前提：窗口的 config_path 和 autostart_key 都指到临时位置，
测试**不会**碰用户真实的配置文件和 Run 键。

    python -m unittest discover
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vpet.config import Config  # noqa: E402
from vpet.render import BlobPet  # noqa: E402
from vpet.window import PetWindow  # noqa: E402

IS_WINDOWS = sys.platform == "win32"
TEST_KEY = r"Software\v-pet\test-window"

if IS_WINDOWS:
    import winreg

_app: QApplication | None = None


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication([])


class WindowCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "config.json"
        self._windows: list[PetWindow] = []

    def tearDown(self) -> None:
        for win in self._windows:
            win.close()
            win.deleteLater()
        self._dir.cleanup()
        if IS_WINDOWS:
            for key in (TEST_KEY, r"Software\v-pet"):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
                except OSError:
                    pass

    def make(self, config: Config | None = None) -> PetWindow:
        cfg = config or Config()
        pet = BlobPet()
        pet.size = cfg.size
        win = PetWindow(pet, cfg, config_path=self.path, autostart_key=TEST_KEY)
        self._windows.append(win)
        return win

    @staticmethod
    def a_visible_point() -> tuple[int, int]:
        g = QApplication.primaryScreen().availableGeometry()
        return g.left() + 20, g.top() + 20


class TestRestorePosition(WindowCase):
    def test_restores_a_position_that_is_still_on_screen(self):
        x, y = self.a_visible_point()
        win = self.make(Config(x=x, y=y))
        self.assertEqual((win.pos().x(), win.pos().y()), (x, y))

    def test_ignores_a_position_from_a_monitor_that_is_gone(self):
        """回归防线：直接 move 过去的话，宠物会待在屏幕外 ——
        进程在跑、托盘图标也在，就是死活看不见。"""
        win = self.make(Config(x=-9999, y=-9999))
        self.assertTrue(
            any(s.availableGeometry().intersects(win.geometry()) for s in QApplication.screens()),
            "宠物落到了所有屏幕之外",
        )

    def test_no_saved_position_is_fine(self):
        win = self.make(Config())
        self.assertTrue(
            any(s.availableGeometry().intersects(win.geometry()) for s in QApplication.screens())
        )


class TestResize(WindowCase):
    def test_resize_updates_window_provider_and_brain(self):
        win = self.make(Config(size=120))
        win._set_size(176)
        self.assertEqual(win.width(), 176)
        self.assertEqual(win.provider.size, 176)
        self.assertEqual(win.brain.size, 176, "brain 的尺寸没跟上，落地高度会算错")

    def test_resize_keeps_the_pet_on_the_ground(self):
        win = self.make(Config(size=96))
        win._set_size(208)          # 变大之后可能陷进地面里
        self.assertLessEqual(win.brain.y, win.brain.ground)

    def test_size_menu_is_disabled_for_bitmap_sprites(self):
        win = self.make()
        win.provider.resizable = False
        self.assertFalse(PetWindow(win.provider, Config(), config_path=self.path,
                                   autostart_key=TEST_KEY)._size_menu.isEnabled())


class TestSavesImmediately(WindowCase):
    """改完设置立刻落盘。只在退出时存的话，从任务管理器强杀就丢了。"""

    def test_resize_is_persisted_without_quitting(self):
        win = self.make(Config(size=120))
        win._set_size(176)
        self.assertEqual(Config.load(self.path).size, 176)

    def test_follow_toggle_is_persisted_without_quitting(self):
        win = self.make(Config(follow=False))
        win._follow_action.setChecked(True)
        self.assertTrue(Config.load(self.path).follow)

    @unittest.skipUnless(IS_WINDOWS, "注册表只有 Windows 有")
    def test_autostart_toggle_is_persisted_and_hits_the_registry(self):
        from vpet import autostart

        win = self.make()
        win._autostart_action.setChecked(True)
        self.assertTrue(autostart.is_enabled(TEST_KEY))
        self.assertTrue(Config.load(self.path).autostart)

    def test_save_on_quit_records_where_it_was_standing(self):
        win = self.make()
        win.brain.x, win.brain.y = 321.0, 210.0
        win.save_config()
        cfg = Config.load(self.path)
        self.assertEqual((cfg.x, cfg.y), (321, 210))


if __name__ == "__main__":
    unittest.main()

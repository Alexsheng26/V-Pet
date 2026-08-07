"""开机自启的测试。

**不会碰真正的 Run 键** —— 测试全部跑在自己建的一个临时子键上，用完删掉。
拿真 Run 键做测试意味着测试挂掉的时候会给用户留一条开机自启项。

    python -m unittest discover
"""

from __future__ import annotations

import sys
import unittest

from vpet import autostart

IS_WINDOWS = sys.platform == "win32"
TEST_KEY = r"Software\v-pet\test-autostart"

if IS_WINDOWS:
    import winreg


class TestLaunchCommand(unittest.TestCase):
    def test_paths_are_quoted(self):
        # 用户名带空格(C:\Users\Foo Bar\...)的话，不加引号开机就起不来
        cmd = autostart.launch_command()
        self.assertTrue(cmd.startswith('"'), cmd)
        self.assertGreaterEqual(cmd.count('"'), 2)

    @unittest.skipUnless(IS_WINDOWS, "只在 Windows 上有意义")
    def test_prefers_pythonw_to_avoid_a_console_window(self):
        cmd = autostart.launch_command()
        self.assertIn("pythonw.exe", cmd.lower())

    def test_points_at_the_entry_point(self):
        self.assertIn("main.py", autostart.launch_command())


@unittest.skipUnless(IS_WINDOWS, "注册表只有 Windows 有")
class TestRegistry(unittest.TestCase):
    def tearDown(self) -> None:
        # 两层都要删: DeleteKey 只删叶子，不收拾它顺手建出来的父键，
        # 否则每跑一次测试就在用户注册表里留一个空的 Software\v-pet
        for key in (TEST_KEY, r"Software\v-pet"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except OSError:
                pass            # 不存在，或者(父键)还有别的子项，都不该删

    def test_disabled_when_the_key_does_not_exist(self):
        self.assertFalse(autostart.is_enabled(TEST_KEY))

    def test_enable_then_disable(self):
        self.assertTrue(autostart.set_enabled(True, TEST_KEY))
        self.assertTrue(autostart.is_enabled(TEST_KEY))
        self.assertFalse(autostart.set_enabled(False, TEST_KEY))
        self.assertFalse(autostart.is_enabled(TEST_KEY))

    def test_enabling_writes_the_launch_command(self):
        autostart.set_enabled(True, TEST_KEY)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as key:
            value, kind = winreg.QueryValueEx(key, autostart.APP_NAME)
        self.assertEqual(kind, winreg.REG_SZ)
        self.assertEqual(value, autostart.launch_command())

    def test_disabling_twice_is_not_an_error(self):
        autostart.set_enabled(True, TEST_KEY)
        autostart.set_enabled(False, TEST_KEY)
        self.assertFalse(autostart.set_enabled(False, TEST_KEY))

    def test_enabling_twice_does_not_duplicate(self):
        autostart.set_enabled(True, TEST_KEY)
        autostart.set_enabled(True, TEST_KEY)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as key:
            self.assertEqual(winreg.QueryInfoKey(key)[1], 1, "Run 键里不该出现两条同名项")

    def test_never_touches_the_real_run_key(self):
        before = autostart.is_enabled()
        autostart.set_enabled(True, TEST_KEY)
        autostart.set_enabled(False, TEST_KEY)
        self.assertEqual(autostart.is_enabled(), before)


if __name__ == "__main__":
    unittest.main()

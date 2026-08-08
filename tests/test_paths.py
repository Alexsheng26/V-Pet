"""程序目录解析的测试，含打包后的分支。

`sys.frozen` 那条分支平时根本走不到 —— 只有打完包运行 exe 才会。
所以这里把它模拟出来测，否则等到发现路径不对时，人已经在调试一个
没有控制台、启动就闪退的 exe 了。

    python -m unittest discover
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from vpet import autostart, paths

FAKE_EXE = Path(r"D:\Apps\v-pet\v-pet.exe") if sys.platform == "win32" else Path("/opt/v-pet/v-pet")


def frozen_at(exe: Path):
    """假装自己是打包后的程序。"""
    return mock.patch.multiple(sys, frozen=True, executable=str(exe), create=True)


class TestDevelopmentLayout(unittest.TestCase):
    def test_not_frozen_when_running_from_source(self):
        self.assertFalse(paths.is_frozen())

    def test_app_dir_is_the_repo_root(self):
        self.assertTrue((paths.app_dir() / "main.py").is_file())
        self.assertTrue((paths.app_dir() / "vpet").is_dir())

    def test_sprites_live_under_the_app_dir(self):
        self.assertEqual(paths.sprites_dir(), paths.app_dir() / "sprites")


class TestFrozenLayout(unittest.TestCase):
    def test_app_dir_follows_the_executable(self):
        with frozen_at(FAKE_EXE):
            self.assertTrue(paths.is_frozen())
            self.assertEqual(paths.app_dir(), FAKE_EXE.parent)

    def test_sprites_sit_next_to_the_exe(self):
        """打包进包体的话用户就换不了皮了，必须解析到 exe 旁边。"""
        with frozen_at(FAKE_EXE):
            self.assertEqual(paths.sprites_dir(), FAKE_EXE.parent / "sprites")

    def test_autostart_launches_the_exe_directly(self):
        with frozen_at(FAKE_EXE):
            cmd = autostart.launch_command()
        self.assertEqual(cmd, f'"{FAKE_EXE}"')
        self.assertNotIn("main.py", cmd, "打包后不该再去找源码入口")
        self.assertNotIn("python", cmd.lower(), "打包后机器上可能根本没有 Python")


if __name__ == "__main__":
    unittest.main()

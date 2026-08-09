"""打包剔除规则的测试。不需要 Qt。

v1.0 的发布包混进了 6.8MB 的 libcrypto-3-x64.dll：过滤表里写的是精确文件名
libcrypto-3.dll，本地 Python 3.14 正好叫这个、CI 的 3.13 带 -x64 后缀，
于是静默漏过。这个文件就是那次的回归防线。

    python -m unittest discover
"""

from __future__ import annotations

import unittest

from tools.bundle import is_unwanted


class TestUnwanted(unittest.TestCase):
    def test_catches_openssl_under_every_name_seen_so_far(self):
        for name in ("libcrypto-3.dll", "libcrypto-3-x64.dll",
                     "libssl-3.dll", "libssl-3-x64.dll"):
            self.assertTrue(is_unwanted(name), name)

    def test_catches_the_big_ones(self):
        self.assertTrue(is_unwanted("opengl32sw.dll"))      # 单个 20MB
        self.assertTrue(is_unwanted("d3dcompiler_47.dll"))

    def test_catches_whole_qt_families(self):
        for name in ("Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll",
                     "Qt6Quick.dll", "Qt6QuickControls2.dll",
                     "Qt6Pdf.dll", "Qt6Network.dll", "Qt6NetworkAuth.dll",
                     "Qt6OpenGL.dll", "Qt6OpenGLWidgets.dll"):
            self.assertTrue(is_unwanted(name), name)

    def test_is_case_insensitive(self):
        """PyInstaller 报的文件名大小写不保证和磁盘一致。"""
        self.assertTrue(is_unwanted("OPENGL32SW.DLL"))
        self.assertTrue(is_unwanted("qt6qml.dll"))

    def test_keeps_what_the_program_actually_needs(self):
        """前缀匹配最怕误伤 —— 少一个 Qt6Core 程序就起不来了。"""
        for name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
                     "python313.dll", "python314.dll", "qwindows.dll",
                     "qoffscreen.dll", "Qt6Svg.dll", "MSVCP140.dll"):
            self.assertFalse(is_unwanted(name), name)

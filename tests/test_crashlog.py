"""崩溃日志的测试。不需要 Qt。

这个模块的存在理由是：console=False 的窗口程序没有可看的 stderr，
未捕获异常的表现就是"宠物突然不见了"。所以这里测的每一条都是
"崩了之后还剩下什么"。

    python -m unittest discover
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from vpet import crashlog


def boom(message: str = "炸了") -> tuple:
    """造一个带真实 traceback 的异常三元组。"""
    try:
        raise RuntimeError(message)
    except RuntimeError:
        return sys.exc_info()


class CrashCase(unittest.TestCase):
    def setUp(self) -> None:
        crashlog.reset()
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "nested" / "crash.log"
        self.addCleanup(self._dir.cleanup)
        self.addCleanup(crashlog.reset)


class TestRecording(CrashCase):
    def test_writes_the_traceback(self):
        written = crashlog.record(*boom("具体的错误信息"), path=self.path)
        self.assertEqual(written, self.path)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("RuntimeError", text)
        self.assertIn("具体的错误信息", text)
        self.assertIn("test_crashlog.py", text, "没有 traceback 就没法定位")

    def test_records_the_environment(self):
        """光有 traceback 不够 —— 得知道是哪个版本、打包了没有。"""
        crashlog.record(*boom(), path=self.path)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("v-pet", text)
        self.assertIn("Python", text)
        self.assertIn("frozen=", text)

    def test_creates_missing_directories(self):
        self.assertFalse(self.path.parent.exists())
        crashlog.record(*boom(), path=self.path)
        self.assertTrue(self.path.is_file())

    def test_appends_instead_of_overwriting(self):
        crashlog.record(*boom("第一次"), path=self.path)
        crashlog.record(*boom("第二次"), path=self.path)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("第一次", text)
        self.assertIn("第二次", text)


class TestDeduplication(CrashCase):
    """60fps 的主循环里，同一个 bug 每秒会犯 60 次。"""

    def test_the_same_crash_is_only_recorded_once(self):
        first = crashlog.record(*boom("一直是这个"), path=self.path)
        second = crashlog.record(*boom("一直是这个"), path=self.path)
        self.assertIsNotNone(first)
        self.assertIsNone(second, "重复的崩溃不该再写一遍")

    def test_a_flood_does_not_grow_the_file(self):
        crashlog.record(*boom("循环里的 bug"), path=self.path)
        size = self.path.stat().st_size
        for _ in range(600):                 # 十秒钟的量
            crashlog.record(*boom("循环里的 bug"), path=self.path)
        self.assertEqual(self.path.stat().st_size, size)

    def test_different_crashes_are_all_recorded(self):
        self.assertIsNotNone(crashlog.record(*boom("甲"), path=self.path))
        self.assertIsNotNone(crashlog.record(*boom("乙"), path=self.path))


class TestNeverThrows(CrashCase):
    """会崩的崩溃处理器比没有还糟。"""

    def test_unwritable_path_returns_none_instead_of_raising(self):
        blocker = Path(self._dir.name) / "nested"
        blocker.write_text("占位的文件，不是目录", encoding="utf-8")
        self.assertIsNone(crashlog.record(*boom(), path=self.path))

    def test_survives_a_broken_traceback(self):
        self.assertIsNotNone(crashlog.record(ValueError, ValueError("没有 tb"), None, self.path))

    def test_rotates_when_it_gets_too_big(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("x" * (crashlog.MAX_BYTES + 1), encoding="utf-8")
        crashlog.record(*boom(), path=self.path)
        self.assertLess(self.path.stat().st_size, crashlog.MAX_BYTES)
        self.assertIn("RuntimeError", self.path.read_text(encoding="utf-8"))


class TestInstall(CrashCase):
    def setUp(self) -> None:
        super().setUp()
        original = sys.excepthook
        self.addCleanup(lambda: setattr(sys, "excepthook", original))

    def test_takes_over_uncaught_exceptions(self):
        crashlog.install(path=self.path, echo=False)
        sys.excepthook(*boom("经由 excepthook"))
        self.assertIn("经由 excepthook", self.path.read_text(encoding="utf-8"))

    def test_notifies_with_the_log_path(self):
        seen = []
        crashlog.install(path=self.path, notify=seen.append, echo=False)
        sys.excepthook(*boom())
        self.assertEqual(seen, [self.path])

    def test_a_broken_notifier_does_not_take_the_handler_down(self):
        def bad(_path):
            raise OSError("通知本身也炸了")

        crashlog.install(path=self.path, notify=bad, echo=False)
        sys.excepthook(*boom())              # 不该抛
        self.assertTrue(self.path.exists(), "通知失败不该影响日志落盘")


class TestLocation(unittest.TestCase):
    def test_sits_next_to_the_config(self):
        """用户只需要找一个地方。"""
        from vpet.config import config_path
        self.assertEqual(crashlog.log_path().parent, config_path().parent)
        self.assertEqual(crashlog.log_path().name, "crash.log")


if __name__ == "__main__":
    unittest.main()

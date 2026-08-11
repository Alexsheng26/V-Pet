"""单实例保护的测试。不需要 Qt。

**每个用例都用自己的互斥量名字。** 用默认名的话，只要用户机器上真的开着
一只宠物，测试就会抢不到锁而失败 —— 这和"注册表测试不能碰真的 Run 键"
是同一条原则：测试不该和真实运行的东西共享全局资源。

    python -m unittest discover
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest

from vpet import instance

IS_WINDOWS = sys.platform == "win32"


def name_for(case: str) -> str:
    return rf"Local\v-pet.test.{case}"


def acquire_in_child(mutex: str) -> bool:
    """在另一个进程里尝试抢锁 —— 这才是这个功能真正要防的场景。"""
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {sys.path[0]!r})
        from vpet import instance
        sys.exit(0 if instance.acquire({mutex!r}) else 1)
    """)
    return subprocess.run([sys.executable, "-c", code], cwd=".").returncode == 0


class TestAcquire(unittest.TestCase):
    def tearDown(self) -> None:
        instance.release()

    def test_first_one_gets_in(self):
        self.assertTrue(instance.acquire(name_for("first")))

    @unittest.skipUnless(IS_WINDOWS, "只有 Windows 上有互斥量")
    def test_second_attempt_in_the_same_process_is_refused(self):
        mutex = name_for("same-process")
        self.assertTrue(instance.acquire(mutex))
        self.assertFalse(instance.acquire(mutex))

    @unittest.skipUnless(IS_WINDOWS, "只有 Windows 上有互斥量")
    def test_another_process_is_refused_while_we_hold_it(self):
        """真正要防的场景：用户双击了第二次 exe。"""
        mutex = name_for("cross-process")
        self.assertTrue(instance.acquire(mutex))
        self.assertFalse(acquire_in_child(mutex), "第二个进程不该抢到")

    @unittest.skipUnless(IS_WINDOWS, "只有 Windows 上有互斥量")
    def test_another_process_gets_in_after_we_release(self):
        """退出之后必须能重新打开 —— 否则就成了一次性程序。"""
        mutex = name_for("after-release")
        self.assertTrue(instance.acquire(mutex))
        instance.release()
        self.assertTrue(acquire_in_child(mutex))

    @unittest.skipUnless(IS_WINDOWS, "只有 Windows 上有互斥量")
    def test_releasing_twice_is_harmless(self):
        instance.acquire(name_for("double-release"))
        instance.release()
        instance.release()          # 不该抛


class TestWakeMessage(unittest.TestCase):
    @unittest.skipUnless(IS_WINDOWS, "只有 Windows 上有窗口消息")
    def test_id_is_stable_and_usable(self):
        """同一个字符串在任何进程里注册到的值都相同 —— 这正是拿它做跨进程招呼的前提。"""
        first = instance.wake_message()
        self.assertNotEqual(first, 0)
        self.assertEqual(first, instance.wake_message())
        self.assertGreaterEqual(first, 0xC000, "注册消息号应落在 0xC000-0xFFFF 区间")

    @unittest.skipUnless(IS_WINDOWS, "只有 Windows 上有窗口消息")
    def test_the_id_matches_across_processes(self):
        code = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {sys.path[0]!r})
            from vpet import instance
            print(instance.wake_message())
        """)
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(int(out.stdout.strip()), instance.wake_message())

    def test_broadcast_never_raises(self):
        instance.broadcast_wake()       # 没人在听也不该炸


class TestNonWindows(unittest.TestCase):
    @unittest.skipIf(IS_WINDOWS, "这条描述的是其它平台的退化行为")
    def test_no_guard_but_never_blocks(self):
        """没有保护，但也不该拦着人跑。"""
        self.assertTrue(instance.acquire())
        self.assertTrue(instance.acquire())


if __name__ == "__main__":
    unittest.main()

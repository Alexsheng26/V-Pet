"""台面几何的测试。不需要 Qt，也不需要真的开一堆窗口。

    python -m unittest discover
"""

from __future__ import annotations

import unittest

from vpet.ledges import MIN_WIDTH, Ledge, LedgeSet


def ledge(left: int, right: int, y: int, key: int = 0) -> Ledge:
    return Ledge(left, right, y, key)


class TestFiltering(unittest.TestCase):
    def test_narrow_ledges_are_dropped(self):
        """标题栏按钮区那种细条上站个宠物很怪，而且立刻就走到头了。"""
        wide = ledge(0, MIN_WIDTH, 300)
        narrow = ledge(0, MIN_WIDTH - 1, 300)
        self.assertEqual(len(LedgeSet([wide, narrow])), 1)

    def test_spans_excludes_the_right_edge(self):
        self.assertTrue(ledge(100, 200, 0).spans(199))
        self.assertFalse(ledge(100, 200, 0).spans(200))


class TestLanding(unittest.TestCase):
    def setUp(self) -> None:
        self.set = LedgeSet([
            ledge(0, 800, 500, key=1),      # 低的
            ledge(200, 700, 300, key=2),    # 高的，压在上面
        ])

    def test_lands_on_the_highest_surface_below(self):
        got = self.set.landing_below(400, feet_y=100)
        self.assertEqual(got.key, 2)

    def test_ignores_surfaces_above_the_feet(self):
        """否则宠物会往上吸到头顶的窗口上。"""
        got = self.set.landing_below(400, feet_y=400)
        self.assertEqual(got.key, 1)

    def test_outside_the_span_does_not_count(self):
        got = self.set.landing_below(50, feet_y=100)
        self.assertEqual(got.key, 1, "x=50 不在高台面范围内，该落到低的那条")

    def test_nothing_below_means_no_ledge(self):
        self.assertIsNone(self.set.landing_below(400, feet_y=900))

    def test_empty_set_is_fine(self):
        self.assertIsNone(LedgeSet().landing_below(0, 0))


class TestRefresh(unittest.TestCase):
    """窗口被拖动时，脚下那条台面每帧都在变位置。"""

    def test_matches_by_window_not_by_position(self):
        before = ledge(100, 500, 300, key=42)
        after = ledge(160, 560, 340, key=42)        # 同一扇窗，挪了
        got = LedgeSet([after]).refresh(before)
        self.assertEqual((got.left, got.y), (160, 340))

    def test_window_gone_means_no_support(self):
        got = LedgeSet([ledge(0, 500, 300, key=7)]).refresh(ledge(0, 500, 300, key=42))
        self.assertIsNone(got, "句柄对不上就是另一扇窗了")

    def test_a_big_jump_still_counts_as_the_same_window(self):
        """回归防线：曾经还要求宠物落在新范围内，于是 Win+← 这类一次挪半屏的
        吸附会让宠物掉下去。站在窗口上的东西挪多远都该跟着走。"""
        before = ledge(100, 500, 300, key=42)
        after = ledge(1400, 1800, 300, key=42)
        self.assertIsNotNone(LedgeSet([after]).refresh(before))

    def test_no_support_stays_no_support(self):
        self.assertIsNone(LedgeSet([ledge(0, 500, 300)]).refresh(None))


class TestSignature(unittest.TestCase):
    def test_moving_a_window_changes_the_signature(self):
        a = LedgeSet([ledge(0, 500, 300, key=1)])
        b = LedgeSet([ledge(0, 500, 301, key=1)])
        self.assertNotEqual(a.signature(), b.signature())

    def test_same_layout_same_signature(self):
        a = LedgeSet([ledge(0, 500, 300, key=1)])
        b = LedgeSet([ledge(0, 500, 300, key=1)])
        self.assertEqual(a.signature(), b.signature())


if __name__ == "__main__":
    unittest.main()

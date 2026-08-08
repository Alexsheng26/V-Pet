"""屏幕布局几何的测试。不需要 Qt，也不需要真的插第二块显示器。

多屏的坑几乎全在"哪两块屏算挨着"上。这里把各种排列都摆出来测 ——
毕竟大部分人开发时只有一块屏，这些分支平时一次都跑不到。

    python -m unittest discover
"""

from __future__ import annotations

import unittest

from vpet.screens import TOUCH_TOLERANCE, Screen, ScreenLayout, layout_from_rects

# 并排等高：最常见的双屏
SIDE_BY_SIDE = layout_from_rects([(0, 0, 1000, 800), (1000, 0, 2000, 800)])
# 右边那块更矮（分辨率更低），接缝处地面高度不同
STEPPED = layout_from_rects([(0, 0, 1000, 800), (1000, 0, 2000, 600)])
# 中间隔着一段没有屏幕的死区
GAPPED = layout_from_rects([(0, 0, 1000, 800), (1200, 0, 2200, 800)])
# 上下堆叠：水平方向根本挨不着
STACKED = layout_from_rects([(0, 0, 1000, 800), (0, 800, 1000, 1600)])


class TestLocating(unittest.TestCase):
    def test_index_at_finds_the_screen(self):
        self.assertEqual(SIDE_BY_SIDE.index_at(500, 400), 0)
        self.assertEqual(SIDE_BY_SIDE.index_at(1500, 400), 1)

    def test_index_at_returns_none_in_a_dead_zone(self):
        self.assertIsNone(GAPPED.index_at(1100, 400))

    def test_nearest_never_gives_up(self):
        """死区里也必须给出一块屏 —— 宠物总得站在什么上面。"""
        self.assertEqual(GAPPED.nearest_index(1050, 400), 0)
        self.assertEqual(GAPPED.nearest_index(1150, 400), 1)
        self.assertEqual(GAPPED.nearest_index(-9999, -9999), 0)

    def test_right_edge_is_exclusive(self):
        # x=1000 属于右边那块，不属于左边 —— 差一个像素的归属要定死
        self.assertEqual(SIDE_BY_SIDE.index_at(999, 400), 0)
        self.assertEqual(SIDE_BY_SIDE.index_at(1000, 400), 1)


class TestAdjacency(unittest.TestCase):
    def test_touching_screens_are_neighbours(self):
        self.assertEqual(SIDE_BY_SIDE.neighbour(0, 1), 1)
        self.assertEqual(SIDE_BY_SIDE.neighbour(1, -1), 0)

    def test_outer_edges_have_no_neighbour(self):
        """这才是真正的墙。"""
        self.assertIsNone(SIDE_BY_SIDE.neighbour(0, -1))
        self.assertIsNone(SIDE_BY_SIDE.neighbour(1, 1))

    def test_a_gap_is_not_adjacency(self):
        """隔着死区不算挨着，否则宠物会走进两屏之间彻底消失。"""
        self.assertIsNone(GAPPED.neighbour(0, 1))
        self.assertIsNone(GAPPED.neighbour(1, -1))

    def test_stacked_screens_are_not_horizontal_neighbours(self):
        for direction in (-1, 1):
            self.assertIsNone(STACKED.neighbour(0, direction))
            self.assertIsNone(STACKED.neighbour(1, direction))

    def test_a_pixel_of_slack_still_counts(self):
        """缩放取整偶尔会差一两个像素，不该被当成中间有条缝。"""
        nudged = layout_from_rects([(0, 0, 1000, 800), (1000 + TOUCH_TOLERANCE, 0, 2000, 800)])
        self.assertEqual(nudged.neighbour(0, 1), 1)

    def test_picks_the_neighbour_with_the_most_overlap(self):
        # 右边贴着两块屏：一块只擦到边角，一块整个对齐
        layout = layout_from_rects([
            (0, 0, 1000, 800),
            (1000, 700, 2000, 1500),      # 只重叠 100
            (1000, 0, 2000, 800),         # 完全重叠
        ])
        self.assertEqual(layout.neighbour(0, 1), 2)


class TestGeometryForThePet(unittest.TestCase):
    def test_ground_is_the_bottom_minus_the_pet(self):
        self.assertEqual(SIDE_BY_SIDE.ground(0, 100), 700)
        self.assertEqual(STEPPED.ground(1, 100), 500)

    def test_span_keeps_the_whole_window_on_screen(self):
        self.assertEqual(SIDE_BY_SIDE.span(1, 100), (1000, 1900))


class TestDegenerateCases(unittest.TestCase):
    def test_single_helper(self):
        layout = ScreenLayout.single((0, 0, 1920, 1080))
        self.assertEqual(len(layout), 1)
        self.assertIsNone(layout.neighbour(0, 1))

    def test_no_screens_still_yields_something_usable(self):
        """Qt 理论上不会给出空列表，但真给了也不该让宠物崩在这儿。"""
        layout = ScreenLayout([])
        self.assertEqual(len(layout), 1)
        self.assertEqual(layout.nearest_index(0, 0), 0)

    def test_out_of_range_primary_falls_back(self):
        self.assertEqual(ScreenLayout([Screen(0, 0, 100, 100)], primary=7).primary, 0)


class TestSignature(unittest.TestCase):
    """指纹用来判断屏幕配置有没有变，漏判就等于错过了插拔显示器。"""

    def test_same_layout_same_signature(self):
        self.assertEqual(
            layout_from_rects([(0, 0, 1000, 800)]).signature(),
            layout_from_rects([(0, 0, 1000, 800)]).signature(),
        )

    def test_resolution_change_shows_up(self):
        self.assertNotEqual(
            layout_from_rects([(0, 0, 1000, 800)]).signature(),
            layout_from_rects([(0, 0, 1000, 600)]).signature(),
        )

    def test_unplugging_a_monitor_shows_up(self):
        self.assertNotEqual(SIDE_BY_SIDE.signature(), layout_from_rects([(0, 0, 1000, 800)]).signature())

    def test_primary_change_shows_up(self):
        self.assertNotEqual(
            layout_from_rects([(0, 0, 1000, 800), (1000, 0, 2000, 800)], primary=0).signature(),
            layout_from_rects([(0, 0, 1000, 800), (1000, 0, 2000, 800)], primary=1).signature(),
        )


if __name__ == "__main__":
    unittest.main()

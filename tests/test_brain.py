"""行为层的单元测试。

跑这些测试不需要显示器、不需要 Qt —— 这正是把 state.py 和渲染层切开的回报。

    python -m unittest discover tests
"""

from __future__ import annotations

import unittest

from vpet.state import GRAVITY, PetBrain, State

BOUNDS = (0, 0, 1000, 800)   # left, top, right, bottom
SIZE = 100


def brain() -> PetBrain:
    return PetBrain(SIZE, BOUNDS)


class TestSpawn(unittest.TestCase):
    def test_starts_on_the_ground(self):
        b = brain()
        self.assertEqual(b.state, State.IDLE)
        self.assertEqual(b.y, BOUNDS[3] - SIZE)


class TestWalk(unittest.TestCase):
    def test_turns_around_at_the_right_wall(self):
        b = brain()
        b._enter(State.WALK)
        b.vx = abs(b.vx)
        b.x = BOUNDS[2] - SIZE - 1
        b.update(0.5)
        self.assertLessEqual(b.x, BOUNDS[2] - SIZE)
        self.assertLess(b.vx, 0)
        self.assertEqual(b.facing, -1)

    def test_never_walks_into_the_wall_it_is_already_on(self):
        b = brain()
        b.x = float(BOUNDS[0])
        for _ in range(30):
            b._enter(State.WALK)
            self.assertGreater(b.vx, 0, "贴着左墙时不应该再往左走")


class TestFall(unittest.TestCase):
    def test_gravity_accelerates_downward(self):
        b = brain()
        b.y = 100.0
        b._enter(State.FALL)
        b.update(0.1)
        self.assertAlmostEqual(b.vy, GRAVITY * 0.1, places=5)

    def test_settles_into_idle_instead_of_bouncing_forever(self):
        b = brain()
        b.y = 100.0
        b._enter(State.FALL)
        for _ in range(600):          # 10 秒
            b.update(1 / 60)
            if b.state is State.IDLE:
                break
        self.assertEqual(b.state, State.IDLE)
        self.assertEqual(b.y, BOUNDS[3] - SIZE)

    def test_stays_inside_horizontal_bounds_when_thrown(self):
        b = brain()
        b.grab()
        b.y = 200.0
        b.vx = 5000.0                 # 用力往右甩
        b._enter(State.FALL)
        for _ in range(300):
            b.update(1 / 60)
        self.assertGreaterEqual(b.x, BOUNDS[0])
        self.assertLessEqual(b.x, BOUNDS[2] - SIZE)


class TestSleep(unittest.TestCase):
    def test_dozes_off_after_being_left_alone(self):
        b = brain()
        for _ in range(60 * 60):      # 60 秒，中间会 idle/walk 来回切
            b.update(1 / 60)
            if b.state is State.SLEEP:
                break
        self.assertEqual(b.state, State.SLEEP)

    def test_wakes_on_interaction(self):
        b = brain()
        b.doze_off()
        b.wake()
        self.assertEqual(b.state, State.IDLE)

    def test_wandering_does_not_reset_the_sleep_timer(self):
        # 回归测试: 曾经 _tick_walk 每帧把计时器清零，而 IDLE 每几秒就切一次
        # WALK，导致 SLEEP_AFTER 永远攒不满、宠物永远睡不着。
        b = brain()
        b._enter(State.WALK)
        b.undisturbed = 10.0
        b.update(1 / 60)
        self.assertGreater(b.undisturbed, 10.0)

    def test_interaction_resets_the_sleep_timer(self):
        b = brain()
        b.undisturbed = 999.0
        b.grab()
        self.assertEqual(b.undisturbed, 0.0)


class TestDrag(unittest.TestCase):
    def test_release_velocity_is_capped(self):
        b = brain()
        b.grab()
        for i in range(10):           # 疯狂拖动
            b.drag_to(b.x + 500, b.y)
            b.update(1 / 60)
        b.release()
        self.assertLessEqual(abs(b.vx), 900.0)


if __name__ == "__main__":
    unittest.main()

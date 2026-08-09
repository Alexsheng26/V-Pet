"""行为层的单元测试。

跑这些测试不需要显示器、不需要 Qt —— 这正是把 state.py 和渲染层切开的回报。

    python -m unittest discover
"""

from __future__ import annotations

import unittest

from vpet.ledges import Ledge, LedgeSet
from vpet.screens import ScreenLayout, layout_from_rects
from vpet.state import (
    CLING_MARGIN,
    CLING_MIN_HEIGHT,
    CROSSED_IDLE_RANGE,
    DIZZY_TIME,
    FOLLOW_DEADZONE,
    GRAVITY,
    HAPPY_TIME,
    IDLE_RANGE,
    SLEEP_AFTER,
    PetBrain,
    Posture,
    State,
)

BOUNDS = (0, 0, 1000, 800)   # left, top, right, bottom
SIZE = 100
GROUND = BOUNDS[3] - SIZE
STEP = 1 / 60


def brain() -> PetBrain:
    return PetBrain(SIZE, ScreenLayout.single(BOUNDS))


def run(b: PetBrain, seconds: float, until: State | None = None) -> None:
    for _ in range(int(seconds / STEP)):
        b.update(STEP)
        if until is not None and b.state is until:
            return


class TestSpawn(unittest.TestCase):
    def test_starts_on_the_ground(self):
        b = brain()
        self.assertEqual(b.state, State.IDLE)
        self.assertEqual(b.y, GROUND)


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

    def test_settles_instead_of_bouncing_forever(self):
        b = brain()
        b.y = 100.0
        b._enter(State.FALL)
        run(b, 10.0, until=State.DIZZY)
        self.assertIn(b.state, (State.IDLE, State.DIZZY))
        self.assertEqual(b.y, GROUND)

    def test_stays_inside_horizontal_bounds_when_thrown(self):
        b = brain()
        b.grab()
        b.y = 200.0
        b.vx = 5000.0                 # 用力往右甩
        b._enter(State.FALL)
        run(b, 5.0)
        self.assertGreaterEqual(b.x, BOUNDS[0])
        self.assertLessEqual(b.x, BOUNDS[2] - SIZE)


class TestDizzy(unittest.TestCase):
    def test_hard_landing_makes_it_dizzy(self):
        b = brain()
        b.x = 400.0
        b.y = GROUND - 400.0          # 摔够高
        b._enter(State.FALL)
        run(b, 10.0, until=State.DIZZY)
        self.assertEqual(b.state, State.DIZZY)

    def test_gentle_landing_does_not(self):
        b = brain()
        b.x = 400.0
        b.y = GROUND - 40.0
        b._enter(State.FALL)
        run(b, 10.0, until=State.IDLE)
        self.assertEqual(b.state, State.IDLE)

    def test_impact_is_measured_at_first_contact_not_at_rest(self):
        # 回归测试: 每次反弹都比上次轻，等落稳时 vy 已经很小了。
        # 如果在那时候才判定冲击，摔多高都不会懵。
        b = brain()
        b.x = 400.0
        b.y = GROUND - 400.0
        b._enter(State.FALL)
        run(b, 10.0, until=State.DIZZY)
        self.assertGreater(b._impact, 1100.0)

    def test_recovers_on_its_own(self):
        b = brain()
        b._enter(State.DIZZY)
        run(b, DIZZY_TIME + 0.5)
        self.assertEqual(b.state, State.IDLE)


class TestCling(unittest.TestCase):
    def test_sticks_to_the_wall_when_released_next_to_it(self):
        b = brain()
        b.grab()
        b.x, b.y = 5.0, 200.0
        b.release()
        self.assertEqual(b.state, State.CLING)
        self.assertEqual(b.x, BOUNDS[0])
        self.assertEqual(b.facing, 1, "挂左墙上该脸朝屏幕内侧")

    def test_faces_inward_on_the_right_wall_too(self):
        b = brain()
        b.grab()
        b.x, b.y = BOUNDS[2] - SIZE - 5.0, 200.0
        b.release()
        self.assertEqual(b.state, State.CLING)
        self.assertEqual(b.facing, -1)

    def test_does_not_cling_when_released_near_the_floor(self):
        # 贴着地面还挂墙上会很怪，应该直接落地
        b = brain()
        b.grab()
        b.x, b.y = 5.0, GROUND - CLING_MIN_HEIGHT / 2
        b.release()
        self.assertEqual(b.state, State.FALL)

    def test_does_not_cling_from_the_middle_of_the_screen(self):
        b = brain()
        b.grab()
        b.x, b.y = 500.0, 200.0
        b.release()
        self.assertEqual(b.state, State.FALL)

    def test_lets_go_eventually(self):
        b = brain()
        b.grab()
        b.x, b.y = 5.0, 200.0
        b.release()
        b.next_switch = 0.1
        run(b, 1.0, until=State.FALL)
        self.assertEqual(b.state, State.FALL)

    def test_margin_is_actually_used(self):
        b = brain()
        b.grab()
        b.x, b.y = CLING_MARGIN - 1, 200.0
        b.release()
        self.assertEqual(b.state, State.CLING)


class TestFollow(unittest.TestCase):
    def test_walks_toward_the_pointer(self):
        b = brain()
        b.follow = True
        b.set_pointer(900.0, 700.0)
        start = b.x
        run(b, 1.0)
        self.assertGreater(b.x, start)
        self.assertEqual(b.facing, 1)

    def test_stops_once_it_arrives(self):
        b = brain()
        b.follow = True
        b.set_pointer(900.0, 700.0)
        run(b, 8.0)
        self.assertLessEqual(abs(900.0 - (b.x + SIZE / 2)), FOLLOW_DEADZONE + 5)

    def test_does_not_twitch_between_idle_and_walk_once_arrived(self):
        # 回归测试: 站定后 _tick_idle 若还随机切 WALK，_tick_walk 会立刻切回
        # IDLE，两个姿态每帧互跳，画面会抖。
        b = brain()
        b.follow = True
        b.set_pointer(b.x + SIZE / 2, 700.0)   # 就在脚下
        run(b, 3.0)
        self.assertEqual(b.state, State.IDLE)

    def test_does_not_fall_asleep_while_following(self):
        b = brain()
        b.follow = True
        b.set_pointer(900.0, 700.0)
        run(b, SLEEP_AFTER + 10.0)
        self.assertNotEqual(b.state, State.SLEEP)

    def test_ignores_the_pointer_when_switched_off(self):
        b = brain()
        b.set_pointer(900.0, 700.0)
        self.assertIsNone(b._pointer_dx())


class TestHeadPat(unittest.TestCase):
    def test_makes_it_happy(self):
        b = brain()
        b.head_pat()
        self.assertEqual(b.state, State.HAPPY)

    def test_resets_the_sleep_timer(self):
        b = brain()
        b.undisturbed = 999.0
        b.head_pat()
        self.assertEqual(b.undisturbed, 0.0)

    def test_does_not_interrupt_a_drag(self):
        b = brain()
        b.grab()
        b.head_pat()
        self.assertEqual(b.state, State.DRAG)

    def test_wears_off(self):
        b = brain()
        b.head_pat()
        run(b, HAPPY_TIME + 0.5)
        self.assertEqual(b.state, State.IDLE)


class TestSleep(unittest.TestCase):
    def test_dozes_off_after_being_left_alone(self):
        b = brain()
        run(b, SLEEP_AFTER + 10.0, until=State.SLEEP)
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
        b.update(STEP)
        self.assertGreater(b.undisturbed, 10.0)

    def test_interaction_resets_the_sleep_timer(self):
        b = brain()
        b.undisturbed = 999.0
        b.grab()
        self.assertEqual(b.undisturbed, 0.0)


class TestMultipleScreens(unittest.TestCase):
    """多屏下"边界"不再是一个矩形：接缝不是墙，外侧才是。"""

    SIDE_BY_SIDE = [(0, 0, 1000, 800), (1000, 0, 2000, 800)]
    STEPPED_UP = [(0, 0, 1000, 800), (1000, 0, 2000, 600)]   # 右屏更矮 → 地面更高
    GAPPED = [(0, 0, 1000, 800), (1200, 0, 2200, 800)]       # 中间是死区

    def on(self, rects) -> PetBrain:
        return PetBrain(SIZE, layout_from_rects(rects))

    def walking(self, rects, x: float, direction: int, screen: int = 0) -> PetBrain:
        b = self.on(rects)
        b.screen = screen
        b._enter(State.WALK)
        # 关掉随机的走路时长。_enter(WALK) 会抽一个 0.8~2.5 秒的值，
        # 抽短了宠物还没走到接缝就自己停下来了 —— 这些用例测的是跨屏，
        # 不该被那个随机数变成偶发失败。
        b.next_switch = 999.0
        b.vx = direction * abs(b.vx)
        b.facing = direction
        b.x, b.y = x, b.ground
        return b

    # 这些用例都只跑很短的一段：WALK 本身 0.8~2.5 秒就会自然切回 IDLE，
    # 观察窗口开长了，断言到的是随机状态机而不是跨屏行为。
    # 跨过接缝只需要走 10px，0.2 秒足够。
    def test_walks_across_the_seam_instead_of_turning_around(self):
        b = self.walking(self.SIDE_BY_SIDE, 940.0, 1)
        run(b, 0.6)
        self.assertEqual(b.screen, 1, "没走过接缝")
        self.assertGreater(b.x, 950)

    def test_still_turns_around_at_the_outer_edge(self):
        b = self.walking(self.SIDE_BY_SIDE, 1880.0, 1, screen=1)
        run(b, 1.0)
        self.assertLessEqual(b.x, 1900)
        self.assertEqual(b.screen, 1)
        self.assertLess(b.vx, 0, "撞到最外侧该掉头")

    def test_a_gap_between_screens_is_a_wall(self):
        """否则宠物会走进死区，进程还在、托盘还在，人就是找不着它。"""
        b = self.walking(self.GAPPED, 940.0, 1)
        run(b, 3.0)
        self.assertEqual(b.screen, 0)
        self.assertLessEqual(b.x, 900)

    def test_steps_up_onto_a_shorter_screen(self):
        b = self.walking(self.STEPPED_UP, 940.0, 1)
        run(b, 0.6)
        self.assertEqual(b.screen, 1)
        self.assertEqual(b.state, State.WALK, "迈个台阶不该打断走路")
        self.assertEqual(b.y, b.ground)

    def test_walks_off_a_ledge_and_falls(self):
        # 反过来走：从矮屏走回高屏，等于走下一个台阶
        b = self.walking(self.STEPPED_UP, 1010.0, -1, screen=1)
        run(b, 3.0, until=State.FALL)
        self.assertEqual(b.state, State.FALL, "落差 200px 该掉下去而不是瞬移")
        self.assertEqual(b.screen, 0)

    def test_does_not_cling_to_an_internal_seam(self):
        """挂在两块屏中间等于吊在桌面正中，很怪。"""
        b = self.on(self.SIDE_BY_SIDE)
        b.grab()
        b.x, b.y = 995.0, 200.0     # 贴着屏 1 的左边缘，但那是接缝不是墙
        b.release()
        self.assertEqual(b.state, State.FALL)

    def test_still_clings_to_the_outer_edge(self):
        b = self.on(self.SIDE_BY_SIDE)
        b.grab()
        b.x, b.y = 1895.0, 200.0    # 屏 1 的右边缘，整个桌面的最外侧
        b.release()
        self.assertEqual(b.state, State.CLING)

    def test_release_re_resolves_which_screen_it_is_on(self):
        b = self.on(self.SIDE_BY_SIDE)
        b.grab()
        b.x, b.y = 1400.0, 300.0    # 被拖到了副屏
        b.release()
        self.assertEqual(b.screen, 1)

    def test_dropped_in_a_dead_zone_lands_on_the_nearest_screen(self):
        b = self.on(self.GAPPED)
        b.grab()
        b.x, b.y = 1150.0, 300.0    # 两块屏之间，没有任何屏幕
        b.release()
        run(b, 5.0, until=State.IDLE)
        self.assertIsNotNone(b.layout.index_at(b.x + SIZE / 2, b.y + SIZE / 2))

    def test_unplugging_a_monitor_does_not_strand_the_pet(self):
        """位置必须**立刻**挪回来，不能指望它自己走回来。

        宠物默认在发呆，发呆是不动的 —— 只改屏幕下标的话，表现就是拔掉副屏后
        宠物再也找不着了，而托盘图标还在。
        """
        b = self.on(self.SIDE_BY_SIDE)
        b.x, b.y, b.screen = 1500.0, 700.0, 1
        b.set_layout(layout_from_rects([(0, 0, 1000, 800)]))
        self.assertEqual(b.screen, 0)
        self.assertLessEqual(b.x, 900, "还停在一块已经不存在的屏幕上")
        self.assertIsNotNone(b.layout.index_at(b.x + SIZE / 2, b.y + SIZE / 2))

    def test_shrinking_a_screen_pulls_the_pet_back_in(self):
        # 改分辨率、改缩放走的是同一条路径
        b = self.on([(0, 0, 1920, 1080)])
        b.x, b.y = 1800.0, 980.0
        b.set_layout(layout_from_rects([(0, 0, 1280, 720)]))
        self.assertLessEqual(b.x, 1280 - SIZE)
        self.assertLessEqual(b.y, b.ground)

    def test_single_screen_behaves_exactly_as_before(self):
        b = brain()
        self.assertIsNone(b.layout.neighbour(0, 1))
        self.assertIsNone(b.layout.neighbour(0, -1))


class TestLedges(unittest.TestCase):
    """站在窗口上沿。任务栏不再是唯一的地面。"""

    WINDOW = Ledge(200, 700, 400, key=42)      # 上沿 y=400 的一扇窗

    def on_window(self) -> PetBrain:
        b = brain()
        b.set_ledges(LedgeSet([self.WINDOW]))
        return b

    def test_falls_onto_a_window_instead_of_the_floor(self):
        b = self.on_window()
        b.x, b.y = 400.0, 50.0
        b._enter(State.FALL)
        run(b, 5.0, until=State.IDLE)
        self.assertIsNotNone(b.support, "没踩到窗口")
        self.assertEqual(b.y, self.WINDOW.y - SIZE)

    def test_misses_the_window_when_not_above_it(self):
        b = self.on_window()
        b.x, b.y = 20.0, 50.0                  # 窗口左边以外
        b._enter(State.FALL)
        run(b, 5.0, until=State.IDLE)
        self.assertIsNone(b.support)
        self.assertEqual(b.y, GROUND)

    def test_turns_around_at_the_edge_of_the_window(self):
        b = self.on_window()
        b.support = self.WINDOW
        b.y = b.ground
        b._enter(State.WALK)
        b.next_switch, b.vx = 99.0, abs(b.vx)
        b.x = float(self.WINDOW.right - SIZE - 2)
        run(b, 1.0)
        self.assertLessEqual(b.x, self.WINDOW.right - SIZE)
        self.assertIsNotNone(b.support, "掉头就好，不该掉下去")

    def test_rides_a_window_that_moves(self):
        """窗口被拖着走时宠物跟着台面一起动 —— 站在窗口上就该是这样。"""
        b = self.on_window()
        b.support = self.WINDOW
        b.x, b.y = 400.0, b.ground
        b.set_ledges(LedgeSet([Ledge(260, 760, 350, key=42)]))   # 右移 60，上移 50
        self.assertEqual(b.y, 350 - SIZE)
        self.assertEqual(b.support.left, 260)
        self.assertEqual(b.x, 460.0, "只对齐 y 不平移 x 的话，窗口横移宠物会留在原地")

    def test_rides_even_a_snap_across_the_screen(self):
        b = self.on_window()
        b.support = self.WINDOW
        b.x, b.y = 400.0, b.ground
        b.set_ledges(LedgeSet([Ledge(500, 1000, 400, key=42)]))  # Win+→ 那种吸附
        self.assertIsNotNone(b.support, "一次挪太远不该判成掉下去")
        self.assertEqual(b.x, 700.0)

    def test_falls_when_the_window_closes(self):
        b = self.on_window()
        b.support = self.WINDOW
        b.x, b.y = 400.0, b.ground
        b._enter(State.IDLE)
        b.support = self.WINDOW               # _enter(IDLE) 不清 support
        b.set_ledges(LedgeSet())
        self.assertEqual(b.state, State.FALL)
        self.assertIsNone(b.support)

    def test_grabbing_leaves_the_window(self):
        b = self.on_window()
        b.support = self.WINDOW
        b.grab()
        self.assertIsNone(b.support)

    def test_ledges_below_the_taskbar_are_ignored(self):
        # 任务栏下面的东西站不了，否则宠物会沉到屏幕外
        b = brain()
        b.set_ledges(LedgeSet([Ledge(0, 900, BOUNDS[3] + 50, key=9)]))
        b.x, b.y = 400.0, 50.0
        b._enter(State.FALL)
        run(b, 5.0, until=State.IDLE)
        self.assertIsNone(b.support)
        self.assertEqual(b.y, GROUND)

    def test_a_hard_landing_on_a_window_still_dizzies(self):
        b = self.on_window()
        b.x, b.y = 400.0, float(self.WINDOW.y - SIZE) - 400.0
        b._enter(State.FALL)
        run(b, 6.0, until=State.DIZZY)
        self.assertEqual(b.state, State.DIZZY)


class TestPosture(unittest.TestCase):
    """抱手是待机时的姿势变化，和"在做什么"正交，所以不是一个 State。"""

    def test_starts_relaxed(self):
        self.assertEqual(brain().posture, Posture.RELAXED)

    def test_every_other_state_needs_its_hands(self):
        # 走路要摆手、被抓要扬手、贴墙要抓着 —— 抱着手做这些都不对
        for st in (State.WALK, State.DRAG, State.FALL, State.SLEEP,
                   State.HAPPY, State.CLING, State.DIZZY):
            b = brain()
            b.posture = Posture.CROSSED
            b._enter(st)
            self.assertEqual(b.posture, Posture.RELAXED, f"{st.value} 不该保持抱手")

    def test_both_postures_occur_when_idling(self):
        b = brain()
        seen = set()
        for _ in range(200):
            b._enter(State.IDLE)
            seen.add(b.posture)
        self.assertEqual(seen, {Posture.RELAXED, Posture.CROSSED})

    def test_the_two_idle_durations_do_not_overlap(self):
        """区间一重叠，"抱手站得更久"就只是概率上成立 —— 实际仍会抽到比垂手更短的。

        这里断言常量本身而不是采样值: 采样断言在边界上会偶发失败，
        而且失败时指向的是运气而不是配置。
        """
        self.assertGreaterEqual(CROSSED_IDLE_RANGE[0], IDLE_RANGE[1])

    def test_each_posture_draws_from_its_own_range(self):
        b = brain()
        durations = {Posture.RELAXED: [], Posture.CROSSED: []}
        for _ in range(200):
            b._enter(State.IDLE)
            durations[b.posture].append(b.next_switch)
        for posture, span in ((Posture.RELAXED, IDLE_RANGE), (Posture.CROSSED, CROSSED_IDLE_RANGE)):
            self.assertGreaterEqual(min(durations[posture]), span[0], posture.value)
            self.assertLessEqual(max(durations[posture]), span[1], posture.value)


class TestDrag(unittest.TestCase):
    def test_release_velocity_is_capped(self):
        b = brain()
        b.grab()
        for _ in range(10):           # 疯狂拖动
            b.drag_to(b.x + 500, b.y)
            b.update(STEP)
        b.release()
        self.assertLessEqual(abs(b.vx), 900.0)


if __name__ == "__main__":
    unittest.main()

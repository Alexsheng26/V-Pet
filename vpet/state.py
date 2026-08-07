"""宠物的行为状态机。

这个文件**不 import Qt**，一个像素都不画。它只回答两个问题:
"宠物现在处于什么状态"和"它在屏幕的什么位置"。

这么切的理由:
  1. 行为逻辑可以脱离 GUI 直接跑单元测试(见 tests/test_brain.py);
  2. 以后换渲染方式(换素材、换成 Live2D、甚至换 GUI 框架)不用碰这里。
"""

from __future__ import annotations

import random
from enum import Enum


class Posture(str, Enum):
    """待机时手怎么放。

    刻意**不做成 State**: 它和"在做什么"是正交的，塞进 State 会多出一个
    没人会去画的 sprites/crossed/ 目录，把素材约定搞脏。
    和 follow 一样，是状态之外的一个维度。
    """

    RELAXED = "relaxed"     # 手垂着
    CROSSED = "crossed"     # 抱手


class State(str, Enum):
    """状态值直接就是 sprites/ 下的目录名，渲染层靠它找素材。"""

    IDLE = "idle"
    WALK = "walk"
    DRAG = "drag"
    FALL = "fall"
    SLEEP = "sleep"
    HAPPY = "happy"     # 被摸头
    CLING = "cling"     # 挂在屏幕边上
    DIZZY = "dizzy"     # 摔懵了


# --- 手感参数，都在这儿调 ---------------------------------------------------
GRAVITY = 2000.0        # px/s^2
WALK_SPEED = 55.0       # px/s，自己溜达
FOLLOW_SPEED = 130.0    # px/s，追鼠标时走快点
FOLLOW_DEADZONE = 26.0  # 离鼠标这么近就算追上了，免得在原地抖
BOUNCE = 0.35           # 落地反弹系数
SETTLE_SPEED = 180.0    # 垂直速度低于这个值就算落稳，不再弹
THROW_LIMIT = 900.0     # 甩出去的速度上限，防止一把甩飞出屏幕
SLEEP_AFTER = 30.0      # 连续没被打扰多久开始打瞌睡(秒)
DIZZY_SPEED = 1100.0    # 落地冲击超过这个值会摔懵
DIZZY_TIME = 1.8
HAPPY_TIME = 2.2
CLING_MARGIN = 20.0     # 松手时离墙这么近就挂上去
CLING_MIN_HEIGHT = 30.0 # 离地太近就别挂了，直接落地更自然
IDLE_RANGE = (1.2, 4.0)
WALK_RANGE = (0.8, 2.5)
CLING_RANGE = (6.0, 15.0)
CROSS_CHANCE = 0.45     # 每次停下来抱手的概率
# 抱着手的待机要站得更久，用普通的 1.2~4 秒经常刚抱上就又走了。
# 注意下界必须 >= IDLE_RANGE 的上界: 两个区间一重叠，"抱手站得更久"就只是
# 概率上成立，实际还是会抽到比垂手更短的时长。tests 里有断言盯着这条。
CROSSED_IDLE_RANGE = (4.0, 7.5)


class PetBrain:
    """位置 + 状态 + 状态转移。坐标是窗口左上角的屏幕逻辑坐标。"""

    def __init__(self, size: int, bounds: tuple[int, int, int, int]) -> None:
        self.size = size
        self.set_bounds(bounds)

        self.x = float(self.left + (self.right - self.left - size) // 2)
        self.y = float(self.ground)
        self.vx = 0.0
        self.vy = 0.0
        self.facing = 1          # 1 朝右, -1 朝左

        self.state = State.IDLE
        self.posture = Posture.RELAXED
        self.state_t = 0.0       # 进入当前状态后过了多久
        # 距离上次"被用户打扰"过了多久，攒够 SLEEP_AFTER 就去睡。
        # 注意只有交互(grab/wake/head_pat)才清零 —— 它自己溜达一圈不算被打扰，
        # 否则 IDLE↔WALK 来回切会把计时器一直按在 0，永远睡不着。
        self.undisturbed = 0.0

        # 追鼠标是个"模式"而不是状态: 开着的时候它照样走 WALK，
        # 只是 WALK 的方向从随机改成朝鼠标。所以不用新加状态。
        self.follow = False
        self.pointer: tuple[float, float] | None = None

        self.next_switch = random.uniform(*IDLE_RANGE)
        self._impact = 0.0       # 这轮下落的最大落地冲击，用来判定摔懵
        self._prev_x = self.x
        self._prev_y = self.y

    # --- 外部输入 ---------------------------------------------------------
    def set_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        """屏幕可用区域(已排除任务栏)。换显示器时重新调用。"""
        self.left, self.top, self.right, self.bottom = bounds
        self.ground = self.bottom - self.size

    def set_pointer(self, x: float, y: float) -> None:
        self.pointer = (x, y)

    def grab(self) -> None:
        self._enter(State.DRAG)
        self.undisturbed = 0.0
        self.vx = self.vy = 0.0
        self._prev_x, self._prev_y = self.x, self.y

    def drag_to(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def release(self) -> None:
        """松手。靠墙够近就挂上去，否则带着甩出去的速度掉下来。"""
        self.vx = _clamp(self.vx, -THROW_LIMIT, THROW_LIMIT)
        self.vy = _clamp(self.vy, -THROW_LIMIT, THROW_LIMIT)

        high_enough = self.y < self.ground - CLING_MIN_HEIGHT
        if high_enough and self.x <= self.left + CLING_MARGIN:
            self.x = float(self.left)
            self.facing = 1          # 背靠墙，脸朝屏幕内侧
            self._enter(State.CLING)
        elif high_enough and self.x >= self.right - self.size - CLING_MARGIN:
            self.x = float(self.right - self.size)
            self.facing = -1
            self._enter(State.CLING)
        else:
            self._enter(State.FALL)

    def head_pat(self) -> None:
        """摸头。正被拖着的时候不打断。"""
        if self.state is State.DRAG:
            return
        self.undisturbed = 0.0
        self._enter(State.HAPPY)

    def wake(self) -> None:
        self.undisturbed = 0.0
        if self.state is State.SLEEP:
            self._enter(State.IDLE)

    def doze_off(self) -> None:
        self._enter(State.SLEEP)

    # --- 主循环 -----------------------------------------------------------
    def update(self, dt: float) -> None:
        self.state_t += dt

        # 发呆和溜达都算"没被打扰"，攒够了随时可以睡过去。
        # 开着追鼠标就别睡了 —— 正盯着你呢。
        if self.state in (State.IDLE, State.WALK) and not self.follow:
            self.undisturbed += dt
            if self.undisturbed >= SLEEP_AFTER:
                self._enter(State.SLEEP)
                return

        if self.state is State.IDLE:
            self._tick_idle(dt)
        elif self.state is State.WALK:
            self._tick_walk(dt)
        elif self.state is State.DRAG:
            self._tick_drag(dt)
        elif self.state is State.FALL:
            self._tick_fall(dt)
        elif self.state is State.CLING:
            self._tick_cling(dt)
        elif self.state in (State.HAPPY, State.DIZZY):
            self._tick_timed(dt)
        # SLEEP 不用 tick，等外部 wake()

    def _tick_idle(self, dt: float) -> None:
        dx = self._pointer_dx()
        if dx is not None:
            if abs(dx) > FOLLOW_DEADZONE:
                self._enter(State.WALK)  # 鼠标跑远了，立刻追，不等发呆计时
            # 追鼠标模式下不随机溜达: 否则刚站定就随机切 WALK，
            # 而 _tick_walk 发现已经到位又立刻切回 IDLE，两个姿态每帧互跳会闪。
            return
        if self.state_t >= self.next_switch:
            self._enter(State.WALK)

    def _tick_walk(self, dt: float) -> None:
        dx = self._pointer_dx()
        if dx is not None:
            if abs(dx) <= FOLLOW_DEADZONE:
                self._enter(State.IDLE)
                return
            self.vx = FOLLOW_SPEED if dx > 0 else -FOLLOW_SPEED

        self.x += self.vx * dt

        # 撞墙就掉头，而不是卡在边上。但追鼠标时不掉头 ——
        # 否则鼠标停在屏幕外侧，宠物会贴着墙反复原地转身。
        if self.x <= self.left:
            self.x = float(self.left)
            if dx is None:
                self.vx = abs(self.vx)
        elif self.x >= self.right - self.size:
            self.x = float(self.right - self.size)
            if dx is None:
                self.vx = -abs(self.vx)
        self.facing = 1 if self.vx >= 0 else -1

        if dx is None and self.state_t >= self.next_switch:
            self._enter(State.IDLE)

    def _tick_drag(self, dt: float) -> None:
        # 位置由鼠标直接给，这里只反推速度，供松手时用。
        # 做一次指数平滑，否则单帧抖动会被放大成一次乱甩。
        if dt > 0:
            self.vx = 0.7 * self.vx + 0.3 * (self.x - self._prev_x) / dt
            self.vy = 0.7 * self.vy + 0.3 * (self.y - self._prev_y) / dt
        self._prev_x, self._prev_y = self.x, self.y
        if abs(self.vx) > 5:
            self.facing = 1 if self.vx > 0 else -1

    def _tick_fall(self, dt: float) -> None:
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

        if self.x <= self.left:
            self.x, self.vx = float(self.left), -self.vx * BOUNCE
        elif self.x >= self.right - self.size:
            self.x, self.vx = float(self.right - self.size), -self.vx * BOUNCE
        self.y = max(self.y, float(self.top))

        if self.y >= self.ground:
            self.y = float(self.ground)
            # 记的是**第一次**触地的冲击。后面每次反弹都更轻，
            # 等落稳时 vy 已经很小了，那时候再判定就永远不会懵。
            self._impact = max(self._impact, self.vy)
            if self.vy > SETTLE_SPEED:
                self.vy = -self.vy * BOUNCE   # 还有劲，弹一下
                self.vx *= 0.8
            else:
                self._enter(State.DIZZY if self._impact > DIZZY_SPEED else State.IDLE)

    def _tick_cling(self, dt: float) -> None:
        if self.state_t >= self.next_switch:
            self.vx = -self.facing * 20.0    # 蹬一下墙再掉下去
            self._enter(State.FALL)

    def _tick_timed(self, dt: float) -> None:
        limit = HAPPY_TIME if self.state is State.HAPPY else DIZZY_TIME
        if self.state_t >= limit:
            self._enter(State.IDLE)

    # --- 状态转移 ---------------------------------------------------------
    def _enter(self, state: State) -> None:
        self.state = state
        self.state_t = 0.0
        # 除了发呆，其它状态手都有正事要干 —— 走路要摆、被抓要扬、贴墙要抓着，
        # 所以默认先把姿势清回垂手，只有 IDLE 分支才可能改成抱手。
        self.posture = Posture.RELAXED

        if state is State.IDLE:
            self.vx = self.vy = 0.0
            if random.random() < CROSS_CHANCE:
                self.posture = Posture.CROSSED
                self.next_switch = random.uniform(*CROSSED_IDLE_RANGE)
            else:
                self.next_switch = random.uniform(*IDLE_RANGE)
        elif state is State.WALK:
            self.next_switch = random.uniform(*WALK_RANGE)
            dx = self._pointer_dx()
            if dx is not None and abs(dx) > FOLLOW_DEADZONE:
                direction = 1 if dx > 0 else -1
                self.vx = direction * FOLLOW_SPEED
            else:
                direction = random.choice((-1, 1))
                # 已经贴边了就别往墙里走，原地转身更自然
                if self.x <= self.left:
                    direction = 1
                elif self.x >= self.right - self.size:
                    direction = -1
                self.vx = direction * WALK_SPEED
            self.facing = direction
        elif state is State.FALL:
            self._impact = 0.0
        elif state is State.CLING:
            self.vx = self.vy = 0.0
            self.next_switch = random.uniform(*CLING_RANGE)
        elif state in (State.SLEEP, State.HAPPY, State.DIZZY):
            self.vx = self.vy = 0.0
            if state is State.SLEEP:
                self.undisturbed = 0.0

    def _pointer_dx(self) -> float | None:
        """追鼠标模式下，鼠标相对宠物中心的水平偏移；没开就是 None。"""
        if not self.follow or self.pointer is None:
            return None
        return self.pointer[0] - (self.x + self.size / 2)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v

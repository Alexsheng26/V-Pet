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


class State(str, Enum):
    """状态值直接就是 sprites/ 下的目录名，渲染层靠它找素材。"""

    IDLE = "idle"
    WALK = "walk"
    DRAG = "drag"
    FALL = "fall"
    SLEEP = "sleep"


# --- 手感参数，都在这儿调 ---------------------------------------------------
GRAVITY = 2000.0        # px/s^2
WALK_SPEED = 55.0       # px/s
BOUNCE = 0.35           # 落地反弹系数
SETTLE_SPEED = 180.0    # 垂直速度低于这个值就算落稳，不再弹
THROW_LIMIT = 900.0     # 甩出去的速度上限，防止一把甩飞出屏幕
SLEEP_AFTER = 30.0      # 连续发呆多久开始打瞌睡(秒)
IDLE_RANGE = (1.2, 4.0)
WALK_RANGE = (0.8, 2.5)


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
        self.state_t = 0.0       # 进入当前状态后过了多久
        # 距离上次"被用户打扰"过了多久，攒够 SLEEP_AFTER 就去睡。
        # 注意只有交互(grab/wake)才清零 —— 它自己溜达一圈不算被打扰，
        # 否则 IDLE↔WALK 来回切会把计时器一直按在 0，永远睡不着。
        self.undisturbed = 0.0
        self.next_switch = random.uniform(*IDLE_RANGE)
        self._prev_x = self.x
        self._prev_y = self.y

    # --- 外部输入 ---------------------------------------------------------
    def set_bounds(self, bounds: tuple[int, int, int, int]) -> None:
        """屏幕可用区域(已排除任务栏)。换显示器时重新调用。"""
        self.left, self.top, self.right, self.bottom = bounds
        self.ground = self.bottom - self.size

    def grab(self) -> None:
        self._enter(State.DRAG)
        self.undisturbed = 0.0
        self.vx = self.vy = 0.0
        self._prev_x, self._prev_y = self.x, self.y

    def drag_to(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def release(self) -> None:
        # 松手时把拖拽速度当初速度甩出去，比直接垂直掉下来生动
        self.vx = _clamp(self.vx, -THROW_LIMIT, THROW_LIMIT)
        self.vy = _clamp(self.vy, -THROW_LIMIT, THROW_LIMIT)
        self._enter(State.FALL)

    def wake(self) -> None:
        self.undisturbed = 0.0
        if self.state is State.SLEEP:
            self._enter(State.IDLE)

    def doze_off(self) -> None:
        self._enter(State.SLEEP)

    # --- 主循环 -----------------------------------------------------------
    def update(self, dt: float) -> None:
        self.state_t += dt

        # 发呆和溜达都算"没被打扰"，攒够了随时可以睡过去
        if self.state in (State.IDLE, State.WALK):
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
        # SLEEP 不用 tick，等外部 wake()

    def _tick_idle(self, dt: float) -> None:
        if self.state_t >= self.next_switch:
            self._enter(State.WALK)

    def _tick_walk(self, dt: float) -> None:
        self.x += self.vx * dt
        # 撞墙就掉头，而不是卡在边上
        if self.x <= self.left:
            self.x, self.vx = float(self.left), abs(self.vx)
        elif self.x >= self.right - self.size:
            self.x, self.vx = float(self.right - self.size), -abs(self.vx)
        self.facing = 1 if self.vx >= 0 else -1
        if self.state_t >= self.next_switch:
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
            if self.vy > SETTLE_SPEED:
                self.vy = -self.vy * BOUNCE   # 还有劲，弹一下
                self.vx *= 0.8
            else:
                self._enter(State.IDLE)

    # --- 状态转移 ---------------------------------------------------------
    def _enter(self, state: State) -> None:
        self.state = state
        self.state_t = 0.0

        if state is State.IDLE:
            self.vx = self.vy = 0.0
            self.next_switch = random.uniform(*IDLE_RANGE)
        elif state is State.WALK:
            self.next_switch = random.uniform(*WALK_RANGE)
            direction = random.choice((-1, 1))
            # 已经贴边了就别往墙里走，原地转身更自然
            if self.x <= self.left:
                direction = 1
            elif self.x >= self.right - self.size:
                direction = -1
            self.vx = direction * WALK_SPEED
            self.facing = direction
        elif state is State.SLEEP:
            self.vx = self.vy = 0.0
            self.undisturbed = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v

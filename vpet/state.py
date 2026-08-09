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

from .ledges import Ledge, LedgeSet
from .screens import ScreenLayout


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
    CURIOUS = "curious" # 被放到了桌面图标上，正在打量它


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
CURIOUS_TIME = 2.0
CLING_MARGIN = 20.0     # 松手时离墙这么近就挂上去
CLING_MIN_HEIGHT = 30.0 # 离地太近就别挂了，直接落地更自然
# 走过屏幕接缝时两侧地面的高度差：小于这个值直接迈上去，大于就是走下了个台阶，
# 交给重力处理。分界值太小的话，两块屏差几像素也会触发一次没必要的下落。
STEP_LIMIT = 12.0
IDLE_RANGE = (1.2, 4.0)
WALK_RANGE = (0.8, 2.5)
CLING_RANGE = (6.0, 15.0)
# 趴在墙上会慢慢往下滑 —— 完全静止不动看着像贴纸，有一点点位移才像"扒住了但在滑"。
# 速度要远小于 WALK_SPEED，否则不像滑而像沿墙走。
CLING_SLIDE = 14.0      # px/s
CROSS_CHANCE = 0.45     # 每次停下来抱手的概率
# 抱着手的待机要站得更久，用普通的 1.2~4 秒经常刚抱上就又走了。
# 注意下界必须 >= IDLE_RANGE 的上界: 两个区间一重叠，"抱手站得更久"就只是
# 概率上成立，实际还是会抽到比垂手更短的时长。tests 里有断言盯着这条。
CROSSED_IDLE_RANGE = (4.0, 7.5)


class PetBrain:
    """位置 + 状态 + 状态转移。坐标是窗口左上角的屏幕逻辑坐标。"""

    def __init__(self, size: int, layout: ScreenLayout) -> None:
        self.size = size
        self.layout = layout
        self.screen = layout.primary          # 当前站在哪块屏上
        self.ledges = LedgeSet()
        # 当前踩着的窗口上沿；None = 站在屏幕地面（任务栏上沿）
        self.support: Ledge | None = None

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
        self._pending_notice = False   # 落地后要不要打量脚下的桌面图标
        self._prev_x = self.x
        self._prev_y = self.y

    # --- 当前所在屏幕 ------------------------------------------------------
    # 这几个值都是从"现在站在哪块屏上"推出来的，不再是构造时固定的字段。
    # 走过接缝、被拖到副屏之后它们会跟着变。
    @property
    def left(self) -> int:
        return self.layout.screens[self.screen].left

    @property
    def top(self) -> int:
        return self.layout.screens[self.screen].top

    @property
    def right(self) -> int:
        return self.layout.screens[self.screen].right

    @property
    def bottom(self) -> int:
        return self.layout.screens[self.screen].bottom

    @property
    def screen_ground(self) -> float:
        return self.layout.ground(self.screen, self.size)

    @property
    def ground(self) -> float:
        """脚下那一层的高度。踩着窗口时是窗口上沿，否则是任务栏上沿。"""
        if self.support is not None:
            return float(self.support.y - self.size)
        return self.screen_ground

    # --- 外部输入 ---------------------------------------------------------
    def set_layout(self, layout: ScreenLayout) -> None:
        """屏幕配置变了（插拔显示器、改分辨率或缩放）时调用。

        原来那块屏可能已经没了，所以要按当前位置重新认屏，
        否则 self.screen 会是一个越界的下标。

        认完屏还必须**把位置挪回来**。只改下标的话，宠物会停在一块已经不存在的
        屏幕上；而它默认处在发呆状态，自己永远不会走回来 —— 表现就是拔掉副屏后
        宠物再也找不着了，托盘图标却还在。
        """
        self.layout = layout
        self.screen = layout.nearest_index(self.x + self.size / 2, self.y + self.size / 2)
        low, high = layout.span(self.screen, self.size)
        self.x = _clamp(self.x, low, high)
        # 上界是 ground 而不是 bottom：下落中 y < ground，这里不会误伤
        self.y = _clamp(self.y, float(self.top), self.ground)

    def set_ledges(self, ledges: LedgeSet) -> None:
        """刷新可站的台面。窗口开关和移动都走这里。"""
        self.ledges = ledges
        if self.support is None:
            return

        settled = self.state in (State.IDLE, State.WALK, State.SLEEP)
        refreshed = ledges.refresh(self.support)
        if refreshed is None:
            self.support = None
            if settled:
                self._enter(State.FALL)      # 脚下那扇窗关掉了 / 最小化了
            return

        shift = refreshed.left - self.support.left
        self.support = refreshed
        if settled:
            # 跟着窗口平移，保持在窗口上的相对位置。只把 y 对齐、不管 x 的话，
            # 窗口一横移宠物就留在原地了 —— 站在桌上的东西不会这样。
            self.x = _clamp(
                self.x + shift, float(refreshed.left), float(refreshed.right - self.size)
            )
            self.y = self.ground

    def set_pointer(self, x: float, y: float) -> None:
        self.pointer = (x, y)

    def notice_on_landing(self) -> None:
        """告诉宠物"你被放到某个桌面图标上了"。

        不立刻切状态：松手时它还在半空，得先落下去。落地那一刻才打量图标，
        顺序才对。摔得很重的话由摔懵优先 —— 撞晕了顾不上好奇。
        """
        self._pending_notice = True

    def grab(self) -> None:
        self._enter(State.DRAG)
        self._pending_notice = False          # 重新抓起来，上一次的意图作废
        self.undisturbed = 0.0
        self.vx = self.vy = 0.0
        self._prev_x, self._prev_y = self.x, self.y

    def drag_to(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def release(self) -> None:
        """松手。靠墙够近就挂上去，否则带着甩出去的速度掉下来。"""
        self.vx = _clamp(self.vx, -THROW_LIMIT, THROW_LIMIT)
        self.vy = _clamp(self.vy, -THROW_LIMIT, THROW_LIMIT)
        # 可能被拖到了另一块屏，甚至拖进了两块屏之间的死区，先重新认屏
        self.screen = self.layout.nearest_index(self.x + self.size / 2, self.y + self.size / 2)

        high_enough = self.y < self.ground - CLING_MIN_HEIGHT
        # 只在**外侧**边缘挂住。两块屏之间的接缝不是墙 ——
        # 挂在那儿等于吊在双屏桌面的正中间，很怪。
        if high_enough and self.x <= self.left + CLING_MARGIN and self._wall(-1):
            self.x = float(self.left)
            self.facing = 1          # 背靠墙，脸朝屏幕内侧
            self._enter(State.CLING)
        elif high_enough and self.x >= self.right - self.size - CLING_MARGIN and self._wall(1):
            self.x = float(self.right - self.size)
            self.facing = -1
            self._enter(State.CLING)
        else:
            self._enter(State.FALL)

    def _wall(self, direction: int) -> bool:
        """这一侧是真正的墙（没有邻屏）吗。"""
        return self.layout.neighbour(self.screen, direction) is None

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
        elif self.state in (State.HAPPY, State.DIZZY, State.CURIOUS):
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
        self._resolve_edge(turn_around=dx is None)
        if self.state is not State.WALK:
            return                    # 走下了接缝处的台阶，已经切到 FALL 了

        self.facing = 1 if self.vx >= 0 else -1
        if dx is None and self.state_t >= self.next_switch:
            self._enter(State.IDLE)

    def _resolve_edge(self, turn_around: bool) -> None:
        """走到本屏边缘：能过去就过去，过不去才当墙。

        换屏看的是宠物**中心**有没有越过接缝，而不是整个窗口有没有出本屏 ——
        后者会让宠物在离边缘一个身位的地方就被拦下，永远走不到接缝。
        跨越过程中窗口同时压在两块屏上，本来就该这样。

        turn_around=False 是追鼠标的情况，撞墙不掉头 ——
        否则鼠标停在屏幕外侧时，宠物会贴着墙反复原地转身。
        """
        if self.support is not None:
            # 站在窗口上：台面两端就是边界。走到头掉头而不是掉下去 ——
            # 掉下去更"真实"，但实际用起来是宠物一直在往下摔，很吵。
            low = float(self.support.left)
            high = float(self.support.right - self.size)
            if self.x < low:
                self.x = low
                if turn_around:
                    self.vx = abs(self.vx)
            elif self.x > high:
                self.x = high
                if turn_around:
                    self.vx = -abs(self.vx)
            return

        if self._cross_seam():
            return

        # 只有没有邻屏的那一侧才是墙，这时才把整个窗口拦在本屏内
        low, high = self.layout.span(self.screen, self.size)
        if self.x < low and self._wall(-1):
            self.x = low
            if turn_around:
                self.vx = abs(self.vx)
        elif self.x > high and self._wall(1):
            self.x = high
            if turn_around:
                self.vx = -abs(self.vx)

    def _cross_seam(self) -> bool:
        """中心越过接缝就换屏。返回是否发生了状态切换。"""
        centre = self.x + self.size / 2
        here = self.layout.screens[self.screen]
        if centre < here.left:
            return self._step_across(-1)
        if centre >= here.right:
            return self._step_across(1)
        return False

    def _step_across(self, direction: int) -> bool:
        """跨过屏幕接缝。两侧地面不一样高时，往上是迈台阶，往下是踩空。

        返回"是否切了状态"，而不是"是否换了屏" —— 调用方只关心还该不该继续
        按 WALK 处理。换了屏但只是迈了个台阶的话，走路照常继续。
        """
        neighbour = self.layout.neighbour(self.screen, direction)
        if neighbour is None:
            return False
        self.screen = neighbour
        drop = self.ground - self.y          # 新地面更低 => 正数
        if drop > STEP_LIMIT:
            self._enter(State.FALL)          # 保留水平速度，走着走着掉下去
            return True
        self.y = self.ground                 # 台阶，直接迈上去
        return False

    def _tick_drag(self, dt: float) -> None:
        # 位置由鼠标直接给，这里只反推速度，供松手时用。
        # 做一次指数平滑，否则单帧抖动会被放大成一次乱甩。
        if dt > 0:
            self.vx = 0.7 * self.vx + 0.3 * (self.x - self._prev_x) / dt
            self.vy = 0.7 * self.vy + 0.3 * (self.y - self._prev_y) / dt
        self._prev_x, self._prev_y = self.x, self.y
        if abs(self.vx) > 5:
            self.facing = 1 if self.vx > 0 else -1

    def _landing_surface(self) -> Ledge | None:
        """这一步会踩到的台面；None 表示会一路落到屏幕地面。

        必须在**移动之前**算：等 y 更新完再找的话，脚底已经穿过台面了，
        那条台面就不再满足"在脚底下方"，宠物会直接穿过去。
        """
        ledge = self.ledges.landing_below(
            self.x + self.size / 2,
            self.y + self.size,
            ceiling=float(self.top + self.size),   # 站上去要放得下整只
        )
        if ledge is None or ledge.y - self.size > self.screen_ground:
            return None                       # 比任务栏还低的台面没有意义
        return ledge

    def _tick_fall(self, dt: float) -> None:
        surface = self._landing_surface()
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt

        # 下落时的水平边界同理: 接缝可以飘过去，只有外侧边缘才反弹。
        # 换屏同样以中心为准 —— 用窗口边缘的话会提前半个身位换屏，
        # 地面高度跟着提前变，看起来像是空中被弹了一下。
        centre = self.x + self.size / 2
        here = self.layout.screens[self.screen]
        if centre < here.left:
            self._drift_across(-1)
        elif centre >= here.right:
            self._drift_across(1)

        low, high = self.layout.span(self.screen, self.size)
        if self.x < low and self._wall(-1):
            self.x, self.vx = low, -self.vx * BOUNCE
        elif self.x > high and self._wall(1):
            self.x, self.vx = high, -self.vx * BOUNCE
        self.y = max(self.y, float(self.top))

        ground = float(surface.y - self.size) if surface else self.screen_ground
        if self.y >= ground:
            self.y = ground
            self.support = surface
            # 记的是**第一次**触地的冲击。后面每次反弹都更轻，
            # 等落稳时 vy 已经很小了，那时候再判定就永远不会懵。
            self._impact = max(self._impact, self.vy)
            if self.vy > SETTLE_SPEED:
                self.vy = -self.vy * BOUNCE   # 还有劲，弹一下
                self.vx *= 0.8
            else:
                notice, self._pending_notice = self._pending_notice, False
                if self._impact > DIZZY_SPEED:
                    self._enter(State.DIZZY)  # 撞晕了就顾不上好奇了
                elif notice:
                    self._enter(State.CURIOUS)
                else:
                    self._enter(State.IDLE)

    def _drift_across(self, direction: int) -> bool:
        """下落途中飘过接缝。这里不动 y —— 它正在空中，地面由新屏决定。"""
        neighbour = self.layout.neighbour(self.screen, direction)
        if neighbour is None:
            return False
        self.screen = neighbour
        return True

    def _tick_cling(self, dt: float) -> None:
        self.y += CLING_SLIDE * dt           # 扒住了，但在慢慢往下滑
        if self.y >= self.ground:
            self.y = self.ground
            self._enter(State.IDLE)          # 滑到底了，直接站起来，没必要再摔一下
            return
        if self.state_t >= self.next_switch:
            self.vx = -self.facing * 20.0    # 蹬一下墙再掉下去
            self._enter(State.FALL)

    def _tick_timed(self, dt: float) -> None:
        limit = {State.HAPPY: HAPPY_TIME, State.DIZZY: DIZZY_TIME,
                 State.CURIOUS: CURIOUS_TIME}[self.state]
        if self.state_t >= limit:
            self._enter(State.IDLE)

    # --- 状态转移 ---------------------------------------------------------
    def _enter(self, state: State) -> None:
        self.state = state
        self.state_t = 0.0
        # 除了发呆，其它状态手都有正事要干 —— 走路要摆、被抓要扬、贴墙要抓着，
        # 所以默认先把姿势清回垂手，只有 IDLE 分支才可能改成抱手。
        self.posture = Posture.RELAXED
        if state in (State.DRAG, State.FALL, State.CLING):
            self.support = None               # 已经离开台面了，落点重新找

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
        elif state in (State.SLEEP, State.HAPPY, State.DIZZY, State.CURIOUS):
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

"""屏幕布局的几何。和 state.py 一样**不 import Qt**。

单屏时"边界"就是一个矩形，多屏之后这个模型直接不成立了：

- 屏幕之间的**接缝不是墙**，宠物该走过去；但最外侧的边缘是墙。
- 两块屏可能高度不同、上下有偏移，接缝处**地面高度会变**。
- 排列可能是 L 形或者错开的，于是存在**没有任何屏幕的死区**。
  拿所有屏幕的外接矩形当边界是最容易想到的做法，也是错的 ——
  宠物会走进死区，进程还在跑、托盘图标还在，人就是找不着它。

所以这里保留每块屏各自的矩形，逐块回答"能不能往那边走"，
而不是把它们揉成一个大矩形。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# 相邻判定的容差。Windows 排列出来的屏幕通常是严丝合缝的，
# 但缩放取整偶尔会差一两个像素，差这么点不该被当成"中间有条缝"。
TOUCH_TOLERANCE = 2


@dataclass(frozen=True)
class Screen:
    """一块屏幕的可用区域。right / bottom 不含，和 Qt 的 x()+width() 一致。"""

    left: int
    top: int
    right: int
    bottom: int

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def distance_to(self, x: float, y: float) -> float:
        """点到矩形的距离（在矩形内为 0）。用平方省一次开方。"""
        dx = max(self.left - x, 0.0, x - (self.right - 1))
        dy = max(self.top - y, 0.0, y - (self.bottom - 1))
        return dx * dx + dy * dy


class ScreenLayout:
    def __init__(self, screens: Iterable[Screen], primary: int = 0) -> None:
        self.screens: tuple[Screen, ...] = tuple(screens)
        if not self.screens:
            # 理论上不会发生，但真发生了也不该让宠物崩在这儿
            self.screens = (Screen(0, 0, 1920, 1080),)
        self.primary = primary if 0 <= primary < len(self.screens) else 0

    @classmethod
    def single(cls, bounds: tuple[int, int, int, int]) -> ScreenLayout:
        """单屏的快捷构造。测试和退化情况用。"""
        return cls([Screen(*bounds)])

    def __len__(self) -> int:
        return len(self.screens)

    def signature(self) -> tuple:
        """布局指纹。用来判断屏幕配置有没有变（插拔、改分辨率、改缩放）。"""
        return tuple((s.left, s.top, s.right, s.bottom) for s in self.screens) + (self.primary,)

    # --- 定位 -------------------------------------------------------------
    def index_at(self, x: float, y: float) -> int | None:
        for i, s in enumerate(self.screens):
            if s.contains(x, y):
                return i
        return None

    def nearest_index(self, x: float, y: float) -> int:
        """点落在死区里时的兜底。绝不返回 None —— 宠物总得站在某块屏上。"""
        return min(range(len(self.screens)), key=lambda i: self.screens[i].distance_to(x, y))

    # --- 宠物关心的量 -----------------------------------------------------
    def ground(self, index: int, size: int) -> float:
        """窗口左上角落在地面上时的 y。地面 = 可用区域下沿，也就是任务栏上沿。"""
        return float(self.screens[index].bottom - size)

    def span(self, index: int, size: int) -> tuple[float, float]:
        """窗口左上角 x 在这块屏上的合法范围。"""
        s = self.screens[index]
        return float(s.left), float(s.right - size)

    def neighbour(self, index: int, direction: int) -> int | None:
        """紧挨着的左/右邻屏；没有就是 None，那一侧才是真正的墙。

        要求两块屏**垂直方向有重叠** —— 上下堆叠的两块屏在水平方向上挨不着，
        横着走过去没有意义。有多个候选时取重叠最多的那块。
        """
        here = self.screens[index]
        best: tuple[int, int] | None = None
        for i, other in enumerate(self.screens):
            if i == index:
                continue
            if direction > 0:
                touching = abs(other.left - here.right) <= TOUCH_TOLERANCE
            else:
                touching = abs(other.right - here.left) <= TOUCH_TOLERANCE
            if not touching:
                continue
            overlap = min(here.bottom, other.bottom) - max(here.top, other.top)
            if overlap <= 0:
                continue
            if best is None or overlap > best[1]:
                best = (i, overlap)
        return None if best is None else best[0]


def layout_from_rects(rects: Sequence[tuple[int, int, int, int]], primary: int = 0) -> ScreenLayout:
    return ScreenLayout([Screen(*r) for r in rects], primary=primary)

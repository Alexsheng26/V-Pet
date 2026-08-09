"""可以站的台面。和 state.py / screens.py 一样**不 import Qt**。

任务栏上沿是一条台面，每个可见窗口的**上边缘**也是一条。宠物落下来时停在
脚底下方最高的那条上；走到台面尽头就掉头；台面消失（窗口关掉/移走）就掉下去。

坐标系约定：`y` 是**脚底**所在的位置，不是窗口左上角。宠物左上角 = y - size。
`screens.py` 那边的 `ground()` 已经替调用方减过 size 了，这里刻意不这么做 ——
台面是几何概念，不该知道站在上面的东西有多高。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# 比这窄的台面不站。窗口的标题栏按钮区、细长的工具条上站个宠物很怪，
# 而且站上去几乎立刻就会走到头。
MIN_WIDTH = 120

# 台面高度变化小于这个值就认为"还是同一条"，直接跟着走而不是判定为掉下去。
# 窗口被拖动时每帧会挪几像素，没有这个容差宠物会疯狂抖动。
FOLLOW_TOLERANCE = 6.0


@dataclass(frozen=True)
class Ledge:
    """一条水平台面。right 不含。"""

    left: int
    right: int
    y: int
    key: int = 0        # 来源窗口句柄，用来跨帧认出"还是那扇窗"

    def spans(self, x: float) -> bool:
        return self.left <= x < self.right

    @property
    def width(self) -> int:
        return self.right - self.left


class LedgeSet:
    def __init__(self, ledges: Iterable[Ledge] = ()) -> None:
        # 太窄的直接丢掉，后面所有查询就不用再操心这件事
        self.ledges: tuple[Ledge, ...] = tuple(
            l for l in ledges if l.width >= MIN_WIDTH
        )

    def __len__(self) -> int:
        return len(self.ledges)

    def signature(self) -> tuple:
        return tuple((l.left, l.right, l.y, l.key) for l in self.ledges)

    def landing_below(self, x: float, feet_y: float, ceiling: float | None = None) -> Ledge | None:
        """从 feet_y 往下掉，第一个会踩到的台面。

        取的是"在脚底**下方**、y 最小"的那条 —— 也就是最高的那个落点。
        脚底上方的台面一概不算，否则宠物会往上吸。

        `ceiling` 是台面高度的上限：最大化窗口的上沿在 y=0，宠物站上去整个
        身子都在屏幕外面，看不见。调用方传 `屏幕上沿 + 宠物高度` 把这类台面排掉。
        """
        best: Ledge | None = None
        for ledge in self.ledges:
            if not ledge.spans(x) or ledge.y < feet_y:
                continue
            if ceiling is not None and ledge.y < ceiling:
                continue
            if best is None or ledge.y < best.y:
                best = ledge
        return best

    def refresh(self, support: Ledge | None) -> Ledge | None:
        """窗口动了之后，把旧的支撑面换成这一帧对应的那条。

        **只按窗口句柄认，不看位置。** 曾经还要求宠物仍落在新位置的范围内，
        结果是慢慢拖窗口没事、但 Win+← 这种一次挪半个屏的吸附会让宠物掉下去。
        站在窗口上的东西就该跟着窗口走，挪多远都一样 —— 位移由调用方补给宠物。

        返回 None 只有一个含义：那扇窗真的没了（关掉或最小化）。
        """
        if support is None:
            return None
        for ledge in self.ledges:
            if ledge.key == support.key:
                return ledge
        return None
